"""
Hashes that identify data: file hashes and order-independent content hashes.

The content hash depends only on the column names, their Arrow types and the multiset of
typed values. It ignores row order and file format, so a table read back from SQL Server,
from Parquet or from Spark hashes the same when the data is the same.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa

_NULL = "\x00"
"""The canonical text of NULL. No real value's text is a bare NUL character."""


def file_sha256(path: Path | str, chunk: int = 1 << 20) -> str:
    """
    Hash a file's bytes.

    Args:
        path: File to hash.
        chunk: Bytes read at a time (1 MiB by default), so a big file never sits in memory.

    Returns:
        The SHA-256 as lower-case hex.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    """
    Hash text as UTF-8.

    Args:
        text: Text to hash.

    Returns:
        The SHA-256 as lower-case hex.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value: Any) -> str:
    """
    Render one value as unambiguous text for hashing.

    Zero is unsigned, so ``-0.0`` and ``Decimal('-0.00')`` hash as plain zero. Strings are
    JSON-quoted, so no string can pass for NULL or for a value of another type. Floats use
    ``repr``, which round-trips exactly, and datetimes always carry microseconds.

    Args:
        value: One Python value, as an Arrow column's ``to_pylist`` gives it.

    Returns:
        The value's canonical text.

    Raises:
        TypeError: The value's type has no canonical form.
    """
    if value is None:
        return _NULL
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, decimal.Decimal):
        if value == 0:
            value = value.copy_abs()
        return format(value, "f")
    if isinstance(value, float):
        if value != value:
            return "nan"
        return repr(0.0 if value == 0 else value)
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    raise TypeError(f"cannot fingerprint {type(value).__name__}")


def content_sha256(table: pa.Table, exclude: Iterable[str] = ()) -> str:
    """
    Hash a table's typed values, independent of row order.

    A header of column names and Arrow types is hashed first, then the canonical text of
    every row, sorted, so the same multiset of rows always gives the same hash.

    Args:
        table: Table to hash.
        exclude: Columns to leave out, such as volatile audit columns.

    Returns:
        The SHA-256 as lower-case hex.
    """
    skip = set(exclude)
    cols = [name for name in table.column_names if name not in skip]
    header = "|".join(f"{name}:{table.schema.field(name).type}" for name in cols)
    columns = [table.column(name).to_pylist() for name in cols]
    lines = sorted("\x1f".join(canonical(v) for v in row) for row in zip(*columns, strict=True))
    digest = hashlib.sha256(header.encode("utf-8"))
    for line in lines:
        digest.update(b"\n")
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()
