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


def test_estate_shows_the_runs_own_jobs_and_open_escalations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    from lansh.contracts import Escalation

    created = datetime(2026, 11, 12, tzinfo=UTC)
    stopped = Escalation(escalation_id="X1-E1", job_id="X1", stage="generate", reason="guardrail",
                         diagnosis="1 of 13 trap tests fail", created_at=created)  # fmt: skip
    # X1's metrics record its stop at code review as an ERROR; its open escalation says why
    for job_id, status, escalations in (("T04", "MATCH", []), ("X1", "ERROR", [stopped])):
        job = tmp_path / "r2" / job_id  # a run id of its own: the page caches a run by its id
        job.mkdir(parents=True)
        report = EvidenceReport(job_id=job_id, generated_at=created, legacy_path=f"{job_id}.sql",
                                legacy_sha256="0" * 64, escalations=escalations)  # fmt: skip
        (job / "evidence.json").write_text(report.model_dump_json())
        (job / "metrics.json").write_text(json.dumps({"status": status, "cost_usd_equivalent": 1}))
    # the estate's plan also places X2, which this run never ran
    plan = {"waves": [{"number": 1, "job_ids": ["T04", "X1", "X2"]}],
            "edges": [{"upstream": "X2", "downstream": "T04", "tables": ["rpt.x"]}]}  # fmt: skip
    (tmp_path / "r2" / "estate.json").write_text(json.dumps(plan))
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert not app.exception
    waves = [m.value for m in app.markdown if m.value.startswith("**Wave")]
    assert len(waves) == 1
    assert "X1 ⚠️ ESCALATED" in waves[0]
    assert "X2" not in waves[0]
    assert app.metric[4].value == "$1.00"  # Claude per job, not the folder's total
