"""
The reconciliation engine: compare a candidate output with its legacy (golden) output.

The checks run in the order plan §8.6 gives: schema, counts (in total and per partition),
totals of every numeric column, key integrity, a full outer join on the keys with null-safe
equality, a comparison of each column under its policy (§8.4), and a status for every row.
Outputs without keys are compared as multisets, joined on every compared column.

Collations are used **only inside comparisons**: ``ci_rtrim`` compares under Spark's
``UTF8_LCASE_RTRIM`` (SQL Server's case- and trailing-space-insensitive equality) and
``rtrim`` under ``UTF8_BINARY_RTRIM``. Inputs are stripped of collations once the schema check
has seen them, and every frame the engine returns has plain strings, because Delta refuses
collated types and Parquet would keep them. The decisions behind every rule here, and the
gotchas each one avoids, are in ``spikes/README.md`` ("Spark reconciliation").

Column names compare case-insensitively, as in SQL Server, SAS and the contracts: keys,
partition columns, policies and masked columns may be given in any case, and a candidate
column that differs from the legacy one only in case is the same column.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import reduce
from operator import and_, or_
from typing import Any

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from lansh.contracts import (
    Approach,
    ColumnDiff,
    ComparisonPolicy,
    CountCheck,
    DataContract,
    DiffSignature,
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

log = logging.getLogger(__name__)

# equality as in SQL Server under a CI collation: case-insensitive, trailing spaces ignored
CI_RTRIM_COLLATION = "UTF8_LCASE_RTRIM"
# character equality as in SAS: case-sensitive, trailing blanks ignored
RTRIM_COLLATION = "UTF8_BINARY_RTRIM"

MATCH, VALUE_DIFF, MISSING, EXTRA = "match", "value_diff", "missing", "extra"
STATUSES = (MATCH, VALUE_DIFF, MISSING, EXTRA)

EXACT = ComparisonPolicy()
_TEXT_POLICIES = frozenset({PolicyKind.CI_RTRIM, PolicyKind.RTRIM, PolicyKind.BLANK_IS_NULL})
# surrogate_ref is compared through its business key by the caller, never value for value
_NOT_COMPARED = frozenset({PolicyKind.EXCLUDE, PolicyKind.SURROGATE, PolicyKind.SURROGATE_REF})
_NOT_ALLOWED_ON_KEYS = frozenset({PolicyKind.FLOAT_REL, *_NOT_COMPARED})
_INTEGRAL = (T.ByteType, T.ShortType, T.IntegerType, T.LongType)
_FLOATING = (T.FloatType, T.DoubleType)
_NUMERIC = (*_INTEGRAL, *_FLOATING, T.DecimalType)
# the unit roundoff of a double: a sum of n doubles is within (n-1)*eps*sum|x| of exact
_DOUBLE_EPS = 2.0**-53
# a masked sample value: the first characters of the value's SHA-256
_MASK_PREFIX = "pii:"
_MASK_CHARS = 10


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


def refuse_collated(df: DataFrame, what: str) -> None:
    """
    Refuse a frame that is about to be written while it still holds a collated type.

    Args:
        df: The frame about to be written.
        what: What is being written, for the error message.

    Raises:
        ValueError: If any column, at any depth, is collated.
    """
    if bad := collated_columns(df):
        raise ValueError(f"{what}: collated columns can't be written (Delta refuses them): {bad}")


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
        floor = F.lit(policy.abs_tolerance or 0.0)
        # a bare |a-b| <= tol*max(|a|,|b|) would accept NaN vs 1.0 and inf vs 1e308, because
        # Spark orders NaN above everything and treats NaN = NaN as true: guard both
        close = (
            _finite(legacy)
            & _finite(candidate)
            & (
                F.abs(legacy - candidate)
                <= F.greatest(tolerance * F.greatest(F.abs(legacy), F.abs(candidate)), floor)
            )
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


### Names: matched case-insensitively, as the contracts do


def _fold(name: str) -> str:
    """
    Fold a column name so that names compare case-insensitively.
    """
    return name.casefold()


def _check_columns(df: DataFrame, side: str) -> dict[str, str]:
    """
    Map each folded column name of one side to its spelling, refusing names that clash.

    Raises:
        ValueError: If two columns' names differ only in case, or repeat.
    """
    folded: dict[str, str] = {}
    for name in df.columns:
        if _fold(name) in folded:
            raise ValueError(f"{side} has duplicate column names: {folded[_fold(name)]}, {name}")
        folded[_fold(name)] = name
    return folded


def _resolve(names: Sequence[str], folded: Mapping[str, str], what: str, side: str) -> list[str]:
    """
    Spell each wanted name as the frame spells it.

    Raises:
        ValueError: If a name isn't a column of the frame.
    """
    out = []
    for name in names:
        if _fold(name) not in folded:
            raise ValueError(f"{what} {name!r} is not in the {side} output")
        out.append(folded[_fold(name)])
    return out


def _validate(
    legacy: DataFrame,
    candidate: DataFrame,
    keys: Sequence[str],
    policies: Mapping[str, ComparisonPolicy],
) -> None:
    """
    Check the policies and keys, already spelt as the legacy frame spells them.

    Raises:
        ValueError: If a key column repeats, a policy doesn't suit its column's type, or a key
            has a policy keys can't use.
    """
    if len({_fold(k) for k in keys}) != len(keys):
        raise ValueError(f"duplicate key columns: {list(keys)}")
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
    :meth:`to_report` builds the contract's ``ReconReport`` from it directly.

    Attributes:
        keys: The key columns, as the legacy output spells them.
        policies: The policy of every column both sides have.
        column_mismatches: Rows that differ, per compared non-key column (zeros included).
        column_diffs: Only the columns that differ, each with up to five masked samples.
        missing_samples: Up to five masked rows only in the legacy output.
        extra_samples: Up to five masked rows only in the candidate.
        signatures: Recognised patterns in the differences (filled in by
            :mod:`lansh.reconcile.signatures`).
        rows_df: One row per joined row: the keys as given (the legacy side's, or the
            candidate's for an extra row), ``_dup``, ``_status``, ``_diff_columns``, and
            ``<column>__legacy`` and ``<column>__candidate``. Plain strings throughout.
        masked: The columns whose sample values are masked.
    """

    keys: list[str]
    policies: dict[str, ComparisonPolicy]
    schema: SchemaDiff
    counts: CountCheck
    totals: list[TotalCheck]
    key_integrity: KeyIntegrity
    rows: RowCounts
    column_mismatches: dict[str, int]
    column_diffs: list[ColumnDiff]
    missing_samples: list[dict[str, Any]]
    extra_samples: list[dict[str, Any]]
    rows_df: DataFrame
    started_at: datetime
    timings: dict[str, float]
    masked: list[str] = field(default_factory=list)
    signatures: list[DiffSignature] = field(default_factory=list)
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

    @property
    def status(self) -> ReconStatus:
        """
        The verdict: ERROR when a check couldn't complete, else MATCH or MISMATCH.
        """
        if self.errors:
            return ReconStatus.ERROR
        return ReconStatus.MATCH if self.is_match else ReconStatus.MISMATCH

    def explain(self) -> str:
        """
        Say in plain English what the comparison found, for gates, reports and the Diagnoser.

        Returns:
            One paragraph: the verdict, then each kind of difference with its size, the
            totals that differ, and the patterns recognised.
        """
        if self.errors:
            return "The comparison could not be completed: " + "; ".join(self.errors) + "."
        n_l, n_c = self.counts.legacy, self.counts.candidate
        if self.is_match:
            how = f"on the keys {self.keys}" if self.keys else "as multisets (no key)"
            return (
                f"MATCH: all {n_l:,} rows agree record for record, compared {how}; counts, "
                "totals and every compared column agree under their policies."
            )
        parts = [f"MISMATCH: the legacy output has {n_l:,} rows and the candidate {n_c:,}."]
        if not self.schema.ok:
            bits = []
            if self.schema.missing_columns:
                bits.append(f"the candidate lacks {self.schema.missing_columns}")
            if self.schema.extra_columns:
                bits.append(f"it adds {self.schema.extra_columns}")
            bits += [
                f"{m.column} is {m.candidate_type}, not {m.legacy_type}"
                for m in self.schema.type_mismatches
            ]
            parts.append("Schema: " + "; ".join(bits) + ".")
        bad_parts = [p for p in self.counts.by_partition if p.legacy != p.candidate]
        if bad_parts:
            shown = ", ".join(f"{p.partition} ({p.legacy} vs {p.candidate})" for p in bad_parts[:4])
            parts.append(f"Row counts differ in {len(bad_parts)} partitions: {shown}.")
        if self.rows.missing or self.rows.extra:
            parts.append(
                f"{self.rows.missing:,} legacy rows have no partner in the candidate and "
                f"{self.rows.extra:,} candidate rows have none in the legacy output."
            )
        if self.rows.value_diff:
            cols = ", ".join(f"{d.column} ({d.n_rows:,})" for d in self.column_diffs)
            parts.append(f"{self.rows.value_diff:,} matched rows differ in: {cols}.")
        bad_totals = [t for t in self.totals if not t.matches]
        if bad_totals:
            shown = "; ".join(f"{t.column} {t.legacy} vs {t.candidate}" for t in bad_totals[:4])
            parts.append(f"Totals differ (legacy vs candidate): {shown}.")
        for sig in self.signatures:
            parts.append(sig.explanation)
        return " ".join(parts)

    def to_report(
        self,
        job_id: str,
        table: str,
        mode: ReconMode = ReconMode.CANDIDATE,
        *,
        run_id: str | None = None,
        approach: Approach = Approach.LANSH,
        code_sha256: str | None = None,
        contract_sha256: str | None = None,
        golden_sha256: str | None = None,
        candidate_sha256: str | None = None,
    ) -> ReconReport:
        """
        Build the contract's ``ReconReport`` from this result.

        Args:
            job_id: The job whose output was compared.
            table: The output table that was compared.
            mode: How the comparison was set up.
            run_id: The run the comparison belongs to.
            approach: Who or what produced the candidate.
            code_sha256: The candidate job's code.
            contract_sha256: The data contract (keys and policies) the comparison used.
            golden_sha256: The golden output's content hash.
            candidate_sha256: The candidate output's content hash.

        Returns:
            The report, valid under the contract.
        """
        return ReconReport(
            job_id=job_id,
            table=table,
            mode=mode,
            status=self.status,
            run_id=run_id,
            approach=approach,
            code_sha256=code_sha256,
            keys=self.keys,
            schema_diff=self.schema,
            counts=self.counts,
            totals=self.totals,
            key_integrity=self.key_integrity,
            rows=self.rows,
            column_diffs=self.column_diffs,
            missing_samples=self.missing_samples,
            extra_samples=self.extra_samples,
            signatures=self.signatures,
            explanation=self.explain(),
            contract_sha256=contract_sha256,
            golden_sha256=golden_sha256,
            candidate_sha256=candidate_sha256,
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


def _rel_close(a: float, b: float, tolerance: float, floor: float = 0.0) -> bool:
    """
    Tell whether two double totals agree within a relative tolerance or an absolute floor.

    As in :func:`values_equal`, NaN matches only NaN and an infinity only the same infinity:
    with a tolerance, a bare relative check would accept inf against -inf, as inf <= inf.
    """
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return a == b or abs(a - b) <= max(tolerance * max(abs(a), abs(b)), floor)


def _schema_diff(legacy: DataFrame, candidate: DataFrame) -> SchemaDiff:
    """
    Compare the two sides' columns by folded name, and their types as ``simpleString()`` text.

    The candidate has already been renamed to the legacy spelling where names differ only in
    case, so names are reported as the legacy output spells them.
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


@dataclass(frozen=True)
class _Stats:
    """
    One side's row count and per-column totals, from one Spark action.

    Attributes:
        totals: The total per numeric column; None when an integer or decimal total
            overflowed or every value is NULL.
        non_null: Non-NULL values per column.
        non_finite: NaN and infinite values per column; 0 for integers and decimals.
        abs_totals: The sum of absolute values per double column, which bounds the rounding
            error of the double total.
    """

    rows: int
    totals: dict[str, Any]
    non_null: dict[str, int]
    non_finite: dict[str, int]
    abs_totals: dict[str, float]


def _side_stats(df: DataFrame, columns: Sequence[str]) -> _Stats:
    """
    Count one side's rows and total its numeric columns, all in one Spark action.

    Args:
        df: One side's output.
        columns: The numeric columns to total.

    Returns:
        The row count and the totals, as :class:`_Stats`.
    """
    aggs = [F.count(F.lit(1)).alias("_n")]
    for i, name in enumerate(columns):
        data_type = df.schema[name].dataType
        non_finite = F.lit(0)
        abs_total = F.lit(0.0)
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
            as_double = _c(name).cast("double")
            total = F.sum(as_double)
            non_finite = F.count(F.when(~_finite(as_double), 1))
            abs_total = F.sum(F.when(_finite(as_double), F.abs(as_double)))
        aggs += [
            total.alias(f"_t{i}"),
            F.count(_c(name)).alias(f"_c{i}"),
            non_finite.alias(f"_f{i}"),
            abs_total.alias(f"_a{i}"),
        ]
    row = df.agg(*aggs).first()
    assert row is not None
    return _Stats(
        rows=row["_n"],
        totals={name: row[f"_t{i}"] for i, name in enumerate(columns)},
        non_null={name: row[f"_c{i}"] for i, name in enumerate(columns)},
        non_finite={name: row[f"_f{i}"] for i, name in enumerate(columns)},
        abs_totals={name: float(row[f"_a{i}"] or 0.0) for i, name in enumerate(columns)},
    )


def _total_check(
    column: str, legacy: _Stats, candidate: _Stats, policy: ComparisonPolicy
) -> tuple[TotalCheck, list[str]]:
    """
    Compare one column's two totals, reporting a total that overflowed as an error.

    An integer or decimal total overflowed when it is None although the column has values; a
    double total when it isn't finite although every value is. Decimals and integers compare
    exactly, by value, whatever their scale.

    Doubles agree within the column's ``float_rel`` tolerance, or else within the rounding
    error that summing in a different order can cause: ``(n-1) * 2**-53 * sum(|x|)`` per side.
    Spark adds doubles in partition order, which differs between two frames holding the same
    rows, so an exact comparison of double totals would report differences that no row has.
    Every row is still compared under its own policy.

    Returns:
        The contract's check, and an error message for each side whose total overflowed.
    """
    lv, cv = legacy.totals[column], candidate.totals[column]
    errors = [
        f"total of {column!r} overflowed on the {side} side"
        for side, value, stats in (("legacy", lv, legacy), ("candidate", cv, candidate))
        if (value is None and stats.non_null[column] > 0)
        or (isinstance(value, float) and not math.isfinite(value) and stats.non_finite[column] == 0)
    ]
    rel = abs_tol = None
    if isinstance(lv, float) or isinstance(cv, float):
        a = None if lv is None else float(lv)
        b = None if cv is None else float(cv)
        if a is None or b is None:
            matches = a is None and b is None
        else:
            if policy.kind is PolicyKind.FLOAT_REL:
                rel, abs_tol = policy.rel_tolerance, policy.abs_tolerance
            bound = max(
                (max(s.non_null[column], 1) - 1) * _DOUBLE_EPS * s.abs_totals[column]
                for s in (legacy, candidate)
            )
            # a sum of magnitudes that overflowed bounds nothing; fall back to exact
            bound = bound if math.isfinite(bound) else 0.0
            matches = _rel_close(a, b, rel or 0.0, max(abs_tol or 0.0, 2 * bound))
    else:
        matches = lv == cv  # decimal equality ignores scale
    check = TotalCheck(
        column=column,
        legacy=number_text(lv),
        candidate=number_text(cv),
        matches=matches and not errors,
        policy=policy.kind,
        rel_tolerance=rel,
        abs_tolerance=abs_tol,
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


def jsonable(value: Any) -> Any:
    """
    Make a sampled value safe for JSON: decimals, non-finite doubles, dates and bytes as text.

    Args:
        value: A value from a collected Spark row.

    Returns:
        The value, or its text where JSON has no exact form for it.
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
        return [jsonable(v) for v in value]
    return value


def mask_value(value: Any) -> Any:
    """
    Mask one personal value for a sample Claude may see (plan §8.6, data minimisation).

    The value is replaced with the first characters of its SHA-256, so two samples of the
    same value still look the same and nothing of the value itself is shown. NULL stays NULL,
    because whether a value is missing is often the point of the sample.

    Args:
        value: The value to mask.

    Returns:
        None for None, otherwise ``pii:`` and ten hex characters.
    """
    if value is None:
        return None
    digest = hashlib.sha256(str(jsonable(value)).encode("utf-8")).hexdigest()
    return _MASK_PREFIX + digest[:_MASK_CHARS]


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
    keys: Sequence[str] = (),
    policies: Mapping[str, ComparisonPolicy] | None = None,
    *,
    partition_by: Sequence[str] = (),
    sample_rows: int = 5,
    mask: Collection[str] = (),
    use_collations: bool = True,
) -> ReconResult:
    """
    Reconcile a candidate output against its legacy (golden) output, plan §8.6.

    ``keys`` may be empty: the outputs are then compared as multisets, joined on every
    compared column. Columns without a policy are compared ``exact``. ``exclude``,
    ``surrogate`` and ``surrogate_ref`` columns are neither compared nor totalled.

    Args:
        legacy_df: The legacy output.
        candidate_df: The migrated job's output.
        keys: The key columns; empty for a multiset comparison.
        policies: The comparison policy per column; a column left out is compared ``exact``.
        partition_by: Columns to count rows by, as well as in total.
        sample_rows: The most sample rows to keep per differing column, and of missing and
            of extra rows; 0 keeps none (plan §8.6).
        mask: Columns whose values are masked in every sample (the ``pii`` columns).
        use_collations: Whether the text policies use collations, or the plain-string
            fallback.

    Returns:
        Everything the checks found, including the lazy per-row frame.

    Raises:
        ValueError: If the inputs or policies are invalid, or there is nothing to join on.
    """
    started_at = datetime.now(UTC)
    timings: dict[str, float] = {}
    sample_rows = max(0, min(sample_rows, 5))

    # names: the legacy spelling wins; a candidate column differing only in case is renamed
    lfold = _check_columns(legacy_df, "legacy")
    cfold = _check_columns(candidate_df, "candidate")
    renames = {cfold[f]: lfold[f] for f in cfold if f in lfold and cfold[f] != lfold[f]}
    candidate_df = candidate_df.withColumnsRenamed(renames) if renames else candidate_df
    cfold = {f: lfold.get(f, name) for f, name in cfold.items()}
    keys = _resolve(list(keys), lfold, "key column", "legacy")
    _resolve(keys, cfold, "key column", "candidate")
    partition_by = _resolve(list(partition_by), lfold, "partition column", "legacy")
    _resolve(partition_by, cfold, "partition column", "candidate")
    every = lfold | {f: n for f, n in cfold.items() if f not in lfold}
    chosen: dict[str, ComparisonPolicy] = {}
    for name, pol in (policies or {}).items():
        if _fold(name) not in every:
            raise ValueError(f"policies for unknown columns: [{name!r}]")
        chosen[every[_fold(name)]] = pol
    masked = sorted({every[_fold(m)] for m in mask if _fold(m) in every})
    _validate(legacy_df, candidate_df, keys, chosen)

    def policy(name: str) -> ComparisonPolicy:
        """
        Give a column's chosen policy, or ``exact`` when none was chosen.
        """
        return chosen.get(name, EXACT)

    def shown(name: str, value: Any) -> Any:
        """
        Give a sampled value as it may be shown: masked for a pii column, else as JSON.
        """
        return mask_value(value) if name in masked else jsonable(value)

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
        lstats, cstats = _side_stats(legacy, numeric), _side_stats(candidate, numeric)
        totals = []
        for c in numeric:
            check, problems = _total_check(c, lstats, cstats, policy(c))
            totals.append(check)
            errors += problems
        by_partition = (
            _partition_counts(legacy, candidate, partition_by, policy, use_collations)
            if partition_by
            else []
        )
        counts = CountCheck(legacy=lstats.rows, candidate=cstats.rows, by_partition=by_partition)

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

        rows_df = plain_strings(
            joined.select(
                *[key_as_given(k).alias(k) for k in keys],
                F.coalesce(F.col("_ldup"), F.col("_rdup")).alias("_dup"),
                "_status",
                "_diff_columns",
                *values_out,
            )
        )

    # samples: up to sample_rows rows per differing column, and of missing and extra rows
    column_diffs: list[ColumnDiff] = []
    missing_samples: list[dict[str, Any]] = []
    extra_samples: list[dict[str, Any]] = []
    with _timed(timings, "samples"):
        differing = [c for c in value_cols if mismatches[c]]
        samples: dict[str, list[dict[str, Any]]] = {c: [] for c in differing}
        order_keys = [*[_c(k).asc_nulls_first() for k in keys], F.col("_dup")]
        if differing and sample_rows > 0:
            exploded = rows_df.where(F.col("_status") == VALUE_DIFF).select(
                "*", F.explode("_diff_columns").alias("_column")
            )
            window = Window.partitionBy("_column").orderBy(*order_keys)
            picked = (
                exploded.withColumn("_rn", F.row_number().over(window))
                .where(F.col("_rn") <= sample_rows)
                .collect()
            )
            for row in sorted(picked, key=lambda r: (r["_column"], r["_rn"])):
                column = row["_column"]
                sample = {k: shown(k, row[f"{k}__legacy"]) for k in keys}
                sample |= {
                    "legacy": shown(column, row[f"{column}__legacy"]),
                    "candidate": shown(column, row[f"{column}__candidate"]),
                }
                samples[column].append(sample)
        column_diffs = [
            ColumnDiff(column=c, policy=policy(c).kind, n_rows=mismatches[c], samples=samples[c])
            for c in differing
        ]
        for status, cols, out in (
            (MISSING, legacy.columns, missing_samples),
            (EXTRA, candidate.columns, extra_samples),
        ):
            if not sample_rows or not (rows.missing if status == MISSING else rows.extra):
                continue
            suffix = "__legacy" if status == MISSING else "__candidate"
            picked = (
                rows_df.where(F.col("_status") == status)
                .orderBy(*[_c(f"{c}{suffix}").asc_nulls_first() for c in cols])
                .limit(sample_rows)
                .collect()
            )
            out += [{c: shown(c, row[f"{c}{suffix}"]) for c in cols} for row in picked]

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
        missing_samples=missing_samples,
        extra_samples=extra_samples,
        rows_df=rows_df,
        started_at=started_at,
        timings=timings,
        masked=masked,
        errors=errors,
    )


def contract_inputs(contract: DataContract) -> dict[str, Any]:
    """
    Give the comparison settings a data contract defines, as :func:`compare` takes them.

    Args:
        contract: The output's approved data contract.

    Returns:
        ``keys``, ``policies``, ``partition_by`` and ``mask`` (the ``pii`` columns).
    """
    return {
        "keys": list(contract.keys),
        "policies": {c.name: c.policy for c in contract.columns},
        "partition_by": list(contract.partition_columns),
        "mask": [c.name for c in contract.columns if "pii" in c.tags],
    }


### Cross-check with datacompy


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
