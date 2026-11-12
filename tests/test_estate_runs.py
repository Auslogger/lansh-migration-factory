"""
The estate-level pieces: waves, flows of tagged columns, schedules, comparison runs, scoring.

``test_waves_match_the_plan`` is plan step 3.6's "done when": Discover finds the waves of
plan §7.2 on its own, from what each job reads and writes.
"""

from __future__ import annotations

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


def test_scorecard_traces_every_number(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    card = scorecard.build("r")
    values = {m.name: m.value for m in card.metrics}
    assert values["Jobs reconciled record for record (MATCH, zero unexplained differences)"] == "1"
    assert values["Outputs whose content hash equals the legacy output's"] == "1"
    assert values["API-equivalent cost per job (not billed: subscription)"] == "1.10"
    assert all(m.sources for m in card.metrics)
    rows = card.business_case["rows"]
    assert [r["case"] for r in rows] == ["low", "middle", "high"]
    assert card.business_case["gate_load"]["every gate for every job"] == 8000


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
