"""
The legacy SQL Server database: DDL for the source extracts, and loading them.

``SynthInsureDW`` is rebuilt from scratch for every golden capture and every
``make legacy-verify`` run: base objects, the nine ``stg`` tables (DDL generated from the
data dictionary), then the committed Parquet extracts, loaded in ``_row_seq`` order. After
loading, every table is read back and its content hash compared with the Parquet file's, so
the legacy engine provably holds exactly the committed data.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pyarrow as pa

from lansh.config import DATA_DIR, LEGACY_DATABASE, TSQL_DIR
from lansh.contracts import TableSchema
from lansh.engines import mssql
from lansh.estate.fingerprint import content_sha256
from lansh.estate.generate import DICTIONARY_PATH, load_dictionary, read_tables

log = logging.getLogger(__name__)

DDL_DIR = TSQL_DIR / "ddl"
BASE_DDL = DDL_DIR / "00_base.sql"
STG_DDL = DDL_DIR / "01_stg_tables.sql"
"""Generated from the data dictionary by ``lansh estate ddl``; never edit it by hand."""


def stg_ddl(schemas: list[TableSchema]) -> str:
    """
    Build the CREATE TABLE script for the source extracts from the data dictionary.

    Each table is dropped first if it exists, so the script can be run again.
    ``tests/test_generate.py`` checks that the committed :data:`STG_DDL` matches it.

    Args:
        schemas: The ``stg`` table schemas, in dictionary order.

    Returns:
        The T-SQL script, with ``GO`` after every batch.
    """
    out = [
        "/*" + "=" * 78,
        "  SynthInsure Data Warehouse - source extract tables (schema stg)",
        "",
        "  GENERATED from estate/data/dictionary.yaml by `lansh estate ddl`.",
        "  Do not edit by hand: change the dictionary and regenerate.",
        "=" * 78 + "*/",
        "SET NOCOUNT ON;",
        "GO",
    ]
    for schema in schemas:
        width = max(len(c.name) for c in schema.columns)
        out.append(f"IF OBJECT_ID(N'{schema.name}', N'U') IS NOT NULL DROP TABLE {schema.name};")
        out.append("GO")
        if schema.description:
            out.append(f"-- {' '.join(schema.description.split())}")
        out.append(f"CREATE TABLE {schema.name} (")
        lines = []
        for col in schema.columns:
            null = "NULL" if col.nullable else "NOT NULL"
            lines.append(f"    {col.name.ljust(width)}  {col.legacy_type:<14} {null}")
        out.append(",\n".join(lines))
        out.append(");")
        out.append("GO")
    return "\n".join(out) + "\n"


def write_ddl(path: Path = STG_DDL) -> Path:
    """
    Regenerate the ``stg`` DDL script from the data dictionary (``lansh estate ddl``).

    Args:
        path: Where to write the script.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stg_ddl(load_dictionary(DICTIONARY_PATH)), encoding="utf-8")
    return path


def load_database(
    database: str = LEGACY_DATABASE, data_dir: Path = DATA_DIR, verify: bool = True
) -> dict[str, int]:
    """
    Recreate the legacy database and load every source extract.

    Args:
        database: The database to drop and recreate.
        data_dir: Folder holding the committed Parquet extracts.
        verify: Read every table back afterwards and compare content hashes.

    Returns:
        Rows loaded per bare table name.

    Raises:
        RuntimeError: With ``verify``, a table in SQL Server differs from its extract.
    """
    started = time.perf_counter()
    mssql.recreate_database(database)
    tables = read_tables(data_dir)
    counts: dict[str, int] = {}
    with mssql.connect(database) as conn:
        mssql.run_script(conn, BASE_DDL.read_text(encoding="utf-8"))
        mssql.run_script(conn, STG_DDL.read_text(encoding="utf-8"))
        for name, table in tables.items():
            t0 = time.perf_counter()
            ordered = table.sort_by("_row_seq")
            counts[name] = mssql.load_table(conn, f"stg.{name}", ordered)
            log.info(
                "loaded stg.%-22s %7d rows in %5.1fs", name, counts[name], time.perf_counter() - t0
            )
        if verify:
            verify_loaded(conn, tables)
    log.info(
        "loaded %d rows into %s in %.1fs",
        sum(counts.values()),
        database,
        time.perf_counter() - started,
    )
    return counts


def verify_loaded(conn: object, tables: dict[str, pa.Table]) -> None:
    """
    Read every ``stg`` table back and check it hashes the same as its Parquet extract.

    Args:
        conn: Open connection to the legacy database.
        tables: The extracts that were loaded, by bare table name.

    Raises:
        RuntimeError: A table's row count or content hash differs from its extract.
    """
    for name, table in tables.items():
        _, back = mssql.fetch_table(conn, f"stg.{name}")
        expected, actual = content_sha256(table), content_sha256(back)
        if back.num_rows != table.num_rows or expected != actual:
            raise RuntimeError(
                f"stg.{name} in SQL Server differs from its Parquet extract "
                f"({back.num_rows} vs {table.num_rows} rows)"
            )
    log.info("all %d source tables verified against their Parquet hashes", len(tables))
