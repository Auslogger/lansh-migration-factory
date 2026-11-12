"""
T04 runs through all five stages and gates in replay mode, with no Claude, SQL Server or SAS.

Plan step 2.10's "done when": ``lansh run-job T04`` ends in MATCH, with BUG-03 reproduced and
flagged. Marked ``e2e`` (``make test-e2e``): it starts several Spark workers and takes about a
minute. Pending-gate behaviour for a person is covered without running the job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lansh import pipeline
from lansh.contracts import Gate, GateOutcome, RunStatus
from lansh.estate.inventory import load_inventory
from lansh.governance.gatelog import GateLog
from lansh.pipeline import AwaitingApproval, GateBlocked, approve_pending, open_run, pass_gate


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Point the pipeline's runs and migrated folders at a temporary folder.
    """
    monkeypatch.setattr(pipeline, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(pipeline, "MIGRATED_DIR", tmp_path / "migrated")
    return tmp_path


def test_a_person_must_decide_and_blockers_stop_the_gate(runs: Path) -> None:
    ctx = open_run("person", load_inventory(), mode="replay", reviewer="person:aoife")
    with pytest.raises(AwaitingApproval) as stop:
        pass_gate(ctx, Gate.H1, ["T04"], [], warnings=["low confidence"], blockers=[])
    pending = stop.value.pending
    assert json.loads(pending.read_text())["warnings"] == ["low confidence"]
    decision = approve_pending("person", pending, "person:aoife", "checked by hand", approve=True)
    assert decision.outcome is GateOutcome.APPROVE
    assert not pending.exists()
    # resuming with the same evidence reuses the person's decision
    again = pass_gate(ctx, Gate.H1, ["T04"], [], warnings=["low confidence"], blockers=[])
    assert again.decision_id == decision.decision_id
    with pytest.raises(GateBlocked, match="not unique"):
        pass_gate(ctx, Gate.H2, ["T04"], [], warnings=[], blockers=["key not unique"])


@pytest.mark.e2e
@pytest.mark.spark
def test_t04_end_to_end_offline(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lansh.engines import mssql

    def unreachable(*args: object, **kwargs: object) -> None:
        raise AssertionError("the replay must not need SQL Server")

    monkeypatch.setattr(mssql, "connect", unreachable)
    ctx = open_run("e2e", load_inventory(), mode="replay")
    outcome = pipeline.run_job(ctx, "T04")
    assert outcome.status is RunStatus.MATCH, outcome.message
    assert outcome.stopped_at is None
    log = GateLog(runs / "runs" / "e2e" / "gates.jsonl")
    assert log.passed("T04", Gate.H5)
    assert log.verify() == []
    assert not log.human_signoff("T04")  # an agent ran it: never a person's sign-off
    evidence = json.loads((runs / "runs" / "e2e" / "T04" / "evidence.json").read_text())
    fan_out = next(d for d in evidence["defects"] if "fan-out" in d["title"].lower())
    assert fan_out["impact"]["rows_affected"] == 289  # BUG-03 flagged with its impact
    assert {d["defect_id"] for d in evidence["defect_decisions"]} >= {fan_out["defect_id"]}
    assert all(r["status"] == "MATCH" for r in evidence["recon"])
    assert evidence["recon"][0]["candidate_sha256"] == evidence["recon"][0]["golden_sha256"]
    assert sum(t["status"] == "pass" for t in evidence["tests"]) == len(evidence["tests"]) > 0
    module = (runs / "migrated" / "jobs" / "t04.py").read_text()
    assert "LANSH-DEFECT" in module  # BUG-03 reproduced on purpose, and marked
    assert outcome.metrics is not None
    assert outcome.metrics.llm_live_calls == 0


def test_a_person_decides_each_defect_and_flow(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import typer

    from lansh.contracts import ColumnRef, ColumnTag, SuspectedDefect, TaggedFlow

    inventory = load_inventory()
    job = inventory.job("T04")
    defect = SuspectedDefect(
        defect_id="T04-D1",
        job_id="T04",
        title="fan-out",
        description="d",
        source="llm",
        confidence=0.9,
    )
    source = ColumnRef(table="stg.customers", column="email")
    output = ColumnRef(table="dw.dim_customer", column="email")
    flow = TaggedFlow(
        flow_id="F-1-pii",
        tag=ColumnTag.PII,
        source=source,
        output=output,
        path=[source, output],
        job_ids=["T01"],
    )
    ctx = open_run("decide", inventory, mode="replay", reviewer="person:aoife")
    # waiting, not asked: one blocker per undecided item
    assert pipeline._decide_defects(ctx, job, [defect], Gate.H2) == [
        "suspected defect T04-D1 (fan-out) has no decision"
    ]
    assert pipeline._decide_flows(ctx, [flow])[0].endswith("has no decision")
    # asked in the terminal: the person's answers are recorded as theirs
    ctx.interactive = True
    answers = iter(["f", "fix the join after cut-over", "accepted: business need"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(typer, "echo", lambda *a, **k: None)
    assert pipeline._decide_defects(ctx, job, [defect], Gate.H2) == []
    assert pipeline._decide_flows(ctx, [flow]) == []
    (decided,) = ctx.gatelog.defect_decisions("T04")
    assert (decided.decision.value, decided.decided_by) == ("fix_after_cutover", "person:aoife")
    (flow_decision,) = ctx.gatelog.flow_decisions()
    assert flow_decision.decision == "reproduce_accepted"


def test_only_a_person_accepts_a_literal_and_only_for_that_code(runs: Path) -> None:
    from lansh.governance.gatelog import GateRefused
    from lansh.pipeline import accept_literal, accepted_literals

    module = runs / "runs" / "lit" / "T04" / "jobs" / "t04.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n")
    with pytest.raises(GateRefused, match="only a person"):
        accept_literal("lit", "T04", "777", 3, "agent:lansh-dev", "looks fine")
    with pytest.raises(GateRefused, match="needs a reason"):
        accept_literal("lit", "T04", "777", 3, "person:aoife", " ")
    accept_literal("lit", "T04", "777", 3, "person:aoife", "the product code for travel")
    from lansh.estate.fingerprint import file_sha256

    folder = module.parent.parent
    assert accepted_literals(folder, file_sha256(module)) == {
        ("777", 3): ("person:aoife", "the product code for travel")
    }
    module.write_text("x = 2\n")  # a patched module needs its literals accepted again
    assert accepted_literals(folder, file_sha256(module)) == {}
