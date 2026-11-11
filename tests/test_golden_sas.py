"""
SAS staging writes date literals, sizes text from legacy types and numbers rows in key order.

These offline tests need no SAS session or SQL Server: where one is needed, a stand-in
plays its part.
"""

from __future__ import annotations

import datetime as dt
import locale
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from lansh.config import LABELS_DIR
from lansh.contracts import ColumnSpec
from lansh.engines import mssql
from lansh.estate import golden_sas
from lansh.estate.golden_sas import char_lengths, prelude, sas_date_literal, with_key_order_row_seq
from lansh.estate.inventory import load_inventory
from lansh.estate.labels import sas_check_ids


def test_sas_date_literal() -> None:
    """
    ISO dates become SAS date literals such as '31DEC2025'd.
    """
    assert sas_date_literal("2025-12-31") == "'31DEC2025'd"
    assert sas_date_literal("2024-02-29") == "'29FEB2024'd"


# time locales whose month abbreviations are not English, such as Dez, déc. and dic
FOREIGN_TIME_LOCALES = ("de_DE.UTF-8", "fr_FR.UTF-8", "es_ES.UTF-8", "de_DE", "fr_FR")


def test_sas_date_literal_ignores_the_locale() -> None:
    """
    Month names stay English under any time locale, as SAS date literals need.
    """
    saved = locale.setlocale(locale.LC_TIME)
    try:
        for name in FOREIGN_TIME_LOCALES:
            try:
                locale.setlocale(locale.LC_TIME, name)
                break
            except locale.Error:
                continue
        else:
            pytest.skip("no non-English time locale is installed")
        literals = [sas_date_literal(f"2025-{month:02d}-01") for month in range(1, 13)]
    finally:
        locale.setlocale(locale.LC_TIME, saved)
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    assert literals == [f"'01{month}2025'd" for month in months]


def test_prelude_passes_the_as_of_date() -> None:
    text = prelude(load_inventory().job("S01"))
    assert "options mprint;" in text
    assert "%let as_of = '31DEC2025'd;" in text


def test_char_lengths_follow_legacy_widths() -> None:
    cols = [
        ColumnSpec(name="name", data_type="string", legacy_type="NVARCHAR(40)"),
        ColumnSpec(name="code", data_type="string", legacy_type="CHAR(6)"),
        ColumnSpec(name="notes", data_type="string", legacy_type="NVARCHAR(MAX)"),
        ColumnSpec(name="n", data_type="int", legacy_type="INT"),
    ]
    # NVARCHAR counts characters and a fada takes two bytes; MAX and numbers get no length
    assert char_lengths(cols) == {"name": 80, "code": 6}


def test_key_order_row_seq_sorts_typed_values_nulls_first() -> None:
    table = pa.table(
        {
            "id": pa.array([-5, -10, None, 7, 7], pa.int32()),
            "amount": pa.array(
                [Decimal(1), Decimal(2), Decimal(3), Decimal("0.5"), None], pa.decimal128(12, 2)
            ),
            "d": pa.array([dt.date(2025, 1, 1)] * 5, pa.date32()),
        }
    )
    seq = with_key_order_row_seq(table).column("_row_seq").to_pylist()
    # NULL id first, then -10 and -5; the two 7s are ordered by amount, NULL first
    assert seq == [3, 2, 1, 5, 4]


def test_dev_inputs_fall_back_to_the_legacy_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    In dev mode, before its job is captured, a T-SQL output is read from the database that
    LEGACY_DATABASE names, and numbered in key order.
    """
    opened: list[str | None] = []

    @contextmanager
    def connect(database: str | None = None) -> Iterator[object]:
        """
        Stand in for mssql.connect, recording the database asked for.
        """
        opened.append(database)
        yield object()

    def fetch_table(conn: object, table: str) -> tuple[list[mssql.SqlColumn], pa.Table]:
        """
        Stand in for mssql.fetch_table: two customers, out of key order.
        """
        column = mssql.SqlColumn(
            name="customer_id",
            sql_type="int",
            max_length=None,
            precision=None,
            scale=None,
            nullable=False,
            is_identity=False,
        )
        return [column], pa.table({"customer_id": pa.array([20, 10], pa.int32())})

    monkeypatch.setattr(golden_sas, "GOLDEN_DIR", tmp_path)  # nothing captured yet
    monkeypatch.setattr(golden_sas, "LEGACY_DATABASE", "ScratchDW")
    monkeypatch.setattr(mssql, "connect", connect)
    monkeypatch.setattr(mssql, "fetch_table", fetch_table)
    found = golden_sas.input_table("dw.dim_customer", load_inventory(), "dev")
    assert found is not None
    data, cols = found
    assert opened == ["ScratchDW"]
    assert data.column("_row_seq").to_pylist() == [2, 1]
    assert [c.name for c in cols] == ["customer_id"]


@dataclass
class FakeSession:
    """
    Just enough of SasSession for run_sas_checks: it records the code it is given to run.
    """

    submitted: list[str] = field(default_factory=list)

    def __enter__(self) -> FakeSession:
        """
        Open the session; nothing starts.
        """
        return self

    def __exit__(self, *exc_info: object) -> None:
        """
        End the session; an exception still propagates.
        """

    def submit(self, code: str, label: str) -> None:
        """
        Record the code; nothing runs.
        """
        self.submitted.append(code)

    def remote_path(self, *parts: str) -> str:
        """
        Build a path under a made-up home directory.
        """
        return "/".join(["/home/u1", *parts])

    def ensure_dir(self, remote_dir: str) -> None:
        """
        Pretend to create the directory.
        """


def _run_checks(monkeypatch: pytest.MonkeyPatch, job_id: str, check_ids: list[str]) -> list[Any]:
    """
    Run a job's SAS checks in a stand-in session whose export holds one row per check id.
    """
    rows = len(check_ids)
    frame = pd.DataFrame({"check_id": check_ids, "affected": [3.0] * rows, "detail": ["x"] * rows})
    monkeypatch.setattr(golden_sas.sase, "SasSession", FakeSession)
    monkeypatch.setattr(
        golden_sas.sase, "export_table", lambda *args, **kwargs: SimpleNamespace(frame=frame)
    )
    return golden_sas.run_sas_checks(job_id)


def test_run_sas_checks_requires_the_declared_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The checks that come back must be the ones the job's check file declares.
    """
    declared = sas_check_ids((LABELS_DIR / "checks" / "S03.sas").read_text(encoding="utf-8"))
    assert len(declared) >= 2
    results = _run_checks(monkeypatch, "S03", declared)
    assert [(r.check_id, r.affected, r.passed) for r in results] == [(c, 3, True) for c in declared]
    with pytest.raises(RuntimeError, match="declared checks"):
        _run_checks(monkeypatch, "S03", declared[:-1])
