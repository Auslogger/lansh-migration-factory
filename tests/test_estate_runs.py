"""
The estate-level pieces: waves, flows of tagged columns, schedules, comparison runs, scoring.

``test_waves_match_the_plan`` is plan step 3.6's "done when": Discover finds the waves of
plan §7.2 on its own, from what each job reads and writes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from lansh import scorecard
from lansh.benchmark import NotDraftable, sqlglot_module
from lansh.config import REPO_ROOT
from lansh.contracts import ColumnTag, LineageEdge, LineageKind
from lansh.discover.estate import estate_plan, tagged_flows, wave_of, waves
from lansh.estate.inventory import load_inventory
from lansh.estate.labels import JobLabel
from lansh.estate.scoring import score_job
from lansh.generate.guardrails import check_strings, check_tree
from lansh.operate.run import sla_check, wave_schedules, write_schedule


def test_waves_match_the_plan() -> None:
    inventory = load_inventory()
    # the development estate's waves; unsealed held-out jobs (step 3.11) only read sources
    development = inventory.model_copy(
        update={"jobs": [j for j in inventory.jobs if not j.holdout]}
    )
    assert all(not set(j.inputs) - set(inventory.sources) for j in inventory.jobs if j.holdout)
    inventory = development
    assert waves(inventory) == [
        ["S01", "T01", "T04", "T05", "T06"],
        ["T02", "T08"],
        ["T03"],
        ["S03"],
        ["S04"],
    ]
    assert wave_of(inventory, "S04") == 5
    plan = estate_plan(inventory)
    edges = {(e.upstream, e.downstream): e.tables for e in plan.edges}
    assert edges[("T01", "S04")] == ["dw.dim_customer"]
    assert len(plan.waves) == 5


def edge(job: str, out_table: str, out_col: str, in_table: str, in_col: str) -> LineageEdge:
    """
    One derives edge.
    """
    return LineageEdge(
        job_id=job,
        output_table=out_table,
        output_column=out_col,
        input_table=in_table,
        input_column=in_col,
        kind=LineageKind.DERIVES,
        source="llm",
    )


def test_tagged_flows_cross_jobs() -> None:
    lineage = [
        edge("T01", "dw.dim_customer", "date_of_birth", "stg.customers", "date_of_birth"),
        edge("S04", "rpt.risk_scores", "age", "dw.dim_customer", "date_of_birth"),
        edge("S04", "rpt.risk_scores", "age_load", "dw.dim_customer", "date_of_birth"),
    ]
    sources = {("stg.customers", "date_of_birth"): [ColumnTag.PII, ColumnTag.PROTECTED]}
    flows = tagged_flows(sources, lineage)
    into_s04 = [f for f in flows if f.output.table == "rpt.risk_scores"]
    assert {(f.output.column, f.tag.value) for f in into_s04} == {
        ("age", "pii"),
        ("age", "protected"),
        ("age_load", "pii"),
        ("age_load", "protected"),
    }
    assert all(f.job_ids == ["T01", "S04"] for f in into_s04)
    assert tagged_flows(sources, lineage) == flows  # ids are stable from run to run


def test_wave_schedules_map_to_databricks_workflows(tmp_path: Path) -> None:
    inventory = load_inventory()
    schedules = wave_schedules(waves(inventory), inventory)
    assert [s.trigger for s in schedules[:2]] == ["cron: 0 2 * * *", "after wave 1"]
    path = write_schedule(schedules[1], inventory, tmp_path)
    data = yaml.safe_load(path.read_text())
    assert data["databricks_workflow"]["name"] == "lansh-wave-2"
    assert {t["task_key"] for t in data["databricks_workflow"]["tasks"]} == {"T02", "T08"}


def test_sla_check_flags_breaches() -> None:
    from lansh.contracts import ContractColumn, DataContract, SlaSpec

    contract = DataContract(
        job_id="T04",
        table="gold.x",
        legacy_table="rpt.x",
        layer="gold",
        grain="test",
        columns=[ContractColumn(name="a", data_type="int")],
        sla=SlaSpec(max_runtime_seconds=10, expected_rows=100, row_tolerance_pct=10),
    )
    assert sla_check("T04", "rpt.x", 5, 105, contract).breaches == []
    assert sla_check("T04", "rpt.x", 11, 80, contract).breaches == ["runtime", "rows"]


def test_sqlglot_alone_drafts_simple_jobs_and_refuses_the_rest() -> None:
    inventory = load_inventory()
    t04 = inventory.job("T04")
    source = sqlglot_module(t04, (REPO_ROOT / t04.path).read_text())
    import ast

    tree = ast.parse(source)
    assert check_tree(tree) == []  # plain Spark SQL over temporary views, no I/O
    found, _ = check_strings(tree)
    # parameters are bound into the SQL text at run time, which an agent's module may not do
    assert all("plain string literal" in f for f in found)
    assert "stg_claims" in source
    from lansh.lakehouse import input_schemas

    typed = sqlglot_module(t04, (REPO_ROOT / t04.path).read_text(), input_schemas(inventory, t04))
    assert "claim_number + '/'" in source
    assert "claim_number + '/'" not in typed  # once typed, T-SQL's + on text becomes CONCAT
    for job_id, why in (("T02", "MERGE"), ("T06", "UPDATE"), ("S01", "SAS")):
        job = inventory.job(job_id)
        with pytest.raises(NotDraftable, match=why):
            sqlglot_module(job, (REPO_ROOT / job.path).read_text())


def test_the_oneshot_prompt_has_the_interface_but_not_the_knowledge() -> None:
    from lansh.generate.translator import _SAS_RULES, _TSQL_RULES, oneshot_request

    inventory = load_inventory()
    for job_id in ("T02", "S03"):
        job = inventory.job(job_id)
        system = oneshot_request(job, "x", "0" * 64, {"stg.claims": []}, []).system_prompt
        # the same module interface as the factory's translator, so a failure is the model's
        assert 'by its legacy name in lower case (e.g. "stg.claims")' in system
        assert "_row_seq" in system
        # and none of LANSH's knowledge: no language rules, no trap findings
        assert _TSQL_RULES not in system
        assert _SAS_RULES not in system
        assert "Handle every trap finding" not in system
    stateful = oneshot_request(inventory.job("T02"), "x", "0" * 64, {}, []).system_prompt
    assert "keeps history between batches" in stateful  # its own previous output is an input


def test_scoring_against_an_answer_key() -> None:
    label = JobLabel.model_validate(
        {
            "job_id": "T04",
            "legacy_path": "x.sql",
            "summary": "test",
            "traps": [
                {"trap_id": "TSQL-01", "kind": "semantic", "armed": True, "lines": [10, 10],
                 "where": "w", "effect": "e", "check": "T04_a"},
                {"trap_id": "TSQL-05", "kind": "semantic", "armed": False, "lines": [20, 20],
                 "where": "w", "effect": "e"},
            ],
            "bugs": [
                {"bug_id": "BUG-03", "lines": [30, 35], "where": "w", "does": "d", "intended": "i",
                 "check": "T04_b"},
            ],
        }
    )  # fmt: skip
    findings = [
        {"trap_id": "TSQL-01", "line_start": 10, "line_end": 10},
        {"trap_id": "TSQL-04", "line_start": 50, "line_end": 50},
    ]
    defects = [
        {"defect_id": "T04-D1", "evidence_lines": [31, 40]},
        {"defect_id": "T04-D2", "evidence_lines": [20]},
        {"defect_id": "T04-D3", "evidence_lines": [90]},
    ]
    score = score_job(label, findings, defects)
    assert (score.detected_traps, score.labelled_traps) == (2, 2)  # TSQL-05 through a defect
    assert (score.true_findings, score.findings) == (1, 2)
    assert score.bug_matches == {"BUG-03": "T04-D1"}
    assert (score.defects_confirmed, score.defects) == (2, 3)
    assert "defect T04-D3 lines 90-90" in score.unconfirmed


def _one_job_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Write a run ``r`` holding T04 at MATCH, and point the scorecard at it.
    """
    run = tmp_path / "r"
    (run / "T04").mkdir(parents=True)
    report = {"table": "rpt.x", "status": "MATCH", "counts": {"legacy": 10, "candidate": 10},
              "candidate_sha256": "a" * 64, "golden_sha256": "a" * 64, "run_id": "r"}  # fmt: skip
    (run / "T04" / "evidence.json").write_text(
        json.dumps({"recon": [report], "tests": [{"status": "pass"}], "defects": [{}], "heal": []})
    )
    (run / "T04" / "metrics.json").write_text(
        json.dumps(
            {"status": "MATCH", "llm_calls": 6, "cost_usd_equivalent": 1.1, "duration_seconds": 120}
        )
    )
    monkeypatch.setattr(scorecard, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(scorecard, "BASELINE_TIMESHEET", tmp_path / "timesheet.csv")


def test_scorecard_traces_every_number(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _one_job_run(tmp_path, monkeypatch)
    card = scorecard.build("r")
    values = {m.name: m.value for m in card.metrics}
    assert values["Jobs reconciled record for record (MATCH, zero unexplained differences)"] == "1"
    assert values["Outputs whose content hash equals the legacy output's"] == "1"
    assert values["API-equivalent cost per job (not billed: subscription)"] == "1.10"
    assert all(m.sources for m in card.metrics)
    assert [r["case"] for r in card.business_case["by_hand"]] == ["low", "middle", "high"]
    assert card.business_case["gate_load"]["every gate for every job"] == 8000
    assert "bias" not in card.business_case  # the run has no S04


def test_sensitivity_gives_people_and_cost_per_assumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the default assumptions, with no manual baseline recorded (the deck quotes the baseline's)
    _one_job_run(tmp_path, monkeypatch)
    bc = scorecard.build("r").business_case
    middle = next(r for r in bc["by_hand"] if r["case"] == "middle")
    assert (middle["people for 4 months"], middle["cost (EUR)"]) == ("21", "1097355")
    people = {
        (r["escalated to a person"], r["review minutes per job"]): r["people for 4 months"]
        for r in bc["rows"]
    }
    assert people == {
        ("15%", "30"): "4.5", ("15%", "60"): "5.8",
        ("30%", "30"): "7.6", ("30%", "60"): "8.9",
        ("50%", "30"): "11.8", ("50%", "60"): "13.1",
    }  # fmt: skip
    assert any("review minutes as assumptions" in note for note in bc["notes"])


def test_manual_baseline_drives_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Sum recorded phases per job and use the measured average in the projection.
    """
    _one_job_run(tmp_path, monkeypatch)
    monkeypatch.setattr(scorecard, "GOLDEN_DIR", tmp_path / "golden")
    golden = tmp_path / "golden" / "T04"
    golden.mkdir(parents=True)
    (golden / "manifest.json").write_text(json.dumps({"capture_seconds": 0}))
    timesheet = tmp_path / "timesheet.csv"
    lines = ["job,phase,minutes"]
    for job, phase, minutes in (
        ("T05", "understand", 26),
        ("T05", "translate_and_check", 122),
        ("S01", "understand", 34),
        ("S01", "translate_and_check", 135),
    ):
        lines.append(f"{job},{phase},{minutes}")
    timesheet.write_text("\n".join(lines) + "\n")
    card = scorecard.build("r")
    bc = card.business_case
    assert bc["manual_baseline"] == {
        "minutes_per_job": 158.5,
        "sources": [
            {"path": str(timesheet), "sha256": hashlib.sha256(timesheet.read_bytes()).hexdigest()}
        ],
    }
    assert bc["by_hand"][0]["case"] == "manual baseline"
    assert bc["by_hand"][0]["person-hours"] == "4227"
    assert bc["rows"][0]["person-hours"] == "1434"
    assert bc["measured"]["manual_baseline_minutes"] == 158.5
    json_path, md_path = scorecard.write(card)
    assert (
        json.loads(json_path.read_text())["business_case"]["manual_baseline"]
        == bc["manual_baseline"]
    )
    assert "manual baseline" in md_path.read_text()


def test_published_scorecard_uses_the_committed_baseline() -> None:
    """
    Pin the showcase scorecard to the committed timesheet, and to the figures slide 7 quotes.
    """
    timesheet = REPO_ROOT / "baseline" / "timesheet.csv"
    card = json.loads((REPO_ROOT / "runs" / "showcase" / "scorecard.json").read_text())
    bc = card["business_case"]
    assert bc["manual_baseline"]["sources"] == [
        {
            "path": "baseline/timesheet.csv",
            "sha256": hashlib.sha256(timesheet.read_bytes()).hexdigest(),
        }
    ]
    assert bc["manual_baseline"]["minutes_per_job"] == 158.5  # T05 148, S01 169
    by_hand = bc["by_hand"][0]
    assert (by_hand["case"], by_hand["people for 4 months"]) == ("manual baseline", "6.9")
    people = {
        (r["escalated to a person"], r["review minutes per job"]): r["people for 4 months"]
        for r in bc["rows"]
    }
    assert people == {
        ("15%", "30"): "2.4", ("15%", "60"): "3.7",
        ("30%", "30"): "3.4", ("30%", "60"): "4.7",
        ("50%", "30"): "4.8", ("50%", "60"): "6.1",
    }  # fmt: skip


def test_human_review_is_pinned_to_the_log_and_included_in_the_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lansh.contracts import Gate, GateOutcome
    from lansh.governance.gatelog import GateLog

    _one_job_run(tmp_path, monkeypatch)
    run = tmp_path / "r"
    log = GateLog(run / "gates.jsonl")
    decision = log.decide(log.show(Gate.H1, ["T04"]), GateOutcome.APPROVE, "agent:dev")
    original = log.path.read_bytes()
    review = {
        "status": "reviewed_and_accepted",
        "confirmed_by": "person:team-lansh",
        "confirmation_recorded_on": "2026-11-16",
        "gate_log_sha256": hashlib.sha256(original).hexdigest(),
        "gate_decision_ids": [decision.decision_id],
    }
    path = run / "human_review.json"
    path.write_text(json.dumps(review))
    card = scorecard.build("r")
    metric = next(
        m for m in card.metrics if m.name == "Gate decisions reviewed and accepted by people"
    )
    assert metric.value == "1"
    assert len(metric.sources) == 2
    assert log.path.read_bytes() == original
    assert log.verify() == []
    assert any("reviewed and accepted by humans" in n for n in card.business_case["notes"])
    # A confirmation cannot silently carry over to decisions added after the human review.
    log.decide(log.show(Gate.H2, ["T04"]), GateOutcome.APPROVE, "agent:dev")
    with pytest.raises(ValueError, match="invalid human review confirmation"):
        scorecard.build("r")
    # Re-pinning the log alone cannot claim review of a decision absent from the confirmation.
    review["gate_log_sha256"] = hashlib.sha256(log.path.read_bytes()).hexdigest()
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="invalid human review confirmation"):
        scorecard.human_review(run)


def test_bias_table_reproduces_from_the_golden_outputs() -> None:
    # plan step 5.5's "done when": S04's tiers by age band and county, from committed outputs
    bias = scorecard.bias_table()
    assert bias is not None
    under_25 = {"age band": "under 25", "risk scores": 168, "rated HIGH (%)": "14.3"}
    assert bias["by_age"][0] == under_25
    assert [b["rated HIGH (%)"] for b in bias["by_age"][1:]] == ["6.6", "4.4", "5.1", "5.6"]
    assert bias["ages_25_59"] == {"risk scores": 1404, "rated HIGH (%)": "5.3"}
    county = bias["by_county"]
    assert county["counties"] == 20
    assert (county["lowest"]["county"], county["lowest"]["rated HIGH (%)"]) == ("Clare", "1.3")
    assert (county["highest"]["county"], county["highest"]["rated HIGH (%)"]) == ("Laois", "9.7")


def test_showcase_publishes_evidence_without_bulky_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from lansh import cli, config

    for run in ("r1", "h1"):
        job = tmp_path / run / ("T04" if run == "r1" else "X1")
        (job / "staging").mkdir(parents=True)
        (job / "staging" / "input.parquet").write_text("bulky")
        (job / "evidence.json").write_text(json.dumps({"path": f"runs/{run}/T04/evidence.md"}))
        (tmp_path / run / "gates.jsonl").write_text("")
    (tmp_path / "freeze.json").write_text("{}")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    result = CliRunner().invoke(cli.app, ["showcase", "--from", "r1", "--holdout", "h1"])
    assert result.exit_code == 0, result.output
    show = tmp_path / "showcase"
    assert not (show / "T04" / "staging").exists()  # the bulky data stays behind
    assert "runs/showcase/T04" in (show / "T04" / "evidence.json").read_text()
    assert "runs/showcase/held-out/" in (show / "held-out" / "X1" / "evidence.json").read_text()
    assert (show / "freeze.json").exists()  # proof the held-out run used the frozen factory
