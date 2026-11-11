"""Spike 0.4 (SAS): a saspy round trip of awkward values, with explicit informats and formats.

Everything runs in one SAS OnDemand session, which the spike always ends:

1. It uploads about 20 planted rows and reads them with explicit informats.
2. A DATA step copies them and adds ``total = sum(a, b)`` and ``plus = a + b``.
3. It exports with explicit formats (BEST32., YYMMDD10., E8601DT26.6, $CHARw.) plus HEX16.,
   downloads, parses back to typed pandas and compares every value with what was expected.
4. A bulk probe measures, over thousands of values, whether SAS reads decimal text exactly
   and how often BEST32. text alone loses a double.
5. A calendar probe compares SAS day numbers with Python's around the leap days SAS skips.

It needs saspy set up for SAS OnDemand (README.md setup step 5). Results are written up in
spikes/README.md ("SAS round trip").

Usage:
    uv run python spikes/sas_roundtrip.py [--out DIR] [--probe-rows N] [--seed N]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from lansh.engines.sas import (
    ROW_SEQ,
    SasSession,
    export_table,
    float_to_hex16,
    parse_export,
    upload_table,
)

REMOTE_PARTS = ("lansh", "spike")
# sum() skips a missing operand, while + makes the whole result missing
TRANSFORM = """\
data work.planted_out;
  set work.planted;
  total = sum(a, b);
  plus = a + b;
run;
"""
# ?? reads text that isn't a number as missing without an error, so the probe can count it
PROBE_STEP = """\
data work.probe_out;
  set work.probe;
  x = input(txt, ?? BEST32.);
run;
"""

# n is the raw SAS day number; d is the same number with a date format, exported as its label
CALENDAR_STEP = """\
data work.calendar_out;
  set work.calendar;
  d = input(txt, ?? YYMMDD10.);
  n = d;
  format d YYMMDD10.;
run;
"""
# leap days under the century rule (1600, 1700, 2000, 2400) and in years divisible by 4000,
# up to the 9999-12-31 sentinel: where SAS's calendar might part from Python's
CALENDAR = ["1600-02-29", "1700-02-28", "1700-03-01", "2000-02-29", "2400-02-29", "3999-12-31",
            "4000-02-28", "4000-02-29", "4000-03-01", "4000-12-31", "8000-02-28", "8000-02-29",
            "8000-03-01", "9999-12-31"]  # fmt: skip

# 200 characters with fadas, which take 220 bytes in UTF-8: SAS lengths are bytes
LONG_200 = ("Siobhán Ní Bhriain agus Seán Ó Briain; " * 6)[:200]

### The planted rows

INT_VAL = [0, 1, -1, 42, 2**31 - 1, -(2**31), 2**53 - 1, 2**53, -(2**53), None,
           10**15, 123456789012345, -7, 100, 999, 2**40, 65535, -65536, 31, 12]  # fmt: skip
MONEY = ["0.00", "0.10", "0.20", "-0.01", "-1234.56", "1234567.89", "0.07", "2.68", "1.01",
         "99999999.99", None, "0.30", "-0.10", "19.99", "0.01", "1234567890123.45",
         "123456789012345.68", "-0.50", "5.55", "-99999999.99"]  # fmt: skip
DBL = [0.1 + 0.2, 1 / 3, 2 / 3, math.pi, math.e, 1 + 2**-52, 123456789.12345678, 1e-07, 1e20,
       -0.0, 0.1, None, -2.5, 1e-300, 9.999999999999998, 0.12345678901234568,
       3000000000.0000005, 1e300, -1.0000000000000002, 4.35]  # fmt: skip
A = [0.1, 1.0, None, None, -1.5, 1e16, 0.7, 2.0**53, 5.0, -0.0,
     -0.0, 1e-300, 123.456, -2.5, 0.0, 1.1, 100.0, None, 1e-07, 0.3]  # fmt: skip
B = [0.2, None, 2.0, None, 1.5, 1.0, 0.1, 1.0, -5.0, 0.0,
     -0.0, 1e-300, 0.004, None, 0.0, 2.2, 0.01, -0.5, 1e-07, -0.1]  # fmt: skip
D = [date(1960, 1, 1), date(1959, 12, 31), date(2024, 2, 29), date(2025, 12, 31), None,
     date(1582, 10, 15), date(9999, 12, 31), date(2000, 2, 29), date(1900, 3, 1),
     date(2019, 1, 1), date(2025, 1, 1), date(2024, 12, 31), date(2023, 2, 28),
     date(2020, 2, 29), date(1970, 1, 1), date(2038, 1, 19), date(2100, 3, 1),
     date(1582, 1, 1), date(2025, 6, 30), date(1999, 12, 31)]  # fmt: skip
TS = [datetime(1960, 1, 1), datetime(1959, 12, 31, 23, 59, 59), datetime(2024, 2, 29, 23, 59, 59),
      datetime(2025, 12, 31), None, datetime(2024, 6, 30, 12, 34, 56, 123456),
      datetime(2025, 1, 1, 0, 0, 0, 999999), datetime(1999, 12, 31, 23, 59, 59, 500000),
      datetime(2025, 12, 31, 23, 59, 59, 999999), datetime(1970, 1, 1),
      datetime(2000, 1, 1, 0, 0, 0, 1), datetime(1939, 6, 7, 13, 48, 3, 939733),
      datetime(2038, 1, 19, 3, 14, 7), datetime(2019, 1, 1, 9, 30), datetime(2024, 3, 31, 1),
      datetime(2024, 10, 27, 1, 30), datetime(1900, 1, 1, 0, 0, 0, 1),
      datetime(2120, 1, 1, 0, 0, 0, 1), datetime(1959, 12, 31, 23, 59, 59, 500000),
      datetime(2025, 7, 4, 23, 59, 59)]  # fmt: skip
S = ["plain", "trailing  ", "  leading", " both ", "has,comma", 'has "quote"',
     '"starts with a quote', "O'Brien", "Seán Ó Briain", "Siobhán", "", None, "   ", ".",
     "tab\there", "€100", LONG_200, "007", "MEDIUM", "ÁÉÍÓÚ áéíóú"]  # fmt: skip


def planted_frame() -> pd.DataFrame:
    """
    Build the 20 planted rows, deliberately in reverse ``_row_seq`` order.

    The CSV writer sorts by ``_row_seq``, so the reversal checks that the SAS data set still
    comes out in that order.

    Returns:
        The planted rows: ``_row_seq`` and one column per planted list.
    """
    frame = pd.DataFrame(
        {
            ROW_SEQ: pd.array(range(1, 21), dtype="Int64"),
            "int_val": pd.array(INT_VAL, dtype="Int64"),
            "money": [None if m is None else Decimal(m) for m in MONEY],
            "dbl": [math.nan if v is None else v for v in DBL],
            "a": [math.nan if v is None else v for v in A],
            "b": [math.nan if v is None else v for v in B],
            "d": D,
            "ts": pd.Series(TS, dtype="datetime64[us]"),
            "s": pd.array(S, dtype="string"),
        }
    )
    return frame.iloc[::-1].reset_index(drop=True)


def _num(v: Any) -> float | None:
    """
    Turn a planted number into the float SAS holds, keeping None for missing.
    """
    if v is None:
        return None
    return float(v)


def _sas_text(s: str | None) -> str | None:
    """
    Give the value SAS returns for a planted string.

    SAS values are blank-padded, so trailing blanks are lost, and a blank value is missing.
    """
    if s is None or s.strip(" ") == "":
        return None
    return s.rstrip(" ")


def expected_columns() -> dict[str, list[Any]]:
    """
    Work out what each output column should hold after SAS.

    ``total`` follows SAS's ``sum()``, which skips a missing operand, and ``plus`` follows
    ``+``, which makes the result missing when either operand is.

    Returns:
        The expected values per column, in ``_row_seq`` order.
    """
    total = []
    plus = []
    for a, b in zip(A, B, strict=True):
        present = [v for v in (a, b) if v is not None]
        total.append(None if not present else (present[0] if len(present) == 1 else a + b))
        plus.append(None if a is None or b is None else a + b)
    return {
        ROW_SEQ: [float(i) for i in range(1, 21)],
        "int_val": [_num(v) for v in INT_VAL],
        "money": [_num(None if m is None else Decimal(m)) for m in MONEY],
        "dbl": [_num(v) for v in DBL],
        "a": [_num(v) for v in A],
        "b": [_num(v) for v in B],
        "d": list(D),
        "ts": list(TS),
        "s": [_sas_text(v) for v in S],
        "total": total,
        "plus": plus,
    }


# the planted values as written, before SAS semantics changed any of them
ORIGINAL: dict[str, list[Any]] = {
    "int_val": INT_VAL,
    "money": MONEY,
    "dbl": DBL,
    "a": A,
    "b": B,
    "d": D,
    "ts": TS,
    "s": S,
}

### Comparison


def _cell(value: Any) -> Any:
    """
    Turn a frame cell into plain Python, with every missing marker as None.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float):  # numpy float64 included
        return None if math.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def same(expected: Any, got: Any) -> bool:
    """
    Tell whether two values are exactly equal, with doubles compared bit for bit.

    Comparing the IEEE bits keeps -0.0 apart from 0.0. Two missing values count as equal.

    Args:
        expected: The value SAS should have returned, or None for missing.
        got: The value that came back, or None for missing.

    Returns:
        True if the two values are identical.
    """
    if expected is None or got is None:
        return expected is None and got is None
    if isinstance(expected, float) and isinstance(got, float):
        return float_to_hex16(expected) == float_to_hex16(got)
    return bool(expected == got)


def compare(frame: pd.DataFrame, expected: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Find, per column, the rows where a parsed export differs from what was expected.

    Args:
        frame: The export parsed back into pandas, in ``_row_seq`` order.
        expected: The expected values per column, from :func:`expected_columns`.

    Returns:
        For every expected column, its differing rows as ``row_seq``, ``expected`` and
        ``got``. An empty list means the whole column matched.
    """
    diffs: dict[str, list[dict[str, Any]]] = {}
    for column, want in expected.items():
        got = [_cell(v) for v in frame[column].tolist()]
        rows = []
        for i, (w, g) in enumerate(zip(want, got, strict=True), start=1):
            if not same(w, g):
                rows.append({"row_seq": i, "expected": w, "got": g})
        diffs[column] = rows
    return diffs


def what_changed(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """
    List the values that came back different from the planted originals.

    Most changes are SAS semantics, by design: trailing blanks go, a blank value becomes
    missing, and money keeps 17 significant digits. A value that came back missing is
    listed too.

    Args:
        frame: The export parsed back into pandas, in ``_row_seq`` order.

    Returns:
        One entry per changed value with its ``column``, ``row_seq``, ``original`` and
        ``got``, plus ``why`` where the reason is known.
    """
    changed: list[dict[str, Any]] = []
    got_rows = {c: [_cell(v) for v in frame[c].tolist()] for c in ORIGINAL}
    for column, originals in ORIGINAL.items():
        for i, original in enumerate(originals, start=1):
            got = got_rows[column][i - 1]
            # a missing value can't be read as money or an integer; the plain comparison
            # below lists it instead
            if column == "money" and original is not None and got is not None:
                kept = Decimal(repr(got)).quantize(Decimal("0.01")) == Decimal(original)
                if not kept:
                    changed.append({"column": column, "row_seq": i, "original": original,
                                    "got": repr(got), "why": "17 significant digits"})  # fmt: skip
                continue
            if column == "int_val" and original is not None and got is not None:
                if int(got) != original:
                    changed.append({"column": column, "row_seq": i, "original": original,
                                    "got": got, "why": "integer"})  # fmt: skip
                continue
            want = float(original) if isinstance(original, float) else original
            if not same(want, got):
                changed.append({"column": column, "row_seq": i, "original": original, "got": got})
    return changed


def show(value: Any) -> str:
    """
    Format a value for the report: a double with its HEX16. bits, a long string shortened.

    Args:
        value: Any value from the comparison.

    Returns:
        The value's ``repr``, with the bits added or the text cut to 20 characters.
    """
    if isinstance(value, float):
        return f"{value!r} [{float_to_hex16(value)}]"
    if isinstance(value, str) and len(value) > 40:
        return f"{value[:20]!r}…({len(value)} chars)"
    return repr(value)


### The bulk probe

# subnormals, the smallest and largest normal doubles, and values that are hard to read or
# print exactly: 17 significant digits, integers beyond 2**53, 1e22 and 1e23
EXTREMES = [5e-324, 1e-320, 2.225073858507201e-308, 2.2250738585072014e-308, 1e-300,
            1.7976931348623157e308, -1.7976931348623157e308, 1e308, -5e-324, 4.9e-324,
            2.0**-1022, 0.1 + 0.2, 1 / 3, 9007199254740993.0, 1e22, 1e23]  # fmt: skip


def probe_frame(rows: int, seed: int) -> pd.DataFrame:
    """
    Build the bulk probe: random numbers as text, each with a random datetime, then extremes.

    The random rows take turns between four kinds: money with 2 decimal places, doubles of
    random magnitude, random 64-bit patterns and integers within ±2**53. Their datetimes fall
    between 1900 and 2090 with random microseconds. The extremes all use 1960-01-01.

    Args:
        rows: How many random rows to make before the extremes.
        seed: The random seed, so a run can be repeated exactly.

    Returns:
        The probe rows: ``_row_seq``, ``kind``, the number's text ``txt`` and ``ts``.
    """
    rng = random.Random(seed)
    kinds: list[str] = []
    texts: list[str] = []
    stamps: list[datetime] = []
    epoch = datetime(1960, 1, 1)
    for i in range(rows):
        kind = ("money", "double", "bits", "int")[i % 4]
        if kind == "money":
            cents = rng.randint(-(10**15) + 1, 10**15 - 1)  # up to 13 digits before the point
            sign = "-" if cents < 0 else ""
            text = f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
        elif kind == "double":
            text = repr(rng.uniform(-1, 1) * 10.0 ** rng.randint(-30, 30))
        elif kind == "bits":
            while True:
                x = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
                if math.isfinite(x):
                    break
            text = repr(x)
        else:
            text = str(rng.randint(-(2**53), 2**53))
        kinds.append(kind)
        texts.append(text)
        stamps.append(
            epoch
            + timedelta(
                seconds=rng.randint(-60 * 365 * 86400, 130 * 365 * 86400),
                microseconds=rng.randint(0, 999_999),
            )
        )
    for x in EXTREMES:
        kinds.append("extreme")
        texts.append(repr(x))
        stamps.append(epoch)
    return pd.DataFrame(
        {
            ROW_SEQ: range(1, len(texts) + 1),
            "kind": pd.array(kinds, dtype="string"),
            "txt": pd.array(texts, dtype="string"),
            "ts": pd.Series(stamps, dtype="datetime64[us]"),
        }
    )


def probe_summary(
    probe: pd.DataFrame, exact_frame: pd.DataFrame, text_frame: pd.DataFrame
) -> dict[str, Any]:
    """
    Count, per kind, the probe values SAS read exactly and those that survive as text.

    A value SAS read as missing counts as unreadable. The summary also keeps up to 8 values
    that SAS read inexactly, the worst relative error of the BEST32. text, and how many
    datetimes came back exact through HEX16. and through their text.

    Args:
        probe: The probe rows that were uploaded.
        exact_frame: The probe's export, read through the HEX16. sidecar.
        text_frame: The same export, read from its formatted text alone.

    Returns:
        The summary, as it goes into ``summary.json``.
    """
    by_kind: dict[str, dict[str, int]] = {}
    examples: list[dict[str, Any]] = []
    worst: dict[str, Any] = {"rel": 0.0}
    for i, (kind, text) in enumerate(zip(probe["kind"], probe["txt"], strict=True)):
        want = float(text)
        got = _cell(exact_frame["x"].iloc[i])
        best = _cell(text_frame["x"].iloc[i])
        stats = by_kind.setdefault(kind, {"rows": 0, "read_exact": 0, "unreadable": 0,
                                          "best32_exact": 0})  # fmt: skip
        stats["rows"] += 1
        if got is None:
            stats["unreadable"] += 1
        elif same(want, got):
            stats["read_exact"] += 1
        elif len(examples) < 8:
            examples.append({"kind": kind, "text": text, "sas": show(got), "python": show(want)})
        if best is not None and same(want, best):
            stats["best32_exact"] += 1
        if best is not None and got is not None and got != 0 and math.isfinite(got):
            rel = abs(best - got) / abs(got)
            if rel > worst["rel"]:
                worst.update(rel=rel, text=text, best32=repr(best), exact=repr(got))
    ts_want = [v.to_pydatetime() for v in probe["ts"]]
    ts_exact = sum(
        same(w, _cell(g)) for w, g in zip(ts_want, exact_frame["ts"].tolist(), strict=True)
    )
    ts_text = sum(
        same(w, _cell(g)) for w, g in zip(ts_want, text_frame["ts"].tolist(), strict=True)
    )
    return {
        "by_kind": by_kind,
        "read_mismatch_examples": examples,
        "best32_worst_relative_error": worst,
        "datetimes": {"rows": len(ts_want), "exact_via_hex16": ts_exact, "exact_via_text": ts_text},
    }


### Main


def main() -> int:
    """
    Run the round trip and both probes in one SAS session, then print and save the findings.

    The files, the redacted SAS log and ``summary.json`` go to ``--out``, or to a new
    temporary folder.

    Returns:
        Exit code 0 if, read through HEX16., every value matches SAS semantics exactly and
        the row order was kept; otherwise 1.
    """
    # the description is the module docstring's first line, which is why that docstring keeps
    # its summary on the opening quotes' line instead of following the house layout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="where to keep the files (default: a temp dir)")
    parser.add_argument("--probe-rows", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261110)
    args = parser.parse_args()
    out = args.out or Path(tempfile.mkdtemp(prefix="lansh-sas-spike-"))
    out.mkdir(parents=True, exist_ok=True)

    frame = planted_frame()
    probe = probe_frame(args.probe_rows, args.seed)
    wall = time.perf_counter()
    with SasSession() as sas:
        remote = sas.remote_path(*REMOTE_PARTS)
        sas.ensure_dir(remote)
        uploaded = upload_table(sas, frame, "work.planted", remote_dir=remote, local_dir=out)
        sas.submit(TRANSFORM, label="transform work.planted")
        result = export_table(sas, "work.planted_out", remote_dir=remote, local_dir=out)
        probe_up = upload_table(sas, probe, "work.probe", remote_dir=remote, local_dir=out)
        sas.submit(PROBE_STEP, label="probe: x = input(txt, ?? BEST32.)")
        probe_out = export_table(sas, "work.probe_out", remote_dir=remote, local_dir=out)
        calendar = pd.DataFrame(
            {ROW_SEQ: range(1, len(CALENDAR) + 1), "txt": pd.array(CALENDAR, dtype="string")}
        )
        upload_table(sas, calendar, "work.calendar", remote_dir=remote, local_dir=out)
        sas.submit(CALENDAR_STEP, label="calendar: d = input(txt, ?? YYMMDD10.)")
        calendar_out = export_table(sas, "work.calendar_out", remote_dir=remote, local_dir=out)
        version, encoding = sas.version, sas.encoding
        log_path = sas.write_log(out / "sas.log")
        data_notes = sorted({n for e in sas.logs for n in e.data_notes})
        warnings_seen = sorted({w for e in sas.logs for w in e.warnings})
    wall = time.perf_counter() - wall
    timings = list(sas.timings)  # read after the session has ended, so "end session" is in

    # the same export again, with numbers read from the BEST32. text only (no HEX16. sidecar)
    text_only = parse_export(result.csv_path, result.contents.variables, nobs=result.contents.nobs)
    probe_text = parse_export(
        probe_out.csv_path, probe_out.contents.variables, nobs=probe_out.contents.nobs
    ).frame
    expected = expected_columns()
    exact_diffs = compare(result.frame, expected)
    text_diffs = compare(text_only.frame, expected)

    print(f"SAS {version}, session encoding {encoding}; files in {out}")
    print(f"uploaded {uploaded.rows} planted rows (CSV sha256 {uploaded.sha256[:12]}…)")
    for note in uploaded.warnings:
        print(f"  writer warning: {note}")
    print("\nPROC CONTENTS of work.planted_out:")
    for v in result.contents.variables:
        fmt = f"{v.format or '-'} {v.formatl}.{v.formatd}"
        print(f"  {v.varnum:>2} {v.name:<9} {v.type:<4} len={v.length:<4} {fmt:<14} {v.category}")
    order = [int(x) for x in result.frame[ROW_SEQ]]
    print(f"\nphysical order is _row_seq order: {order == list(range(1, 21))}")
    print(f"dtypes: {dict(result.frame.dtypes.astype(str))}")

    print("\nValue by value against SAS semantics")
    print("(exact = values from the HEX16. sidecar; text-only = BEST32./E8601DT26.6 text alone):")
    for column in expected:
        n = len(expected[column])
        print(f"  {column:<9} exact {n - len(exact_diffs[column]):>2}/{n}   "
              f"text-only {n - len(text_diffs[column]):>2}/{n}")  # fmt: skip
        for d in exact_diffs[column]:
            print(f"    EXACT MISMATCH row {d['row_seq']}: expected {show(d['expected'])}, "
                  f"got {show(d['got'])}")  # fmt: skip
        for d in text_diffs[column]:
            print(
                f"    text-only loses row {d['row_seq']}: {show(d['expected'])} -> {show(d['got'])}"
            )

    print("\nWhat changed from the original values (by design: SAS semantics):")
    changed = what_changed(result.frame)
    for c in changed:
        print(f"  {c['column']} row {c['row_seq']}: {show(c['original'])} -> {show(c['got'])}"
              + (f" ({c['why']})" if "why" in c else ""))  # fmt: skip

    print("\nText-vs-exact differences counted by the parser:", result.text_differs)
    for note in result.warnings:
        print(f"  parser note: {note}")
    print("SAS data notes:", data_notes)
    print("SAS warnings:", warnings_seen)

    summary_probe = probe_summary(probe, probe_out.frame, probe_text)
    print(f"\nBulk probe ({probe_up.rows} values, seed {args.seed}):")
    for kind, stats in summary_probe["by_kind"].items():
        print(f"  {kind:<8} rows={stats['rows']:<5} read exactly={stats['read_exact']:<5} "
              f"unreadable={stats['unreadable']:<3} "
              f"BEST32. text exact={stats['best32_exact']}")  # fmt: skip
    for ex in summary_probe["read_mismatch_examples"]:
        print(f"    read mismatch: {ex}")
    print(f"  datetimes: {summary_probe['datetimes']}")
    print(f"  BEST32. worst relative error: {summary_probe['best32_worst_relative_error']}")

    print("\nCalendar probe (SAS day number vs days after 1960-01-01 in Python/Spark):")
    calendar_rows = []
    for text, label, number in zip(
        CALENDAR, calendar_out.frame["d"].tolist(), calendar_out.frame["n"].tolist(), strict=True
    ):
        python_days = (date.fromisoformat(text) - date(1960, 1, 1)).days
        sas_days = _cell(number)
        row = {
            "text": text,
            "sas_day": None if sas_days is None else int(sas_days),
            "python_day": python_days,
            "difference": None if sas_days is None else python_days - int(sas_days),
            "sas_label": None if _cell(label) is None else str(label),
        }
        calendar_rows.append(row)
        print(f"  {text}: SAS {row['sas_day']}, Python {python_days}, "
              f"difference {row['difference']}, label {row['sas_label']}")  # fmt: skip

    print(f"\nTimings (wall {wall:.1f}s):")
    for label, seconds in timings:
        print(f"  {seconds:6.2f}s  {label}")

    summary = {
        "sas_version": version,
        "session_encoding": encoding,
        "rows": uploaded.rows,
        "row_order_kept": order == list(range(1, 21)),
        "exact_mismatches": {c: len(v) for c, v in exact_diffs.items()},
        "text_only_mismatches": {c: len(v) for c, v in text_diffs.items()},
        "text_differs": result.text_differs,
        "changed_from_original": [{k: str(v) for k, v in c.items()} for c in changed],
        "probe": summary_probe,
        "calendar": calendar_rows,
        "data_notes": data_notes,
        "warnings": warnings_seen,
        "timings": [[label, round(s, 3)] for label, s in timings],
        "wall_seconds": round(wall, 2),
        "log": str(log_path),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    ok = not any(exact_diffs.values()) and order == list(range(1, 21))
    print(f"\n{'PASS' if ok else 'FAIL'}: every value matches SAS semantics exactly via HEX16.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
