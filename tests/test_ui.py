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


def test_demo_run_filter_preserves_local_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lansh.ui import app

    names = ["showcase", "showcase/held-out", "showcase/learning", "video", "dev-estate"]
    for name in names:
        job = tmp_path / name / "T04"
        job.mkdir(parents=True)
        (job / "evidence.json").write_text("{}")
    monkeypatch.setattr(app, "RUNS_DIR", tmp_path)
    monkeypatch.setenv("LANSH_DEMO_RUNS", "1")
    assert app.runs() == names[:4]
    assert (tmp_path / "dev-estate" / "T04" / "evidence.json").exists()
    monkeypatch.delenv("LANSH_DEMO_RUNS")
    assert "dev-estate" in app.runs()


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
    for page in ("Estate", "Demo", "Job", "Scorecard", "Audit"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page


def test_guided_demo_shows_verified_examples_and_navigates(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LANSH_DEMO_RUNS", "1")
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "Demo"
    for step in range(6):
        assert not app.exception, step
        if step in (0, 3, 4):
            for toggle in list(app.toggle):
                toggle.set_value(True)
            app.run()
            assert not app.exception, step
        if step == 0:
            metrics = {m.label: m.value for m in app.metric}
            assert metrics["Claims affected"] == "289"
            assert metrics["Payments in the ledger"] != metrics["Legacy report says"]
        if step == 2:
            assert {m.label: m.value for m in app.metric}["Rows matched"] == "823 / 823"
        if step == 4:
            assert {m.label: m.value for m in app.metric}["Before repair · differing rows"] == "719"
            assert {m.label: m.value for m in app.metric}["After repair · differing rows"] == "0"
        next(b for b in app.button if b.key == "demo_next").click().run()
    assert app.session_state["demo_step"] == 0


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
