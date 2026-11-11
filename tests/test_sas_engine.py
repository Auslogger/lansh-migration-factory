"""
The SAS engine (lansh.engines.sas) moves tables to SAS and back exactly.

Its sessions always end, raise on errors and redact their logs. Everything here runs offline
except ``test_live_round_trip``, which is marked ``sas`` and needs SAS OnDemand through saspy
(``make test-sas``). Values marked "seen on SAS" were observed on SAS 9.4M9 (SAS OnDemand)
during the spike; see spikes/README.md ("SAS round trip").
"""

from __future__ import annotations

import hashlib
import math
import sys
import types
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from lansh.engines.sas import (
    CONTENTS_VARIABLES,
    HEX_OBS,
    META_DATASET,
    ROW_SEQ,
    ColumnKind,
    InputColumn,
    SasCategory,
    SasError,
    SasSession,
    SasVariable,
    check_dataset,
    check_name,
    check_remote_path,
    contents_step,
    date_to_sas,
    datetime_to_sas,
    export_step,
    export_table,
    float_to_hex16,
    format_cell,
    hex16_to_float,
    infer_columns,
    kind_for_logical_type,
    name_literal,
    parse_export,
    read_contents,
    read_step,
    sas_string,
    sas_to_date,
    sas_to_datetime,
    scan_log,
    upload_table,
    write_input_csv,
)

### Names, literals and paths


def test_check_name_accepts_sas_names_and_refuses_the_rest() -> None:
    assert check_name("claim_id") == "claim_id"
    assert check_name(ROW_SEQ) == ROW_SEQ
    for bad in ("1st", "my col", "a" * 33, "_lansh_v", "_N_", "_error_", "café"):
        with pytest.raises(ValueError, match=r"SAS name|reserved"):
            check_name(bad)


def test_literals_and_paths_are_quoted_safely() -> None:
    assert sas_string("O'Brien") == "'O''Brien'"
    assert name_literal("plain") == "plain"
    assert name_literal("my var") == "'my var'n"
    assert name_literal("it's") == "'it''s'n"
    assert check_dataset("work.claims") == "work.claims"
    assert check_remote_path("/home/u1/lansh/x.csv") == "/home/u1/lansh/x.csv"
    for bad_ds in ("toolonglib.x", "work.", "a b"):
        with pytest.raises(ValueError, match="data set name"):
            check_dataset(bad_ds)
    for bad_path in ("lansh/x.csv", "/home/u1/it's.csv", "/a;b", "/a&b", "/a%b", '/a"b'):
        with pytest.raises(ValueError, match="unsafe"):
            check_remote_path(bad_path)
    with pytest.raises(ValueError, match="line break"):
        sas_string("two\nlines")


def test_names_with_a_trailing_newline_are_refused() -> None:
    """
    A pattern ending in ``$`` also matches just before a final line break; the checks must not.
    """
    with pytest.raises(ValueError, match="SAS name"):
        check_name("abc\n")
    with pytest.raises(ValueError, match="data set name"):
        check_dataset("work.x\n")
    # not a V7 name, so it needs a name literal, and a literal can't hold a line break
    with pytest.raises(ValueError, match="line break"):
        name_literal("abc\n")


### Exact numbers, dates and datetimes


def test_hex16_matches_what_sas_writes() -> None:
    # seen on SAS: put(0.1, hex16.) = 3FB999999999999A, and -0.0 keeps its sign bit
    assert float_to_hex16(0.1) == "3FB999999999999A"
    assert float_to_hex16(0.1 + 0.2) == "3FD3333333333334"
    assert float_to_hex16(-0.0) == "8000000000000000"
    assert hex16_to_float("3FD3333333333334") == 0.1 + 0.2
    negative_zero = hex16_to_float("8000000000000000")
    assert negative_zero == 0.0
    assert negative_zero is not None
    assert math.copysign(1.0, negative_zero) == -1.0
    # blanks, a padded "." and the special missing values .A and ._ all read as missing
    for missing in (None, "", "   ", "               .", "A", "_"):
        assert hex16_to_float(missing) is None
    with pytest.raises(ValueError, match="HEX16"):
        hex16_to_float("3FB9")


@pytest.mark.parametrize(
    ("day", "sas_value"),
    [
        (date(1960, 1, 1), 0),
        (date(1959, 12, 31), -1),
        (date(2024, 2, 29), 23435),  # seen on SAS
        (date(1582, 10, 15), -137774),  # seen on SAS
        (date(1600, 2, 29), -131428),  # seen on SAS
        (date(4000, 2, 28), 745153),  # seen on SAS
        (date(4000, 3, 1), 745154),  # seen on SAS: no 29 Feb 4000
        (date(8000, 3, 1), 2206123),  # seen on SAS: no 29 Feb 8000 either
        (date(9999, 12, 31), 2936547),  # seen on SAS; Python counts 2936549 days
    ],
)
def test_sas_calendar(day: date, sas_value: int) -> None:
    """
    Dates convert to SAS day numbers and back, matching the values seen on SAS.
    """
    assert date_to_sas(day) == sas_value
    assert sas_to_date(sas_value) == day


def test_sas_calendar_has_no_29_february_in_years_divisible_by_4000() -> None:
    # Python's calendar keeps both leap days, so it counts two days more than SAS
    assert (date(9999, 12, 31) - date(1960, 1, 1)).days == 2936549
    with pytest.raises(ValueError, match="calendar"):
        date_to_sas(date(4000, 2, 29))
    with pytest.raises(ValueError, match="calendar"):
        format_cell(ColumnKind.DATE, date(8000, 2, 29))


def test_datetimes_round_to_the_nearest_microsecond_exactly() -> None:
    # seen on SAS: E8601DT26.6 printed .939734 for this value, but its bits say .939733
    assert sas_to_datetime(hex16_to_float("C1C35809B607B6D4") or 0.0) == datetime(
        1939, 6, 7, 13, 48, 3, 939733
    )
    assert sas_to_datetime(hex16_to_float("41DE54521C07E6B4") or 0.0) == datetime(
        2024, 6, 30, 12, 34, 56, 123456
    )
    assert sas_to_datetime(-0.5) == datetime(1959, 12, 31, 23, 59, 59, 500000)
    stamp = datetime(2025, 12, 31, 23, 59, 59, 999999)
    assert sas_to_datetime(float(datetime_to_sas(stamp))) == stamp


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_infinite_values_are_outside_pythons_range(value: float) -> None:
    """
    An infinite value raises the documented ValueError, not an OverflowError.
    """
    with pytest.raises(ValueError, match="outside Python's"):
        sas_to_date(value)
    with pytest.raises(ValueError, match="outside Python's"):
        sas_to_datetime(value)


### Input columns and the input CSV


def test_kind_for_logical_type() -> None:
    """
    Each contract logical type maps to a SAS input kind, and a type with none is refused.
    """
    assert kind_for_logical_type("bigint") is ColumnKind.INT
    assert kind_for_logical_type("decimal(18,2)") is ColumnKind.DECIMAL
    assert kind_for_logical_type("double") is ColumnKind.DOUBLE
    assert kind_for_logical_type("boolean") is ColumnKind.BOOL
    assert kind_for_logical_type("date") is ColumnKind.DATE
    assert kind_for_logical_type("timestamp_ntz") is ColumnKind.DATETIME
    assert kind_for_logical_type("string") is ColumnKind.CHAR
    with pytest.raises(ValueError, match="no SAS input kind"):
        kind_for_logical_type("binary")


def test_infer_columns_measures_text_in_utf8_bytes() -> None:
    frame = pd.DataFrame(
        {
            ROW_SEQ: [1, 2],
            "n": pd.array([1, None], dtype="Int64"),
            "amount": [Decimal("1.50"), None],
            "x": [0.5, math.nan],
            "flag": [True, False],
            "d": [date(2024, 1, 1), None],
            "ts": pd.Series([datetime(2024, 1, 1), None], dtype="datetime64[us]"),
            "name": pd.array(["Seán", None], dtype="string"),
        }
    )
    kinds = {c.name: (c.kind, c.length) for c in infer_columns(frame)}
    assert kinds == {
        ROW_SEQ: (ColumnKind.INT, None),
        "n": (ColumnKind.INT, None),
        "amount": (ColumnKind.DECIMAL, None),
        "x": (ColumnKind.DOUBLE, None),
        "flag": (ColumnKind.BOOL, None),
        "d": (ColumnKind.DATE, None),
        "ts": (ColumnKind.DATETIME, None),
        "name": (ColumnKind.CHAR, 5),  # "Seán" is 4 characters, 5 bytes
    }
    assert infer_columns(frame, {"name": 40})[-1].length == 40
    with pytest.raises(ValueError, match="shorter"):
        infer_columns(frame, {"name": 4})
    with pytest.raises(ValueError, match="not character"):
        infer_columns(frame, {"n": 4})
    with pytest.raises(ValueError, match="only nulls"):
        infer_columns(pa.table({ROW_SEQ: [1], "empty": pa.nulls(1)}))


def test_input_column_informats_and_formats() -> None:
    """
    Each kind gets an explicit informat and format, and only character columns take a length.
    """
    text = InputColumn(name="s", kind=ColumnKind.CHAR, length=15)
    assert (text.sas_length, text.informat, text.format) == ("$15", "$CHAR15.", "$CHAR15.")
    money = InputColumn(name="m", kind=ColumnKind.DECIMAL)
    assert (money.sas_length, money.informat, money.format) == ("8", "BEST32.", "BEST32.")
    day = InputColumn(name="d", kind=ColumnKind.DATE)
    assert (day.informat, day.format) == ("YYMMDD10.", "YYMMDD10.")
    stamp = InputColumn(name="t", kind=ColumnKind.DATETIME)
    assert (stamp.informat, stamp.format) == ("E8601DT26.6", "E8601DT26.6")
    with pytest.raises(ValueError, match="needs a length"):
        InputColumn(name="s", kind=ColumnKind.CHAR)
    with pytest.raises(ValueError, match="only character"):
        InputColumn(name="n", kind=ColumnKind.INT, length=8)


def awkward_frame() -> pd.DataFrame:
    """
    Build three rows of awkward values, deliberately out of _row_seq order.
    """
    return pd.DataFrame(
        {
            ROW_SEQ: [3, 1, 2],
            "n": pd.array([-(2**53), 7, None], dtype="Int64"),
            "amount": [Decimal("-0.10"), Decimal("1234.56"), None],
            "x": [0.1 + 0.2, math.nan, -0.0],
            "d": [date(1959, 12, 31), None, date(2024, 2, 29)],
            "ts": pd.Series(
                [datetime(2024, 6, 30, 12, 34, 56, 123456), None, datetime(1960, 1, 1)],
                dtype="datetime64[us]",
            ),
            "s": pd.array(['  say "hi", Seán  ', "", None], dtype="string"),
        }
    )


def test_write_input_csv_dialect(tmp_path: Path) -> None:
    """
    The CSV is in _row_seq order, with NULL as an empty field and every text value quoted.
    """
    written = write_input_csv(awkward_frame(), tmp_path / "t.csv")
    expected = (
        "_row_seq,n,amount,x,d,ts,s\n"
        '1,7,1234.56,,,,""\n'
        "2,,,-0.0,2024-02-29,1960-01-01T00:00:00.000000,\n"
        "3,-9007199254740992,-0.10,0.30000000000000004,1959-12-31,"
        '2024-06-30T12:34:56.123456,"  say ""hi"", Seán  "\n'
    )
    payload = (tmp_path / "t.csv").read_bytes()
    assert payload == expected.encode("utf-8")
    assert written.rows == 3
    assert written.sha256 == hashlib.sha256(payload).hexdigest()
    assert written.columns[-1] == InputColumn(name="s", kind=ColumnKind.CHAR, length=19)
    assert written.warnings == ()


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame({"x": [1]}), "_row_seq"),
        (pd.DataFrame({ROW_SEQ: [1, 1]}), "duplicates"),
        (pd.DataFrame({ROW_SEQ: [1.0, 2.0]}), "integer"),
        (pd.DataFrame({ROW_SEQ: pd.array([1, None], dtype="Int64")}), "nulls"),
        (pd.DataFrame({ROW_SEQ: [1], "A": [1], "a": [2]}), "ignoring case"),
        (pd.DataFrame({ROW_SEQ: [1], "my col": [1]}), "not a SAS name"),
        (pd.DataFrame({ROW_SEQ: [1], "s": ["two\nlines"]}), "line break"),
        (pd.DataFrame({ROW_SEQ: [1], "n": [2**53 + 1]}), "2\\*\\*53"),
        (pd.DataFrame({ROW_SEQ: [1], "x": [math.inf]}), "infinity"),
        (pd.DataFrame({ROW_SEQ: [1], "x": [5e-324]}), "subnormal"),
        (pd.DataFrame({ROW_SEQ: [1], "d": [date(1581, 12, 31)]}), "1582"),
        (pd.DataFrame({ROW_SEQ: [1], "d": [date(4000, 2, 29)]}), "calendar"),
        (
            pd.DataFrame({ROW_SEQ: [1], "ts": pd.to_datetime(["2024-01-01 00:00:00.000000001"])}),
            "microsecond",
        ),
    ],
)
def test_write_input_csv_refuses_what_sas_cannot_hold(
    tmp_path: Path, frame: pd.DataFrame, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        write_input_csv(frame, tmp_path / "t.csv")


def test_write_input_csv_checks_declared_lengths(tmp_path: Path) -> None:
    frame = pd.DataFrame({ROW_SEQ: [1], "s": ["Siobhán"]})  # 7 characters but 8 bytes
    columns = [InputColumn(name=ROW_SEQ, kind=ColumnKind.INT),
               InputColumn(name="s", kind=ColumnKind.CHAR, length=7)]  # fmt: skip
    with pytest.raises(ValueError, match="bytes"):
        write_input_csv(frame, tmp_path / "t.csv", columns)


def test_write_input_csv_warns_about_precision(tmp_path: Path) -> None:
    # 17 significant digits, and a microsecond too far from 1960 for a double to keep
    frame = pd.DataFrame(
        {
            ROW_SEQ: [1],
            "amount": [Decimal("123456789012345.68")],
            "ts": pd.Series([datetime(2300, 1, 1, 0, 0, 0, 1)], dtype="datetime64[us]"),
        }
    )
    written = write_input_csv(frame, tmp_path / "t.csv")
    assert len(written.warnings) == 2
    assert "15 significant digits" in written.warnings[0]
    assert "microseconds" in written.warnings[1]


### Generated SAS code


def test_read_step_code() -> None:
    """
    The read step gives every column an explicit informat and reads datetimes as text first.
    """
    columns = [
        InputColumn(name=ROW_SEQ, kind=ColumnKind.INT),
        InputColumn(name="amount", kind=ColumnKind.DECIMAL),
        InputColumn(name="d", kind=ColumnKind.DATE),
        InputColumn(name="ts", kind=ColumnKind.DATETIME),
        InputColumn(name="s", kind=ColumnKind.CHAR, length=15),
    ]
    expected = """\
/* LANSH: read t.csv into work.t with explicit informats */
data work.t;
  infile '/home/x/lansh/t.csv' dsd dlm=',' firstobs=2 truncover lrecl=256
    encoding='utf-8' termstr=LF;
  length
    _row_seq  8
    amount    8
    d         8
    ts        8
    s         $15
    _lansh_t4 $26
  ;
  format
    _row_seq  BEST32.
    amount    BEST32.
    d         YYMMDD10.
    ts        E8601DT26.6
    s         $CHAR15.
  ;
  input
    _row_seq  :BEST32.
    amount    :BEST32.
    d         :YYMMDD10.
    _lansh_t4 :$26.
    s         :$CHAR15.
  ;
  if not missing(_lansh_t4) then ts = input(_lansh_t4, E8601DT26.6);
  drop _lansh_t4;
run;
"""
    assert read_step("work.t", "/home/x/lansh/t.csv", columns) == expected
    with pytest.raises(ValueError, match="_row_seq"):
        read_step("work.t", "/home/x/t.csv", columns[1:])


def _var(name: str, varnum: int, category: str, length: int = 8) -> SasVariable:
    """
    Describe a variable as PROC CONTENTS would, with its type following from its category.
    """
    kind = "char" if category == "char" else "num"
    return SasVariable(name=name, varnum=varnum, type=kind, length=length, category=category)


EXPORT_VARIABLES = [
    _var(ROW_SEQ, 1, "num"),
    _var("d", 2, "date"),
    _var("ts", 3, "datetime"),
    _var("s", 4, "char", 20),
    _var("my var", 5, "num"),
]


def test_export_step_uses_explicit_formats() -> None:
    code = export_step("work.t", "/home/x/out.csv", EXPORT_VARIABLES, "/home/x/out.hex.csv")
    for fragment in (
        "filename _lxcsv '/home/x/out.csv' encoding='utf-8' nobom termstr=LF",
        "filename _lxhex '/home/x/out.hex.csv' encoding='utf-8' nobom termstr=LF",
        "_lansh_v = strip(put(_row_seq, BEST32.));",
        "_lansh_v = put(d, YYMMDD10.);",
        "_lansh_v = put(ts, E8601DT26.6);",
        "_lansh_v = tranwrd(put(s, $CHAR20.), '\"', '\"\"');",
        "_lansh_v = '\"' || trimn(_lansh_v) || '\"';",
        "if missing('my var'n) then _lansh_l = 0;",
        "_lansh_v = put('my var'n, HEX16.); _lansh_l = 16;",
        "put _lansh_v $varying32767. _lansh_l @;",
        "put '\"_row_seq\"' @;",
        "put ',\"my var\"' @;",
        f"put '\"{HEX_OBS}\"' @;",
    ):
        assert fragment in code, fragment
    # the header is written before SET, so an empty data set still gets one
    assert code.index("if _n_ = 1 then do;") < code.index("set work.t;")
    # every numeric variable, and only those, goes to the HEX16. sidecar
    assert code.count("HEX16.") == 4
    plain = export_step("work.t", "/home/x/out.csv", EXPORT_VARIABLES)
    assert "HEX16." not in plain
    assert "_lxhex" not in plain


def test_contents_step_code() -> None:
    """
    The metadata step sorts by VARNUM, gives each variable a category and deletes its raw copy.
    """
    code = contents_step("work.out")
    assert "proc contents data=work.out out=work._lansh_meta_raw noprint;" in code
    assert "by varnum;" in code
    assert "category = lowcase(fmtinfo(format, 'cat'));" in code
    assert f"data {META_DATASET};" in code
    assert "delete _lansh_meta_raw;" in code
    assert [v.name for v in CONTENTS_VARIABLES] == [
        "varnum", "name", "type", "length", "format", "formatl", "formatd", "informat",
        "label", "nobs", "category",
    ]  # fmt: skip


### Parsing exports

# the metadata SAS wrote for work.planted_out in the spike, one line per variable
CONTENTS_CSV = """\
"varnum","name","type","length","format","formatl","formatd","informat","label","nobs","category"
1,"_row_seq","num",8,"BEST",32,0,,,2,"num"
2,"d","num",8,"YYMMDD",10,0,,,2,"date"
3,"ts","num",8,"E8601DT",26,6,,,2,"datetime"
4,"s","char",220,"$CHAR",220,0,,,2,"char"
5,"total","num",8,,0,0,,,2,"num"
"""


def test_read_contents(tmp_path: Path) -> None:
    """
    The metadata gives each variable's type, length, category and format, and the row count.
    """
    path = tmp_path / "t.contents.csv"
    path.write_text(CONTENTS_CSV, encoding="utf-8")
    contents = read_contents(path)
    assert contents.nobs == 2
    assert [(v.name, v.type, v.length, v.category) for v in contents.variables] == [
        (ROW_SEQ, "num", 8, SasCategory.NUM),
        ("d", "num", 8, SasCategory.DATE),
        ("ts", "num", 8, SasCategory.DATETIME),
        ("s", "char", 220, SasCategory.CHAR),
        ("total", "num", 8, SasCategory.NUM),
    ]
    assert contents.variables[1].format == "YYMMDD"
    assert contents.variables[4].format == ""
    assert contents.variables[3].export_format == "$CHAR220."


def _write_export(tmp_path: Path, csv_text: str, hex_text: str | None) -> tuple[Path, Path | None]:
    """
    Write an export and, unless hex_text is None, its HEX16. sidecar; return both paths.
    """
    csv_path = tmp_path / "out.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    if hex_text is None:
        return csv_path, None
    hex_path = tmp_path / "out.hex.csv"
    hex_path.write_text(hex_text, encoding="utf-8")
    return csv_path, hex_path


PARSE_VARIABLES = [
    _var(ROW_SEQ, 1, "num"),
    _var("x", 2, "num"),
    _var("d", 3, "date"),
    _var("ts", 4, "datetime"),
    _var("s", 5, "char", 20),
]
# three rows as the export writes them: BEST32. gives 0.3 for 0.1 + 0.2 and drops -0.0's sign,
# and E8601DT26.6 prints .939734 where the bits say .939733 (both seen on SAS); the text also
# starts with an invisible BOM, which the parser must skip
PARSE_CSV = (
    '﻿"_row_seq","x","d","ts","s"\n'
    '1,0.3,2024-02-29,1939-06-07T13:48:03.939734,"  lead, ""q"""\n'
    "2,0,9999-12-31,,\n"
    '3,,,1960-01-01T00:00:00.000000,"Seán"\n'
)
PARSE_HEX = (
    '"_lansh_obs","_row_seq","x","d","ts"\n'
    "1,3FF0000000000000,3FD3333333333334,40D6E2C000000000,C1C35809B607B6D4\n"
    "2,4000000000000000,8000000000000000,4146677180000000,\n"
    "3,4008000000000000,,,0000000000000000\n"
)


def _cells(series: pd.Series) -> list[Any]:
    """
    List a column's values, with every kind of missing as None and timestamps as datetimes.
    """
    out = []
    for value in series.tolist():
        missing = value is None or value is pd.NA or value is pd.NaT
        if missing or (isinstance(value, float) and math.isnan(value)):
            out.append(None)
        elif isinstance(value, pd.Timestamp):
            out.append(value.to_pydatetime())
        else:
            out.append(value)
    return out


def test_parse_export_types_values_from_hex16(tmp_path: Path) -> None:
    csv_path, hex_path = _write_export(tmp_path, PARSE_CSV, PARSE_HEX)
    parsed = parse_export(csv_path, PARSE_VARIABLES, hex_path, nobs=3)
    frame = parsed.frame
    assert parsed.exact
    assert {c: str(t) for c, t in frame.dtypes.items()} == {
        ROW_SEQ: "float64",
        "x": "float64",
        "d": "date32[day][pyarrow]",
        "ts": "datetime64[us]",
        "s": "string",
    }
    x = _cells(frame["x"])
    assert x[0] == 0.1 + 0.2
    assert math.copysign(1.0, x[1]) == -1.0
    assert x[2] is None
    assert _cells(frame["d"]) == [date(2024, 2, 29), date(9999, 12, 31), None]
    assert _cells(frame["ts"]) == [
        datetime(1939, 6, 7, 13, 48, 3, 939733),
        None,
        datetime(1960, 1, 1),
    ]
    assert _cells(frame["s"]) == ['  lead, "q"', None, "Seán"]
    assert parsed.text_differs == {"x": 2, "ts": 1}


def test_parse_export_from_text_alone(tmp_path: Path) -> None:
    """
    Without the HEX16. sidecar, values keep the rounding of their formatted text.
    """
    csv_path, _ = _write_export(tmp_path, PARSE_CSV, None)
    parsed = parse_export(csv_path, PARSE_VARIABLES)
    assert not parsed.exact
    assert _cells(parsed.frame["x"]) == [0.3, 0.0, None]
    assert _cells(parsed.frame["ts"])[0] == datetime(1939, 6, 7, 13, 48, 3, 939734)
    assert parsed.text_differs == {}


@pytest.mark.parametrize(
    ("csv_text", "hex_text", "nobs", "message"),
    [
        (PARSE_CSV.replace('"x"', '"y"'), PARSE_HEX, 3, "header"),
        (PARSE_CSV, PARSE_HEX, 4, "PROC CONTENTS"),
        (PARSE_CSV, PARSE_HEX.replace("\n2,", "\n9,"), 3, "out of step"),
        (PARSE_CSV, PARSE_HEX.replace("3FD3333333333334", "4000000000000000"), 3, "is not HEX16"),
        (PARSE_CSV.replace("\n3,,", "\n3,1.5,"), PARSE_HEX, 3, "missing"),
        (PARSE_CSV.replace("9999-12-31", "9999-12-30"), PARSE_HEX, 3, "is not HEX16"),
        (PARSE_CSV.replace("\n2,0,", "\n2,0,x,"), PARSE_HEX, 3, "fields"),
    ],
)
def test_parse_export_refuses_files_out_of_step(
    tmp_path: Path, csv_text: str, hex_text: str, nobs: int, message: str
) -> None:
    csv_path, hex_path = _write_export(tmp_path, csv_text, hex_text)
    with pytest.raises(ValueError, match=message):
        parse_export(csv_path, PARSE_VARIABLES, hex_path, nobs=nobs)


def test_parse_export_overflowed_datetime_needs_hex16(tmp_path: Path) -> None:
    # SAS fills a field with asterisks when a value overflows its format
    text = PARSE_CSV.replace("1960-01-01T00:00:00.000000", "*" * 26)
    csv_path, hex_path = _write_export(tmp_path, text, PARSE_HEX)
    parsed = parse_export(csv_path, PARSE_VARIABLES, hex_path)
    assert _cells(parsed.frame["ts"])[2] == datetime(1960, 1, 1)
    assert any("overflowed" in note for note in parsed.warnings)
    with pytest.raises(ValueError, match="overflowed"):
        parse_export(csv_path, PARSE_VARIABLES)


PLANTED_OUT_VARIABLES = [
    _var(name, i, category, 220 if category == "char" else 8)
    for i, (name, category) in enumerate(
        [(ROW_SEQ, "num"), ("int_val", "num"), ("money", "num"), ("dbl", "num"), ("a", "num"),
         ("b", "num"), ("d", "date"), ("ts", "datetime"), ("s", "char"), ("total", "num"),
         ("plus", "num")],
        start=1,
    )
]  # fmt: skip


def test_export_written_by_sas_parses_back(tmp_path: Path) -> None:
    """
    Row 6 of work.planted_out, byte for byte as SAS wrote it in the spike, parses back exactly.
    """
    csv_path, hex_path = _write_export(
        tmp_path,
        '"_row_seq","int_val","money","dbl","a","b","d","ts","s","total","plus"\n'
        "6,-2147483648,1234567.89,1,10000000000000000,1,1582-10-15,2024-06-30T12:34:56.123456,"
        '"has ""quote""",10000000000000000,10000000000000000\n',
        '"_lansh_obs","_row_seq","int_val","money","dbl","a","b","d","ts","total","plus"\n'
        "1,4018000000000000,C1E0000000000000,4132D687E3D70A3D,3FF0000000000001,"
        "4341C37937E08000,3FF0000000000000,C100D17000000000,41DE54521C07E6B4,"
        "4341C37937E08000,4341C37937E08000\n",
    )
    parsed = parse_export(csv_path, PLANTED_OUT_VARIABLES, hex_path, nobs=1)
    row = {column: _cells(parsed.frame[column])[0] for column in parsed.frame.columns}
    assert row == {
        ROW_SEQ: 6.0,
        "int_val": -2147483648.0,
        "money": 1234567.89,
        "dbl": 1.0000000000000002,  # BEST32. wrote "1"
        "a": 1e16,
        "b": 1.0,
        "d": date(1582, 10, 15),
        "ts": datetime(2024, 6, 30, 12, 34, 56, 123456),
        "s": 'has "quote"',
        "total": 1e16,  # sum(1e16, 1): the 1 is absorbed, as in any IEEE double
        "plus": 1e16,
    }
    assert parsed.text_differs == {"dbl": 1}


### Logs and the session (with a stand-in for saspy)

SAMPLE_LOG = """\
NOTE: The infile '~/lansh/x.csv' is:
NOTE: Invalid data for ts in line 2 4-4.
ERROR 22-322: Syntax error, expecting one of the following: ;.
WARNING: The data set WORK.A may be incomplete.
NOTE: Missing values were generated as a result of performing an operation on missing values.
NOTE: Invalid argument to function INPUT at line 5 column 10.
"""


def test_scan_log() -> None:
    """
    A log's errors, warnings, read problems and data notes are each picked out.
    """
    scan = scan_log(SAMPLE_LOG)
    assert scan.errors == ("ERROR 22-322: Syntax error, expecting one of the following: ;.",)
    assert scan.warnings == ("WARNING: The data set WORK.A may be incomplete.",)
    assert len(scan.read_problems) == 2
    assert scan.data_notes[0].startswith("NOTE: Missing values were generated")


class FakeSASsession:
    """
    Just enough of saspy.SASsession for SasSession's own logic.

    With identity=False, the start-up code reports no home directory or user ID.
    """

    def __init__(self, cfgname: str, results: str, identity: bool = True) -> None:
        self.cfgname = cfgname
        self._io = object()
        self.sasver = "9.04.01M9P06052025"
        self.sascei = "utf-8"
        self.identity = identity
        self.submitted: list[str] = []
        self.ended = 0

    def submit(self, code: str, results: str = "TEXT") -> dict[str, str]:
        """
        Record the code and answer with the log SAS would write for it.
        """
        self.submitted.append(code)
        if "LANSH_HOME" in code:
            # SAS echoes the line that turns the echo off
            log = "1  options nosource;\n"
            if self.identity:
                log += "LANSH_HOME=/home/u123\nLANSH_USER=u123\n"
            return {"LOG": log, "LST": ""}
        if "boom" in code:
            return {"LOG": "ERROR: boom in /home/u123/lansh for u123\n", "LST": ""}
        if "LANSH_NOBS" in code:
            # the echoed source line holds the marker too, but not at the start of a line
            return {"LOG": "3   put 'LANSH_NOBS=' _lansh_n;\nLANSH_NOBS=20\n", "LST": ""}
        if "LANSH_DIR" in code:
            return {"LOG": "LANSH_DIR=OK\n", "LST": ""}
        return {"LOG": "NOTE: wrote /home/u123/lansh/x.csv\n", "LST": ""}

    def endsas(self) -> None:
        """
        Count the times the session is ended.
        """
        self.ended += 1


def _install_fake_saspy(monkeypatch: pytest.MonkeyPatch, identity: bool) -> list[FakeSASsession]:
    """
    Replace the saspy module with a fake whose sessions are FakeSASsession objects.

    Args:
        monkeypatch: Pytest's monkeypatch, which undoes the replacement after the test.
        identity: Whether each fake session reports a home directory and user ID.

    Returns:
        The fake sessions, appended to as SasSession starts them.
    """
    created: list[FakeSASsession] = []
    module = types.ModuleType("saspy")

    def factory(**kwargs: Any) -> FakeSASsession:
        created.append(FakeSASsession(identity=identity, **kwargs))
        return created[-1]

    module.SASsession = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "saspy", module)
    return created


@pytest.fixture
def fake_saspy(monkeypatch: pytest.MonkeyPatch) -> list[FakeSASsession]:
    """
    Swap in a fake saspy whose sessions report a home directory and user ID.
    """
    return _install_fake_saspy(monkeypatch, identity=True)


def _fail_inside_a_session() -> None:
    """
    Raise inside an open session, as a failing job would.
    """
    with SasSession("oda") as sas:
        assert sas.is_open
        raise RuntimeError("job failed")


def test_session_ends_even_after_an_error(fake_saspy: list[FakeSASsession]) -> None:
    with pytest.raises(RuntimeError, match="job failed"):
        _fail_inside_a_session()
    assert fake_saspy[0].ended == 1
    # SAS OnDemand starts sessions with NONOTES, so the start-up code turns notes on
    assert "options source notes;" in fake_saspy[0].submitted[0]


def test_session_redacts_logs_and_raises_on_errors(fake_saspy: list[FakeSASsession]) -> None:
    with SasSession("oda") as sas:
        assert sas.remote_path("lansh", "spike") == "/home/u123/lansh/spike"
        with pytest.raises(ValueError, match="bad path"):
            sas.remote_path("..", "etc")
        entry = sas.submit("data _null_; run;", label="ok")
        assert entry.log == "NOTE: wrote ~/lansh/x.csv\n"
        assert sas.nobs("work.t") == 20
        with pytest.raises(SasError, match="boom") as failure:
            sas.submit("boom", label="bad")
        assert failure.value.log_text == "ERROR: boom in ~/lansh for <user>\n"
        assert [e.label for e in sas.logs] == ["ok", "count work.t", "bad"]
        assert "u123" not in sas.full_log()
        # the user ID is replaced only where it stands as a whole word
        assert sas.redact("/home/u123/x u123, u1234 xu123") == "~/x <user>, u1234 xu123"
    assert fake_saspy[0].ended == 1
    sas.close()  # a second close is harmless
    assert fake_saspy[0].ended == 1
    with pytest.raises(SasError):
        sas.submit("data _null_; run;", label="closed")


def test_ensure_dir_creates_folders_under_home_only(fake_saspy: list[FakeSASsession]) -> None:
    """
    Each missing folder under home is created in turn. A path that climbs out of home with
    ``..``, or isn't under it, is refused before any code runs.
    """
    with SasSession("oda") as sas:
        sas.ensure_dir("/home/u123/lansh/x")
        code = fake_saspy[0].submitted[-1]
        assert "dcreate('lansh', '/home/u123')" in code
        assert "dcreate('x', '/home/u123/lansh')" in code
        submitted = len(fake_saspy[0].submitted)
        for bad in ("/home/u123/../x", "/home/u123/lansh/../../x", "/home/u1234/x"):
            with pytest.raises(ValueError, match="under the SAS home"):
                sas.ensure_dir(bad)
        assert len(fake_saspy[0].submitted) == submitted


def test_session_ends_if_it_cannot_find_home(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _install_fake_saspy(monkeypatch, identity=False)
    with pytest.raises(SasError, match="LANSH_HOME"):
        SasSession("oda").open()
    assert created[0].ended == 1


### Live: a round trip through SAS OnDemand


@pytest.mark.sas
def test_live_round_trip(tmp_path: Path) -> None:
    """
    A table sent to SAS OnDemand, transformed and exported comes back exactly as SAS holds it.
    """
    frame = awkward_frame()
    frame["a"] = [0.1, 1.0, math.nan]
    frame["b"] = [0.2, math.nan, math.nan]
    with SasSession() as sas:
        remote = sas.remote_path("lansh", "spike", "pytest")
        sas.ensure_dir(remote)
        uploaded = upload_table(sas, frame, "work.t", remote_dir=remote, local_dir=tmp_path)
        sas.submit(
            "data work.t_out;\n  set work.t;\n  total = sum(a, b);\n  plus = a + b;\nrun;\n",
            label="transform",
        )
        out = export_table(sas, "work.t_out", remote_dir=remote, local_dir=tmp_path)
        logs = list(sas.logs)
    assert uploaded.rows == 3
    assert not any(e.read_problems or e.errors for e in logs)
    assert any("Missing values were generated" in n for e in logs for n in e.data_notes)
    result = out.frame
    assert [v.category for v in out.contents.variables] == [
        SasCategory.NUM, SasCategory.NUM, SasCategory.NUM, SasCategory.NUM, SasCategory.DATE,
        SasCategory.DATETIME, SasCategory.CHAR, SasCategory.NUM, SasCategory.NUM,
        SasCategory.NUM, SasCategory.NUM,
    ]  # fmt: skip
    assert _cells(result[ROW_SEQ]) == [1.0, 2.0, 3.0]  # physical order is _row_seq order
    assert _cells(result["n"]) == [7.0, None, float(-(2**53))]
    assert _cells(result["amount"]) == [1234.56, None, -0.1]
    x = _cells(result["x"])
    assert x[0] is None
    assert float_to_hex16(x[1]) == "8000000000000000"
    assert x[2] == 0.1 + 0.2
    assert _cells(result["d"]) == [None, date(2024, 2, 29), date(1959, 12, 31)]
    assert _cells(result["ts"]) == [
        None,
        datetime(1960, 1, 1),
        datetime(2024, 6, 30, 12, 34, 56, 123456),
    ]
    # SAS keeps leading blanks, drops trailing ones and has no empty string
    assert _cells(result["s"]) == [None, None, '  say "hi", Seán']
    assert _cells(result["total"]) == [1.0, None, 0.1 + 0.2]  # SUM skips missing values
    assert _cells(result["plus"]) == [None, None, 0.1 + 0.2]  # + propagates them
    assert out.text_differs["total"] == 1  # BEST32. writes 0.3
