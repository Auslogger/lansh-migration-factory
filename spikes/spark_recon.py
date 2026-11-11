"""
Spike 0.4, Spark reconciliation: find planted case, trailing-space and NULL differences.

A prototype of the reconciliation engine in plan §8.6, run on two small planted tables. It
follows the checks in order: schema, counts (in total and per partition), totals of numeric
columns, key integrity, a full outer join on the keys with null-safe equality, a comparison of
each column under its policy (§8.4), and a status for every row.

Collations are used **only inside comparisons**: ``ci_rtrim`` compares under Spark's
``UTF8_LCASE_RTRIM`` (SQL Server's case- and trailing-space-insensitive equality) and
``rtrim`` under ``UTF8_BINARY_RTRIM``. Delta refuses collated string types, so anything that
is written goes through :func:`plain_strings` first.

Results and decisions: ``spikes/README.md ("Spark reconciliation")``.

Usage:
    uv run python spikes/spark_recon.py              # the demonstration
    uv run pytest tests/test_spark_recon_spike.py    # its tests
"""

from __future__ import annotations

import contextlib
import io
import logging
import math
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import reduce
from operator import and_, or_
from pathlib import Path
from typing import Any

from pyspark.errors import AnalysisException, ArithmeticException
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from lansh.contracts import (
    ColumnDiff,
    ComparisonPolicy,
    CountCheck,
    KeyIntegrity,
    PartitionCount,
    PolicyKind,
    ReconMode,
    ReconReport,
    ReconStatus,
    RowCounts,
    SchemaDiff,
    TotalCheck,
    TypeMismatch,
)
from lansh.spark import get_spark

log = logging.getLogger(__name__)

# equality as in SQL Server under a CI collation: case-insensitive, trailing spaces ignored
CI_RTRIM_COLLATION = "UTF8_LCASE_RTRIM"
# character equality as in SAS: case-sensitive, trailing blanks ignored
RTRIM_COLLATION = "UTF8_BINARY_RTRIM"

MATCH, VALUE_DIFF, MISSING, EXTRA = "match", "value_diff", "missing", "extra"
STATUSES = (MATCH, VALUE_DIFF, MISSING, EXTRA)

EXACT = ComparisonPolicy()
_TEXT_POLICIES = frozenset({PolicyKind.CI_RTRIM, PolicyKind.RTRIM, PolicyKind.BLANK_IS_NULL})
_NOT_COMPARED = frozenset({PolicyKind.EXCLUDE, PolicyKind.SURROGATE})
_NOT_ALLOWED_ON_KEYS = frozenset({PolicyKind.FLOAT_REL, PolicyKind.EXCLUDE, PolicyKind.SURROGATE})
_INTEGRAL = (T.ByteType, T.ShortType, T.IntegerType, T.LongType)
_FLOATING = (T.FloatType, T.DoubleType)
_NUMERIC = (*_INTEGRAL, *_FLOATING, T.DecimalType)


### Collations stay inside comparisons


def _c(name: str) -> Column:
    """
    Refer to a column by name, even when the name holds dots or other odd characters.
    """
    return F.col("`" + name.replace("`", "``") + "`")


def plain_type(data_type: T.DataType) -> T.DataType:
    """
    Replace every collated string inside a type, at any depth, with plain ``string``.

    Args:
        data_type: Any Spark type, arrays, maps and structs included.

    Returns:
        The same type without collations. A type with no strings comes back unchanged.
    """
    if isinstance(data_type, T.StringType):
        return T.StringType()
    if isinstance(data_type, T.ArrayType):
        return T.ArrayType(plain_type(data_type.elementType), data_type.containsNull)
    if isinstance(data_type, T.MapType):
        return T.MapType(
            plain_type(data_type.keyType),
            plain_type(data_type.valueType),
            data_type.valueContainsNull,
        )
    if isinstance(data_type, T.StructType):
        return T.StructType(
            [
                T.StructField(f.name, plain_type(f.dataType), f.nullable, f.metadata)
                for f in data_type.fields
            ]
        )
    return data_type


def collated_columns(df: DataFrame) -> list[str]:
    """
    List the top-level columns whose type holds a collated string anywhere inside it.

    Args:
        df: Any DataFrame.

    Returns:
        The names of those columns, in schema order.
    """
    return [f.name for f in df.schema.fields if plain_type(f.dataType) != f.dataType]


def plain_strings(df: DataFrame) -> DataFrame:
    """
    Cast every collated string, nested ones included, back to plain ``string``.

    Delta rejects collated types with ``DELTA_UNSUPPORTED_DATA_TYPES``; Parquet accepts them
    and keeps the collation in the file schema. Either way nothing collated is ever written.

    Args:
        df: Any DataFrame.

    Returns:
        The frame itself when nothing in it is collated, otherwise the same columns with the
        collated ones cast.
    """
    if not collated_columns(df):
        return df
    return df.select(
        *[
            _c(f.name).cast(plain_type(f.dataType)).alias(f.name)
            if plain_type(f.dataType) != f.dataType
            else _c(f.name)
            for f in df.schema.fields
        ]
    )


### Policies


def normalise(col: Column, policy: ComparisonPolicy, *, use_collations: bool = True) -> Column:
    """
    Give the value a column is joined, grouped and compared on under its policy.

    ``use_collations=False`` is the decided fallback: plain-string normalisation with
    ``lower(rtrim())`` instead of a collation. It uses ``lower`` rather than ``upper`` because
    UTF8_LCASE is defined by lower-casing: ``upper`` also equates 'ß' with 'SS' and 'ı' with
    'I', which the collation does not.

    Args:
        col: The column to normalise.
        policy: The column's comparison policy.
        use_collations: Whether the text policies use collations, or the fallback.

    Returns:
        The column under a collation (or the fallback's plain-string form) for ``ci_rtrim``
        and ``rtrim``, the right-trimmed text with blanks as NULL for ``blank_is_null``, and
        the column unchanged for every other policy.
    """
    kind = policy.kind
    if kind is PolicyKind.CI_RTRIM:
        return F.collate(col, CI_RTRIM_COLLATION) if use_collations else F.lower(F.rtrim(col))
    if kind is PolicyKind.RTRIM:
        return F.collate(col, RTRIM_COLLATION) if use_collations else F.rtrim(col)
    if kind is PolicyKind.BLANK_IS_NULL:
        # as in SAS, a blank value is missing and trailing blanks never count
        return F.nullif(F.rtrim(col), F.lit(""))
    return col


def _finite(col: Column) -> Column:
    """
    Build a condition that holds where a floating-point column is neither NaN nor infinite.
    """
    return ~F.isnan(col) & (F.abs(col) != F.lit(math.inf))


def values_equal(
    legacy: Column,
    candidate: Column,
    policy: ComparisonPolicy,
    legacy_type: T.DataType,
    candidate_type: T.DataType,
    *,
    use_collations: bool = True,
) -> Column:
    """
    Build a never-NULL condition that holds where the two values are equal under the policy.

    NULL equals NULL under every policy. Values whose types differ compare by number when
    both are numeric, and otherwise as text.

    Args:
        legacy: The legacy side's column.
        candidate: The candidate side's column.
        policy: The column's comparison policy.
        legacy_type: The legacy column's Spark type.
        candidate_type: The candidate column's Spark type.
        use_collations: Whether the text policies use collations, or the fallback.

    Returns:
        A boolean column that is never NULL.
    """
    kind = policy.kind
    if kind is PolicyKind.FLOAT_REL:
        tolerance = F.lit(policy.rel_tolerance)
        # a bare |a-b| <= tol*max(|a|,|b|) would accept NaN vs 1.0 and inf vs 1e308, because
        # Spark orders NaN above everything and treats NaN = NaN as true: guard both
        close = (
            _finite(legacy)
            & _finite(candidate)
            & (F.abs(legacy - candidate) <= tolerance * F.greatest(F.abs(legacy), F.abs(candidate)))
        )
        equal = legacy.eqNullSafe(candidate) | F.coalesce(close, F.lit(False))
    elif kind in _TEXT_POLICIES:
        equal = normalise(legacy, policy, use_collations=use_collations).eqNullSafe(
            normalise(candidate, policy, use_collations=use_collations)
        )
    elif legacy_type == candidate_type or (
        isinstance(legacy_type, _NUMERIC) and isinstance(candidate_type, _NUMERIC)
    ):
        # numbers compare by value: decimal(10,2) 100.10 equals decimal(10,1) 100.1
        equal = legacy.eqNullSafe(candidate)
    else:
        # other type mismatches (the schema check reports them) compare as text, because an
        # implicit cast under ANSI mode raises on the first value that doesn't parse
        equal = legacy.cast("string").eqNullSafe(candidate.cast("string"))
    return F.coalesce(equal, F.lit(False))


def _validate(
    legacy: DataFrame,
    candidate: DataFrame,
    keys: Sequence[str],
    policies: Mapping[str, ComparisonPolicy],
    partition_by: Sequence[str],
) -> None:
    """
    Check the inputs and the policies before any Spark work starts.

    Raises:
        ValueError: If a side has duplicate column names, a key column repeats, a key or
            partition column is missing from a side, a policy names an unknown column, a
            policy doesn't suit its column's type, or a key has a policy keys can't use.
    """
    for df, side in ((legacy, "legacy"), (candidate, "candidate")):
        dupes = sorted({c for c in df.columns if df.columns.count(c) > 1})
        if dupes:
            raise ValueError(f"{side} has duplicate column names: {dupes}")
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate key columns: {list(keys)}")
    for col in [*keys, *partition_by]:
        for df, side in ((legacy, "legacy"), (candidate, "candidate")):
            if col not in df.columns:
                raise ValueError(f"column {col!r} is not in the {side} output")
    unknown = sorted(set(policies) - set(legacy.columns) - set(candidate.columns))
    if unknown:
        raise ValueError(f"policies for unknown columns: {unknown}")
    for name, policy in policies.items():
        types = [df.schema[name].dataType for df in (legacy, candidate) if name in df.columns]
        if policy.kind in _TEXT_POLICIES and not all(isinstance(t, T.StringType) for t in types):
            raise ValueError(f"{policy.kind} applies to string columns only, not {name!r}")
        if policy.kind is PolicyKind.FLOAT_REL and not all(isinstance(t, _FLOATING) for t in types):
            raise ValueError(f"float_rel applies to float/double columns only, not {name!r}")
        if name in keys and policy.kind in _NOT_ALLOWED_ON_KEYS:
            raise ValueError(f"key column {name!r} cannot use policy {policy.kind}")


### Result


@dataclass
class ReconResult:
    """
    Everything one comparison found.

    Each check's result is a ``lansh.contracts`` model wherever the contracts have one, so
    :meth:`to_report` can build the contract's ``ReconReport`` from it directly.
    """

    keys: list[str]
    policies: dict[str, ComparisonPolicy]
    schema: SchemaDiff
    counts: CountCheck
    totals: list[TotalCheck]
    key_integrity: KeyIntegrity
    rows: RowCounts
    # rows that differ, per compared non-key column (zeros included)
    column_mismatches: dict[str, int]
    # only the columns that differ, each with up to five sample rows
    column_diffs: list[ColumnDiff]
    # one row per joined row: the keys as given (the legacy side's, or the candidate's for an
    # extra row), _dup, _status, _diff_columns, and <column>__legacy and <column>__candidate
    rows_df: DataFrame
    started_at: datetime
    timings: dict[str, float]
    errors: list[str] = field(default_factory=list)

    @property
    def is_match(self) -> bool:
        """
        Tell whether the outputs match: schema, counts, totals and rows, with no errors.
        """
        return (
            self.schema.ok
            and self.counts.ok
            and all(t.matches for t in self.totals)
            and self.rows.differences == 0
            and not self.errors
        )

    def to_report(
        self, job_id: str, table: str, mode: ReconMode = ReconMode.CANDIDATE
    ) -> ReconReport:
        """
        Build the contract's ``ReconReport`` from this result.

        It shows that the contract models carry everything the engine finds. Any error makes
        the status ``ERROR``; otherwise it is ``MATCH`` or ``MISMATCH``.

        Args:
            job_id: The job whose output was compared.
            table: The output table that was compared.
            mode: How the comparison was set up.

        Returns:
            The report, valid under the contract.
        """
        if self.errors:
            status = ReconStatus.ERROR
        else:
            status = ReconStatus.MATCH if self.is_match else ReconStatus.MISMATCH
        return ReconReport(
            job_id=job_id,
            table=table,
            mode=mode,
            status=status,
            keys=self.keys,
            schema_diff=self.schema,
            counts=self.counts,
            totals=self.totals,
            key_integrity=self.key_integrity,
            rows=self.rows,
            column_diffs=self.column_diffs,
            started_at=self.started_at,
            duration_seconds=round(sum(self.timings.values()), 3),
            error="; ".join(self.errors) or None,
        )


### The checks


def number_text(value: Any) -> str | None:
    """
    Write a total as canonical decimal text, whatever its scale.

    ``Decimal('2261.10')`` and ``2261.1`` both give ``'2261.1'``. Doubles keep their shortest
    round-trip form.

    Args:
        value: A total from Spark: a decimal, an integer, a double or None.

    Returns:
        The canonical text, or None for None, NaN and infinity.
    """
    if value is None:
        return None
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else None
    number = Decimal(value)
    return "0" if number.is_zero() else format(number.normalize(), "f")


def _rel_close(a: float, b: float, tolerance: float) -> bool:
    """
    Tell whether two double totals agree within a relative tolerance.

    As in :func:`values_equal`, NaN matches only NaN and an infinity only the same infinity:
    with a tolerance, a bare relative check would accept inf against -inf, as inf <= inf.
    """
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return a == b or abs(a - b) <= tolerance * max(abs(a), abs(b))


def _schema_diff(legacy: DataFrame, candidate: DataFrame) -> SchemaDiff:
    """
    Compare the two sides' column names, and their types as ``simpleString()`` text.
    """
    lt = {f.name: f.dataType.simpleString() for f in legacy.schema.fields}
    ct = {f.name: f.dataType.simpleString() for f in candidate.schema.fields}
    return SchemaDiff(
        missing_columns=[c for c in lt if c not in ct],
        extra_columns=[c for c in ct if c not in lt],
        type_mismatches=[
            TypeMismatch(column=c, legacy_type=lt[c], candidate_type=ct[c])
            for c in lt
            if c in ct and lt[c] != ct[c]
        ],
    )


def _side_stats(
    df: DataFrame, columns: Sequence[str]
) -> tuple[int, dict[str, Any], dict[str, int], dict[str, int]]:
    """
    Count one side's rows and total its numeric columns, all in one Spark action.

    Args:
        df: One side's output.
        columns: The numeric columns to total.

    Returns:
        The row count; the total per column, None when an integer or decimal total
        overflowed or every value is NULL; the count of non-NULL values per column; and the
        count of NaN and infinite values per column, always 0 for integers and decimals.
    """
    aggs = [F.count(F.lit(1)).alias("_n")]
    for i, name in enumerate(columns):
        data_type = df.schema[name].dataType
        non_finite = F.lit(0)
        if isinstance(data_type, _INTEGRAL):
            # sum(bigint) raises ARITHMETIC_OVERFLOW under ANSI; decimal(38,0) has room
            total = F.try_sum(_c(name).cast("decimal(38,0)"))
        elif isinstance(data_type, T.DecimalType):
            # sum(decimal(p,s)) is decimal(min(38,p+10),s). On overflow plain sum raises
            # NUMERIC_VALUE_OUT_OF_RANGE under ANSI; try_sum returns NULL, which the
            # non-NULL count below turns into an explicit error
            total = F.try_sum(_c(name))
        else:
            # a double sum overflows to infinity without an error, even under ANSI; the
            # count of values that aren't finite tells an overflow from an infinite value
            total = F.sum(_c(name).cast("double"))
            non_finite = F.count(F.when(~_finite(_c(name).cast("double")), 1))
        aggs += [
            total.alias(f"_t{i}"),
            F.count(_c(name)).alias(f"_c{i}"),
            non_finite.alias(f"_f{i}"),
        ]
    row = df.agg(*aggs).first()
    assert row is not None
    totals = {name: row[f"_t{i}"] for i, name in enumerate(columns)}
    non_null = {name: row[f"_c{i}"] for i, name in enumerate(columns)}
    non_finite_values = {name: row[f"_f{i}"] for i, name in enumerate(columns)}
    return row["_n"], totals, non_null, non_finite_values


def _total_check(
    column: str,
    legacy: Any,
    candidate: Any,
    non_null: tuple[int, int],
    non_finite: tuple[int, int],
    policy: ComparisonPolicy,
) -> tuple[TotalCheck, list[str]]:
    """
    Compare one column's two totals, reporting a total that overflowed as an error.

    An integer or decimal total overflowed when it is None although the column has values; a
    double total when it isn't finite although every value is. Doubles agree within the
    column's ``float_rel`` tolerance, or else exactly; decimals and integers compare by
    value, whatever their scale.

    Returns:
        The contract's check, and an error message for each side whose total overflowed.
    """
    errors = [
        f"total of {column!r} overflowed on the {side} side"
        for side, value, n, bad in (
            ("legacy", legacy, non_null[0], non_finite[0]),
            ("candidate", candidate, non_null[1], non_finite[1]),
        )
        if (value is None and n > 0)
        or (isinstance(value, float) and not math.isfinite(value) and bad == 0)
    ]
    if isinstance(legacy, float) or isinstance(candidate, float):
        a = None if legacy is None else float(legacy)
        b = None if candidate is None else float(candidate)
        if a is None or b is None:
            matches = a is None and b is None
        else:
            tolerance = policy.rel_tolerance if policy.kind is PolicyKind.FLOAT_REL else 0.0
            matches = _rel_close(a, b, tolerance or 0.0)
    else:
        matches = legacy == candidate  # decimal equality ignores scale
    check = TotalCheck(
        column=column,
        legacy=number_text(legacy),
        candidate=number_text(candidate),
        matches=matches and not errors,
    )
    return check, errors


def _partition_counts(
    legacy: DataFrame,
    candidate: DataFrame,
    partition_by: Sequence[str],
    policy: Callable[[str], ComparisonPolicy],
    use_collations: bool,
) -> list[PartitionCount]:
    """
    Count rows per partition value, grouping and matching under each column's policy.

    Under ``exact``, 'MOT ' and 'MOT' are separate partitions; under ``ci_rtrim`` they are one.
    A partition is labelled with a value as given, not its normalised form: the smallest raw
    value in the group, legacy's if legacy has the partition, so the label is deterministic.

    Returns:
        One count per partition value found on either side, sorted by its label.
    """

    def side_counts(df: DataFrame, tag: str) -> DataFrame:
        """
        Count one side's rows per normalised partition value, in columns tagged ``l`` or ``r``.
        """
        groups = [
            normalise(_c(c), policy(c), use_collations=use_collations).alias(f"_{tag}p{i}")
            for i, c in enumerate(partition_by)
        ]
        shown = [F.min(_c(c)).alias(f"_{tag}v{i}") for i, c in enumerate(partition_by)]
        return df.groupBy(*groups).agg(F.count(F.lit(1)).alias(f"_{tag}n"), *shown)

    on = reduce(
        and_,
        [F.col(f"_lp{i}").eqNullSafe(F.col(f"_rp{i}")) for i in range(len(partition_by))],
    )
    joined = side_counts(legacy, "l").join(side_counts(candidate, "r"), on=on, how="full_outer")
    counts = []
    for row in joined.collect():
        tag = "l" if row["_ln"] is not None else "r"
        label = ", ".join(
            f"{c}={row[f'_{tag}v{i}']!r}" if row[f"_{tag}p{i}"] is not None else f"{c}=NULL"
            for i, c in enumerate(partition_by)
        )
        counts.append(
            PartitionCount(partition=label, legacy=row["_ln"] or 0, candidate=row["_rn"] or 0)
        )
    return sorted(counts, key=lambda p: p.partition)


def _jsonable(value: Any) -> Any:
    """
    Make a sampled value safe for JSON: decimals, non-finite doubles, dates and bytes as text.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@contextlib.contextmanager
def _timed(timings: dict[str, float], step: str) -> Iterator[None]:
    """
    Time the enclosed block, recording its seconds under ``step`` even if it raises.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[step] = round(time.perf_counter() - start, 3)


def compare(
    legacy_df: DataFrame,
    candidate_df: DataFrame,
    keys: Sequence[str],
    policies: Mapping[str, ComparisonPolicy] | None = None,
    *,
    partition_by: Sequence[str] = (),
    sample_rows: int = 5,
    use_collations: bool = True,
) -> ReconResult:
    """
    Reconcile a candidate output against its legacy (golden) output, plan §8.6.

    ``keys`` may be empty: the outputs are then compared as multisets, joined on every
    compared column. Columns without a policy are compared ``exact``. ``exclude`` and
    ``surrogate`` columns are neither compared nor totalled.

    Args:
        legacy_df: The legacy output.
        candidate_df: The migrated job's output.
        keys: The key columns; empty for a multiset comparison.
        policies: The comparison policy per column; a column left out is compared ``exact``.
        partition_by: Columns to count rows by, as well as in total.
        sample_rows: The most sample rows to keep per differing column.
        use_collations: Whether the text policies use collations, or the plain-string
            fallback.

    Returns:
        Everything the checks found, including the lazy per-row frame.

    Raises:
        ValueError: If the inputs or policies are invalid, or there is nothing to join on.
    """
    started_at = datetime.now(UTC)
    timings: dict[str, float] = {}
    keys = list(keys)
    chosen = dict(policies or {})
    _validate(legacy_df, candidate_df, keys, chosen, partition_by)

    def policy(name: str) -> ComparisonPolicy:
        """
        Give a column's chosen policy, or ``exact`` when none was chosen.
        """
        return chosen.get(name, EXACT)

    # 1. schema, on the types as given, so a stray collated column shows up as a mismatch;
    #    then strip collations, so exact really is binary equality
    with _timed(timings, "schema"):
        schema = _schema_diff(legacy_df, candidate_df)
        legacy, candidate = plain_strings(legacy_df), plain_strings(candidate_df)
        ltypes = {f.name: f.dataType for f in legacy.schema.fields}
        ctypes = {f.name: f.dataType for f in candidate.schema.fields}
        common = [c for c in legacy.columns if c in ctypes]
        compared = [c for c in common if c not in keys and policy(c).kind not in _NOT_COMPARED]
        join_cols = keys or compared
        value_cols = compared if keys else []
        if not join_cols:
            raise ValueError("nothing to join on: no keys and no compared columns")
        if not keys and any(policy(c).kind is PolicyKind.FLOAT_REL for c in compared):
            log.warning("multiset comparison joins on every column: float_rel acts as exact")

    # 2 and 3. counts and totals, in one aggregate per side
    errors: list[str] = []
    with _timed(timings, "counts_totals"):
        numeric = [
            c
            for c in common
            if policy(c).kind not in _NOT_COMPARED
            and isinstance(ltypes[c], _NUMERIC)
            and isinstance(ctypes[c], _NUMERIC)
        ]
        legacy_n, legacy_totals, legacy_nn, legacy_nf = _side_stats(legacy, numeric)
        candidate_n, candidate_totals, candidate_nn, candidate_nf = _side_stats(candidate, numeric)
        totals = []
        for c in numeric:
            check, problems = _total_check(
                c,
                legacy_totals[c],
                candidate_totals[c],
                (legacy_nn[c], candidate_nn[c]),
                (legacy_nf[c], candidate_nf[c]),
                policy(c),
            )
            totals.append(check)
            errors += problems
        by_partition = (
            _partition_counts(legacy, candidate, partition_by, policy, use_collations)
            if partition_by
            else []
        )
        counts = CountCheck(legacy=legacy_n, candidate=candidate_n, by_partition=by_partition)

    # 4 to 7. number duplicate keys within each side, full outer join on the normalised keys
    #    (null-safe) plus that number, compare each column, and give every row a status; a
    #    key whose type differs between the sides (and isn't numeric on both) joins as text,
    #    since under ANSI mode an implicit cast raises on the first value that won't parse
    as_text = {
        c
        for c in join_cols
        if ltypes[c] != ctypes[c]
        and not (isinstance(ltypes[c], _NUMERIC) and isinstance(ctypes[c], _NUMERIC))
    }

    def side(df: DataFrame, name: str, tag: str) -> DataFrame:
        """
        Prepare one side for the join: its normalised keys, a duplicate number and its values.

        The duplicate number counts rows within each normalised key, ordered by the normalised
        compared values, so duplicates pair up in the join instead of multiplying it.
        """
        norms = [
            normalise(
                _c(c).cast("string") if c in as_text else _c(c),
                policy(c),
                use_collations=use_collations,
            )
            for c in join_cols
        ]
        order = [
            normalise(_c(c), policy(c), use_collations=use_collations).asc_nulls_first()
            for c in value_cols
            if not isinstance(df.schema[c].dataType, T.MapType)
        ] + [
            _c(c).asc_nulls_first()
            for c in df.columns
            if policy(c).kind in _NOT_COMPARED and not isinstance(df.schema[c].dataType, T.MapType)
        ]
        window = Window.partitionBy(*norms).orderBy(*(order or [F.lit(1)]))
        return df.select(
            *[n.alias(f"_{tag}k{i}") for i, n in enumerate(norms)],
            (F.row_number().over(window) - 1).alias(f"_{tag}dup"),
            F.lit(True).alias(f"_in_{name}"),
            *[_c(c).alias(f"{c}__{name}") for c in df.columns],
        )

    with _timed(timings, "join_compare"):
        on = reduce(
            and_,
            [F.col(f"_lk{i}").eqNullSafe(F.col(f"_rk{i}")) for i in range(len(join_cols))],
        ) & (F.col("_ldup") == F.col("_rdup"))
        joined = side(legacy, "legacy", "l").join(
            side(candidate, "candidate", "r"), on=on, how="full_outer"
        )
        in_legacy = F.col("_in_legacy").isNotNull()
        in_candidate = F.col("_in_candidate").isNotNull()
        joined = joined.withColumns(
            {
                f"_d{i}": in_legacy
                & in_candidate
                & ~values_equal(
                    _c(f"{c}__legacy"),
                    _c(f"{c}__candidate"),
                    policy(c),
                    ltypes[c],
                    ctypes[c],
                    use_collations=use_collations,
                )
                for i, c in enumerate(value_cols)
            }
        )
        diff_columns = (
            F.filter(
                F.array(*[F.when(F.col(f"_d{i}"), F.lit(c)) for i, c in enumerate(value_cols)]),
                lambda x: x.isNotNull(),
            )
            if value_cols
            else F.array().cast("array<string>")
        )
        joined = joined.withColumn("_diff_columns", diff_columns).withColumn(
            "_status",
            F.when(~in_candidate, MISSING)
            .when(~in_legacy, EXTRA)
            .when(F.size("_diff_columns") > 0, VALUE_DIFF)
            .otherwise(MATCH),
        )
        aggs = [F.count(F.when(F.col("_status") == s, 1)).alias(s) for s in STATUSES]
        aggs += [
            F.count(F.when(F.col(f"_d{i}"), 1)).alias(f"_d{i}") for i in range(len(value_cols))
        ]
        if keys:
            null_l = reduce(or_, [F.col(f"_lk{i}").isNull() for i in range(len(keys))])
            null_r = reduce(or_, [F.col(f"_rk{i}").isNull() for i in range(len(keys))])
            aggs += [
                F.count(F.when(F.col("_ldup") == 1, 1)).alias("_ldupkeys"),
                F.count(F.when(F.col("_rdup") == 1, 1)).alias("_rdupkeys"),
                F.count(F.when(in_legacy & null_l, 1)).alias("_lnull"),
                F.count(F.when(in_candidate & null_r, 1)).alias("_rnull"),
            ]
        stats = joined.agg(*aggs).first()
        assert stats is not None
        rows = RowCounts(
            matched=stats[MATCH],
            value_diff=stats[VALUE_DIFF],
            missing=stats[MISSING],
            extra=stats[EXTRA],
        )
        mismatches = {c: stats[f"_d{i}"] for i, c in enumerate(value_cols)}
        key_integrity = (
            KeyIntegrity(
                legacy_duplicate_keys=stats["_ldupkeys"],
                candidate_duplicate_keys=stats["_rdupkeys"],
                legacy_null_keys=stats["_lnull"],
                candidate_null_keys=stats["_rnull"],
            )
            if keys
            else KeyIntegrity()
        )
        values_out = []
        for c in [*legacy.columns, *[c for c in candidate.columns if c not in ltypes]]:
            if c in ltypes:
                values_out.append(_c(f"{c}__legacy"))
            if c in ctypes:
                values_out.append(_c(f"{c}__candidate"))

        def key_as_given(k: str) -> Column:
            """
            Give a row's key as the legacy side holds it, or the candidate's for an extra row.

            The join used the policy-normalised key, which may not be the value given: the
            fallback lower-cases and trims it, and ``blank_is_null`` trims it. A key whose types
            differ comes out as text, as it was joined.
            """
            sides = [_c(f"{k}__legacy"), _c(f"{k}__candidate")]
            return F.coalesce(*[s.cast("string") if k in as_text else s for s in sides])

        rows_df = joined.select(
            *[key_as_given(k).alias(k) for k in keys],
            F.coalesce(F.col("_ldup"), F.col("_rdup")).alias("_dup"),
            "_status",
            "_diff_columns",
            *values_out,
        )

    # samples: up to sample_rows rows per differing column, in one query
    column_diffs: list[ColumnDiff] = []
    with _timed(timings, "samples"):
        differing = [c for c in value_cols if mismatches[c]]
        samples: dict[str, list[dict[str, Any]]] = {c: [] for c in differing}
        if differing and sample_rows > 0:
            exploded = rows_df.where(F.col("_status") == VALUE_DIFF).select(
                "*", F.explode("_diff_columns").alias("_column")
            )
            window = Window.partitionBy("_column").orderBy(
                *[_c(k).asc_nulls_first() for k in keys], "_dup"
            )
            picked = (
                exploded.withColumn("_rn", F.row_number().over(window))
                .where(F.col("_rn") <= sample_rows)
                .collect()
            )
            for row in sorted(picked, key=lambda r: (r["_column"], r["_rn"])):
                sample = {k: _jsonable(row[f"{k}__legacy"]) for k in keys}
                sample |= {
                    "legacy": _jsonable(row[f"{row['_column']}__legacy"]),
                    "candidate": _jsonable(row[f"{row['_column']}__candidate"]),
                }
                samples[row["_column"]].append(sample)
        column_diffs = [
            ColumnDiff(column=c, policy=policy(c).kind, n_rows=mismatches[c], samples=samples[c])
            for c in differing
        ]

    return ReconResult(
        keys=keys,
        policies={c: policy(c) for c in common},
        schema=schema,
        counts=counts,
        totals=totals,
        key_integrity=key_integrity,
        rows=rows,
        column_mismatches=mismatches,
        column_diffs=column_diffs,
        rows_df=rows_df,
        started_at=started_at,
        timings=timings,
        errors=errors,
    )


### Cross-check with datacompy, and the Delta round trip


@dataclass(frozen=True)
class DatacompySummary:
    """
    What datacompy's ``PandasCompare`` found, in the engine's terms.
    """

    intersect_rows: int
    legacy_only: int
    candidate_only: int
    matching_rows: int
    column_mismatches: dict[str, int]


def datacompy_summary(
    legacy_df: DataFrame,
    candidate_df: DataFrame,
    keys: Sequence[str],
    *,
    ignore_case: bool = False,
    ignore_spaces: bool = False,
) -> DatacompySummary:
    """
    Run datacompy's ``PandasCompare`` on the same data, with zero tolerances.

    datacompy can only cross-check ``exact`` policies: its ``ignore_case`` never applies to
    join columns, and its ``ignore_spaces`` strips leading whitespace too.

    Args:
        legacy_df: The legacy output.
        candidate_df: The candidate output.
        keys: The join columns.
        ignore_case: Passed on to datacompy, which then upper-cases text before comparing.
        ignore_spaces: Passed on to datacompy, which then strips text before comparing.

    Returns:
        What datacompy found.
    """
    import datacompy

    result = datacompy.PandasCompare(
        legacy_df.toPandas(),
        candidate_df.toPandas(),
        join_columns=list(keys),
        abs_tol=0,
        rel_tol=0,
        df1_name="legacy",
        df2_name="candidate",
        ignore_case=ignore_case,
        ignore_spaces=ignore_spaces,
    )
    return DatacompySummary(
        intersect_rows=len(result.intersect_rows),
        legacy_only=len(result.df1_unq_rows),
        candidate_only=len(result.df2_unq_rows),
        matching_rows=int(result.count_matching_rows()),
        column_mismatches={
            str(s["column"]): int(s["unequal_cnt"])
            for s in result.column_stats
            if s["column"] not in keys
        },
    )


def disagreements(result: ReconResult, summary: DatacompySummary) -> list[str]:
    """
    List every way the engine and datacompy disagree.

    Args:
        result: The engine's result under ``exact`` policies.
        summary: datacompy's result on the same data.

    Returns:
        One message per disagreement. An empty list means they agree.
    """
    pairs = {
        "rows in common": (result.rows.matched + result.rows.value_diff, summary.intersect_rows),
        "only in legacy": (result.rows.missing, summary.legacy_only),
        "only in candidate": (result.rows.extra, summary.candidate_only),
        "matching rows": (result.rows.matched, summary.matching_rows),
        "compared columns": (sorted(result.column_mismatches), sorted(summary.column_mismatches)),
    }
    found = [
        f"{what}: engine {ours} vs datacompy {theirs}"
        for what, (ours, theirs) in pairs.items()
        if ours != theirs
    ]
    for column, ours in result.column_mismatches.items():
        theirs = summary.column_mismatches.get(column)
        if theirs is not None and ours != theirs:
            found.append(f"{column} mismatches: engine {ours} vs datacompy {theirs}")
    return found


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
