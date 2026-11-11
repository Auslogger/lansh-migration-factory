"""
The SAS engine: run legacy SAS through saspy and move tables in and out exactly.

Plan step 0.4 (the SAS spike) built and measured this module, and step 1.6 (golden capture)
uses it. The evidence behind every choice below is in ``spikes/README.md`` ("SAS round trip").

How a table travels
-------------------
1. **Python to SAS.** :func:`write_input_csv` writes a CSV in the dialect below,
   :meth:`SasSession.upload` copies it to the SAS server byte for byte, and :func:`read_step`
   reads it with an explicit informat for every column, ``_row_seq`` included.
2. **SAS to Python.** :func:`contents_step` records the PROC CONTENTS metadata,
   :func:`export_step` writes the data with explicit formats plus an exact ``HEX16.`` copy of
   every numeric variable, and :func:`parse_export` turns the download back into typed pandas.

Input CSV dialect
-----------------
- UTF-8 without a BOM, comma-separated, LF line endings, one header row of column names.
- Rows are written in ``_row_seq`` order, so the SAS data set's physical order is that order.
- NULL is an empty, unquoted field. Character values are always double-quoted with embedded
  quotes doubled, so ``""`` is an empty string. (SAS reads both as blank: it has no empty string.)
- Numbers are unquoted: integers as digits, decimals in fixed notation, doubles as Python's
  shortest round-trip ``repr``. pandas NaN counts as NULL.
- Dates are ``YYYY-MM-DD``; datetimes ``YYYY-MM-DDTHH:MM:SS.ffffff`` (always six decimals).
- Line breaks inside values are refused: SAS's INFILE ends a record at a line break, even
  inside quotes.

Informats and formats
---------------------
========== ================ ================ =============================================
Kind       Informat (read)  Format (export)  Why
========== ================ ================ =============================================
numbers    ``BEST32.``      ``BEST32.``      ``BEST32.`` (an alias of ``32.``) reads every
                                             decimal string correctly rounded, 17 digits
                                             included, and never implies a decimal point
dates      ``YYMMDD10.``    ``YYMMDD10.``    ISO dates, 1582-01-01 to 9999-12-31
datetimes  ``E8601DT26.6``  ``E8601DT26.6``  ISO 8601 with microseconds; read as text and
                                             converted with INPUT() only when present,
                                             because the informat calls an empty field
                                             invalid data
character  ``$CHARw.``      ``$CHARw.``      DSD list input keeps leading blanks inside
                                             quotes; ``w`` is the length in bytes (UTF-8,
                                             so a fada takes two)
========== ================ ================ =============================================

``BEST32.`` *writes* at most 15 significant digits (as few as 10 for small numbers), so it
cannot round-trip every double: ``0.1 + 0.2`` comes out as ``0.3`` and ``-0.0`` as ``0``.
``E8601DT26.6`` can print a pre-1960 datetime one microsecond high and overflows after 9999.
The export therefore also writes ``HEX16.`` (the IEEE 754 bits, big-endian) of every numeric
variable to a sidecar file, and :func:`parse_export` takes numbers, dates and datetimes from
it, after checking that it agrees with the formatted text.

Session details: SAS OnDemand starts sessions with ``NONOTES``, so :class:`SasSession` turns
notes on (records read, observations written and invalid data must reach the log), and
output files are opened with ``NOBOM`` because ``ENCODING='UTF-8'`` otherwise writes a BOM.

What SAS cannot keep: trailing blanks (values are blank-padded), the difference between an
empty string and a missing value (a blank character value *is* missing), special missing
values (``.A``–``.Z``, ``._``, exported as missing), integers beyond 2**53, subnormal doubles
(the numeric informats cannot read them), microseconds on datetimes outside 1688–2232, and
29 February in years divisible by 4000 (see :data:`SAS_SKIPPED_LEAP_DAYS`).
"""

from __future__ import annotations

import csv
import hashlib
import logging
import math
import re
import struct
import sys
import time
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Self

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lansh.config import env

if TYPE_CHECKING:
    import saspy

log = logging.getLogger(__name__)

### Constants

# the saspy configuration used unless the caller or ``LANSH_SAS_CFGNAME`` names another
DEFAULT_CFGNAME = "oda"
# the column recording each row's original order. Every table sent to SAS carries it
ROW_SEQ = "_row_seq"
# generated code names its own variables and data sets with this prefix. (Its filerefs,
# which SAS limits to 8 characters, start with ``_lx`` instead)
RESERVED_PREFIX = "_lansh"
# first column of the HEX16. sidecar: the observation number, to prove the files line up
HEX_OBS = "_lansh_obs"

SAS_EPOCH_DATE = date(1960, 1, 1)
# SAS dates start on 1 Jan 1582; an earlier date reads as missing
SAS_MIN_DATE = date(1582, 1, 1)
# every integer with an absolute value up to 2**53 is exact in a SAS numeric (an 8-byte double)
MAX_EXACT_INT = 2**53
# within this many seconds of 1960 a double resolves a microsecond (1688 to 2232): below
# 2**33 the spacing of doubles is at most 2**-20 s, so rounding to the nearest microsecond is
# exact. Beyond it, microseconds can shift (9999-12-31T23:59:59.999999 reads as year 10000)
EXACT_DATETIME_SECONDS = 2**33
# a decimal with more significant digits than this may not survive the trip through a double
EXACT_DECIMAL_DIGITS = 15
MAX_CHAR_LENGTH = 32767  # the longest SAS character value, in bytes
NUM_WIDTH = 32  # the w of BEST32.: the longest number text read or written

# the table in the module docstring says why each informat and format was chosen
NUM_INFORMAT = NUM_FORMAT = "BEST32."
DATE_INFORMAT = DATE_FORMAT = "YYMMDD10."
DATETIME_INFORMAT = DATETIME_FORMAT = "E8601DT26.6"
HEX_FORMAT = "HEX16."

### Names, literals and paths in generated code

# used with fullmatch: a pattern ending in $ would also accept a final line break
_V7_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}")
_DATASET = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]{0,7}\.)?[A-Za-z_][A-Za-z0-9_]{0,31}")
_AUTOMATIC_NAMES = frozenset({"_n_", "_error_", "_iorc_", "_infile_", "_file_", "_cmd_", "_msg_"})
_UNSAFE_PATH_CHARS = frozenset("'\"\n\r;&%")


def check_name(name: str) -> str:
    """
    Return ``name`` if generated code can use it as a variable name.

    It must be a V7 name: letters, digits and underscores, at most 32, not starting with a
    digit. SAS's automatic variables (such as ``_n_``) and names starting with
    :data:`RESERVED_PREFIX` are reserved, whatever their case, since SAS ignores case.

    Args:
        name: The proposed variable name.

    Returns:
        ``name``, unchanged.

    Raises:
        ValueError: If ``name`` is not a V7 name, or is reserved.
    """
    if not _V7_NAME.fullmatch(name):
        raise ValueError(
            f"{name!r} is not a SAS name: use letters, digits and underscores, at most 32, "
            "not starting with a digit"
        )
    lowered = name.lower()
    if lowered.startswith(RESERVED_PREFIX) or lowered in _AUTOMATIC_NAMES:
        raise ValueError(f"{name!r} is reserved in generated SAS code")
    return name


def check_dataset(dataset: str) -> str:
    """
    Return ``dataset`` if it is a SAS data set name, such as ``work.claims`` or ``claims``.

    Args:
        dataset: A ``libref.member`` or bare ``member`` name. A libref has at most 8
            characters and a member at most 32.

    Returns:
        ``dataset``, unchanged.

    Raises:
        ValueError: If it is not such a name.
    """
    if not _DATASET.fullmatch(dataset):
        raise ValueError(f"{dataset!r} is not a SAS data set name such as work.claims")
    return dataset


def check_remote_path(path: str) -> str:
    """
    Return ``path`` if it is an absolute server path that is safe inside a quoted SAS literal.

    Quotes, line breaks, ``;``, ``&`` and ``%`` are refused: they could end the literal or
    the statement, or be read as macro code.

    Args:
        path: A path on the SAS server.

    Returns:
        ``path``, unchanged.

    Raises:
        ValueError: If the path is relative or holds one of those characters.
    """
    if not path.startswith("/") or any(ch in _UNSAFE_PATH_CHARS for ch in path):
        raise ValueError(
            f"unsafe SAS server path {path!r}: use an absolute path without quotes, ;, & or %"
        )
    return path


def sas_string(text: str) -> str:
    """
    Quote ``text`` as a single-quoted SAS literal, which the macro processor leaves alone.

    Args:
        text: Any text without line breaks.

    Returns:
        The literal, with embedded quotes doubled, such as ``'O''Brien'``.

    Raises:
        ValueError: If ``text`` holds a line break.
    """
    if "\n" in text or "\r" in text:
        raise ValueError("a SAS literal cannot contain a line break")
    return "'" + text.replace("'", "''") + "'"


def name_literal(name: str) -> str:
    """
    Refer to a variable in generated code: plainly if it is a V7 name, else as ``'x y'n``.

    SAS OnDemand allows any name (``VALIDVARNAME=ANY``), so a job can create one such as
    ``'Total Paid'n``.

    Args:
        name: The variable's name, as PROC CONTENTS reports it.

    Returns:
        The name, or its name literal.
    """
    return name if _V7_NAME.fullmatch(name) else sas_string(name) + "n"


def csv_quote(text: str) -> str:
    """
    Quote a CSV field as both the input CSV and the export do: always, with quotes doubled.

    Args:
        text: The field's text, which may hold commas and quotes.

    Returns:
        The quoted field, such as ``"has ""quotes"" inside"``.
    """
    return '"' + text.replace('"', '""') + '"'


def _comment(text: str) -> str:
    """
    Wrap ``text`` in a SAS block comment that no name or path can close early.
    """
    return "/* " + text.replace("*/", "* /") + " */"


### Exact numbers, dates and datetimes


def float_to_hex16(value: float) -> str:
    """
    Write a double as SAS's ``HEX16.`` format does: its IEEE 754 bits, big-endian.

    Args:
        value: Any double.

    Returns:
        16 upper-case hex digits, such as ``3FD3333333333334`` for ``0.1 + 0.2``.
    """
    return struct.pack(">d", value).hex().upper()


def hex16_to_float(text: str | None) -> float | None:
    """
    Read one ``HEX16.`` field back into a double.

    An empty field, ``.`` or a special-missing letter (``A`` to ``Z``, or ``_``) is missing.
    So is a NaN, since SAS keeps its missing values as NaN bit patterns.

    Args:
        text: The field from the sidecar, or None.

    Returns:
        The double, or None if the value is missing.

    Raises:
        ValueError: If the field is not 16 hex digits.
    """
    if text is None:
        return None
    stripped = text.strip()
    if (
        not stripped
        or stripped == "."
        or (len(stripped) == 1 and stripped in "_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    ):
        return None
    if len(stripped) != 16:
        raise ValueError(f"{text!r} is not a HEX16. value")
    value = struct.unpack(">d", bytes.fromhex(stripped))[0]
    return None if math.isnan(value) else value


# SAS's calendar has no 29 February in years divisible by 4000; the proleptic Gregorian
# calendar of Python and Spark has one. So day numbers differ after 28 Feb 4000 (by one day)
# and after 28 Feb 8000 (by two): 9999-12-31 is SAS day 2936547 but 2936549 days after
# 1960-01-01 in Python and Spark. Date *labels* agree; arithmetic across those days does not
SAS_SKIPPED_LEAP_DAYS = (date(4000, 2, 29), date(8000, 2, 29))
_DAY_MICROS = 86_400 * 1_000_000


def _skipped_before(value: date) -> int:
    """
    Count the SAS-skipped 29 Februaries that fall on or before ``value``.
    """
    return sum(1 for leap in SAS_SKIPPED_LEAP_DAYS if value >= leap)


def date_to_sas(value: date) -> int:
    """
    Convert a date to SAS's date value: days since 1 Jan 1960 in SAS's calendar.

    After each of :data:`SAS_SKIPPED_LEAP_DAYS` the value is one day lower than plain day
    arithmetic gives.

    Args:
        value: A date that exists in SAS's calendar.

    Returns:
        The SAS date value, negative before 1960.

    Raises:
        ValueError: If ``value`` is one of the skipped 29 Februaries.
    """
    if value in SAS_SKIPPED_LEAP_DAYS:
        raise ValueError(f"{value} does not exist in SAS's calendar")
    return (value - SAS_EPOCH_DATE).days - _skipped_before(value)


def sas_to_date(days: float) -> date:
    """
    Convert a SAS date value to a date, in SAS's calendar.

    A fractional day is dropped, as SAS's date formats do.

    Args:
        days: Days since 1 Jan 1960 in SAS's calendar.

    Returns:
        The date.

    Raises:
        ValueError: If the date is outside Python's range, or ``days`` is infinite or NaN.
    """
    try:
        whole = math.floor(days)  # inside the try, as an infinite value overflows here
        candidate = SAS_EPOCH_DATE + timedelta(days=whole)
        # find d with d = epoch + whole + _skipped_before(d); each pass can only move the
        # candidate later, so one pass per skipped day, plus one to confirm, is enough
        for _ in range(len(SAS_SKIPPED_LEAP_DAYS) + 1):
            adjusted = SAS_EPOCH_DATE + timedelta(days=whole + _skipped_before(candidate))
            if adjusted == candidate:
                break
            candidate = adjusted
    except OverflowError as exc:
        raise ValueError(f"SAS date value {days!r} is outside Python's date range") from exc
    return candidate


def datetime_to_sas(value: datetime) -> Fraction:
    """
    Convert a naive datetime to SAS's datetime value, exactly.

    Args:
        value: A naive datetime whose date exists in SAS's calendar.

    Returns:
        Seconds since 1960-01-01T00:00:00, as a fraction so that microseconds stay exact.

    Raises:
        ValueError: If the date is one of :data:`SAS_SKIPPED_LEAP_DAYS`.
    """
    day = date_to_sas(value.date())
    micros = (value.hour * 3600 + value.minute * 60 + value.second) * 1_000_000
    return Fraction(day * _DAY_MICROS + micros + value.microsecond, 1_000_000)


def sas_to_datetime(seconds: float) -> datetime:
    """
    Convert a SAS datetime value to a naive datetime, rounded to the nearest microsecond.

    The rounding is exact (halves go to even): the double becomes a fraction first, so no
    float arithmetic can shift it. Days count in SAS's calendar, as in :func:`sas_to_date`.

    Args:
        seconds: Seconds since 1960-01-01T00:00:00.

    Returns:
        The datetime.

    Raises:
        ValueError: If it is outside Python's range, or ``seconds`` is infinite or NaN.
    """
    try:
        # inside the try, as Fraction() overflows on an infinite value
        days, micros = divmod(round(Fraction(seconds) * 1_000_000), _DAY_MICROS)
        return datetime.combine(sas_to_date(days), datetime.min.time()) + timedelta(
            microseconds=micros
        )
    except OverflowError as exc:
        raise ValueError(f"SAS datetime value {seconds!r} is outside Python's range") from exc


### Input columns: how each column travels to SAS


class ColumnKind(StrEnum):
    """
    The logical kind of an input column, which picks its informat.
    """

    INT = "int"
    DECIMAL = "decimal"
    DOUBLE = "double"
    BOOL = "bool"  # SAS has no boolean: 1 or 0
    DATE = "date"
    DATETIME = "datetime"
    CHAR = "char"


class InputColumn(BaseModel):
    """
    One input column: its name, kind and (for character columns) its SAS length in bytes.

    Lengths are bytes, not characters, because the session is UTF-8: a fada takes two.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: ColumnKind
    length: int | None = Field(
        default=None, ge=1, le=MAX_CHAR_LENGTH, description="Bytes; character columns only."
    )

    @field_validator("name")
    @classmethod
    def _valid_name(cls, name: str) -> str:
        """
        Refuse a name that generated SAS code cannot use; see :func:`check_name`.
        """
        return check_name(name)

    @model_validator(mode="after")
    def _check(self) -> InputColumn:
        """
        Require a length for a character column, and refuse one for any other kind.
        """
        if self.kind is ColumnKind.CHAR and self.length is None:
            raise ValueError(f"character column {self.name!r} needs a length in bytes")
        if self.kind is not ColumnKind.CHAR and self.length is not None:
            raise ValueError(f"only character columns have a length ({self.name!r})")
        return self

    @property
    def sas_length(self) -> str:
        """
        The LENGTH statement entry: ``$n`` for character, 8 bytes for every number.
        """
        return f"${self.length}" if self.kind is ColumnKind.CHAR else "8"

    @property
    def informat(self) -> str:
        """
        The informat :func:`read_step` reads this column with.

        A datetime is read as text first, and converted with this informat only when present.
        """
        match self.kind:
            case ColumnKind.DATE:
                return DATE_INFORMAT
            case ColumnKind.DATETIME:
                return DATETIME_INFORMAT
            case ColumnKind.CHAR:
                return f"$CHAR{self.length}."
            case _:
                return NUM_INFORMAT

    @property
    def format(self) -> str:
        """
        The format :func:`read_step` attaches to this column.

        It lets PROC CONTENTS tell dates and datetimes from plain numbers later.
        """
        match self.kind:
            case ColumnKind.DATE:
                return DATE_FORMAT
            case ColumnKind.DATETIME:
                return DATETIME_FORMAT
            case ColumnKind.CHAR:
                return f"$CHAR{self.length}."
            case _:
                return NUM_FORMAT

    @property
    def max_field_bytes(self) -> int:
        """
        The longest this column's CSV field can be, quotes and doubled quotes included.

        :func:`read_step` sizes its record length from it.
        """
        match self.kind:
            case ColumnKind.CHAR:
                return 2 * (self.length or 1) + 2
            case ColumnKind.DATE:
                return 10
            case ColumnKind.DATETIME:
                return 26
            case ColumnKind.BOOL:
                return 1
            case _:
                return NUM_WIDTH


_INT_TYPES = frozenset({"tinyint", "smallint", "int", "integer", "bigint", "long", "short", "byte"})


def kind_for_logical_type(data_type: str) -> ColumnKind:
    """
    Map a contract's logical type (``ColumnSpec.data_type``) to an input kind.

    Args:
        data_type: The logical type, such as ``bigint``, ``decimal(12,2)`` or
            ``timestamp_ntz``, in any case.

    Returns:
        The input kind.

    Raises:
        ValueError: If no input kind fits the type.
    """
    t = data_type.strip().lower()
    if t in _INT_TYPES:
        return ColumnKind.INT
    if t.startswith(("decimal", "numeric")):
        return ColumnKind.DECIMAL
    if t in {"double", "float", "real"}:
        return ColumnKind.DOUBLE
    if t == "boolean":
        return ColumnKind.BOOL
    if t == "date":
        return ColumnKind.DATE
    if t.startswith("timestamp"):
        return ColumnKind.DATETIME
    if t in {"string", "varchar", "char"} or t.startswith(("varchar(", "char(")):
        return ColumnKind.CHAR
    raise ValueError(f"no SAS input kind for logical type {data_type!r}")


def kind_for_arrow_type(arrow_type: pa.DataType) -> ColumnKind:
    """
    Map an Arrow type to an input kind; a dictionary maps by its value type.

    Args:
        arrow_type: The column's Arrow type.

    Returns:
        The input kind.

    Raises:
        ValueError: If the type is not supported, or is the null type of a column with only
            nulls, which gives nothing to go on.
    """
    if pa.types.is_dictionary(arrow_type):
        return kind_for_arrow_type(arrow_type.value_type)
    if pa.types.is_boolean(arrow_type):
        return ColumnKind.BOOL
    if pa.types.is_integer(arrow_type):
        return ColumnKind.INT
    if pa.types.is_decimal(arrow_type):
        return ColumnKind.DECIMAL
    if pa.types.is_floating(arrow_type):
        return ColumnKind.DOUBLE
    if pa.types.is_date(arrow_type):
        return ColumnKind.DATE
    if pa.types.is_timestamp(arrow_type):
        return ColumnKind.DATETIME
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return ColumnKind.CHAR
    if pa.types.is_null(arrow_type):
        raise ValueError("a column with only nulls has no type: pass its InputColumn explicitly")
    raise ValueError(f"no SAS input kind for Arrow type {arrow_type}")


def to_arrow(table: pd.DataFrame | pa.Table) -> pa.Table:
    """
    Return ``table`` as Arrow, with pandas NaN in float columns as null.

    Args:
        table: A pandas DataFrame, whose index is dropped, or a pyarrow Table.

    Returns:
        The Arrow table; an Arrow input is returned as it is.

    Raises:
        TypeError: If ``table`` is neither.
    """
    if isinstance(table, pa.Table):
        return table
    if isinstance(table, pd.DataFrame):
        return pa.Table.from_pandas(table, preserve_index=False)
    raise TypeError(f"expected a pandas DataFrame or a pyarrow Table, not {type(table).__name__}")


def _python_values(column: pa.ChunkedArray, kind: ColumnKind) -> list[Any]:
    """
    Turn a column into Python values, with dictionaries decoded and timestamps in microseconds.

    Raises:
        ValueError: If a timestamp has a nonzero part below a microsecond, which cannot go
            to SAS.
    """
    if pa.types.is_dictionary(column.type):
        column = column.cast(column.type.value_type)
    if kind is ColumnKind.DATETIME and pa.types.is_timestamp(column.type):
        try:
            column = column.cast(pa.timestamp("us", tz=column.type.tz), safe=True)
        except pa.ArrowInvalid as exc:
            raise ValueError("timestamps finer than a microsecond cannot go to SAS") from exc
    return column.to_pylist()


def _utf8_len(text: str) -> int:
    """
    Return the length of ``text`` in UTF-8 bytes, the unit of SAS character lengths.
    """
    return len(text.encode("utf-8"))


def infer_columns(
    table: pd.DataFrame | pa.Table, lengths: Mapping[str, int] | None = None
) -> list[InputColumn]:
    """
    Choose an :class:`InputColumn` for each column from its type and data.

    A character column's length is the longest value in UTF-8 bytes (at least 1), or the
    length given in ``lengths`` if that is larger.

    Args:
        table: The table to send.
        lengths: Byte lengths for character columns, by column name.

    Returns:
        One input column for each of the table's columns, in order.

    Raises:
        ValueError: If a given length is shorter than a value, a length is given for a
            column that is missing or not character, or a type has no input kind.
    """
    tbl = to_arrow(table)
    wanted = dict(lengths or {})
    columns: list[InputColumn] = []
    for name, column in zip(tbl.column_names, tbl.columns, strict=True):
        kind = kind_for_arrow_type(column.type)
        length = None
        if kind is ColumnKind.CHAR:
            values = _python_values(column, kind)
            observed = max((_utf8_len(v) for v in values if v is not None), default=0)
            declared = wanted.pop(name, None)
            if declared is not None and declared < observed:
                raise ValueError(f"{name}: length {declared} is shorter than a value ({observed})")
            length = max(1, observed, declared or 0)
        columns.append(InputColumn(name=name, kind=kind, length=length))
    if wanted:
        raise ValueError(f"lengths given for columns that are not character: {sorted(wanted)}")
    return columns


### Writing the input CSV


@dataclass(frozen=True)
class InputCsv:
    """
    A CSV written for SAS, with the columns its read step needs.

    Attributes:
        path: Where the CSV was written.
        columns: The columns in file order, ``_row_seq`` among them.
        rows: The number of data rows, not counting the header.
        sha256: SHA-256 of the file's bytes, in hex.
        warnings: Values SAS may not keep exactly, such as decimals with more than 15
            significant digits.
    """

    path: Path
    columns: tuple[InputColumn, ...]
    rows: int
    sha256: str
    warnings: tuple[str, ...] = ()


def _check_sas_day(value: date, name: str) -> None:
    """
    Refuse a date SAS cannot hold: one before 1582-01-01, or a skipped 29 February.
    """
    if value < SAS_MIN_DATE:
        raise ValueError(f"{name}: {value} is before 1582-01-01, the first SAS date")
    if value in SAS_SKIPPED_LEAP_DAYS:
        raise ValueError(f"{name}: {value} does not exist in SAS's calendar")


def _check_number_text(text: str, name: str) -> str:
    """
    Return number text if the numeric informat can read it, that is, at most 32 characters.
    """
    if len(text) > NUM_WIDTH:
        raise ValueError(f"{name}: {text!r} is wider than the {NUM_INFORMAT} informat reads")
    return text


def format_cell(kind: ColumnKind, value: Any, name: str = "value") -> str:
    """
    Format one value for the input CSV; None, and NaN in a double, become an empty field.

    Args:
        kind: The column's kind.
        value: The value, of the Python type that ``kind`` expects.
        name: The column's name, for error messages.

    Returns:
        The CSV field, in the dialect of the module docstring.

    Raises:
        TypeError: If ``value`` is not of the type ``kind`` expects.
        ValueError: If SAS cannot hold the value exactly: an integer beyond 2**53, a
            non-finite decimal, an infinite or subnormal double, number text over 32
            characters, a date before 1582 or on a skipped 29 February, or text with a
            line break.
    """
    if value is None:
        return ""
    match kind:
        case ColumnKind.INT:
            if isinstance(value, bool) or not isinstance(value, int | np.integer):
                raise TypeError(f"{name}: expected an integer, got {value!r}")
            number = int(value)
            if abs(number) > MAX_EXACT_INT:
                raise ValueError(f"{name}: {number} is beyond 2**53, so SAS cannot hold it exactly")
            return str(number)
        case ColumnKind.DECIMAL:
            # a float goes through str, so 0.1 stays 0.1 rather than its binary expansion
            dec = value if isinstance(value, Decimal) else Decimal(str(value))
            if not dec.is_finite():
                raise ValueError(f"{name}: SAS has no {dec}")
            return _check_number_text(format(dec, "f"), name)
        case ColumnKind.DOUBLE:
            number = float(value)
            if math.isnan(number):
                return ""
            if math.isinf(number):
                raise ValueError(f"{name}: SAS has no infinity")
            if number != 0.0 and abs(number) < sys.float_info.min:
                raise ValueError(f"{name}: SAS's informats cannot read the subnormal {number!r}")
            return _check_number_text(repr(number), name)
        case ColumnKind.BOOL:
            return "1" if bool(value) else "0"
        case ColumnKind.DATE:
            if isinstance(value, datetime) or not isinstance(value, date):
                raise TypeError(f"{name}: expected a date, got {value!r}")
            _check_sas_day(value, name)
            return value.isoformat()
        case ColumnKind.DATETIME:
            if not isinstance(value, datetime):
                raise TypeError(f"{name}: expected a datetime, got {value!r}")
            value = _naive_utc(value)
            _check_sas_day(value.date(), name)
            return value.strftime("%Y-%m-%dT%H:%M:%S.%f")
        case ColumnKind.CHAR:
            if not isinstance(value, str):
                raise TypeError(f"{name}: expected text, got {value!r}")
            if "\n" in value or "\r" in value:
                raise ValueError(f"{name}: SAS's INFILE cannot read a line break inside a value")
            return csv_quote(value)
    raise AssertionError(kind)  # pragma: no cover


def _naive_utc(value: datetime) -> datetime:
    """
    Make a datetime naive, as SAS datetimes have no time zone: an aware one becomes UTC first.
    """
    return value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)


def _far_from_1960(value: datetime) -> bool:
    """
    Tell whether a datetime is too far from 1960 for a double to keep its microseconds.

    That is :data:`EXACT_DATETIME_SECONDS` or more, either side.
    """
    try:
        return abs(datetime_to_sas(_naive_utc(value))) >= EXACT_DATETIME_SECONDS
    except ValueError:  # not a SAS day; format_cell reports it with the column name
        return False


def _precision_warnings(column: InputColumn, values: Sequence[Any]) -> list[str]:
    """
    Describe values that can go to SAS but may not come back exactly.

    Those are decimals with more than :data:`EXACT_DECIMAL_DIGITS` significant digits, and
    datetimes with microseconds too far from 1960.
    """
    notes = []
    if column.kind is ColumnKind.DECIMAL:
        wide = [
            v
            for v in values
            if v is not None
            and len(Decimal(v).normalize().as_tuple().digits) > EXACT_DECIMAL_DIGITS
        ]
        if wide:
            notes.append(
                f"{column.name}: {len(wide)} decimal(s) have more than {EXACT_DECIMAL_DIGITS} "
                f"significant digits and may not survive a double, e.g. {wide[0]}"
            )
    if column.kind is ColumnKind.DATETIME:
        far = [v for v in values if v is not None and v.microsecond and _far_from_1960(v)]
        if far:
            notes.append(
                f"{column.name}: {len(far)} datetime(s) are too far from 1960 for a double to "
                f"keep their microseconds, e.g. {far[0]}"
            )
    return notes


def write_input_csv(
    table: pd.DataFrame | pa.Table,
    path: Path,
    columns: Sequence[InputColumn] | None = None,
    *,
    lengths: Mapping[str, int] | None = None,
) -> InputCsv:
    """
    Write ``table`` as a CSV for :func:`read_step`, sorted by ``_row_seq``.

    The file follows the input CSV dialect in the module docstring. Sorting makes the SAS
    data set's physical order ``_row_seq`` order, so order-sensitive SAS (NODUPKEY, RETAIN,
    FIRST. and LAST.) sees the rows in the same order as Spark. Precision warnings are
    logged and returned, not raised.

    Args:
        table: The table to send. Every table sent to SAS carries an integer ``_row_seq``
            column, with no nulls or duplicates (plan §7.1).
        path: Where to write the CSV; missing parent folders are created.
        columns: The columns to write, their order and kinds; by default they are inferred.
        lengths: Byte lengths for character columns, used only when inferring.

    Returns:
        The written file, with its columns, row count, hash and warnings.

    Raises:
        ValueError: If a column is missing, two names differ only in case (SAS ignores it),
            ``_row_seq`` is missing, not an integer, null or duplicated, a text value is
            longer than its column, or SAS cannot hold a value (see :func:`format_cell`).
        TypeError: If a value is not of its column's kind.
    """
    tbl = to_arrow(table)
    cols = list(columns) if columns is not None else infer_columns(tbl, lengths)
    names = [c.name for c in cols]
    missing = [n for n in names if n not in tbl.column_names]
    if missing:
        raise ValueError(f"columns not in the table: {missing}")
    lowered = [n.lower() for n in names]
    if len(set(lowered)) != len(lowered):
        raise ValueError(f"column names must differ ignoring case (SAS ignores it): {names}")
    if ROW_SEQ not in names:
        raise ValueError(f"every table sent to SAS carries {ROW_SEQ} (plan §7.1)")
    if cols[names.index(ROW_SEQ)].kind is not ColumnKind.INT:
        raise ValueError(f"{ROW_SEQ} must be an integer column")
    tbl = tbl.select(names)
    seq = tbl.column(ROW_SEQ)
    if seq.null_count:
        raise ValueError(f"{ROW_SEQ} has nulls")
    if pc.count_distinct(seq).as_py() != tbl.num_rows:
        raise ValueError(f"{ROW_SEQ} has duplicates")
    tbl = tbl.take(pc.sort_indices(tbl, sort_keys=[(ROW_SEQ, "ascending")]))

    values = [_python_values(tbl.column(c.name), c.kind) for c in cols]
    notes: list[str] = []
    for col, col_values in zip(cols, values, strict=True):
        if col.kind is ColumnKind.CHAR:
            longest = max((_utf8_len(v) for v in col_values if v is not None), default=0)
            if longest > (col.length or 0):
                raise ValueError(f"{col.name}: a value has {longest} bytes, over its length")
        notes.extend(_precision_warnings(col, col_values))

    lines = [",".join(names)]
    for row in zip(*values, strict=True):
        lines.append(
            ",".join(format_cell(c.kind, v, c.name) for c, v in zip(cols, row, strict=True))
        )
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    for note in notes:
        log.warning("%s: %s", path.name, note)
    return InputCsv(
        path=path,
        columns=tuple(cols),
        rows=tbl.num_rows,
        sha256=hashlib.sha256(payload).hexdigest(),
        warnings=tuple(notes),
    )


### PROC CONTENTS metadata


class SasCategory(StrEnum):
    """
    What a variable holds, from its type and ``FMTINFO(format, 'cat')``.
    """

    NUM = "num"
    CHAR = "char"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"


class SasVariable(BaseModel):
    """
    One variable of a SAS data set, as PROC CONTENTS describes it.

    Attributes:
        name: Up to 32 characters, of any kind under ``VALIDVARNAME=ANY``.
        varnum: The variable's position in the data set, from 1.
        type: ``num`` or ``char``.
        length: Storage length in bytes.
        format: Name of the attached format, without width or decimals, such as ``YYMMDD``;
            empty if there is none.
        formatl: The format's width, or 0.
        formatd: The format's decimals, or 0.
        informat: Name of the attached informat; empty if there is none.
        label: The variable's label; empty if there is none.
        category: What the variable holds, which decides how it is exported and parsed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=32)
    varnum: int = Field(ge=1)
    type: Literal["num", "char"]
    length: int = Field(ge=1, le=MAX_CHAR_LENGTH)
    format: str = ""
    formatl: int = 0
    formatd: int = 0
    informat: str = ""
    label: str = ""
    category: SasCategory

    @model_validator(mode="after")
    def _check(self) -> SasVariable:
        """
        Require ``category`` to be ``char`` exactly when ``type`` is.
        """
        if (self.type == "char") != (self.category is SasCategory.CHAR):
            raise ValueError(f"{self.name}: type {self.type} does not fit category {self.category}")
        return self

    @property
    def export_format(self) -> str:
        """
        The explicit format :func:`export_step` writes this variable with.
        """
        match self.category:
            case SasCategory.CHAR:
                return f"$CHAR{self.length}."
            case SasCategory.DATE:
                return DATE_FORMAT
            case SasCategory.DATETIME:
                return DATETIME_FORMAT
            case _:
                return NUM_FORMAT

    @property
    def max_field_bytes(self) -> int:
        """
        The longest this variable's exported field can be, quotes and doubled quotes included.
        """
        match self.category:
            case SasCategory.CHAR:
                return 2 * self.length + 2
            case SasCategory.DATE:
                return 10
            case SasCategory.DATETIME:
                return 26
            case _:
                return NUM_WIDTH


# the work data set :func:`contents_step` writes the metadata to
META_DATASET = "work._lansh_meta"

# the variables of :data:`META_DATASET`, in the order :func:`export_step` writes them
CONTENTS_VARIABLES: tuple[SasVariable, ...] = (
    SasVariable(name="varnum", varnum=1, type="num", length=8, category=SasCategory.NUM),
    SasVariable(name="name", varnum=2, type="char", length=32, category=SasCategory.CHAR),
    SasVariable(name="type", varnum=3, type="char", length=4, category=SasCategory.CHAR),
    SasVariable(name="length", varnum=4, type="num", length=8, category=SasCategory.NUM),
    SasVariable(name="format", varnum=5, type="char", length=32, category=SasCategory.CHAR),
    SasVariable(name="formatl", varnum=6, type="num", length=8, category=SasCategory.NUM),
    SasVariable(name="formatd", varnum=7, type="num", length=8, category=SasCategory.NUM),
    SasVariable(name="informat", varnum=8, type="char", length=32, category=SasCategory.CHAR),
    SasVariable(name="label", varnum=9, type="char", length=256, category=SasCategory.CHAR),
    SasVariable(name="nobs", varnum=10, type="num", length=8, category=SasCategory.NUM),
    SasVariable(name="category", varnum=11, type="char", length=8, category=SasCategory.CHAR),
)


def contents_step(dataset: str, meta_dataset: str = META_DATASET) -> str:
    """
    Generate SAS code that writes PROC CONTENTS of ``dataset`` to ``meta_dataset``.

    The metadata has one row per variable, in VARNUM order, with the variables of
    :data:`CONTENTS_VARIABLES`. Each row gets a ``category`` from ``FMTINFO(format, 'cat')``:
    ``date``, ``datetime`` or ``time`` for numbers with such a format, ``num`` for every
    other number (DOLLAR's ``curr`` and user formats included), ``char`` for text.

    Args:
        dataset: The data set to describe, such as ``work.claims``.
        meta_dataset: The data set to write the metadata to.

    Returns:
        The SAS code.

    Raises:
        ValueError: If either name is not a SAS data set name.
    """
    check_dataset(dataset)
    check_dataset(meta_dataset)
    lib, _, member = meta_dataset.rpartition(".")
    raw = f"{meta_dataset}_raw"
    return "\n".join(
        [
            _comment(f"LANSH: metadata of {dataset}"),
            f"proc contents data={dataset} out={raw} noprint;",
            "run;",
            f"proc sort data={raw};",
            "  by varnum;",
            "run;",
            f"data {meta_dataset};",
            "  length type $4 category $8;",
            f"  set {raw}(keep=varnum name type length format formatl formatd informat label nobs",
            "    rename=(type=_lansh_type));",
            "  type = ifc(_lansh_type = 2, 'char', 'num');",
            "  if _lansh_type = 2 then category = 'char';",
            "  else if format = ' ' then category = 'num';",
            "  else category = lowcase(fmtinfo(format, 'cat'));",
            "  if type = 'num' and category not in ('date', 'datetime', 'time') then",
            "    category = 'num';",
            "  drop _lansh_type;",
            "run;",
            f"proc datasets lib={lib or 'work'} nolist;",
            f"  delete {member}_raw;",
            "quit;",
            "",
        ]
    )


@dataclass(frozen=True)
class SasContents:
    """
    A data set's variables in VARNUM order, and its number of observations.
    """

    variables: tuple[SasVariable, ...]
    nobs: int


def _na_to_none(value: Any) -> Any:
    """
    Turn pandas' missing values (None, ``pd.NA`` or NaN) into None.
    """
    return (
        None
        if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))
        else value
    )


def read_contents(csv_path: Path) -> SasContents:
    """
    Parse the metadata CSV that :func:`contents_step` plus :func:`export_step` wrote.

    Args:
        csv_path: The downloaded metadata CSV.

    Returns:
        The variables in VARNUM order, and the number of observations.

    Raises:
        ValueError: If the file does not match :data:`CONTENTS_VARIABLES`.
    """
    frame = parse_export(csv_path, CONTENTS_VARIABLES).frame
    variables = []
    nobs = 0
    for record in frame.to_dict(orient="records"):
        row = {k: _na_to_none(v) for k, v in record.items()}
        variables.append(
            SasVariable(
                name=row["name"],
                varnum=int(row["varnum"]),
                type=row["type"],
                length=int(row["length"]),
                format=row["format"] or "",
                formatl=int(row["formatl"] or 0),
                formatd=int(row["formatd"] or 0),
                informat=row["informat"] or "",
                label=row["label"] or "",
                category=SasCategory(row["category"]),
            )
        )
        nobs = int(row["nobs"]) if row["nobs"] is not None else 0
    variables.sort(key=lambda v: v.varnum)
    return SasContents(variables=tuple(variables), nobs=nobs)


### Generated SAS code: read and export


def read_step(
    dataset: str, csv_path: str, columns: Sequence[InputColumn], *, lrecl: int | None = None
) -> str:
    """
    Generate a DATA step that reads the CSV at ``csv_path`` into ``dataset``.

    Every column has an explicit informat (and the matching format, so PROC CONTENTS can tell
    dates and datetimes apart later). ``_row_seq`` is always among the columns.

    ``E8601DT26.6`` reports an empty field as invalid data, so a datetime is read as text
    first and converted with ``INPUT(text, E8601DT26.6)`` only when present. A malformed
    datetime still shows in the log, as an invalid argument to INPUT.

    Args:
        dataset: The data set to create, such as ``work.claims``.
        csv_path: The CSV's absolute path on the SAS server.
        columns: The CSV's columns, in file order.
        lrecl: The record length; by default the longest possible row, and at least 256.

    Returns:
        The SAS code.

    Raises:
        ValueError: If the data set name or the path is unsafe, or ``_row_seq`` is missing.
    """
    check_dataset(dataset)
    check_remote_path(csv_path)
    names = [c.name for c in columns]
    if ROW_SEQ not in names:
        raise ValueError(f"the read step always includes {ROW_SEQ}")
    if lrecl is None:
        lrecl = max(256, sum(c.max_field_bytes + 1 for c in columns) + 1)
    staged = {c.name: f"{RESERVED_PREFIX}_t{i}" for i, c in enumerate(columns, start=1)
              if c.kind is ColumnKind.DATETIME}  # fmt: skip
    width = max(len(n) for n in [*names, *staged.values()])
    reads = [
        f"    {staged[c.name]:<{width}} :$26." if c.name in staged
        else f"    {c.name:<{width}} :{c.informat}"
        for c in columns
    ]  # fmt: skip
    lines = [
        _comment(
            f"LANSH: read {csv_path.rsplit('/', 1)[-1]} into {dataset} with explicit informats"
        ),
        f"data {dataset};",
        f"  infile {sas_string(csv_path)} dsd dlm=',' firstobs=2 truncover lrecl={lrecl}",
        "    encoding='utf-8' termstr=LF;",
        "  length",
        *(f"    {c.name:<{width}} {c.sas_length}" for c in columns),
        *(f"    {temp:<{width}} $26" for temp in staged.values()),
        "  ;",
        "  format",
        *(f"    {c.name:<{width}} {c.format}" for c in columns),
        "  ;",
        "  input",
        *reads,
        "  ;",
    ]
    for name, temp in staged.items():
        lines.append(f"  if not missing({temp}) then {name} = input({temp}, {DATETIME_INFORMAT});")
    if staged:
        lines.append(f"  drop {' '.join(staged.values())};")
    lines += ["run;", ""]
    return "\n".join(lines)


def _put_field(lines: list[str], first: bool) -> None:
    """
    Append the PUT statements that write ``_lansh_v`` as the next field of the line.

    ``$VARYING32767.`` writes exactly ``_lansh_l`` bytes, so a missing value (length 0) is
    an empty field. A comma goes before every field but the first.
    """
    if not first:
        lines.append("  put ',' @;")
    lines.append("  put _lansh_v $varying32767. _lansh_l @;")


def export_step(
    dataset: str,
    csv_path: str,
    variables: Sequence[SasVariable],
    hex_path: str | None = None,
) -> str:
    """
    Generate a DATA step that writes ``dataset`` to CSV with explicit formats.

    Formats: ``BEST32.`` for numbers, ``YYMMDD10.`` for dates, ``E8601DT26.6`` for datetimes
    and ``$CHARw.`` for text. Text is double-quoted with quotes doubled and trailing blanks
    removed; a missing value of any kind (a blank text value included) is an empty field.

    With ``hex_path``, every numeric variable is also written as ``HEX16.`` to a sidecar CSV,
    one row per observation, numbered in ``_lansh_obs``.

    Args:
        dataset: The data set to export.
        csv_path: The CSV's absolute path on the SAS server.
        variables: The variables to write, in column order, as PROC CONTENTS describes them.
        hex_path: The sidecar's absolute path on the SAS server, or None for no sidecar.

    Returns:
        The SAS code.

    Raises:
        ValueError: If the data set name or a path is unsafe, or there are no variables.
    """
    check_dataset(dataset)
    check_remote_path(csv_path)
    if hex_path is not None:
        check_remote_path(hex_path)
    if not variables:
        raise ValueError("nothing to export: no variables")
    numeric = [v for v in variables if v.type == "num"]
    lrecl = max(256, sum(v.max_field_bytes + 1 for v in variables) + 1)
    hex_lrecl = max(256, NUM_WIDTH + 17 * len(numeric) + 1)

    lines = [
        _comment(f"LANSH: export {dataset} with explicit formats"),
        f"filename _lxcsv {sas_string(csv_path)} encoding='utf-8' nobom termstr=LF lrecl={lrecl};",
    ]
    if hex_path is not None:
        lines.append(
            f"filename _lxhex {sas_string(hex_path)} encoding='utf-8' nobom termstr=LF "
            f"lrecl={hex_lrecl};"
        )
    # the header rows come before SET, so an empty data set still gets them
    lines += ["data _null_;", "  length _lansh_v $32767 _lansh_l 8;", "  if _n_ = 1 then do;"]
    lines.append("    file _lxcsv;")
    for i, var in enumerate(variables):
        lines.append(f"    put {sas_string(('' if i == 0 else ',') + csv_quote(var.name))} @;")
    lines.append("    put;")
    if hex_path is not None:
        lines.append("    file _lxhex;")
        lines.append(f"    put {sas_string(csv_quote(HEX_OBS))} @;")
        for var in numeric:
            lines.append(f"    put {sas_string(',' + csv_quote(var.name))} @;")
        lines.append("    put;")
    lines += ["  end;", f"  set {dataset};", "  file _lxcsv;"]
    for i, var in enumerate(variables):
        ref = name_literal(var.name)
        fmt = var.export_format
        lines.append("  " + _comment(f"{var.name}: {var.type} {var.category} -> {fmt}"))
        lines.append(f"  if missing({ref}) then _lansh_l = 0;")
        if var.category is SasCategory.CHAR:
            lines += [
                "  else do;",
                f"    _lansh_v = tranwrd(put({ref}, {fmt}), '\"', '\"\"');",
                "    _lansh_v = '\"' || trimn(_lansh_v) || '\"';",
                "    _lansh_l = lengthn(_lansh_v);",
                "  end;",
            ]
        else:
            # BEST32. right-aligns its digits in 32 columns, so strip the leading blanks
            value = f"strip(put({ref}, {fmt}))" if fmt == NUM_FORMAT else f"put({ref}, {fmt})"
            lines.append(f"  else do; _lansh_v = {value}; _lansh_l = lengthn(_lansh_v); end;")
        _put_field(lines, first=i == 0)
    lines.append("  put;")
    if hex_path is not None:
        lines += [
            "  file _lxhex;",
            "  _lansh_v = strip(put(_n_, BEST32.)); _lansh_l = lengthn(_lansh_v);",
        ]
        _put_field(lines, first=True)
        for var in numeric:
            ref = name_literal(var.name)
            lines.append("  " + _comment(f"{var.name}: exact bits"))
            lines.append(f"  if missing({ref}) then _lansh_l = 0;")
            lines.append(f"  else do; _lansh_v = put({ref}, {HEX_FORMAT}); _lansh_l = 16; end;")
            _put_field(lines, first=False)
        lines.append("  put;")
    lines += ["run;", "filename _lxcsv clear;"]
    if hex_path is not None:
        lines.append("filename _lxhex clear;")
    lines.append("")
    return "\n".join(lines)


### Parsing an export back into typed pandas


@dataclass(frozen=True)
class ParsedExport:
    """
    A parsed export: the typed frame, and how far the formatted text could be trusted.

    Attributes:
        frame: One typed column per variable.
        exact: Whether numbers, dates and datetimes came from the ``HEX16.`` sidecar.
        text_differs: Per column, the number of values whose formatted text (``BEST32.``,
            ``E8601DT26.6``) is not the exact value; the frame holds the exact value from
            ``HEX16.``.
        warnings: Notes on single values, such as a date with a fraction of a day.
    """

    frame: pd.DataFrame
    exact: bool
    text_differs: dict[str, int]
    warnings: tuple[str, ...] = ()


def _read_csv_rows(path: Path, width: int) -> list[list[str | None]]:
    """
    Read an exported CSV into rows of fields, with an empty unquoted field as None.

    Args:
        path: The CSV file.
        width: Its number of columns, so that an empty line in a one-column file reads as a
            missing value.
    """
    # utf-8-sig: SAS writes a BOM to a file opened with encoding='utf-8' unless told nobom
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows: list[list[str | None]] = list(
            csv.reader(handle, quoting=csv.QUOTE_NOTNULL, strict=True)
        )
    # a one-column row holding a missing value is an empty line, which csv reads as []
    return [[None] if (width == 1 and row == []) else row for row in rows]


# how far formatted text may be from the exact value before the files count as out of step.
# BEST32. keeps 15 significant digits at best and as few as 10 for small numbers (the spike
# saw a relative error of 4.4e-10 at 1.7e-05). Row alignment itself is checked by _lansh_obs
TEXT_REL_TOLERANCE = 1e-7


def _close(text_value: float, exact: float) -> bool:
    """
    Tell whether a value read from text is within :data:`TEXT_REL_TOLERANCE` of the exact one.

    The absolute tolerance lets the text ``0`` match a subnormal, which ``BEST32.`` writes as 0.
    """
    return math.isclose(text_value, exact, rel_tol=TEXT_REL_TOLERANCE, abs_tol=1e-300)


def _parse_float(text: str, where: str) -> float:
    """
    Read number text, naming the cell in the error if it is not a number.
    """
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{where}: {text!r} is not a number") from exc


def _convert_numeric(
    var: SasVariable, texts: list[str | None], hexes: list[str | None] | None
) -> tuple[list[float | None], int]:
    """
    Convert a numeric column, taking the exact values from ``HEX16.`` when there is a sidecar.

    Args:
        var: The variable.
        texts: The column's formatted fields; None where missing.
        hexes: The column's ``HEX16.`` fields, or None without a sidecar.

    Returns:
        The values, and how many of them differ from their text, bit for bit.

    Raises:
        ValueError: If a field is not a number, or the text and ``HEX16.`` disagree on
            missing values or by more than :data:`TEXT_REL_TOLERANCE`.
    """
    values: list[float | None] = []
    differs = 0
    for i, text in enumerate(texts):
        where = f"{var.name} row {i + 1}"
        text_value = None if text is None else _parse_float(text, where)
        if hexes is None:
            values.append(text_value)
            continue
        exact = hex16_to_float(hexes[i])
        if (text_value is None) != (exact is None):
            raise ValueError(f"{where}: text {text!r} and HEX16 {hexes[i]!r} disagree on missing")
        if exact is not None and text_value is not None:
            if not _close(text_value, exact):
                raise ValueError(f"{where}: text {text!r} is not HEX16 {hexes[i]} ({exact!r})")
            if float_to_hex16(text_value) != float_to_hex16(exact):
                differs += 1
        values.append(exact)
    return values, differs


def _text_date(text: str | None) -> date | None:
    """
    Read a ``YYMMDD10.`` field; None if missing or overflowed (SAS then prints asterisks).
    """
    if text is None or "*" in text:
        return None
    return date.fromisoformat(text)


def _text_datetime(text: str | None) -> datetime | None:
    """
    Read an ``E8601DT26.6`` field; None if missing or overflowed (SAS then prints asterisks).
    """
    if text is None or "*" in text:
        return None
    return datetime.fromisoformat(text)


def _convert_temporal(
    var: SasVariable, texts: list[str | None], hexes: list[str | None] | None
) -> tuple[list[Any], int, list[str]]:
    """
    Convert a date or datetime column, taking the exact values from ``HEX16.`` if present.

    Text one microsecond off the exact datetime (``E8601DT26.6`` does that for some pre-1960
    values) or overflowed into asterisks (after 9999) counts as a difference, not an error.

    Args:
        var: The variable, a date or a datetime.
        texts: The column's formatted fields; None where missing.
        hexes: The column's ``HEX16.`` fields, or None without a sidecar.

    Returns:
        The values, how many differ from their text, and notes on fractional days and
        overflowed text.

    Raises:
        ValueError: If text cannot be read, has overflowed with no sidecar, or disagrees with
            ``HEX16.`` on missing values, by more than a microsecond, or (for a date) at all.
    """
    values: list[Any] = []
    differs = 0
    notes: list[str] = []
    is_date = var.category is SasCategory.DATE
    for i, text in enumerate(texts):
        where = f"{var.name} row {i + 1}"
        try:
            from_text = _text_date(text) if is_date else _text_datetime(text)
        except ValueError as exc:
            raise ValueError(f"{where}: cannot read {text!r}") from exc
        if hexes is None:
            if text is not None and from_text is None:
                raise ValueError(f"{where}: {text!r} overflowed its format and there is no HEX16")
            values.append(from_text)
            continue
        seconds = hex16_to_float(hexes[i])
        if (text is None) != (seconds is None):
            raise ValueError(f"{where}: text {text!r} and HEX16 {hexes[i]!r} disagree on missing")
        if seconds is None:
            values.append(None)
            continue
        if is_date:
            exact: Any = sas_to_date(seconds)
            if seconds != math.floor(seconds):
                notes.append(f"{where}: date value {seconds!r} has a fraction of a day")
        else:
            exact = sas_to_datetime(seconds)
        if from_text is None:
            notes.append(f"{where}: {text!r} overflowed its format; HEX16 gives {exact}")
            differs += 1
        elif from_text != exact:
            gap = abs(from_text - exact) if not is_date else timedelta(days=1)
            if is_date or gap > timedelta(microseconds=1):
                raise ValueError(f"{where}: text {text!r} is not HEX16 {hexes[i]} ({exact})")
            differs += 1
        values.append(exact)
    return values, differs, notes


def _typed_array(var: SasVariable, values: list[Any]) -> Any:
    """
    Build the typed pandas column for a variable (see :func:`parse_export` for the types).
    """
    match var.category:
        case SasCategory.CHAR:
            return pd.array(values, dtype="string")
        case SasCategory.DATE:
            return pd.array(values, dtype=pd.ArrowDtype(pa.date32()))
        case SasCategory.DATETIME:
            return pd.array([pd.NaT if v is None else v for v in values], dtype="datetime64[us]")
        case _:
            return np.array([np.nan if v is None else v for v in values], dtype=np.float64)


def parse_export(
    csv_path: Path,
    variables: Sequence[SasVariable],
    hex_path: Path | None = None,
    *,
    nobs: int | None = None,
) -> ParsedExport:
    """
    Parse an export into typed pandas, using the PROC CONTENTS metadata.

    Types: ``char`` -> ``string`` (missing is ``<NA>``); a number with a date format -> date
    (``date32[pyarrow]``); a datetime format -> ``datetime64[us]``; every other number
    (``time`` included, in seconds) -> ``float64`` (missing is NaN). With ``hex_path``, numbers,
    dates and datetimes come from the exact ``HEX16.`` sidecar.

    Args:
        csv_path: The export CSV.
        variables: The variables, in the export's column order.
        hex_path: The ``HEX16.`` sidecar, or None to rely on the formatted text alone.
        nobs: The number of observations PROC CONTENTS reported, to check the row count.

    Returns:
        The typed frame, whether it is exact, and per column how many values the text alone
        would have got wrong.

    Raises:
        ValueError: If the header, the row count or a row's width does not match the
            metadata, the sidecar is out of step with the export, or a value cannot be read.
    """
    names = [v.name for v in variables]
    rows = _read_csv_rows(Path(csv_path), len(names))
    if not rows or rows[0] != names:
        header = rows[0] if rows else None
        raise ValueError(f"{Path(csv_path).name}: header {header} is not the metadata {names}")
    body = rows[1:]
    if nobs is not None and len(body) != nobs:
        raise ValueError(f"{Path(csv_path).name}: {len(body)} rows, but PROC CONTENTS says {nobs}")
    for i, row in enumerate(body, start=1):
        if len(row) != len(names):
            raise ValueError(
                f"{Path(csv_path).name}: row {i} has {len(row)} fields, not {len(names)}"
            )

    numeric = [v for v in variables if v.type == "num"]
    hex_columns: dict[str, list[str | None]] | None = None
    if hex_path is not None:
        hex_header = [HEX_OBS, *(v.name for v in numeric)]
        hex_rows = _read_csv_rows(Path(hex_path), len(hex_header))
        if not hex_rows or hex_rows[0] != hex_header:
            raise ValueError(f"{Path(hex_path).name}: header does not match the numeric variables")
        hex_body = hex_rows[1:]
        if len(hex_body) != len(body):
            raise ValueError(f"{Path(hex_path).name}: {len(hex_body)} rows, not {len(body)}")
        for i, row in enumerate(hex_body, start=1):
            if len(row) != len(hex_header) or row[0] != str(i):
                raise ValueError(f"{Path(hex_path).name}: row {i} is out of step with the export")
        hex_columns = {v.name: [row[j + 1] for row in hex_body] for j, v in enumerate(numeric)}

    data: dict[str, Any] = {}
    differs: dict[str, int] = {}
    notes: list[str] = []
    for j, var in enumerate(variables):
        texts = [row[j] for row in body]
        hexes = hex_columns.get(var.name) if hex_columns is not None else None
        if var.category is SasCategory.CHAR:
            values: list[Any] = texts
            n_diff = 0
        elif var.category in (SasCategory.DATE, SasCategory.DATETIME):
            values, n_diff, more = _convert_temporal(var, texts, hexes)
            notes.extend(more)
        else:
            values, n_diff = _convert_numeric(var, texts, hexes)
        data[var.name] = _typed_array(var, values)
        if n_diff:
            differs[var.name] = n_diff
    frame = pd.DataFrame(data, columns=names)
    return ParsedExport(
        frame=frame, exact=hex_columns is not None, text_differs=differs, warnings=tuple(notes)
    )


### The session

_ERROR = re.compile(r"^ERROR(?: \d+-\d+)?:.*$", re.MULTILINE)
_WARNING = re.compile(r"^WARNING(?: \d+-\d+)?:.*$", re.MULTILINE)
_READ_PROBLEM = re.compile(
    r"^NOTE: (?:Invalid data|Invalid argument|LOST CARD|SAS went to a new line).*$", re.MULTILINE
)
_DATA_NOTE = re.compile(
    r"^NOTE: (?:Missing values were generated|Character values have been converted|"
    r"Numeric values have been converted|Mathematical operations could not be performed|"
    r"Division by zero).*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class LogScan:
    """
    The lines of a SAS log that matter for trusting its results.

    Attributes:
        errors: ``ERROR:`` lines.
        warnings: ``WARNING:`` lines.
        read_problems: Notes that an informat or a record failed, so values were lost.
        data_notes: Notes of legacy semantics at work, such as missing values generated.
    """

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    read_problems: tuple[str, ...]
    data_notes: tuple[str, ...]


def scan_log(text: str) -> LogScan:
    """
    Find errors, warnings, read problems and notable data notes in a SAS log.

    Args:
        text: A SAS log, redacted or not.

    Returns:
        The matching lines, stripped, in log order.
    """
    return LogScan(
        errors=tuple(m.group(0).strip() for m in _ERROR.finditer(text)),
        warnings=tuple(m.group(0).strip() for m in _WARNING.finditer(text)),
        read_problems=tuple(m.group(0).strip() for m in _READ_PROBLEM.finditer(text)),
        data_notes=tuple(m.group(0).strip() for m in _DATA_NOTE.finditer(text)),
    )


class SasError(RuntimeError):
    """
    SAS failed, or its log reported an error.

    Attributes:
        log_text: The failing step's redacted log; empty if there is none.
    """

    def __init__(self, message: str, log_text: str = "") -> None:
        """
        Keep the message, and the log that goes with it.

        Args:
            message: What failed.
            log_text: The failing step's redacted log, if there is one.
        """
        super().__init__(message)
        self.log_text = log_text


@dataclass(frozen=True)
class SubmitLog:
    """
    One step run in a session: what it was, how long it took, and its redacted log.

    The last four fields are the step's :class:`LogScan`.
    """

    label: str
    seconds: float
    log: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    read_problems: tuple[str, ...] = ()
    data_notes: tuple[str, ...] = ()


def _marker(text: str, name: str) -> str:
    """
    Read the value a step printed as ``NAME=value`` at the start of a log line.

    Raises:
        SasError: If no line has it.
    """
    match = re.search(rf"^{re.escape(name)}=(.*)$", text, re.MULTILINE)
    if not match:
        raise SasError(f"SAS did not report {name}")
    return match.group(1).strip()


# options set when a session starts. SAS OnDemand starts workspace sessions with NONOTES,
# which hides records read, observations written and invalid data from the log
SESSION_OPTIONS = "source notes"


class SasSession:
    """
    A saspy session to SAS, normally SAS OnDemand, used as a context manager.

    The session always ends on exit, even after an error. It turns NOTES on (see
    :data:`SESSION_OPTIONS`), and every step's log is kept in :attr:`logs`, with the home
    directory and user ID replaced by ``~`` and ``<user>``. SAS OnDemand may limit concurrent
    sessions, so open one at a time.

    Attributes:
        cfgname: The saspy configuration in use.
        strict: Whether an error in a step's log raises :class:`SasError`.
        logs: Every step's kept log, in order.
        timings: Seconds per step, in order, with the session's start and end.
        version: The SAS version, once open.
        encoding: The session encoding, such as ``utf-8``, once open.
    """

    def __init__(self, cfgname: str | None = None, *, strict: bool = True) -> None:
        """
        Set up a session; SAS starts only on :meth:`open` or entering the ``with`` block.

        Args:
            cfgname: The saspy configuration; by default ``LANSH_SAS_CFGNAME``, or else
                :data:`DEFAULT_CFGNAME`.
            strict: Raise :class:`SasError` when a step's log has an error.
        """
        self.cfgname = cfgname or env("LANSH_SAS_CFGNAME", DEFAULT_CFGNAME) or DEFAULT_CFGNAME
        self.strict = strict
        self.logs: list[SubmitLog] = []
        self.timings: list[tuple[str, float]] = []
        self.version = ""
        self.encoding = ""
        self._home = ""
        self._secrets: list[tuple[re.Pattern[str], str]] = []
        self._sas: saspy.SASsession | None = None

    ### Lifecycle

    def __enter__(self) -> Self:
        """
        Open the session.

        Returns:
            This session, now open.
        """
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        End the session, whatever ended the ``with`` block; an exception still propagates.

        Args:
            exc_type: The type of the exception that ended the block, or None.
            exc: That exception, or None.
            traceback: Its traceback, or None.
        """
        self.close()

    @property
    def is_open(self) -> bool:
        """
        Whether the session is open.
        """
        return self._sas is not None

    def open(self) -> None:
        """
        Start SAS and learn its version, encoding and home directory.

        The home directory and user ID found here are what :meth:`redact` replaces. If
        anything fails once SAS has started, the session is ended before the error
        propagates.

        Raises:
            SasError: If the session is already open, SAS does not start, the saspy
                configuration is not valid, or the home directory cannot be found.
        """
        if self._sas is not None:
            raise SasError("this session is already open")
        import saspy  # imported here so that offline code never touches SAS

        started = time.perf_counter()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sas = saspy.SASsession(cfgname=self.cfgname, results="TEXT")
        except Exception as exc:
            raise SasError(
                f"could not start SAS with saspy config {self.cfgname!r}: {exc}"
            ) from exc
        self._sas = sas
        try:
            if getattr(sas, "_io", None) is None:
                raise SasError(f"saspy config {self.cfgname!r} is not valid")
            self.version = str(getattr(sas, "sasver", ""))
            self.encoding = str(getattr(sas, "sascei", ""))
            raw = self._raw_submit(
                "options nosource;\n%put LANSH_HOME=%sysget(HOME);\n"
                f"%put LANSH_USER=&SYSUSERID;\noptions {SESSION_OPTIONS};\n"
            )
            home = _marker(raw, "LANSH_HOME").rstrip("/")
            user = _marker(raw, "LANSH_USER")
            if not home.startswith("/"):
                raise SasError("could not find the SAS home directory")
            self._home = home
            # longest first, so an ID that contains the other is replaced whole
            ids = sorted({user, home.rsplit("/", 1)[-1]} - {""}, key=len, reverse=True)
            self._secrets = [(re.compile(re.escape(home)), "~")] + [
                (re.compile(rf"(?<![\w]){re.escape(i)}(?![\w])"), "<user>") for i in ids
            ]
        except BaseException:  # even on Ctrl-C, so that no session is left running
            self.close()
            raise
        seconds = time.perf_counter() - started
        self.timings.append(("start session", seconds))
        log.info(
            "SAS %s started in %.1fs (session encoding %s)", self.version, seconds, self.encoding
        )

    def close(self) -> None:
        """
        End the SAS session; safe to call twice, and never raises.
        """
        sas, self._sas = self._sas, None
        if sas is None:
            return
        started = time.perf_counter()
        try:
            sas.endsas()
        except Exception:  # ending must never hide the error that brought us here
            log.warning("ending the SAS session failed", exc_info=True)
        self.timings.append(("end session", time.perf_counter() - started))
        log.info("SAS session ended")

    def _require(self) -> saspy.SASsession:
        """
        Return the saspy session, or raise :class:`SasError` if it is not open.
        """
        if self._sas is None:
            raise SasError("the SAS session is not open")
        return self._sas

    ### Paths and redaction

    def redact(self, text: str) -> str:
        """
        Replace the home directory and user ID in ``text``.

        The home directory becomes ``~`` and the user ID ``<user>``, the ID only where it
        stands as a whole word. Before :meth:`open`, nothing is replaced.

        Args:
            text: A log or message from SAS.

        Returns:
            The redacted text.
        """
        for pattern, replacement in self._secrets:
            text = pattern.sub(replacement, text)
        return text

    def remote_path(self, *parts: str) -> str:
        """
        Build an absolute path under the SAS home directory.

        For example, ``remote_path('lansh', 'x')`` gives ``<home>/lansh/x``.

        Args:
            *parts: Path parts, which may hold slashes. Slashes at either end are ignored,
                and so are empty parts.

        Returns:
            The path, checked by :func:`check_remote_path`.

        Raises:
            SasError: If the session is not open.
            ValueError: If a part has a ``.``, ``..`` or empty segment inside it, or the path
                is unsafe.
        """
        self._require()
        clean = [p.strip("/") for p in parts if p.strip("/")]
        if any(seg in ("", ".", "..") for p in clean for seg in p.split("/")):
            raise ValueError(f"bad path parts {parts!r}")
        return check_remote_path("/".join([self._home, *clean]))

    ### Running code

    def _raw_submit(self, code: str) -> str:
        """
        Submit SAS code and return its log, unredacted.
        """
        sas = self._require()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # saspy warns on ERROR; we raise
            result = sas.submit(code, results="TEXT")
        return str(result.get("LOG", ""))

    def _record(self, label: str, seconds: float, raw_log: str) -> SubmitLog:
        """
        Redact and scan a step's log, keep it with its timing, and log its warnings.
        """
        text = self.redact(raw_log)
        scan = scan_log(text)
        entry = SubmitLog(
            label=label,
            seconds=seconds,
            log=text,
            errors=scan.errors,
            warnings=scan.warnings,
            read_problems=scan.read_problems,
            data_notes=scan.data_notes,
        )
        self.logs.append(entry)
        self.timings.append((label, seconds))
        for line in scan.warnings:
            log.warning("SAS %s: %s", label, line)
        return entry

    def submit(self, code: str, label: str, *, fail_on_read_problems: bool = False) -> SubmitLog:
        """
        Run SAS code and keep its log, even when it then raises.

        Args:
            code: The SAS code.
            label: A short name for the step in logs and timings, such as ``read work.claims``.
            fail_on_read_problems: Also raise on read problems, such as invalid-data notes.

        Returns:
            The step's kept log.

        Raises:
            SasError: If the log has errors (when ``strict``) or, with
                ``fail_on_read_problems``, read problems. The message quotes the first three.
        """
        started = time.perf_counter()
        raw = self._raw_submit(code)
        entry = self._record(label, time.perf_counter() - started, raw)
        if self.strict and entry.errors:
            raise SasError(f"SAS {label}: {'; '.join(entry.errors[:3])}", entry.log)
        if fail_on_read_problems and entry.read_problems:
            raise SasError(f"SAS {label}: {'; '.join(entry.read_problems[:3])}", entry.log)
        log.debug("SAS %s took %.2fs", label, entry.seconds)
        return entry

    def file_size(self, remote: str) -> int | None:
        """
        Find the size of a file on the SAS server.

        Args:
            remote: The file's absolute path on the server.

        Returns:
            The size in bytes, or None if the file does not exist.

        Raises:
            SasError: If the session is not open.
            ValueError: If the path is unsafe.
        """
        sas = self._require()
        check_remote_path(remote)
        info = sas.file_info(remote, quiet=True)
        if not info:
            return None
        size = info.get("File Size (bytes)")
        return int(size) if size not in (None, "") else None

    def upload(self, local: Path, remote: str) -> SubmitLog:
        """
        Copy a local file to the SAS server, bytes unchanged, and check its size.

        Args:
            local: The file to copy.
            remote: Its absolute path on the server; an existing file there is replaced.

        Returns:
            The kept log of the transfer.

        Raises:
            SasError: If saspy reports a failure, or the server's copy has a different size.
        """
        sas = self._require()
        check_remote_path(remote)
        started = time.perf_counter()
        # saspy judges an overwrite by comparing file attributes, which can miss a re-upload
        # within the same second; delete first so success means "the file now exists"
        sas.file_delete(remote, quiet=True)
        result = sas.upload(str(local), remote, overwrite=True)
        size = self.file_size(remote)
        entry = self._record(
            f"upload {Path(local).name}", time.perf_counter() - started, str(result.get("LOG", ""))
        )
        expected = Path(local).stat().st_size
        if not result.get("Success") or size != expected:
            raise SasError(
                f"upload of {Path(local).name} failed ({size} of {expected} bytes)", entry.log
            )
        return entry

    def download(self, remote: str, local: Path) -> SubmitLog:
        """
        Copy a file from the SAS server to ``local``, bytes unchanged, and check its size.

        Args:
            remote: The file's absolute path on the server.
            local: Where to write it; missing parent folders are created.

        Returns:
            The kept log of the transfer.

        Raises:
            SasError: If the file does not exist, saspy reports a failure, or the local copy
                has a different size.
        """
        sas = self._require()
        check_remote_path(remote)
        started = time.perf_counter()
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        size = self.file_size(remote)
        result = sas.download(str(local), remote, overwrite=True)
        name = remote.rsplit("/", 1)[-1]
        entry = self._record(
            f"download {name}", time.perf_counter() - started, str(result.get("LOG", ""))
        )
        got = Path(local).stat().st_size if Path(local).exists() else None
        if not result.get("Success") or size is None or got != size:
            raise SasError(f"download of {name} failed ({got} of {size} bytes)", entry.log)
        return entry

    def ensure_dir(self, remote_dir: str) -> None:
        """
        Create a directory, and any missing parents, under the SAS home directory.

        Args:
            remote_dir: The directory's absolute path on the server.

        Raises:
            ValueError: If the path is unsafe or not under the home directory. A path with a
                ``..`` segment counts as not under it, as it could climb out.
            SasError: If the directory does not exist afterwards.
        """
        self._require()
        check_remote_path(remote_dir)
        if not remote_dir.startswith(self._home + "/") or ".." in remote_dir.split("/"):
            raise ValueError("only directories under the SAS home directory are created")
        parts = remote_dir[len(self._home) + 1 :].strip("/").split("/")
        lines = ["data _null_;", "  length _lansh_p $1024;"]
        parent = self._home
        for part in parts:
            path = f"{parent}/{part}"
            lines.append(
                f"  if fileexist({sas_string(path)}) = 0 then "
                f"_lansh_p = dcreate({sas_string(part)}, {sas_string(parent)});"
            )
            parent = path
        lines += [
            f"  if fileexist({sas_string(remote_dir)}) then put 'LANSH_DIR=OK';",
            "  else put 'LANSH_DIR=MISSING';",
            "run;",
        ]
        entry = self.submit("\n".join(lines), label=f"mkdir {remote_dir[len(self._home) + 1 :]}")
        if _marker(entry.log, "LANSH_DIR") != "OK":
            raise SasError("could not create the directory on the SAS server", entry.log)

    def nobs(self, dataset: str) -> int:
        """
        Count the observations in a data set, without reading any of them.

        Args:
            dataset: The data set, such as ``work.claims``.

        Returns:
            The number of observations.
        """
        check_dataset(dataset)
        entry = self.submit(
            f"data _null_;\n  if 0 then set {dataset} nobs=_lansh_n;\n"
            "  put 'LANSH_NOBS=' _lansh_n;\n  stop;\nrun;\n",
            label=f"count {dataset}",
        )
        return int(_marker(entry.log, "LANSH_NOBS"))

    def full_log(self) -> str:
        """
        Join every kept log, in order, with a header line per step.

        Returns:
            The session's whole log so far.
        """
        parts = [f"=== {e.label} ({e.seconds:.2f}s) ===\n{e.log.rstrip()}\n" for e in self.logs]
        return "\n".join(parts)

    def write_log(self, path: Path) -> Path:
        """
        Write :meth:`full_log` to ``path`` as UTF-8.

        Args:
            path: The file to write; missing parent folders are created.

        Returns:
            ``path``.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.full_log(), encoding="utf-8")
        return path


### Tables in and out


@dataclass(frozen=True)
class UploadedTable:
    """
    A table now in SAS: the data set, the CSV that carried it, and its columns.

    Attributes:
        dataset: The data set the table was read into.
        rows: Its number of observations, the same as the CSV's data rows.
        columns: The columns, as the read step declared them.
        local_csv: The CSV as written locally.
        remote_csv: The CSV's path on the SAS server.
        sha256: SHA-256 of the CSV's bytes, in hex.
        warnings: Values SAS may not keep exactly (see :class:`InputCsv`).
    """

    dataset: str
    rows: int
    columns: tuple[InputColumn, ...]
    local_csv: Path
    remote_csv: str
    sha256: str
    warnings: tuple[str, ...] = ()


def upload_table(
    session: SasSession,
    table: pd.DataFrame | pa.Table,
    dataset: str,
    *,
    remote_dir: str,
    local_dir: Path,
    stem: str | None = None,
    columns: Sequence[InputColumn] | None = None,
    lengths: Mapping[str, int] | None = None,
) -> UploadedTable:
    """
    Write ``table`` as CSV, upload it and read it into ``dataset`` with explicit informats.

    Args:
        session: An open session.
        table: The table to send, with its ``_row_seq`` column.
        dataset: The data set to create, such as ``work.claims``.
        remote_dir: The server directory for the CSV (see :meth:`SasSession.ensure_dir`).
        local_dir: The local directory for the CSV.
        stem: The CSV's file name without ``.csv``; by default the data set's member name
            in lower case.
        columns: The columns to send; by default they are inferred.
        lengths: Byte lengths for character columns, used only when inferring.

    Returns:
        The data set, its row count and columns, and the CSV that carried it.

    Raises:
        SasError: If the upload fails, the read step reports an error or invalid data, or
            the row count differs from the CSV's.
        ValueError: If the table cannot go to SAS (see :func:`write_input_csv`).
    """
    check_dataset(dataset)
    stem = stem or dataset.rsplit(".", 1)[-1].lower()
    written = write_input_csv(table, Path(local_dir) / f"{stem}.csv", columns, lengths=lengths)
    remote_csv = f"{remote_dir.rstrip('/')}/{stem}.csv"
    session.upload(written.path, remote_csv)
    session.submit(
        read_step(dataset, remote_csv, written.columns),
        label=f"read {dataset}",
        fail_on_read_problems=True,
    )
    rows = session.nobs(dataset)
    if rows != written.rows:
        raise SasError(f"{dataset} has {rows} rows; the CSV had {written.rows}")
    return UploadedTable(
        dataset=dataset,
        rows=rows,
        columns=written.columns,
        local_csv=written.path,
        remote_csv=remote_csv,
        sha256=written.sha256,
        warnings=written.warnings,
    )


@dataclass(frozen=True)
class SasTable:
    """
    A data set brought back from SAS: typed frame, metadata and the raw files.

    Attributes:
        dataset: The data set that was exported.
        frame: The typed data (see :func:`parse_export`).
        contents: Its PROC CONTENTS metadata.
        csv_path: The downloaded export.
        hex_path: The downloaded ``HEX16.`` sidecar, or None if the export was not exact.
        contents_path: The downloaded metadata CSV.
        exact: Whether numbers, dates and datetimes came from ``HEX16.``.
        text_differs: Per column, how many values the formatted text alone would have got
            wrong.
        warnings: Notes from parsing, which are also logged.
    """

    dataset: str
    frame: pd.DataFrame
    contents: SasContents
    csv_path: Path
    hex_path: Path | None
    contents_path: Path
    exact: bool
    text_differs: dict[str, int]
    warnings: tuple[str, ...] = ()


def export_table(
    session: SasSession,
    dataset: str,
    *,
    remote_dir: str,
    local_dir: Path,
    stem: str | None = None,
    exact: bool = True,
) -> SasTable:
    """
    Export ``dataset`` with explicit formats, download it and parse it back.

    Writes ``<stem>.contents.csv`` (PROC CONTENTS), ``<stem>.csv`` (the export) and, with
    ``exact``, ``<stem>.hex.csv`` (``HEX16.`` of every numeric variable) into ``local_dir``.
    The metadata comes first, because the export needs each variable's type and format.

    Args:
        session: An open session.
        dataset: The data set to bring back, such as ``work.claims``.
        remote_dir: The server directory for the exported files.
        local_dir: The local directory for the downloads.
        stem: The file name stem; by default the data set's member name in lower case.
        exact: Also export ``HEX16.``, so values come back bit for bit.

    Returns:
        The typed frame, its metadata and the downloaded files.

    Raises:
        SasError: If a step or a download fails.
        ValueError: If the downloaded files do not agree (see :func:`parse_export`).
    """
    check_dataset(dataset)
    stem = stem or dataset.rsplit(".", 1)[-1].lower()
    local_dir = Path(local_dir)
    remote = remote_dir.rstrip("/")
    meta_remote = f"{remote}/{stem}.contents.csv"
    session.submit(
        contents_step(dataset) + export_step(META_DATASET, meta_remote, CONTENTS_VARIABLES),
        label=f"contents {dataset}",
    )
    contents_path = local_dir / f"{stem}.contents.csv"
    session.download(meta_remote, contents_path)
    contents = read_contents(contents_path)

    csv_remote = f"{remote}/{stem}.csv"
    hex_remote = f"{remote}/{stem}.hex.csv" if exact else None
    session.submit(
        export_step(dataset, csv_remote, contents.variables, hex_remote)
        + f"proc datasets lib=work nolist;\n  delete {META_DATASET.split('.')[-1]};\nquit;\n",
        label=f"export {dataset}",
    )
    csv_path = local_dir / f"{stem}.csv"
    session.download(csv_remote, csv_path)
    hex_path = None
    if hex_remote is not None:
        hex_path = local_dir / f"{stem}.hex.csv"
        session.download(hex_remote, hex_path)
    parsed = parse_export(csv_path, contents.variables, hex_path, nobs=contents.nobs)
    for note in parsed.warnings:
        log.warning("%s: %s", dataset, note)
    return SasTable(
        dataset=dataset,
        frame=parsed.frame,
        contents=contents,
        csv_path=csv_path,
        hex_path=hex_path,
        contents_path=contents_path,
        exact=parsed.exact,
        text_differs=parsed.text_differs,
        warnings=parsed.warnings,
    )
