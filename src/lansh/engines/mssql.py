"""
SQL Server adapter for the legacy T-SQL estate.

It opens connections (the password comes from ``.env``), runs deployment scripts split on
``GO``, calls stored procedures, reads whole tables into Arrow with exact types, and loads
Arrow tables fast through multi-row ``INSERT`` statements with literal values, so nothing
passes through a float.
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pymssql

from lansh.config import env, require_env
from lansh.contracts import ColumnSpec

log = logging.getLogger(__name__)

# the legacy server's collation, and the default for new databases: case-insensitive and
# accent-sensitive
SERVER_COLLATION = "SQL_Latin1_General_CP1_CI_AS"
INSERT_BATCH_ROWS = 1000  # SQL Server's limit for one VALUES list
_GO_LINE = re.compile(r"^[ \t]*GO[ \t]*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)
# used with fullmatch: a pattern ending in $ would also accept a final line break
_IDENT = re.compile(r"[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)?")


@dataclass(frozen=True)
class MssqlSettings:
    """
    Where the legacy SQL Server listens, and the login to use.
    """

    host: str
    port: int
    user: str
    password: str


def settings() -> MssqlSettings:
    """
    Read the connection settings from the environment, after loading ``.env``.

    ``LANSH_MSSQL_HOST``, ``LANSH_MSSQL_PORT`` and ``LANSH_MSSQL_USER`` default to
    ``localhost``, 1433 and ``sa``. ``MSSQL_SA_PASSWORD`` has no default.

    Returns:
        The settings that :func:`connect` uses.

    Raises:
        RuntimeError: If ``MSSQL_SA_PASSWORD`` is not set.
    """
    return MssqlSettings(
        host=env("LANSH_MSSQL_HOST", "localhost") or "localhost",
        port=int(env("LANSH_MSSQL_PORT", "1433") or 1433),
        user=env("LANSH_MSSQL_USER", "sa") or "sa",
        password=require_env("MSSQL_SA_PASSWORD"),
    )


@contextmanager
def connect(database: str | None = None, autocommit: bool = True) -> Iterator[Any]:
    """
    Open a pymssql connection, and close it when the ``with`` block ends.

    Autocommit is on by default, as in SSMS and sqlcmd.

    Args:
        database: Database to connect to; ``master`` by default.
        autocommit: Whether every statement commits on its own.

    Yields:
        The open connection.

    Raises:
        RuntimeError: If ``MSSQL_SA_PASSWORD`` is not set.
        pymssql.Error: If the server cannot be reached or refuses the login.
    """
    cfg = settings()
    conn = pymssql.connect(
        server=cfg.host,
        port=str(cfg.port),
        user=cfg.user,
        password=cfg.password,
        database=database or "master",
        login_timeout=15,
        charset="UTF-8",
        autocommit=autocommit,
    )
    try:
        yield conn
    finally:
        conn.close()


def _check_ident(name: str) -> str:
    """
    Return ``name`` if it is safe to paste into T-SQL, else raise ValueError.

    Safe means letters, digits and underscores, not starting with a digit, with at most one
    dot for a schema, as in ``rpt.claims_summary``.
    """
    if not _IDENT.fullmatch(name):
        raise ValueError(f"not a safe identifier: {name!r}")
    return name


def quote_name(name: str) -> str:
    """
    Bracket-quote one name, doubling any ``]`` in it as ``QUOTENAME`` does.

    Every name put in brackets goes through here, so a column such as ``odd]name`` becomes
    ``[odd]]name]`` and can't end the quoting early.

    Args:
        name: A column, table, schema or database name, used as it is.

    Returns:
        The name in square brackets.
    """
    return "[" + name.replace("]", "]]") + "]"


def quote_table(name: str) -> str:
    """
    Bracket-quote a table name: ``rpt.claims_summary`` becomes ``[rpt].[claims_summary]``.

    Args:
        name: Table or procedure name, optionally schema-qualified.

    Returns:
        The name with each part in square brackets.

    Raises:
        ValueError: If ``name`` is not a safe identifier.
    """
    return ".".join(quote_name(part) for part in _check_ident(name).split("."))


def split_batches(script: str) -> list[str]:
    """
    Split a deployment script into batches on lines that hold only ``GO``.

    ``GO`` is a command of sqlcmd and SSMS, not T-SQL, so the server must never see it. A
    ``GO`` line may be in any case, with blanks around it and a trailing ``--`` comment.
    ``GO`` with a repeat count (``GO 5``) is not recognised. Empty batches are dropped.

    Args:
        script: The whole script.

    Returns:
        The batches in order, without their surrounding line breaks.
    """
    return [b.strip("\n") for b in _GO_LINE.split(script) if b.strip()]


def run_script(conn: Any, script: str) -> int:
    """
    Run every batch of a deployment script, in order.

    Every result set of a batch is read, so an error in any of its statements surfaces here.

    Args:
        conn: Open connection.
        script: The script, with batches separated by ``GO`` lines.

    Returns:
        The number of batches run.

    Raises:
        RuntimeError: If a batch fails. The message gives the batch's number and first line,
            and the pymssql error is chained to it.
    """
    batches = split_batches(script)
    cur = conn.cursor()
    for i, batch in enumerate(batches, 1):
        try:
            cur.execute(batch)
            while cur.nextset():
                pass
        except pymssql.Error as exc:
            first = batch.strip().splitlines()[0][:120] if batch.strip() else ""
            raise RuntimeError(f"batch {i}/{len(batches)} failed ({first!r}): {exc}") from exc
    return len(batches)


def exec_proc(conn: Any, proc: str, params: dict[str, Any] | None = None) -> float:
    """
    EXEC a stored procedure with named parameters, and time it.

    Parameter values are written as exact T-SQL literals (see :func:`sql_literal`). Every
    result set is read, so the time covers the whole procedure.

    Args:
        conn: Open connection.
        proc: Procedure name, optionally schema-qualified.
        params: Values by parameter name, without the ``@``.

    Returns:
        The elapsed seconds.

    Raises:
        ValueError: If a name is not a safe identifier, or a value cannot be stored.
        TypeError: If a value has no T-SQL literal.
        pymssql.Error: If the procedure fails.
    """
    args = ", ".join(f"@{_check_ident(k)} = {sql_literal(v)}" for k, v in (params or {}).items())
    statement = f"EXEC {quote_table(proc)} {args}".rstrip()
    start = time.perf_counter()
    cur = conn.cursor()
    cur.execute(statement)
    while cur.nextset():
        pass
    return time.perf_counter() - start


def scalar(conn: Any, query: str) -> Any:
    """
    Run a query and return the first column of its first row.

    Args:
        conn: Open connection.
        query: T-SQL that returns a result set.

    Returns:
        That value, or None if there are no rows.
    """
    cur = conn.cursor()
    cur.execute(query)
    row = cur.fetchone()
    return row[0] if row else None


def server_version(conn: Any) -> str:
    """
    Read the server's product version, such as ``16.0.x`` for SQL Server 2022.

    Args:
        conn: Open connection.

    Returns:
        ``SERVERPROPERTY('ProductVersion')`` as text.
    """
    return str(scalar(conn, "SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30))"))


def recreate_database(name: str, collation: str = SERVER_COLLATION) -> None:
    """
    Drop and create a database, set up for deterministic, repeatable runs.

    The new database uses simple recovery, runs each query on one thread (MAXDOP 1) and has
    no identity cache, so every run of the legacy jobs gives the same rows and surrogate keys.

    Args:
        name: The database. An existing one of that name is dropped first: other
            connections to it are cut off and their open transactions rolled back.
        collation: Collation of the new database.

    Raises:
        ValueError: If ``name`` is not a safe identifier.
    """
    quoted = quote_name(_check_ident(name))
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"IF DB_ID(N'{name}') IS NOT NULL BEGIN "
            f"ALTER DATABASE {quoted} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE {quoted}; END"
        )
        cur.execute(f"CREATE DATABASE {quoted} COLLATE {collation}")
        cur.execute(f"ALTER DATABASE {quoted} SET RECOVERY SIMPLE")
    with connect(name) as conn:
        # one thread per query, so IDENTITY values and ties come out the same on every run;
        # no identity cache, so a server restart between batches can't skip surrogate keys
        conn.cursor().execute("ALTER DATABASE SCOPED CONFIGURATION SET MAXDOP = 1")
        conn.cursor().execute("ALTER DATABASE SCOPED CONFIGURATION SET IDENTITY_CACHE = OFF")
    log.info("created database %s (%s, MAXDOP 1)", name, collation)


### Literals


def sql_literal(value: Any) -> str:
    """
    Render a Python value as an exact T-SQL literal.

    Decimals are written in fixed notation and floats as their shortest round-trip ``repr``,
    so no digit is lost. Datetimes always carry six decimals, and text becomes ``N'...'``
    with its quotes doubled.

    Args:
        value: None, or a bool, int, Decimal, float, date, naive datetime or str.

    Returns:
        The literal, such as ``NULL``, ``-1234.50`` or ``N'O''Brien'``.

    Raises:
        ValueError: For a NaN or infinite number, or a timezone-aware datetime.
        TypeError: For any other type.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):  # before int, as bool is a subclass of int
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise ValueError(f"cannot store {value} in SQL Server")
        return format(value, "f")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"cannot store {value} in SQL Server")
        return repr(value)
    if isinstance(value, dt.datetime):  # before date, as datetime is a subclass of date
        if value.tzinfo is not None:
            raise ValueError("timezone-aware datetimes are not supported; use naive UTC")
        return f"'{value.isoformat(timespec='microseconds')}'"
    if isinstance(value, dt.date):
        return f"'{value.isoformat()}'"
    if isinstance(value, str):
        return "N'" + value.replace("'", "''") + "'"
    raise TypeError(f"no T-SQL literal for {type(value).__name__}")


### Types


@dataclass(frozen=True)
class SqlColumn:
    """
    One column of a SQL Server table, as the catalog describes it.

    Attributes:
        name: Column name.
        sql_type: Base type name in lower case, such as ``varchar``, ``decimal`` or
            ``datetime2``.
        max_length: Length in characters for text types; None for ``MAX``, ``text``,
            ``ntext`` and other types.
        precision: Total digits of a decimal or numeric; None for other types.
        scale: Decimal places of a decimal or numeric, or the fractional-second digits of a
            ``datetime2``; None for other types.
        nullable: Whether the column allows NULL.
        is_identity: Whether it is an IDENTITY column.
    """

    name: str
    sql_type: str
    max_length: int | None
    precision: int | None
    scale: int | None
    nullable: bool
    is_identity: bool

    @property
    def legacy_type(self) -> str:
        """
        The type as DDL spells it, such as ``VARCHAR(20)``, ``DECIMAL(12,2)`` or ``DATETIME2(3)``.
        """
        t = self.sql_type.upper()
        if self.sql_type in ("varchar", "nvarchar", "char", "nchar"):
            return f"{t}({'MAX' if self.max_length is None else self.max_length})"
        if self.sql_type in ("decimal", "numeric"):
            return f"{t}({self.precision},{self.scale})"
        if self.sql_type == "datetime2":
            return f"{t}({self.scale})"
        return t

    @property
    def logical_type(self) -> str:
        """
        The contract's logical (Spark-side) type for this column; see :func:`logical_type`.
        """
        return logical_type(self.sql_type, self.precision, self.scale)

    def arrow_type(self) -> pa.DataType:
        """
        The Arrow type that holds this column's values exactly; see :func:`arrow_type`.
        """
        return arrow_type(self.sql_type, self.precision, self.scale)

    def to_spec(self) -> ColumnSpec:
        """
        Describe this column as a contract column.

        Returns:
            The :class:`~lansh.contracts.ColumnSpec`, with ``max_length`` set for text only.
        """
        return ColumnSpec(
            name=self.name,
            data_type=self.logical_type,
            legacy_type=self.legacy_type,
            nullable=self.nullable,
            max_length=self.max_length if self.sql_type in _TEXT else None,
        )


_TEXT = {"varchar", "nvarchar", "char", "nchar", "text", "ntext"}
# the text types whose sys.columns.max_length is a limit. For text and ntext (and image) it
# is 16, the size of a pointer to the data
_SIZED_TEXT = {"varchar", "nvarchar", "char", "nchar"}
_LOGICAL = {
    "bit": "boolean",
    "tinyint": "smallint",  # SQL Server tinyint is 0..255; Spark tinyint is signed
    "smallint": "smallint",
    "int": "int",
    "bigint": "bigint",
    "float": "double",
    "real": "float",
    "date": "date",
    "datetime": "timestamp_ntz",
    "datetime2": "timestamp_ntz",
    "smalldatetime": "timestamp_ntz",
}


def logical_type(sql_type: str, precision: int | None, scale: int | None) -> str:
    """
    Map a SQL Server type to the contract's logical (Spark-side) type.

    ``money`` and ``smallmoney`` become the decimals that hold them exactly.

    Args:
        sql_type: Base type name in lower case, as ``sys.types`` gives it.
        precision: Total digits of a decimal or numeric; ignored for other types.
        scale: Decimal places of a decimal or numeric; ignored for other types.

    Returns:
        The logical type, such as ``string``, ``decimal(12,2)`` or ``timestamp_ntz``.

    Raises:
        ValueError: If the type is not supported.
    """
    if sql_type in _TEXT:
        return "string"
    if sql_type in ("decimal", "numeric", "money", "smallmoney"):
        if sql_type == "money":
            return "decimal(19,4)"
        if sql_type == "smallmoney":
            return "decimal(10,4)"
        return f"decimal({precision},{scale})"
    try:
        return _LOGICAL[sql_type]
    except KeyError:
        raise ValueError(f"unsupported SQL Server type {sql_type!r}") from None


def arrow_type(sql_type: str, precision: int | None, scale: int | None) -> pa.DataType:
    """
    Map a SQL Server type to the Arrow type that holds its values exactly.

    Decimals become ``decimal128``, and datetimes naive microsecond timestamps.

    Args:
        sql_type: Base type name in lower case, as ``sys.types`` gives it.
        precision: Total digits of a decimal or numeric; ignored for other types.
        scale: Decimal places of a decimal or numeric; ignored for other types.

    Returns:
        The Arrow type.

    Raises:
        ValueError: If the type is not supported.
    """
    logical = logical_type(sql_type, precision, scale)
    if logical.startswith("decimal("):
        p, s = (int(x) for x in logical[8:-1].split(","))
        return pa.decimal128(p, s)
    return {
        "boolean": pa.bool_(),
        "smallint": pa.int16(),
        "int": pa.int32(),
        "bigint": pa.int64(),
        "double": pa.float64(),
        "float": pa.float32(),
        "date": pa.date32(),
        "timestamp_ntz": pa.timestamp("us"),
        "string": pa.string(),
    }[logical]


def table_columns(conn: Any, table: str) -> list[SqlColumn]:
    """
    Read a table's column metadata from the catalog, in column order.

    ``sys.columns`` gives lengths in bytes, so the lengths of N types are halved to
    characters. ``MAX`` (-1), ``text`` and ``ntext`` have no limit and get None: for the last
    two, ``sys.columns`` gives the 16-byte size of a pointer.

    Args:
        conn: Open connection.
        table: Table name, optionally schema-qualified, such as ``rpt.claims_summary``.

    Returns:
        One :class:`SqlColumn` per column.

    Raises:
        LookupError: If the table does not exist.
    """
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT c.name, t.name AS sql_type, c.max_length, c.precision, c.scale,
               c.is_nullable, c.is_identity
        FROM sys.columns AS c
        JOIN sys.types AS t ON t.user_type_id = c.user_type_id
        WHERE c.object_id = OBJECT_ID(%s)
        ORDER BY c.column_id
        """,
        (table,),
    )
    cols = []
    for r in cur.fetchall():
        sql_type = r["sql_type"]
        length = None
        if sql_type in _SIZED_TEXT and r["max_length"] != -1:
            length = r["max_length"] // (2 if sql_type.startswith("n") else 1)
        cols.append(
            SqlColumn(
                name=r["name"],
                sql_type=sql_type,
                max_length=length,
                precision=r["precision"] if sql_type in ("decimal", "numeric") else None,
                scale=r["scale"] if sql_type in ("decimal", "numeric", "datetime2") else None,
                nullable=bool(r["is_nullable"]),
                is_identity=bool(r["is_identity"]),
            )
        )
    if not cols:
        raise LookupError(f"table {table} not found")
    return cols


def fetch_table(conn: Any, table: str) -> tuple[list[SqlColumn], pa.Table]:
    """
    Read a whole table with exact Arrow types.

    DECIMAL stays decimal and DATETIME2 keeps its microseconds, so the result can be hashed
    and compared without float rounding. The query has no ORDER BY, so rows come back in no
    guaranteed order.

    Args:
        conn: Open pymssql connection.
        table: Schema-qualified table name, such as ``rpt.claims_summary``.

    Returns:
        The column definitions, and the rows as a pyarrow Table in that column order.

    Raises:
        LookupError: If the table does not exist.
    """
    cols = table_columns(conn, table)
    select = ", ".join(quote_name(c.name) for c in cols)
    cur = conn.cursor()
    cur.execute(f"SELECT {select} FROM {quote_table(table)}")
    rows = cur.fetchall()
    arrays = []
    for i, col in enumerate(cols):
        values = [r[i] for r in rows]
        arrays.append(pa.array(values, type=col.arrow_type()))
    schema = pa.schema([pa.field(c.name, c.arrow_type(), nullable=c.nullable) for c in cols])
    return cols, pa.Table.from_arrays(arrays, schema=schema)


### Loading


def _rows(table: pa.Table) -> Iterator[tuple[Any, ...]]:
    """
    Yield an Arrow table's rows as tuples of Python values.
    """
    columns = [table.column(i).to_pylist() for i in range(table.num_columns)]
    yield from zip(*columns, strict=True)


def insert_statements(
    table_name: str, columns: Sequence[str], rows: Iterator[tuple[Any, ...]], batch: int
) -> Iterator[str]:
    """
    Yield multi-row INSERT statements of at most ``batch`` rows each.

    Values are exact literals (see :func:`sql_literal`), so nothing passes through a float.

    Args:
        table_name: The target table, optionally schema-qualified.
        columns: Column names, in the order of each row's values.
        rows: The rows, as tuples of Python values.
        batch: Rows per statement; SQL Server takes at most 1000 in one VALUES list.

    Yields:
        One ``INSERT ... VALUES`` statement per batch.
    """
    names = ", ".join(quote_name(c) for c in columns)
    head = f"INSERT INTO {quote_table(table_name)} ({names}) VALUES\n"
    chunk: list[str] = []
    for row in rows:
        chunk.append("(" + ", ".join(sql_literal(v) for v in row) + ")")
        if len(chunk) == batch:
            yield head + ",\n".join(chunk)
            chunk = []
    if chunk:
        yield head + ",\n".join(chunk)


def load_table(conn: Any, table_name: str, data: pa.Table, batch: int = INSERT_BATCH_ROWS) -> int:
    """
    Append an Arrow table to an existing SQL Server table, in one transaction.

    Args:
        conn: Open connection in autocommit mode, as :func:`connect` gives by default.
            Otherwise this transaction nests inside the caller's, which must still commit.
        table_name: The target table, optionally schema-qualified.
        data: The rows to append; every column name must be a column of the target.
        batch: Rows per INSERT statement.

    Returns:
        The number of rows appended.

    Raises:
        pymssql.Error: If an INSERT fails. The transaction is rolled back first, as it is
            when a value has no exact literal, so no row is appended.
    """
    cur = conn.cursor()
    cur.execute("SET NOCOUNT ON")  # no "rows affected" message after every INSERT
    cur.execute("BEGIN TRANSACTION")
    try:
        for statement in insert_statements(table_name, data.column_names, _rows(data), batch):
            cur.execute(statement)
        cur.execute("COMMIT TRANSACTION")
    except Exception:
        cur.execute("IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION")
        raise
    return data.num_rows
