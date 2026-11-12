"""
The Control Tower renders every page of a run without errors, headlessly (Streamlit AppTest).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lansh import config
from lansh.contracts import EvidenceReport

APP = Path(__file__).resolve().parents[1] / "src" / "lansh" / "ui" / "app.py"


def test_every_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    job = tmp_path / "r1" / "T04"
    job.mkdir(parents=True)
    report = EvidenceReport(
        job_id="T04",
        generated_at=datetime(2026, 11, 12, tzinfo=UTC),
        legacy_path="estate/tsql/T04_usp_build_claims_summary.sql",
        legacy_sha256="0" * 64,
    )
    (job / "evidence.json").write_text(report.model_dump_json())
    # no evidence.md, as in a clone (the .gitignore keeps Markdown out): it is rendered
    (job / "metrics.json").write_text(json.dumps({"status": "MATCH", "llm_calls": 6}))
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert not app.exception
    for page in ("Estate", "Job", "Scorecard", "Audit"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
