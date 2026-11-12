"""
Spike 0.4, Spark reconciliation: find planted case, trailing-space and NULL differences.

The spike built the prototype of the reconciliation engine in plan §8.6, and step 2.1 moved it
into the package as :mod:`lansh.reconcile.engine`. This script keeps the spike's planted tables
and its demonstration, run against that engine: schema, counts (in total and per partition),
totals of numeric columns, key integrity, a full outer join on the keys with null-safe
equality, a comparison of each column under its policy (§8.4), and a status for every row.

Collations are used **only inside comparisons**: ``ci_rtrim`` compares under Spark's
``UTF8_LCASE_RTRIM`` (SQL Server's case- and trailing-space-insensitive equality) and
``rtrim`` under ``UTF8_BINARY_RTRIM``. Delta refuses collated string types, so anything that
is written goes through ``plain_strings`` first.

Results and decisions: ``spikes/README.md ("Spark reconciliation")``.

Usage:
    uv run python spikes/spark_recon.py              # the demonstration
    uv run pytest tests/test_spark_recon_spike.py    # its tests
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pyspark.errors import AnalysisException, ArithmeticException
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lansh.contracts import ComparisonPolicy, PolicyKind
from lansh.reconcile.engine import (  # noqa: F401  (re-exported for the spike's tests)
    CI_RTRIM_COLLATION,
    RTRIM_COLLATION,
    ReconResult,
    collated_columns,
    compare,
    datacompy_summary,
    disagreements,
    normalise,
    number_text,
    plain_strings,
    plain_type,
    values_equal,
)
from lansh.spark import get_spark

log = logging.getLogger(__name__)


### The Delta round trip


@dataclass
class DeltaRoundTrip:
    """
    What happened when the per-row result was written to Delta and read back.
    """

    collated_columns: list[str]
    # the first line of the error from writing the frame with its collations, if any
    error: str | None
    read_back: DataFrame
    status_counts: dict[str, int]


def delta_round_trip(spark: SparkSession, rows_df: DataFrame, path: str) -> DeltaRoundTrip:
    """
    Write the per-row result to Delta as it is, then with plain strings, and read it back.

    Args:
        spark: The Spark session.
        rows_df: A comparison's per-row result.
        path: Where to write the Delta table. Anything there is overwritten.

    Returns:
        The collated columns, the first write's error, the frame read back and its counts
        per status.

    Raises:
        AssertionError: If a collation survives :func:`plain_strings`.
    """
    collated = collated_columns(rows_df)
    error = None
    try:
        rows_df.write.format("delta").mode("overwrite").save(path)
    except AnalysisException as exc:
        error = str(exc).strip().splitlines()[0]
    plain = plain_strings(rows_df)
    if collated_columns(plain):
        raise AssertionError("collations survived plain_strings()")
    plain.write.format("delta").mode("overwrite").save(path)
    back = spark.read.format("delta").load(path)
    counts = {r["_status"]: r["count"] for r in back.groupBy("_status").count().collect()}
    return DeltaRoundTrip(collated, error, back, counts)


def join_plan(df: DataFrame) -> list[str]:
    """
    Pick the join lines out of a frame's physical plan, to show how collated keys are joined.

    Args:
        df: Any DataFrame.

    Returns:
        Every line of the plan that mentions a join, stripped.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        df.explain()
    return [line.strip() for line in buffer.getvalue().splitlines() if "Join" in line]


### The planted tables

KEYS = ["policy_id"]
# an audit column's load timestamp differs on every run, so the two sides never agree on it
LEGACY_LOADED_AT = datetime(2026, 11, 10, 8, 0)
CANDIDATE_LOADED_AT = datetime(2026, 11, 10, 9, 30)
LEGACY_SCHEMA = (
    "policy_id string, status string, product string, region string, "
    "premium decimal(10,2), loss_ratio double, loaded_at timestamp_ntz"
)
# the candidate's premium came out as decimal(10,1): same values, different scale
CANDIDATE_SCHEMA = LEGACY_SCHEMA.replace("decimal(10,2)", "decimal(10,1)")


def planted_tables(spark: SparkSession) -> tuple[DataFrame, DataFrame]:
    """
    Build two small policy tables with every planted difference.

    The comments on the rows say what each one plants.

    Args:
        spark: The Spark session.

    Returns:
        The legacy table (11 rows) and the candidate table (12 rows).
    """
    lt, ct = LEGACY_LOADED_AT, CANDIDATE_LOADED_AT
    d = Decimal
    legacy = [
        ("POL-001", "Open", "MOT", "D", d("250.50"), 0.62, lt),  # identical
        ("POL-002", "Open", "HOM", "C", d("410.00"), 0.40, lt),  # case: 'Open' vs 'OPEN'
        ("POL-003", "Open", "MOT ", "G", d("199.90"), 0.55, lt),  # space: 'MOT ' vs 'MOT'
        ("POL-004", "Lapsed", "TRV", None, d("35.00"), 0.10, lt),  # NULL vs 'X'
        ("POL-005", "Open", "HOM", None, None, None, lt),  # NULL vs NULL (must match)
        ("POL-006", "Open", "MOT", "D", d("100.10"), 0.33, lt),  # 100.10 vs 100.1
        ("POL-007", "Open", "MOT", "C", d("320.00"), 0.75, lt),  # double, 1e-12 relative
        ("POL-008", "Closed", "HOM", "G", d("275.20"), 0.5, lt),  # double, 1e-6 relative
        ("POL-009", "Open", "TRV", "D", d("300.00"), 0.20, lt),  # only in legacy
        ("POL-011", "Open", "MOT", "C", d("150.00"), 0.45, lt),  # duplicated in candidate
        ("POL-012", "Open", "HOM", "D", d("220.40"), 0.30, lt),  # key case: 'pol-012'
    ]
    candidate = [
        ("POL-001", "Open", "MOT", "D", d("250.5"), 0.62, ct),
        ("POL-002", "OPEN", "HOM", "C", d("410.0"), 0.40, ct),
        ("POL-003", "Open", "MOT", "G", d("199.9"), 0.55, ct),
        ("POL-004", "Lapsed", "TRV", "X", d("35.0"), 0.10, ct),
        ("POL-005", "Open", "HOM", None, None, None, ct),
        ("POL-006", "Open", "MOT", "D", d("100.1"), 0.33, ct),
        ("POL-007", "Open", "MOT", "C", d("320.0"), 0.75 * (1 + 1e-12), ct),
        ("POL-008", "Closed", "HOM", "G", d("275.2"), 0.5 * (1 + 1e-6), ct),
        ("POL-010", "Open", "TRV", "C", d("150.0"), 0.25, ct),  # only in candidate
        ("POL-011", "Open", "MOT", "C", d("150.0"), 0.45, ct),
        ("POL-011", "Open", "MOT", "C", d("150.0"), 0.45, ct),  # duplicate key
        ("pol-012", "Open", "HOM", "D", d("220.4"), 0.30, ct),  # differs only in case
    ]
    return (
        spark.createDataFrame(legacy, LEGACY_SCHEMA),
        spark.createDataFrame(candidate, CANDIDATE_SCHEMA),
    )


# text pairs where case folding or trimming could go wrong (Irish fadas first)
UNICODE_PAIRS = [
    ("SEÁN", "Seán "),
    ("Ó Briain", "ó briain"),
    ("ß", "SS"),
    ("ı", "I"),
    ("ΣΑΣ", "σας"),
    ("A\t", "a"),
]


def contract_policies() -> dict[str, ComparisonPolicy]:
    """
    Give the policies a data contract would set for the planted table.

    Returns:
        ``ci_rtrim`` for the key and text columns, ``float_rel`` 1e-9 for ``loss_ratio`` and
        ``exclude`` for the audit column ``loaded_at``. ``premium`` stays ``exact``.
    """
    ci = "SQL Server column under SQL_Latin1_General_CP1_CI_AS: = ignores case and trailing spaces"
    ci_rtrim = ComparisonPolicy(kind=PolicyKind.CI_RTRIM, reason=ci)
    return {
        "policy_id": ci_rtrim,
        "status": ci_rtrim,
        "product": ci_rtrim,
        "region": ci_rtrim,
        "loss_ratio": ComparisonPolicy(
            kind=PolicyKind.FLOAT_REL,
            rel_tolerance=1e-9,
            reason="SAS double computed in floating point (spike demo)",
        ),
        "loaded_at": ComparisonPolicy(
            kind=PolicyKind.EXCLUDE, reason="audit column: the load timestamp differs every run"
        ),
    }


### Demonstration


def describe(title: str, result: ReconResult) -> str:
    """
    Summarise one comparison as plain text.

    Args:
        title: The heading for the summary.
        result: The comparison to describe.

    Returns:
        The summary, each line headed by the number of the check it reports.
    """
    lines = [f"== {title} =="]
    policies = {
        c: p.kind.value for c, p in result.policies.items() if p.kind is not PolicyKind.EXACT
    }
    lines.append(f"keys={result.keys} non-exact policies={policies or 'none'}")
    lines.append(
        f"1 schema ok={result.schema.ok} type_mismatches="
        + str([(m.column, m.legacy_type, m.candidate_type) for m in result.schema.type_mismatches])
    )
    lines.append(f"2 counts legacy={result.counts.legacy} candidate={result.counts.candidate}")
    for p in result.counts.by_partition:
        flag = "" if p.legacy == p.candidate else "  <-- differs"
        lines.append(f"    {p.partition}: legacy={p.legacy} candidate={p.candidate}{flag}")
    for t in result.totals:
        lines.append(
            f"3 total {t.column}: legacy={t.legacy} candidate={t.candidate} matches={t.matches}"
        )
    lines.append(f"4 key integrity {result.key_integrity.model_dump()}")
    lines.append(f"5-7 rows {result.rows.model_dump()}")
    lines.append(f"6 mismatches per column {result.column_mismatches}")
    for diff in result.column_diffs:
        lines.append(
            f"    {diff.column} [{diff.policy.value}] n={diff.n_rows} samples={diff.samples}"
        )
    if result.errors:
        lines.append(f"errors {result.errors}")
    lines.append(f"timings (s) {result.timings}")
    return "\n".join(lines)


def _first_line(exc: Exception) -> str:
    """
    Give the first line of an exception's message.
    """
    return str(exc).strip().splitlines()[0]


def main() -> int:
    """
    Run the demonstration on the planted tables, and print what every check found.

    It compares the tables with every column ``exact`` and then under the contract policies,
    cross-checks the first with datacompy, repeats the second without collations, writes the
    per-row result to Delta, and ends with the gotcha probes.

    Returns:
        Exit code 0 if datacompy agrees and the fallback gives the same result, otherwise 1.
    """
    logging.basicConfig(level=logging.WARNING)
    t0 = time.perf_counter()
    spark = get_spark("lansh-spike-spark-recon")
    print(f"Spark {spark.version} session ready in {time.perf_counter() - t0:.1f}s")
    legacy, candidate = planted_tables(spark)
    print("\nLegacy:")
    legacy.orderBy("policy_id").show(truncate=False)
    print("Candidate:")
    candidate.orderBy("policy_id").show(truncate=False)

    exact = compare(legacy, candidate, KEYS, partition_by=["product"])
    print(describe("every column exact", exact))

    summary = datacompy_summary(legacy, candidate, KEYS)
    print(f"\ndatacompy (abs_tol=0, rel_tol=0): {summary}")
    problems = disagreements(exact, summary)
    print("datacompy agrees with the exact policy" if not problems else f"DISAGREES: {problems}")
    loose = datacompy_summary(legacy, candidate, KEYS, ignore_case=True, ignore_spaces=True)
    print(
        "datacompy with ignore_case and ignore_spaces still splits the key 'POL-012'/'pol-012': "
        f"only-in-legacy={loose.legacy_only} only-in-candidate={loose.candidate_only}"
    )

    policies = contract_policies()
    policed = compare(legacy, candidate, KEYS, policies, partition_by=["product"])
    print(
        "\n"
        + describe("contract policies (ci_rtrim keys and text, float_rel 1e-9, exclude)", policed)
    )
    print("Join plan with ci_rtrim keys:")
    for line in join_plan(policed.rows_df):
        print("   ", line)
    print("Per-row result:")
    policed.rows_df.select("policy_id", "_dup", "_status", "_diff_columns").orderBy(
        "policy_id", "_dup"
    ).show(truncate=False)

    fallback = compare(legacy, candidate, KEYS, policies, use_collations=False)
    same = (fallback.rows, fallback.column_mismatches) == (policed.rows, policed.column_mismatches)
    print(f"Fallback lower(rtrim()) without collations gives the same result: {same}")

    with tempfile.TemporaryDirectory(prefix="lansh-spark-recon-") as tmp:
        start = time.perf_counter()
        # the per-row keys are plain values; collate the key as it was joined, to show what
        # Delta does with a collated column
        collated = policed.rows_df.withColumn(
            "policy_id", F.collate("policy_id", CI_RTRIM_COLLATION)
        )
        trip = delta_round_trip(spark, collated, str(Path(tmp) / "recon_rows"))
        print(
            f"\nDelta: collated columns, with the key collated as joined: {trip.collated_columns}"
        )
        print(f"Delta: writing them as they are fails with:\n    {trip.error}")
        schema = trip.read_back.schema.simpleString()
        print(f"Delta: after plain_strings() the read-back schema is {schema}")
        print(
            f"Delta: statuses read back {trip.status_counts} ({time.perf_counter() - start:.1f}s)"
        )

    print("\nGotcha probes:")
    probe = spark.createDataFrame(
        [("Open", "OPEN"), ("MOT ", "MOT"), (None, None), (None, "X")], "l string, r string"
    )
    probe.select(
        "l",
        "r",
        F.col("l").eqNullSafe(F.col("r")).alias("plain <=>"),
        F.collate("l", CI_RTRIM_COLLATION)
        .eqNullSafe(F.collate("r", CI_RTRIM_COLLATION))
        .alias("UTF8_LCASE_RTRIM <=>"),
        (F.collate("l", CI_RTRIM_COLLATION) == F.collate("r", CI_RTRIM_COLLATION)).alias(
            "UTF8_LCASE_RTRIM ="
        ),
    ).show()
    collated = probe.select(F.collate("l", CI_RTRIM_COLLATION).alias("l"), "r")
    try:
        collated.select(F.col("l") == F.col("r")).collect()
    except AnalysisException as exc:
        print(f"collated column = plain column: {_first_line(exc)}")
    big = spark.createDataFrame([(Decimal("9" * 36),)] * 2, "amount decimal(38,2)")
    try:
        big.select(F.sum("amount")).collect()
    except ArithmeticException as exc:
        print(f"sum(decimal(38,2)) overflow under ANSI: {_first_line(exc)[:140]}...")
    print(f"try_sum of the same: {big.select(F.try_sum('amount')).collect()[0][0]}")
    unicode_pairs = spark.createDataFrame(UNICODE_PAIRS, "l string, r string")
    print("ci_rtrim equality: the collation against plain-string fallbacks")
    unicode_pairs.select(
        "l",
        "r",
        F.collate("l", CI_RTRIM_COLLATION)
        .eqNullSafe(F.collate("r", CI_RTRIM_COLLATION))
        .alias(CI_RTRIM_COLLATION),
        F.lower(F.rtrim("l")).eqNullSafe(F.lower(F.rtrim("r"))).alias("lower(rtrim())"),
        F.upper(F.rtrim("l")).eqNullSafe(F.upper(F.rtrim("r"))).alias("upper(rtrim())"),
    ).show(truncate=False)
    print(f"\nTotal wall time {time.perf_counter() - t0:.1f}s")
    return 0 if not problems and same else 1


if __name__ == "__main__":
    sys.exit(main())
