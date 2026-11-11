"""
Golden capture orders jobs by their dependencies and writes byte-stable golden files.

These offline tests need neither SQL Server nor SAS.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import networkx as nx
import pyarrow as pa
import pytest

from lansh.contracts import ColumnSpec, EstateInventory, JobSpec
from lansh.estate import golden
from lansh.estate.golden import job_order, write_output
from lansh.estate.inventory import load_inventory


def test_job_order_runs_tsql_in_dependency_order_then_sas() -> None:
    order = job_order(load_inventory())
    assert order[:7] == ["T01", "T02", "T03", "T04", "T05", "T06", "T08"]
    assert order[7:] == ["S01", "S03", "S04"]


def test_capture_runs_upstream_jobs_and_builds_the_graph_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Capturing T08 and T03 also runs the T-SQL jobs they read from (T01 and T02) without
    freezing them, skips every other job, and builds the dependency graph once.
    """
    builds: list[EstateInventory] = []
    build = golden.dependency_graph
    captured: list[str] = []
    ran: list[str] = []

    def counting_build(inventory: EstateInventory) -> nx.DiGraph:
        """
        Build the graph as usual, counting the builds.
        """
        builds.append(inventory)
        return build(inventory)

    @contextmanager
    def connect(database: str | None = None) -> Iterator[object]:
        """
        Stand in for mssql.connect.
        """
        yield object()

    def capture_tsql(job: JobSpec, conn: object) -> str:
        """
        Stand in for capture_tsql, recording the job instead of freezing it.
        """
        captured.append(job.job_id)
        return job.job_id

    def run_tsql_job(job: JobSpec, conn: object) -> None:
        """
        Stand in for run_tsql_job, recording the job instead of running it.
        """
        ran.append(job.job_id)

    monkeypatch.setattr(golden, "dependency_graph", counting_build)
    monkeypatch.setattr(golden.mssql, "connect", connect)
    monkeypatch.setattr(golden, "capture_tsql", capture_tsql)
    monkeypatch.setattr(golden, "run_tsql_job", run_tsql_job)
    assert golden.capture(["T08", "T03"], reload=False) == ["T03", "T08"]
    assert (captured, ran, len(builds)) == (["T03", "T08"], ["T01", "T02"], 1)


@dataclass
class FakeCursor:
    """
    Just enough of a pymssql cursor: it keeps the last statement and returns canned rows.
    """

    rows: list[tuple[Any, ...]]
    statement: str = ""
    params: Any = None

    def execute(self, statement: str, params: Any = None) -> None:
        """
        Keep the statement and its parameters; nothing runs.
        """
        self.statement, self.params = statement, params

    def fetchall(self) -> list[tuple[Any, ...]]:
        """
        Return the canned rows.
        """
        return self.rows


def test_tsql_log_excerpt_summarises_the_rows_the_job_wrote() -> None:
    """
    Each ``etl.etl_log`` row after ``since_id`` becomes a line: status, step, rows, message.
    """
    cursor = FakeCursor([("load dim", "OK", 10, None), (None, "WARN", None, "late rows")])
    conn = SimpleNamespace(cursor=lambda: cursor)
    assert golden.tsql_log_excerpt(conn, 41) == "OK load dim rows=10\nWARN late rows"
    assert "log_id > %d" in cursor.statement
    assert cursor.params == (41,)


def _table(rows: list[tuple]) -> pa.Table:
    """
    Build an Arrow table with columns id, amount, d, s and ts from row tuples.
    """
    schema = pa.schema(
        [
            ("id", pa.int32()),
            ("amount", pa.decimal128(12, 2)),
            ("d", pa.date32()),
            ("s", pa.string()),
            ("ts", pa.timestamp("us")),
        ]
    )
    return pa.Table.from_pylist(
        [dict(zip(schema.names, r, strict=True)) for r in rows], schema=schema
    )


def test_golden_files_do_not_depend_on_engine_row_order(tmp_path: Path) -> None:
    rows = [
        (2, Decimal("-1.50"), dt.date(2024, 2, 29), "Óg ", dt.datetime(2025, 1, 1, 9)),
        (1, None, None, "", dt.datetime(2025, 1, 1, 10)),
        (3, Decimal("0.00"), dt.date(2025, 12, 31), None, dt.datetime(2025, 1, 1, 11)),
    ]
    cols = [
        ColumnSpec(name=n, data_type=t)
        for n, t in [
            ("id", "int"),
            ("amount", "decimal(12,2)"),
            ("d", "date"),
            ("s", "string"),
            ("ts", "timestamp_ntz"),
        ]
    ]
    a = write_output(tmp_path / "a", "rpt.x", _table(rows), cols, volatile=["ts"])
    b = write_output(tmp_path / "b", "rpt.x", _table(rows[::-1]), cols, volatile=["ts"])
    assert (a.raw_sha256, a.parquet_sha256, a.content_sha256) == (
        b.raw_sha256,
        b.parquet_sha256,
        b.content_sha256,
    )
    shifted = [(*r[:4], r[4] + dt.timedelta(hours=1)) for r in rows]
    c = write_output(tmp_path / "c", "rpt.x", _table(shifted), cols, volatile=["ts"])
    assert c.content_sha256 == a.content_sha256  # volatile column left out of the hash
    assert c.raw_sha256 != a.raw_sha256
