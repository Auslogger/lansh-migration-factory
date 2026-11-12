"""
Diff signatures: recognise the patterns known traps leave in a failed comparison (plan §8.6).

Each signature names a pattern, the column that shows it, how many rows show it and a
plain-English explanation; the trap cards (``lansh.discover.traps``) link each pattern to the
traps that cause it. The Diagnoser reads them, and they are the bridge between a reconciliation
failure and the library of engine differences.

Value patterns are found on the rows that differ (``value_diff``):

- ``null_vs_value``: one side is NULL, the other isn't;
- ``trailing_space_split`` and ``case_split``: text that differs only in trailing spaces, or
  only in letter case;
- ``truncated_string``: one value is a prefix of the other;
- ``integer_truncation``: one side equals the other truncated toward zero;
- ``rounding``: numbers one unit apart in the legacy type's last decimal place, or doubles
  within a relative 1e-6;
- ``off_by_one_period``: integers exactly 1 apart, or dates one day, month or year apart;
- ``row_multiplicity``: one value is an exact whole multiple (2 to 10 times) of the other,
  the shape of a join that fans rows out.

Row patterns are found on the rows that have no partner:

- a filter that ignores case or trailing spaces in the legacy engine leaves legacy rows
  missing whose text values are case or space variants of values the kept rows hold;
- ``row_multiplicity`` again, when a key occurs more often on one side;
- ``order_dependence``: the differing values of a column are the same multiset on both
  sides, assigned to different rows.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql import types as T

from lansh.contracts import DiffSignature, DiffSignatureKind
from lansh.reconcile.engine import EXTRA, MATCH, MISSING, VALUE_DIFF, ReconResult

TrapLookup = Callable[[DiffSignatureKind], list[str]]
"""Gives the trap ids whose cards list a signature kind."""

_K = DiffSignatureKind
# collect at most this many distinct values or value pairs per column
_MAX_COLLECT = 20_000
# how strongly each pattern points at a cause, so the clearest comes first
_ORDER = [
    _K.ROW_MULTIPLICITY,
    _K.INTEGER_TRUNCATION,
    _K.CASE_SPLIT,
    _K.TRAILING_SPACE_SPLIT,
    _K.TRUNCATED_STRING,
    _K.OFF_BY_ONE_PERIOD,
    _K.ROUNDING,
    _K.NULL_VS_VALUE,
    _K.ORDER_DEPENDENCE,
]

_WHAT = {
    _K.NULL_VS_VALUE: "one side is NULL and the other has a value",
    _K.TRAILING_SPACE_SPLIT: "the values differ only in trailing spaces",
    _K.CASE_SPLIT: "the values differ only in letter case",
    _K.TRUNCATED_STRING: "one value is a truncated copy of the other",
    _K.INTEGER_TRUNCATION: "one side is the other truncated to a whole number",
    _K.ROUNDING: "the values differ by a rounding step",
    _K.OFF_BY_ONE_PERIOD: "the values are exactly one period apart",
    _K.ROW_MULTIPLICITY: "one value is an exact whole multiple of the other",
    _K.ORDER_DEPENDENCE: "the same values are assigned to different rows",
}


def _c(name: str) -> Column:
    """
    Refer to a column by name, even when the name holds dots or other odd characters.
    """
    return F.col("`" + name.replace("`", "``") + "`")


def _trunc(col: Column) -> Column:
    """
    Truncate a number toward zero, as T-SQL integer division and SAS ``int()`` do.
    """
    return F.when(col >= 0, F.floor(col)).otherwise(F.ceil(col))


def _value_flags(column: str, data_type: T.DataType) -> dict[DiffSignatureKind, Column]:
    """
    Build one condition per pattern a differing column's value pairs can show.

    Returns:
        The conditions, each true on a row whose pair of values shows the pattern.
    """
    lv, rv = _c(f"{column}__legacy"), _c(f"{column}__candidate")
    both = lv.isNotNull() & rv.isNotNull()
    flags = {_K.NULL_VS_VALUE: lv.isNull() != rv.isNull()}
    if isinstance(data_type, T.StringType):
        lt, rt = F.rtrim(lv), F.rtrim(rv)
        flags[_K.TRAILING_SPACE_SPLIT] = both & (lv != rv) & (lt == rt)
        flags[_K.CASE_SPLIT] = both & (lt != rt) & (F.lower(lt) == F.lower(rt))
        flags[_K.TRUNCATED_STRING] = (
            both
            & (F.length(lt) != F.length(rt))
            & (F.startswith(lt, rt) | F.startswith(rt, lt))
            & (F.length(lt) > 0)
            & (F.length(rt) > 0)
        )
    elif isinstance(data_type, (T.IntegerType, T.LongType, T.ShortType, T.ByteType)):
        a, b = lv.cast("double"), rv.cast("double")
        flags[_K.OFF_BY_ONE_PERIOD] = both & (F.abs(a - b) == 1)
        flags[_K.ROW_MULTIPLICITY] = both & _multiple(a, b)
        # an integer legacy value against a fractional candidate: the legacy truncated
        flags[_K.INTEGER_TRUNCATION] = both & (a == _trunc(b)) & (b != _trunc(b))
    elif isinstance(data_type, (T.DecimalType, T.DoubleType, T.FloatType)):
        a, b = lv.cast("double"), rv.cast("double")
        if isinstance(data_type, T.DecimalType):
            unit = 10.0**-data_type.scale
            rounding = both & (F.abs(a - b) <= unit * 1.000001)
        else:
            rounding = both & (F.abs(a - b) <= F.lit(1e-6) * F.greatest(F.abs(a), F.abs(b)))
        flags[_K.ROUNDING] = rounding
        # a difference no bigger than a rounding step is rounding, not a lost fraction
        flags[_K.INTEGER_TRUNCATION] = (
            both
            & ~rounding
            & (((a == _trunc(b)) & (b != _trunc(b))) | ((b == _trunc(a)) & (a != _trunc(a))))
        )
        flags[_K.ROW_MULTIPLICITY] = both & _multiple(a, b)
    elif isinstance(data_type, T.DateType):
        days = F.abs(F.datediff(lv, rv))
        months = F.abs(F.months_between(lv, rv))
        flags[_K.OFF_BY_ONE_PERIOD] = both & (
            (days == 1) | (months == 1) | (months == 12) | (days == 7)
        )
    return flags


def _multiple(a: Column, b: Column) -> Column:
    """
    Hold where one non-zero number is an exact whole multiple, 2 to 10 times, of the other.
    """
    # try_divide: Spark may evaluate the ratio before the non-zero tests, and ANSI raises
    ratio = F.try_divide(F.greatest(F.abs(a), F.abs(b)), F.least(F.abs(a), F.abs(b)))
    return (
        (a != 0)
        & (b != 0)
        & (F.signum(a) == F.signum(b))
        & (ratio >= 1.999999)
        & (ratio <= 10.000001)
        & F.coalesce(F.abs(ratio - F.round(ratio)) < 1e-9, F.lit(False))
    )


def _example(pairs: list[tuple[Any, Any]]) -> str:
    """
    Show one value pair as text, for an explanation.
    """
    if not pairs:
        return ""
    lv, rv = pairs[0]
    return f" (e.g. legacy {lv!r} vs candidate {rv!r})"


def detect(result: ReconResult, traps_for: TrapLookup | None = None) -> list[DiffSignature]:
    """
    Find every recognised pattern in a comparison's differences.

    Masked (``pii``) columns are analysed like any other, but their values never appear in an
    explanation.

    Args:
        result: The comparison, with its lazy per-row frame.
        traps_for: Gives the trap ids linked to a pattern; none are linked when not given.

    Returns:
        The signatures, clearest pattern first; empty for a MATCH.
    """
    if result.is_match or result.errors:
        return []
    rows = result.rows_df
    found: list[DiffSignature] = []
    types = {
        f.name[: -len("__legacy")]: f.dataType
        for f in rows.schema.fields
        if f.name.endswith("__legacy")
    }

    def add(kind: DiffSignatureKind, column: str | None, n: int, why: str) -> None:
        """
        Record one signature, with the traps its kind points at.
        """
        found.append(
            DiffSignature(
                kind=kind,
                column=column,
                n_rows=n,
                explanation=why,
                suspected_traps=sorted(traps_for(kind)) if traps_for else [],
            )
        )

    # value patterns, on the rows that differ, in one aggregate
    differing = [d.column for d in result.column_diffs]
    flags = {c: _value_flags(c, types[c]) for c in differing if c in types}
    if flags:
        diff_rows = rows.where(F.col("_status") == VALUE_DIFF)
        aggs = [
            F.count(F.when(F.array_contains("_diff_columns", c) & cond, 1)).alias(f"{c}|{k}")
            for c, conds in flags.items()
            for k, cond in conds.items()
        ]
        counts = diff_rows.agg(*aggs).first()
        assert counts is not None
        for c, conds in flags.items():
            n_col = result.column_mismatches.get(c, 0)
            for kind in conds:
                n = counts[f"{c}|{kind}"]
                if not n:
                    continue
                share = f"all {n:,}" if n == n_col else f"{n:,} of the {n_col:,}"
                why = f"{kind.value} in {c}: on {share} rows that differ in {c}, {_WHAT[kind]}"
                if kind is _K.ROW_MULTIPLICITY:
                    why += ", as when a join fans each row out over several matches"
                if c not in result.masked:
                    sample = next(
                        (
                            [(s["legacy"], s["candidate"])]
                            for d in result.column_diffs
                            if d.column == c
                            for s in d.samples
                        ),
                        [],
                    )
                    why += _example(sample)
                add(kind, c, n, why + ".")

    # order dependence: the same multiset of values, on different rows
    for c in differing:
        if c not in types:
            continue
        pairs = (
            rows.where(F.array_contains("_diff_columns", c))
            .select(_c(f"{c}__legacy").cast("string"), _c(f"{c}__candidate").cast("string"))
            .limit(_MAX_COLLECT)
            .collect()
        )
        if len(pairs) >= 2 and Counter(p[0] for p in pairs) == Counter(p[1] for p in pairs):
            add(
                _K.ORDER_DEPENDENCE,
                c,
                len(pairs),
                f"order_dependence in {c}: the {len(pairs):,} differing values are the same "
                "on both sides but sit on different rows, as when a de-duplication, RETAIN, "
                "LAG or ranking depends on row order.",
            )

    # rows with no partner
    if result.rows.missing or result.rows.extra:
        dup = rows.where(F.col("_status").isin(MISSING, EXTRA) & (F.col("_dup") > 0)).count()
        if dup:
            add(
                _K.ROW_MULTIPLICITY,
                None,
                dup,
                f"row_multiplicity: {dup:,} unpartnered rows repeat a key or row that the "
                "other side holds fewer times, as when a join fans rows out (or no longer does).",
            )
        for status, side, partner in (
            (MISSING, "legacy", "candidate"),
            (EXTRA, "candidate", "legacy"),
        ):
            n_status = result.rows.missing if status == MISSING else result.rows.extra
            if not n_status:
                continue
            for c, data_type in types.items():
                if not isinstance(data_type, T.StringType):
                    continue
                variants = _filter_variants(rows, c, status, side)
                for kind, (n, example) in variants.items():
                    where = (
                        "legacy rows are missing from the candidate"
                        if status == MISSING
                        else "candidate rows are not in the legacy output"
                    )
                    shown = (
                        "" if c in result.masked else f" (e.g. {example[0]!r} vs {example[1]!r})"
                    )
                    add(
                        kind,
                        c,
                        n,
                        f"{kind.value} filter on {c}: {n:,} {where}, and their {c} values differ "
                        f"only in {'letter case' if kind is _K.CASE_SPLIT else 'trailing spaces'} "
                        f"from values the {partner} side keeps{shown}. The legacy engine's "
                        "comparison (a filter or join) treats them as equal.",
                    )
    return sorted(found, key=lambda s: (_ORDER.index(s.kind), -s.n_rows, s.column or ""))


def _filter_variants(
    rows: Any, column: str, status: str, side: str
) -> dict[DiffSignatureKind, tuple[int, tuple[str, str]]]:
    """
    Count unpartnered rows whose text is a case or space variant of a value the matched rows hold.

    Args:
        rows: The comparison's per-row frame.
        column: A text column.
        status: ``missing`` (legacy rows) or ``extra`` (candidate rows).
        side: ``legacy`` or ``candidate``: the side the unpartnered rows come from.

    Returns:
        For ``case_split`` and ``trailing_space_split``, the number of rows and one example
        pair (unpartnered value, matched value); only the patterns found.
    """
    col = _c(f"{column}__{side}")
    kept = {
        r[0]
        for r in rows.where(F.col("_status").isin(MATCH, VALUE_DIFF))
        .select(col)
        .distinct()
        .limit(_MAX_COLLECT)
        .collect()
        if r[0] is not None
    }
    if not kept:
        return {}
    by_fold: dict[str, str] = {}
    by_trim: dict[str, str] = {}
    for value in sorted(kept):
        by_fold.setdefault(value.rstrip(" ").lower(), value)
        by_trim.setdefault(value.rstrip(" "), value)
    lost = (
        rows.where(F.col("_status") == status)
        .groupBy(col.alias("v"))
        .count()
        .limit(_MAX_COLLECT)
        .collect()
    )
    out: dict[DiffSignatureKind, tuple[int, tuple[str, str]]] = {}
    for row in sorted(lost, key=lambda r: (r["v"] is None, r["v"] or "")):
        value, n = row["v"], row["count"]
        if value is None or value in kept:
            continue
        if value.rstrip(" ") in by_trim:
            kind, partner = _K.TRAILING_SPACE_SPLIT, by_trim[value.rstrip(" ")]
        elif value.rstrip(" ").lower() in by_fold:
            kind, partner = _K.CASE_SPLIT, by_fold[value.rstrip(" ").lower()]
        else:
            continue
        total, example = out.get(kind, (0, (value, partner)))
        out[kind] = (total + n, example)
    return out


def attach(result: ReconResult, traps_for: TrapLookup | None = None) -> ReconResult:
    """
    Detect a comparison's signatures and keep them on the result, for its report.

    Args:
        result: The comparison.
        traps_for: Gives the trap ids linked to a pattern.

    Returns:
        The same result, with ``signatures`` filled in.
    """
    result.signatures = detect(result, traps_for)
    return result
