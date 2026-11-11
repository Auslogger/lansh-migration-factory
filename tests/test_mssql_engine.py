"""
The SQL Server adapter splits scripts, writes exact literals and round-trips tables without loss.

The round trips are marked ``mssql`` and need the SQL Server container (``make legacy-up``);
everything else runs offline.
"""

from __future__ import annotations

import datetime as dt
import decimal
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa
import pytest

from lansh.engines import mssql

D = decimal.Decimal


def test_split_batches_on_go_lines_only() -> None:
    script = (
        "CREATE TABLE a (x INT)\nGO\n-- GOAL is not GO\nSELECT 'GO'\n  go  \nSELECT 2\nGO -- end\n"
    )
    assert mssql.split_batches(script) == [
        "CREATE TABLE a (x INT)",
        "-- GOAL is not GO\nSELECT 'GO'",
        "SELECT 2",
    ]


@pytest.mark.parametrize(
    ("value", "literal"),
    [
        (None, "NULL"),
        (True, "1"),
        (42, "42"),
        (D("-1234.50"), "-1234.50"),
        (D("1E-7"), "0.0000001"),  # T-SQL would read 1E-7 as a float
        (0.1, "0.1"),
        (dt.date(2024, 2, 29), "'2024-02-29'"),
        (dt.datetime(2025, 12, 31, 23, 59, 59, 5), "'2025-12-31T23:59:59.000005'"),
        ("O'Brien ", "N'O''Brien '"),
        ("Seán Ó Briain", "N'Seán Ó Briain'"),
        ("", "N''"),
    ],
)
def test_sql_literal(value: object, literal: str) -> None:
    """
    Each value becomes the T-SQL literal that stores it exactly.
    """
    assert mssql.sql_literal(value) == literal


def test_sql_literal_refuses_unstorable_values() -> None:
    for bad in (float("nan"), D("NaN"), dt.datetime(2025, 1, 1, tzinfo=dt.UTC)):
        with pytest.raises(ValueError, match=r"cannot store|timezone"):
            mssql.sql_literal(bad)


def test_insert_statements_batch_rows() -> None:
    rows = iter([(1, "a"), (2, None), (3, "c")])
    stmts = list(mssql.insert_statements("stg.t", ["id", "v"], rows, batch=2))
    assert len(stmts) == 2
    assert stmts[0].startswith("INSERT INTO [stg].[t] ([id], [v]) VALUES\n(1, N'a'),\n(2, NULL)")
    assert stmts[1].endswith("(3, N'c')")


def test_quote_table_refuses_injection() -> None:
    assert mssql.quote_table("rpt.claims_summary") == "[rpt].[claims_summary]"
    with pytest.raises(ValueError, match="not a safe identifier"):
        mssql.quote_table("x; DROP TABLE y")


def test_names_with_a_trailing_newline_are_refused() -> None:
    """
    A pattern ending in ``$`` also matches just before a final line break; the check must not.
    """
    for bad in ("dbo.t\n", "t\n"):
        with pytest.raises(ValueError, match="not a safe identifier"):
            mssql.quote_table(bad)
    with pytest.raises(ValueError, match="not a safe identifier"):
        mssql.exec_proc(None, "dbo.p", {"as_of\n": "2025-12-31"})  # refused before any call


@dataclass
class FakeCursor:
    """
    Just enough of a pymssql cursor: it records each statement and returns canned rows.
    """

    rows: list[Any]
    executed: list[str]

    def execute(self, statement: str, params: Any = None) -> None:
        """
        Record the statement; nothing runs.
        """
        self.executed.append(statement)

    def fetchall(self) -> list[Any]:
        """
        Return the canned rows.
        """
        return self.rows


@dataclass
class FakeConnection:
    """
    A stand-in for a pymssql connection to a database holding one table.

    Dict cursors, which :func:`mssql.table_columns` opens, return the catalog rows; plain
    cursors return the table's rows. Every statement is recorded in ``executed``.
    """

    catalog: list[dict[str, Any]]
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    executed: list[str] = field(default_factory=list)

    def cursor(self, as_dict: bool = False) -> FakeCursor:
        """
        Open a cursor over the catalog rows (``as_dict``) or the table's rows.
        """
        return FakeCursor(self.catalog if as_dict else self.rows, self.executed)


def _catalog_row(name: str, sql_type: str, max_length: int) -> dict[str, Any]:
    """
    Describe a nullable column as the catalog query of :func:`mssql.table_columns` returns it.
    """
    return {
        "name": name,
        "sql_type": sql_type,
        "max_length": max_length,
        "precision": 0,
        "scale": 0,
        "is_nullable": True,
        "is_identity": False,
    }


def test_table_columns_treat_text_and_ntext_as_unbounded() -> None:
    """
    For TEXT and NTEXT, ``sys.columns.max_length`` is 16, the size of a pointer, not a limit.
    """
    conn = FakeConnection(
        [
            _catalog_row("notes", "text", 16),
            _catalog_row("memo", "ntext", 16),
            _catalog_row("name", "nvarchar", 80),
            _catalog_row("body", "varchar", -1),
        ]
    )
    cols = mssql.table_columns(conn, "dbo.t")
    assert [c.max_length for c in cols] == [None, None, 40, None]
    assert [c.to_spec().max_length for c in cols] == [None, None, 40, None]
    assert [c.legacy_type for c in cols] == ["TEXT", "NTEXT", "NVARCHAR(40)", "VARCHAR(MAX)"]


def test_bracketed_names_escape_closing_brackets() -> None:
    """
    A ``]`` inside a name is doubled, as QUOTENAME does, wherever a name is bracketed.
    """
    assert mssql.quote_name("odd]name") == "[odd]]name]"
    statement = next(mssql.insert_statements("stg.t", ["odd]name", "id"], iter([(1, 2)]), 10))
    assert statement.startswith("INSERT INTO [stg].[t] ([odd]]name], [id]) VALUES\n(1, 2)")
    conn = FakeConnection([_catalog_row("odd]name", "int", 4)], rows=[(7,)])
    _, data = mssql.fetch_table(conn, "dbo.t")
    assert conn.executed[-1] == "SELECT [odd]]name] FROM [dbo].[t]"
    assert data.column("odd]name").to_pylist() == [7]


@pytest.mark.parametrize(
    ("sql_type", "precision", "scale", "logical"),
    [
        ("varchar", None, None, "string"),
        ("nchar", None, None, "string"),
        ("decimal", 12, 2, "decimal(12,2)"),
        ("int", None, None, "int"),
        ("tinyint", None, None, "smallint"),  # 0 to 255, beyond Spark's signed tinyint
        ("datetime2", None, 0, "timestamp_ntz"),
        ("date", None, None, "date"),
        ("bit", None, None, "boolean"),
    ],
)
def test_type_mapping(
    sql_type: str, precision: int | None, scale: int | None, logical: str
) -> None:
    """
    SQL Server types map to the contract's logical types, and each of those has an Arrow type.
    """
    assert mssql.logical_type(sql_type, precision, scale) == logical
    mssql.arrow_type(sql_type, precision, scale)  # every logical type has an Arrow type


DB = "LanshEngineTest"


@pytest.fixture(scope="module")
def scratch_db() -> Iterator[str]:
    """
    Create a scratch database for this module's round trips, and drop it afterwards.

    Yields:
        The database's name.
    """
    mssql.recreate_database(DB)
    yield DB
    name = mssql.quote_name(DB)
    with mssql.connect() as conn:
        conn.cursor().execute(
            f"ALTER DATABASE {name} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE {name}"
        )


@pytest.mark.mssql
def test_server_is_the_pinned_build() -> None:
    with mssql.connect() as conn:
        assert mssql.server_version(conn).startswith("16.0.")  # SQL Server 2022
        assert mssql.scalar(conn, "SELECT 7/2") == 3  # integer division truncates (TSQL-03)
        collation = mssql.scalar(conn, "SELECT CAST(SERVERPROPERTY('Collation') AS VARCHAR(64))")
        assert collation == mssql.SERVER_COLLATION


@pytest.mark.mssql
def test_load_and_fetch_round_trip_is_exact(scratch_db: str) -> None:
    ddl = """
    CREATE TABLE dbo.awkward (
        id INT NOT NULL, name NVARCHAR(40) NULL, code VARCHAR(10) NULL, pad CHAR(4) NULL,
        amount DECIMAL(12,2) NULL, d DATE NULL, ts DATETIME2(6) NULL, big BIGINT NULL)
    GO
    """
    rows = {
        "id": [1, 2, 3, 4],
        "name": ["Seán Ó Briain", "O'Brien  ", "", None],
        "code": ["MOT ", "mot", "Mot", None],
        "pad": ["STD", "GOLD", None, "X"],
        "amount": [D("-1234.50"), D("0.10"), D("99999999.99"), None],
        "d": [dt.date(2024, 2, 29), dt.date(1960, 1, 1), dt.date(2025, 12, 31), None],
        "ts": [dt.datetime(2025, 12, 31, 23, 59, 59, 123456), None, None, None],
        "big": [2**53 + 1, -1, 0, None],
    }
    data = pa.table(
        rows,
        schema=pa.schema(
            [
                ("id", pa.int32()),
                ("name", pa.string()),
                ("code", pa.string()),
                ("pad", pa.string()),
                ("amount", pa.decimal128(12, 2)),
                ("d", pa.date32()),
                ("ts", pa.timestamp("us")),
                ("big", pa.int64()),
            ]
        ),
    )
    with mssql.connect(scratch_db) as conn:
        mssql.run_script(conn, ddl)
        assert mssql.load_table(conn, "dbo.awkward", data, batch=3) == 4
        # SQL Server semantics the estate relies on: case- and trailing-space-insensitive '='
        assert mssql.scalar(conn, "SELECT COUNT(*) FROM dbo.awkward WHERE code = 'MOT'") == 3
        cols, back = mssql.fetch_table(conn, "dbo.awkward")
    back = back.sort_by("id")
    assert back.column("name").to_pylist() == rows["name"]  # fadas, trailing spaces, '' vs NULL
    assert back.column("code").to_pylist() == rows["code"]
    assert back.column("pad").to_pylist() == ["STD ", "GOLD", None, "X   "]  # CHAR pads
    assert back.column("amount").to_pylist() == rows["amount"]
    assert back.column("d").to_pylist() == rows["d"]
    assert back.column("ts").to_pylist() == rows["ts"]
    assert back.column("big").to_pylist() == rows["big"]
    specs = {c.name: c.to_spec() for c in cols}
    assert specs["amount"].data_type == "decimal(12,2)"
    assert specs["pad"].legacy_type == "CHAR(4)"
    assert specs["name"].max_length == 40
