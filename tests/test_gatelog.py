"""
The gate log refuses illegal transitions, records every decision and keeps its hash chain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lansh.contracts import DefectDecisionKind, Gate, GateOutcome
from lansh.governance.gatelog import GateLog, GateRefused, evidence

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
AGENT = "agent:lansh-dev"
PERSON = "person:aoife"
APPROVE = GateOutcome.APPROVE


def approve(
    log: GateLog,
    gate: Gate,
    jobs: list[str],
    *,
    at: datetime = T0,
    seconds: float = 60,
    wave: int | None = None,
    reviewer: str = PERSON,
    warnings: tuple[str, ...] = (),
    reason: str | None = None,
) -> None:
    """
    Show the evidence for a gate and approve it ``seconds`` later.
    """
    shown = log.show(gate, jobs, warnings=warnings, wave=wave, now=at)
    log.decide(shown, APPROVE, reviewer, reason, now=at + timedelta(seconds=seconds))


def test_gates_pass_in_order_only(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl")
    with pytest.raises(GateRefused, match="H2 needs H1 first"):
        approve(log, Gate.H2, ["T04"])
    for gate in (Gate.H1, Gate.H2, Gate.H3, Gate.H4):
        approve(log, gate, ["T04"])
    assert log.stage_reached("T04") is Gate.H4
    with pytest.raises(GateRefused, match="per wave"):
        approve(log, Gate.H5, ["T04"])
    with pytest.raises(GateRefused, match="not passed by"):
        approve(log, Gate.H5, ["T04", "T05"], wave=1)
    approve(log, Gate.H5, ["T04"], wave=1)
    assert log.passed("T04", Gate.H5)
    assert log.human_signoff("T04")


def test_redeciding_a_gate_retires_later_approvals(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl")
    for gate in (Gate.H1, Gate.H2, Gate.H3, Gate.H4):
        approve(log, gate, ["T04"])
    approve(log, Gate.H3, ["T04"])  # the code was healed and approved again
    assert log.passed("T04", Gate.H3)
    assert not log.passed("T04", Gate.H4)  # the old evidence approval no longer counts
    shown = log.show(Gate.H2, ["T04"], now=T0)
    log.decide(shown, GateOutcome.REJECT, PERSON, "contract keys wrong", now=T0)
    assert log.stage_reached("T04") is Gate.H1


def test_blockers_refuse_approval_but_not_rejection(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl")
    shown = log.show(Gate.H1, ["T04"], blockers=["lineage names unknown column x"], now=T0)
    with pytest.raises(GateRefused, match="blocked"):
        log.decide(shown, APPROVE, PERSON, "looks fine", now=T0 + timedelta(minutes=1))
    rejected = log.decide(shown, GateOutcome.REJECT, PERSON, "fix the lineage", now=T0)
    assert rejected.outcome is GateOutcome.REJECT


def test_warnings_need_a_reason_and_decisions_follow_the_evidence(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl")
    with pytest.raises(GateRefused, match="written reason"):
        approve(log, Gate.H1, ["T04"], warnings=("low-confidence lineage",))
    approve(log, Gate.H1, ["T04"], warnings=("low-confidence lineage",), reason="checked by hand")
    shown = log.show(Gate.H2, ["T04"], now=T0)
    with pytest.raises(GateRefused, match="before the evidence was shown"):
        log.decide(shown, APPROVE, PERSON, now=T0 - timedelta(seconds=1))
    with pytest.raises(GateRefused, match="person:<name> or agent:<name>"):
        log.decide(shown, APPROVE, "aoife", now=T0)


def test_fast_approvals_are_flagged_and_agents_are_not_people(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl", fast_seconds=20)
    approve(log, Gate.H1, ["T04"], seconds=3, reviewer=AGENT)
    approve(log, Gate.H1, ["T05"], seconds=45)
    flags = {d.job_ids[0]: d.flagged_fast for d in log.decisions()}
    assert flags == {"T04": True, "T05": False}
    for gate in (Gate.H2, Gate.H3, Gate.H4):
        approve(log, gate, ["T04"], reviewer=AGENT)
    approve(log, Gate.H5, ["T04"], wave=1, reviewer=AGENT)
    assert log.passed("T04", Gate.H5)
    assert not log.human_signoff("T04")  # an agent's approvals are never a person's


def test_hash_chain_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "gates.jsonl"
    log = GateLog(path)
    approve(log, Gate.H1, ["T04"])
    log.decide_defect("T04-D1", "T04", DefectDecisionKind.REPRODUCE, "reproduce now", PERSON)
    log.decide_flow("S04-F1", "reproduce_flagged", "age loading needs review", PERSON)
    approve(log, Gate.H2, ["T04"])
    assert log.verify() == []
    assert [d.defect_id for d in log.defect_decisions("T04")] == ["T04-D1"]
    assert [f.flow_id for f in log.flow_decisions()] == ["S04-F1"]
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace(PERSON, "person:mallory")
    path.write_text("\n".join(lines) + "\n")
    assert log.verify() == ["entry 2: the chain is broken (an entry before it changed)"]


def test_spot_checks_are_seeded_and_near_their_rate(tmp_path: Path) -> None:
    log = GateLog(tmp_path / "gates.jsonl", spot_rate=0.25)
    for i in range(200):
        approve(log, Gate.H1, [f"T{i:02d}"[:4] if i < 100 else f"S{i - 100:02d}"])
    picked = sum(d.spot_check for d in log.decisions())
    assert 25 <= picked <= 75
    assert all(log._spot(d.decision_id) == d.spot_check for d in log.decisions())


def test_evidence_is_pinned_by_its_hash() -> None:
    ref = evidence("contract", "migrated/contracts/rpt.claims_summary.json", "{}")
    assert ref.sha256 == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
