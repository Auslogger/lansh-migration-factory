"""
Spike 0.4's Spark reconciliation finds every planted difference under each comparison policy.

The prototype is ``spikes/spark_recon.py``. These tests run offline but start a local Spark
session, so they are marked ``spark``; one session and the two planted comparisons serve the
whole module. The last test checks the report of the SAS round-trip spike,
``spikes/sas_roundtrip.py``, offline.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from lansh.config import REPO_ROOT
from lansh.contracts import (
    ComparisonPolicy,
    KeyIntegrity,
    PolicyKind,
    ReconReport,
    ReconStatus,
    RowCounts,
    TypeMismatch,
)

pytestmark = pytest.mark.spark


def _load_spike(script: str = "spark_recon.py", name: str = "spark_recon_spike") -> ModuleType:
    """
    Import a spike from spikes/, which holds scripts rather than part of the package.
    """
    path = REPO_ROOT / "spikes" / script
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recon = _load_spike()

CI_RTRIM = ComparisonPolicy(kind=PolicyKind.CI_RTRIM, reason="SQL Server CI collation")


@pytest.fixture(scope="module")
def planted(spark: SparkSession) -> tuple[DataFrame, DataFrame]:
    """
    Build the two planted policy tables, legacy then candidate.
    """
    return recon.planted_tables(spark)


@pytest.fixture(scope="module")
def exact_result(planted: tuple[DataFrame, DataFrame]) -> Any:
    """
    Compare the planted tables with every column exact, counting rows per product.
    """
    legacy, candidate = planted
    return recon.compare(legacy, candidate, recon.KEYS, partition_by=["product"])


@pytest.fixture(scope="module")
def policy_result(planted: tuple[DataFrame, DataFrame]) -> Any:
    """
    Compare the planted tables under the policies a data contract would give them.
    """
    legacy, candidate = planted
    return recon.compare(
        legacy, candidate, recon.KEYS, recon.contract_policies(), partition_by=["product"]
    )


def row_statuses(result: Any, key: str = "policy_id") -> dict[tuple[Any, int], tuple[str, list]]:
    """
    Map each joined row's key and duplicate number to its status and differing columns.
    """
    return {
        (r[key], r["_dup"]): (r["_status"], list(r["_diff_columns"]))
        for r in result.rows_df.select(key, "_dup", "_status", "_diff_columns").collect()
    }


### The planted tables


def test_exact_policy_finds_every_planted_difference(exact_result: Any) -> None:
    assert exact_result.column_mismatches == {
        "status": 1,  # 'Open' vs 'OPEN'
        "product": 1,  # 'MOT ' vs 'MOT'
        "region": 1,  # NULL vs 'X' (the NULL vs NULL row does not count)
        "premium": 0,  # 100.10 vs 100.1 are equal decimals
        "loss_ratio": 2,  # 1e-12 and 1e-6 relative
        "loaded_at": 9,  # the audit column differs on every common row
    }
    assert exact_result.rows == RowCounts(matched=0, value_diff=9, missing=2, extra=3)
    samples = {d.column: d.samples for d in exact_result.column_diffs}
    assert samples["status"] == [{"policy_id": "POL-002", "legacy": "Open", "candidate": "OPEN"}]
    assert samples["product"] == [{"policy_id": "POL-003", "legacy": "MOT ", "candidate": "MOT"}]
    assert samples["region"] == [{"policy_id": "POL-004", "legacy": None, "candidate": "X"}]
    assert all(len(s) <= 5 for s in samples.values())
    statuses = row_statuses(exact_result)
    # a key that differs only in case is two different keys under exact
    assert statuses[("POL-012", 0)][0] == "missing"
    assert statuses[("pol-012", 0)][0] == "extra"


def test_ci_rtrim_absorbs_case_and_space_but_not_null_vs_value(policy_result: Any) -> None:
    assert policy_result.column_mismatches == {
        "status": 0,
        "product": 0,
        "region": 1,
        "premium": 0,
        "loss_ratio": 1,
    }
    assert "loaded_at" not in policy_result.column_mismatches  # excluded
    assert policy_result.rows == RowCounts(matched=8, value_diff=2, missing=1, extra=2)
    assert row_statuses(policy_result) == {
        ("POL-001", 0): ("match", []),
        ("POL-002", 0): ("match", []),  # 'Open' vs 'OPEN'
        ("POL-003", 0): ("match", []),  # 'MOT ' vs 'MOT'
        ("POL-004", 0): ("value_diff", ["region"]),  # NULL vs 'X' remains
        ("POL-005", 0): ("match", []),  # NULL vs NULL
        ("POL-006", 0): ("match", []),  # 100.10 vs 100.1
        ("POL-007", 0): ("match", []),  # 1e-12 relative passes float_rel 1e-9
        ("POL-008", 0): ("value_diff", ["loss_ratio"]),  # 1e-6 relative fails
        ("POL-009", 0): ("missing", []),
        ("POL-010", 0): ("extra", []),
        ("POL-011", 0): ("match", []),
        ("POL-011", 1): ("extra", []),  # the duplicate key
        ("POL-012", 0): ("match", []),  # 'POL-012' joins 'pol-012' under ci_rtrim
    }


def test_null_vs_null_never_counts(exact_result: Any, policy_result: Any) -> None:
    assert row_statuses(exact_result)[("POL-005", 0)] == ("value_diff", ["loaded_at"])
    assert row_statuses(policy_result)[("POL-005", 0)] == ("match", [])


def test_decimal_scale_is_a_schema_difference_not_a_value_difference(exact_result: Any) -> None:
    assert exact_result.schema.type_mismatches == [
        TypeMismatch(column="premium", legacy_type="decimal(10,2)", candidate_type="decimal(10,1)")
    ]
    assert exact_result.column_mismatches["premium"] == 0
    totals = {t.column: t for t in exact_result.totals}
    # Spark returns 2261.10 and 2261.1; the canonical text is the same, so the totals agree,
    # even though the rows behind them differ (missing 300.00 vs extra 150.0 + 150.0)
    assert (totals["premium"].legacy, totals["premium"].candidate) == ("2261.1", "2261.1")
    assert totals["premium"].matches
    assert not totals["loss_ratio"].matches


def test_counts_key_integrity_and_partitions(exact_result: Any, policy_result: Any) -> None:
    """
    Row counts and key integrity agree under both policies, but partitions follow the policy.
    """
    for result in (exact_result, policy_result):
        assert (result.counts.legacy, result.counts.candidate) == (11, 12)
        assert result.key_integrity == KeyIntegrity(candidate_duplicate_keys=1)
    exact_parts = {p.partition: (p.legacy, p.candidate) for p in exact_result.counts.by_partition}
    assert exact_parts["product='MOT '"] == (1, 0)  # the trailing space splits a partition
    policy_parts = {p.partition: (p.legacy, p.candidate) for p in policy_result.counts.by_partition}
    assert len(policy_parts) == 3
    assert (5, 6) in policy_parts.values()  # MOT and 'MOT ' are one partition under ci_rtrim


def test_report_fits_the_contract(policy_result: Any) -> None:
    report = policy_result.to_report("T04", "rpt.policy_summary")
    assert report.status is ReconStatus.MISMATCH
    assert ReconReport.model_validate_json(report.model_dump_json()) == report


### datacompy cross-check


def test_datacompy_agrees_with_the_exact_policy(
    planted: tuple[DataFrame, DataFrame], exact_result: Any
) -> None:
    legacy, candidate = planted
    summary = recon.datacompy_summary(legacy, candidate, recon.KEYS)
    assert recon.disagreements(exact_result, summary) == []
    assert (summary.intersect_rows, summary.legacy_only, summary.candidate_only) == (9, 2, 3)
    assert summary.column_mismatches == exact_result.column_mismatches


def test_datacompy_cannot_join_keys_case_insensitively(
    planted: tuple[DataFrame, DataFrame],
) -> None:
    legacy, candidate = planted
    loose = recon.datacompy_summary(
        legacy, candidate, recon.KEYS, ignore_case=True, ignore_spaces=True
    )
    # ignore_case never applies to join columns, so 'POL-012' and 'pol-012' stay split
    assert (loose.legacy_only, loose.candidate_only) == (2, 3)


### Collations: joins, storage and the fallback


def test_collated_join_keys_ignore_case_and_trailing_spaces_and_join_null_keys(
    spark: SparkSession,
) -> None:
    legacy = spark.createDataFrame([("K1", 1), ("k2 ", 2), (None, 3)], "k string, v int")
    candidate = spark.createDataFrame([("k1", 1), ("K2", 2), (None, 3)], "k string, v int")
    ci = recon.compare(legacy, candidate, ["k"], {"k": CI_RTRIM})
    assert ci.rows == RowCounts(matched=3)
    assert ci.key_integrity == KeyIntegrity(legacy_null_keys=1, candidate_null_keys=1)
    assert any("collationkey" in line for line in recon.join_plan(ci.rows_df))
    exact = recon.compare(legacy, candidate, ["k"])
    assert exact.rows == RowCounts(matched=1, missing=2, extra=2)  # only NULL <=> NULL joins


def test_delta_rejects_collated_columns_and_plain_strings_fix_it(
    spark: SparkSession, policy_result: Any, tmp_path: Path
) -> None:
    rows = policy_result.rows_df
    assert recon.collated_columns(rows) == []  # the per-row keys are the plain values
    # collate the key as it was joined, to see what Delta does with a collated column
    collated = rows.withColumn("policy_id", F.collate("policy_id", recon.CI_RTRIM_COLLATION))
    trip = recon.delta_round_trip(spark, collated, str(tmp_path / "rows"))
    assert trip.collated_columns == ["policy_id"]
    assert trip.error is not None
    assert "DELTA_UNSUPPORTED_DATA_TYPES" in trip.error
    assert "UTF8_LCASE_RTRIM" in trip.error
    assert recon.collated_columns(trip.read_back) == []
    assert trip.status_counts == {"match": 8, "value_diff": 2, "missing": 1, "extra": 2}


def test_plain_strings_strips_nested_collations(spark: SparkSession) -> None:
    df = spark.createDataFrame([("Ab ",)], "s string").select(
        F.collate("s", recon.CI_RTRIM_COLLATION).alias("s"),
        F.array(F.collate("s", recon.CI_RTRIM_COLLATION)).alias("a"),
        F.struct(F.collate("s", recon.CI_RTRIM_COLLATION).alias("f")).alias("st"),
    )
    assert recon.collated_columns(df) == ["s", "a", "st"]
    plain = recon.plain_strings(df)
    assert recon.collated_columns(plain) == []
    row = plain.first()
    assert row is not None
    assert (row["s"], row["a"], row["st"]["f"]) == ("Ab ", ["Ab "], "Ab ")


def test_fallback_without_collations_gives_the_same_result(
    planted: tuple[DataFrame, DataFrame], policy_result: Any
) -> None:
    legacy, candidate = planted
    fallback = recon.compare(
        legacy, candidate, recon.KEYS, recon.contract_policies(), use_collations=False
    )
    assert fallback.rows == policy_result.rows
    assert fallback.column_mismatches == policy_result.column_mismatches
    assert not any("collationkey" in line for line in recon.join_plan(fallback.rows_df))
    # the per-row keys are the values as given, 'POL-012' and not lower(rtrim()) 'pol-012'
    assert row_statuses(fallback) == row_statuses(policy_result)


def test_per_row_keys_are_the_values_as_given(spark: SparkSession) -> None:
    """
    Each row shows the legacy side's key, or the candidate's for a row only it has.
    """
    blank_is_null = ComparisonPolicy(kind=PolicyKind.BLANK_IS_NULL, reason="SAS character key")
    legacy = spark.createDataFrame([("K1 ", 1), ("K2", 2)], "k string, v int")
    candidate = spark.createDataFrame([("K1", 1), ("K3  ", 3)], "k string, v int")
    result = recon.compare(legacy, candidate, ["k"], {"k": blank_is_null})
    keys = {(r["k"], r["_status"]) for r in result.rows_df.collect()}
    assert keys == {("K1 ", "match"), ("K2", "missing"), ("K3  ", "extra")}


def test_fallback_agrees_with_the_collation_on_unicode_text(spark: SparkSession) -> None:
    df = spark.createDataFrame(recon.UNICODE_PAIRS, "l string, r string")
    string = T.StringType()
    rows = df.select(
        "l",
        recon.values_equal(F.col("l"), F.col("r"), CI_RTRIM, string, string).alias("collation"),
        recon.values_equal(
            F.col("l"), F.col("r"), CI_RTRIM, string, string, use_collations=False
        ).alias("fallback"),
    ).collect()
    assert {r["l"]: r["collation"] for r in rows} == {
        "SEÁN": True,  # a fada survives case folding (Á to á), and the trailing space is ignored
        "Ó Briain": True,
        "ß": False,  # upper() would make 'ß' equal 'SS'; lower() and the collation don't
        "ı": False,  # likewise dotless i and 'I'
        "ΣΑΣ": True,
        "A\t": False,  # only spaces are trimmed, as in SQL Server
    }
    assert all(r["collation"] == r["fallback"] for r in rows)


def test_duplicates_pair_in_policy_order(spark: SparkSession) -> None:
    # in binary order 'Banana' < 'apple' but 'APPLE' < 'banana', which would pair the wrong
    # duplicates; ordering duplicates by the policy-normalised value pairs them correctly
    legacy = spark.createDataFrame([("K", "apple"), ("K", "Banana")], "k string, v string")
    candidate = spark.createDataFrame([("K", "APPLE"), ("K", "banana")], "k string, v string")
    result = recon.compare(legacy, candidate, ["k"], {"v": CI_RTRIM})
    assert result.rows == RowCounts(matched=2)
    assert result.key_integrity == KeyIntegrity(legacy_duplicate_keys=1, candidate_duplicate_keys=1)


def test_exact_stays_binary_when_an_input_column_is_collated(spark: SparkSession) -> None:
    legacy = spark.createDataFrame([(1, "Open")], "id int, status string")
    candidate = spark.createDataFrame([(1, "OPEN")], "id int, status string").select(
        "id", F.collate("status", recon.CI_RTRIM_COLLATION).alias("status")
    )
    result = recon.compare(legacy, candidate, ["id"])
    assert result.column_mismatches == {"status": 1}
    assert result.schema.type_mismatches == [
        TypeMismatch(
            column="status", legacy_type="string", candidate_type="string collate UTF8_LCASE_RTRIM"
        )
    ]


### Other policies and modes


def test_rtrim_and_blank_is_null_policies(spark: SparkSession) -> None:
    """
    The rtrim policy ignores trailing blanks, and blank_is_null also makes a blank value missing.
    """
    pairs = [
        (1, "abc ", "abc"),  # trailing blank: equal under both
        (2, "Abc", "abc"),  # case: different under both (SAS is case-sensitive)
        (3, "", None),  # blank vs missing: equal only under blank_is_null
        (4, "   ", None),
        (5, None, None),
        (6, "a", None),
    ]
    legacy = spark.createDataFrame([(i, a, a) for i, a, _ in pairs], "id int, r string, b string")
    candidate = spark.createDataFrame(
        [(i, b, b) for i, _, b in pairs], "id int, r string, b string"
    )
    policies = {
        "r": ComparisonPolicy(kind=PolicyKind.RTRIM, reason="SAS character value"),
        "b": ComparisonPolicy(kind=PolicyKind.BLANK_IS_NULL, reason="SAS missing character"),
    }
    result = recon.compare(legacy, candidate, ["id"], policies)
    diffs = {key[0]: cols for key, (_, cols) in row_statuses(result, "id").items()}
    assert diffs == {1: [], 2: ["r", "b"], 3: ["r"], 4: ["r"], 5: [], 6: ["r", "b"]}


def test_float_rel_guards_nan_and_infinity(spark: SparkSession) -> None:
    inf, nan = math.inf, math.nan
    pairs = [
        (1, 0.75, 0.75 * (1 + 1e-12)),
        (2, 0.5, 0.5 * (1 + 1e-6)),
        (3, nan, 1.0),  # a bare |a-b| <= tol*max(|a|,|b|) says equal: Spark's NaN <= NaN
        (4, inf, 1e308),  # ... and inf <= inf
        (5, inf, inf),
        (6, nan, nan),
        (7, None, None),
        (8, None, 1.0),
        (9, 0.0, -0.0),
    ]
    legacy = spark.createDataFrame([(i, a) for i, a, _ in pairs], "id int, x double")
    candidate = spark.createDataFrame([(i, b) for i, _, b in pairs], "id int, x double")
    policy = ComparisonPolicy(kind=PolicyKind.FLOAT_REL, rel_tolerance=1e-9, reason="SAS double")
    result = recon.compare(legacy, candidate, ["id"], {"x": policy})
    differing = {
        key[0] for key, (status, _) in row_statuses(result, "id").items() if status != "match"
    }
    assert differing == {2, 3, 4, 8}


def test_key_type_mismatch_joins_as_text(spark: SparkSession) -> None:
    legacy = spark.createDataFrame([(1, "a"), (2, "b")], "id int, v string")
    candidate = spark.createDataFrame([("1", "a"), ("2", "b"), ("x", "c")], "id string, v string")
    result = recon.compare(legacy, candidate, ["id"])  # ANSI would reject CAST('x' AS INT)
    assert result.rows == RowCounts(matched=2, extra=1)
    assert [m.column for m in result.schema.type_mismatches] == ["id"]


def test_multiset_comparison_without_keys(spark: SparkSession) -> None:
    """
    Without keys, whole rows are matched as a multiset, so duplicates count.
    """
    legacy = spark.createDataFrame([("a",), ("a",), ("b",)], "v string")
    candidate = spark.createDataFrame([("a",), ("b",), ("b",)], "v string")
    result = recon.compare(legacy, candidate, [])
    assert result.rows == RowCounts(matched=2, missing=1, extra=1)


def test_decimal_total_overflow_is_reported_not_raised(spark: SparkSession) -> None:
    big = [(1, Decimal("9" * 36)), (2, Decimal("9" * 36))]
    legacy = spark.createDataFrame(big, "id int, amount decimal(38,2)")
    result = recon.compare(legacy, legacy, ["id"])
    total = next(t for t in result.totals if t.column == "amount")
    assert total.legacy is None
    assert not total.matches
    assert any("overflowed" in e for e in result.errors)
    assert result.to_report("T04", "rpt.big").status is ReconStatus.ERROR


def test_double_total_overflow_is_reported(spark: SparkSession) -> None:
    """
    A double total that overflows to infinity is an error, but a column holding one isn't.
    """
    big = spark.createDataFrame([(1, 1e308), (2, 1e308)], "id int, x double")
    result = recon.compare(big, big, ["id"])
    total = next(t for t in result.totals if t.column == "x")
    assert not total.matches
    assert "total of 'x' overflowed on the legacy side" in result.errors
    assert result.to_report("T04", "rpt.big").status is ReconStatus.ERROR
    infinite = spark.createDataFrame([(1, math.inf), (2, 1.0)], "id int, x double")
    assert recon.compare(infinite, infinite, ["id"]).errors == []


def test_float_rel_totals_guard_infinity(spark: SparkSession) -> None:
    # with a tolerance, a bare |a-b| <= tol*max(|a|,|b|) says inf and -inf agree: inf <= inf
    policy = ComparisonPolicy(kind=PolicyKind.FLOAT_REL, rel_tolerance=1e-9, reason="SAS double")
    for legacy_x, candidate_x, matches in (
        (math.inf, -math.inf, False),
        (math.inf, 1e308, False),
        (math.inf, math.inf, True),
    ):
        legacy = spark.createDataFrame([(1, legacy_x)], "id int, x double")
        candidate = spark.createDataFrame([(1, candidate_x)], "id int, x double")
        result = recon.compare(legacy, candidate, ["id"], {"x": policy})
        total = next(t for t in result.totals if t.column == "x")
        assert total.matches is matches, (legacy_x, candidate_x)


def test_policies_are_validated(planted: tuple[DataFrame, DataFrame]) -> None:
    """
    Text policies on numbers, unkeyable policies on keys and unknown columns are refused.
    """
    legacy, candidate = planted
    with pytest.raises(ValueError, match="string columns only"):
        recon.compare(legacy, candidate, recon.KEYS, {"premium": CI_RTRIM})
    exclude = ComparisonPolicy(kind=PolicyKind.EXCLUDE, reason="audit")
    with pytest.raises(ValueError, match="cannot use policy"):
        recon.compare(legacy, candidate, recon.KEYS, {"policy_id": exclude})
    with pytest.raises(ValueError, match="unknown columns"):
        recon.compare(legacy, candidate, recon.KEYS, {"nope": CI_RTRIM})


def test_number_text_is_canonical() -> None:
    assert recon.number_text(Decimal("2261.10")) == recon.number_text(Decimal("2261.1"))
    assert recon.number_text(Decimal("100")) == "100"
    assert recon.number_text(Decimal("-0.00")) == "0"
    assert recon.number_text(4.2) == "4.2"
    assert recon.number_text(math.inf) is None


### The SAS round trip's report


def test_sas_report_lists_a_value_that_came_back_missing() -> None:
    """
    A money or integer value that SAS returned as missing is listed, rather than a crash.
    """
    # loaded here, not with the module, so that only this test needs the SAS engine to import
    sas_spike = _load_spike("sas_roundtrip.py", "sas_roundtrip_spike")
    expected = sas_spike.expected_columns()
    frame = pd.DataFrame({column: expected[column] for column in sas_spike.ORIGINAL})
    frame.loc[0, "money"] = None
    frame.loc[1, "int_val"] = None

    changed = {(c["column"], c["row_seq"]): c for c in sas_spike.what_changed(frame)}

    assert (changed[("money", 1)]["original"], changed[("money", 1)]["got"]) == ("0.00", None)
    assert (changed[("int_val", 2)]["original"], changed[("int_val", 2)]["got"]) == (1, None)
    assert changed[("s", 2)]["got"] == "trailing"  # a change by design is still listed
