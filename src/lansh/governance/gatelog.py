"""
The gate log: an append-only, hash-chained record of every decision at H1–H5 (plan §8.9).

Each line of the log file is one entry: a :class:`~lansh.contracts.GateDecision`, or a decision
on one suspected defect (:class:`~lansh.contracts.DefectDecision`) or one flow of a tagged
column (:class:`~lansh.contracts.FlowDecision`). Every entry carries the SHA-256 of the line
before it, so editing or removing a line breaks the chain, which :meth:`GateLog.verify` checks
(``lansh audit verify``).

**Transitions.** The gates close the stages in order. A job may be decided at H*n* only once it
has passed H*n-1*, and passing means the latest decision at that gate approved and came after
the job passed the gate before it. So re-deciding an earlier gate (a contract changed, code
was healed) silently retires every later approval, which must be given again. H5 is decided
per wave, for jobs that have all passed H4.

**Automation-bias controls.**

- A decision records when the evidence was shown and refuses one made before it.
- Approving with warnings, or any outcome but a plain approval, needs a written reason.
- An approval with *blockers* (what plan §6.3 enforces before approval, such as a status other
  than MATCH at H4) is refused outright; a rejection is always allowed.
- An approval faster than ``fast_seconds`` is flagged.
- A seeded share (``spot_rate``) of approvals is picked for random re-review.

**Who decides.** ``reviewer`` names a person (``person:<name>``) or an agent
(``agent:<name>``). Development runs record the agent's approvals as the agent's; only a person
can stand behind the product's sign-offs, and :meth:`GateLog.human_signoff` tells them apart.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from lansh.contracts import (
    GATE_STAGE,
    DefectDecision,
    DefectDecisionKind,
    EvidenceRef,
    FlowDecision,
    Gate,
    GateDecision,
    GateOutcome,
)

GATE_ORDER: tuple[Gate, ...] = (Gate.H1, Gate.H2, Gate.H3, Gate.H4, Gate.H5)
"""The gates in the order their stages run."""

# below this many seconds between showing the evidence and deciding, an approval is flagged
DEFAULT_FAST_SECONDS = 20.0
# the share of approvals picked for random re-review
DEFAULT_SPOT_RATE = 0.1

EntryKind = Literal["gate", "defect", "flow"]


class GateRefused(Exception):
    """
    A decision the gate log won't record: out of order, with blockers, or otherwise invalid.
    """


def _canonical(data: dict) -> str:
    """
    Serialise an entry the same way every time: sorted keys, compact, UTF-8 text kept.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(line: str) -> str:
    """
    Hash one log line, as the next entry's ``prev_hash``.
    """
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entry:
    """
    One line of the log, read back: its kind, its record and the line's own hash.
    """

    kind: EntryKind
    record: GateDecision | DefectDecision | FlowDecision
    prev_hash: str | None
    line_hash: str


@dataclass(frozen=True)
class Shown:
    """
    Evidence put in front of a reviewer, before a decision on it.

    Attributes:
        gate: The gate the evidence is for.
        job_ids: The jobs it covers.
        evidence: The evidence, each piece pinned by its hash.
        warnings: What the reviewer must read; approving needs a written reason.
        blockers: What must be fixed first; approving is refused while any remains.
        wave: The wave, for H5 (and wave-level approvals at other gates).
        shown_at: When it was shown.
    """

    gate: Gate
    job_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    wave: int | None
    shown_at: datetime


class GateLog:
    """
    The append-only gate log of one run, kept in a JSON Lines file.

    Args:
        path: The log file; created on the first decision.
        fast_seconds: Approvals quicker than this are flagged.
        spot_rate: The share of approvals picked for random re-review.
    """

    def __init__(
        self,
        path: Path,
        *,
        fast_seconds: float = DEFAULT_FAST_SECONDS,
        spot_rate: float = DEFAULT_SPOT_RATE,
    ) -> None:
        """
        Open (or prepare) a gate log; nothing is read until it is needed.
        """
        self.path = Path(path)
        self.fast_seconds = fast_seconds
        self.spot_rate = spot_rate

    ### Reading

    def entries(self) -> list[Entry]:
        """
        Read every entry, in the order they were appended.

        Returns:
            The entries; empty when the log doesn't exist yet.

        Raises:
            ValueError: If a line isn't a valid entry.
        """
        if not self.path.exists():
            return []
        out = []
        for number, line in enumerate(self.path.read_text("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            data = json.loads(line)
            kind = data.pop("entry")
            prev = data.get("prev_hash")
            if kind == "gate":
                record: GateDecision | DefectDecision | FlowDecision = GateDecision.model_validate(
                    data
                )
            elif kind == "defect":
                data.pop("prev_hash", None)
                record = DefectDecision.model_validate(data)
            elif kind == "flow":
                data.pop("prev_hash", None)
                record = FlowDecision.model_validate(data)
            else:
                raise ValueError(f"line {number}: unknown entry kind {kind!r}")
            out.append(Entry(kind, record, prev, _hash(line)))
        return out

    def decisions(self) -> list[GateDecision]:
        """
        Every gate decision, in order.
        """
        return [e.record for e in self.entries() if isinstance(e.record, GateDecision)]

    def defect_decisions(self, job_id: str | None = None) -> list[DefectDecision]:
        """
        Every decision on a suspected defect, optionally for one job, in order.
        """
        return [
            e.record
            for e in self.entries()
            if isinstance(e.record, DefectDecision) and job_id in (None, e.record.job_id)
        ]

    def flow_decisions(self) -> list[FlowDecision]:
        """
        Every decision on a flow of a tagged column, in order.
        """
        return [e.record for e in self.entries() if isinstance(e.record, FlowDecision)]

    def passed(self, job_id: str, gate: Gate) -> bool:
        """
        Tell whether a job has passed a gate, every earlier gate included, in order.

        Args:
            job_id: The job.
            gate: The gate.

        Returns:
            True when the latest decision at each gate up to this one approved, each after the
            gate before it was passed.
        """
        return self._passed_at(job_id, gate) is not None

    def _passed_at(self, job_id: str, gate: Gate) -> int | None:
        """
        Give the position in the log of the approval through which a job passed a gate.
        """
        decisions = self.decisions()
        earliest = -1
        for g in GATE_ORDER[: GATE_ORDER.index(gate) + 1]:
            latest = None
            for i, d in enumerate(decisions):
                if d.gate is g and job_id in d.job_ids:
                    latest = i
            if latest is None or latest <= earliest:
                return None
            if decisions[latest].outcome is GateOutcome.REJECT:
                return None
            earliest = latest
        return earliest

    def stage_reached(self, job_id: str) -> Gate | None:
        """
        Give the last gate a job has passed, in order.

        Returns:
            The gate, or None when it hasn't passed H1.
        """
        reached = None
        for gate in GATE_ORDER:
            if not self.passed(job_id, gate):
                break
            reached = gate
        return reached

    def human_signoff(self, job_id: str) -> bool:
        """
        Tell whether a person, not an agent, made every approval through which a job passed H5.
        """
        if not self.passed(job_id, Gate.H5):
            return False
        decisions = self.decisions()
        for gate in GATE_ORDER:
            latest = max(
                i for i, d in enumerate(decisions) if d.gate is gate and job_id in d.job_ids
            )
            if not decisions[latest].reviewer.startswith("person:"):
                return False
        return True

    ### Writing

    def show(
        self,
        gate: Gate,
        job_ids: Iterable[str],
        evidence: Iterable[EvidenceRef] = (),
        *,
        warnings: Iterable[str] = (),
        blockers: Iterable[str] = (),
        wave: int | None = None,
        now: datetime | None = None,
    ) -> Shown:
        """
        Put evidence in front of a reviewer, starting the clock on their decision.

        Nothing is written: the record of what was shown is part of the decision.

        Args:
            gate: The gate.
            job_ids: The jobs the evidence covers.
            evidence: The evidence, pinned by hashes.
            warnings: What needs a written reason to approve.
            blockers: What makes approval impossible until fixed.
            wave: The wave, for H5.
            now: The time to record; the current UTC time when not given.

        Returns:
            What was shown, to pass to :meth:`decide`.
        """
        return Shown(
            gate=gate,
            job_ids=tuple(job_ids),
            evidence=tuple(evidence),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            wave=wave,
            shown_at=now or datetime.now(UTC),
        )

    def decide(
        self,
        shown: Shown,
        outcome: GateOutcome,
        reviewer: str,
        reason: str | None = None,
        *,
        now: datetime | None = None,
        re_review_of: str | None = None,
    ) -> GateDecision:
        """
        Record a reviewer's decision on the evidence shown, if the rules allow it.

        Args:
            shown: What was shown, from :meth:`show`.
            outcome: Approve, approve with changes, or reject.
            reviewer: ``person:<name>`` or ``agent:<name>``.
            reason: The written reason; required with warnings or any non-approval.
            now: The decision time; the current UTC time when not given.
            re_review_of: The decision a spot-check re-examines.

        Returns:
            The recorded decision.

        Raises:
            GateRefused: If the reviewer isn't named as a person or an agent, an approval has
                blockers, a job hasn't passed the gate before, H5 lacks a wave, or the decision
                is otherwise invalid (no reason with warnings, decided before shown).
        """
        if not reviewer.startswith(("person:", "agent:")):
            raise GateRefused(f"reviewer {reviewer!r} must be person:<name> or agent:<name>")
        approving = outcome is not GateOutcome.REJECT
        if approving and shown.blockers:
            raise GateRefused(
                f"{shown.gate.value} can't be approved while blocked: " + "; ".join(shown.blockers)
            )
        position = GATE_ORDER.index(shown.gate)
        if position and re_review_of is None:
            before = GATE_ORDER[position - 1]
            behind = [j for j in shown.job_ids if not self.passed(j, before)]
            if behind:
                raise GateRefused(
                    f"{shown.gate.value} needs {before.value} first; not passed by {behind}"
                )
        decided_at = now or datetime.now(UTC)
        seconds = (decided_at - shown.shown_at).total_seconds()
        decision_id = uuid.uuid4().hex[:12]
        try:
            decision = GateDecision(
                decision_id=decision_id,
                gate=shown.gate,
                stage=GATE_STAGE[shown.gate],
                job_ids=list(shown.job_ids),
                wave=shown.wave,
                outcome=outcome,
                reviewer=reviewer,
                reason=reason,
                evidence=list(shown.evidence),
                warnings=list(shown.warnings),
                shown_at=shown.shown_at,
                decided_at=decided_at,
                flagged_fast=approving and seconds < self.fast_seconds,
                spot_check=approving and self._spot(decision_id),
                re_review_of=re_review_of,
            )
        except ValidationError as exc:
            problems = "; ".join(e["msg"] for e in exc.errors(include_url=False))
            raise GateRefused(f"{shown.gate.value}: {problems}") from exc
        self._append("gate", decision)
        return self.decisions()[-1]

    def decide_defect(
        self,
        defect_id: str,
        job_id: str,
        decision: DefectDecisionKind,
        reason: str,
        reviewer: str,
        *,
        gate: Gate = Gate.H2,
        now: datetime | None = None,
    ) -> DefectDecision:
        """
        Record a decision on one suspected legacy defect (plan §8.4).

        Args:
            defect_id: The suspected defect.
            job_id: Its job.
            decision: Reproduce, fix after cut-over, or not a defect.
            reason: Why.
            reviewer: ``person:<name>`` or ``agent:<name>``.
            gate: H2, or H4 for a defect found while reconciling.
            now: The decision time.

        Returns:
            The recorded decision.
        """
        if not reviewer.startswith(("person:", "agent:")):
            raise GateRefused(f"reviewer {reviewer!r} must be person:<name> or agent:<name>")
        record = DefectDecision(
            defect_id=defect_id,
            job_id=job_id,
            decision=decision,
            reason=reason,
            decided_by=reviewer,
            decided_at=now or datetime.now(UTC),
            gate=gate,
        )
        self._append("defect", record)
        return record

    def decide_flow(
        self,
        flow_id: str,
        decision: Literal["reproduce_accepted", "reproduce_flagged"],
        reason: str,
        reviewer: str,
        *,
        now: datetime | None = None,
    ) -> FlowDecision:
        """
        Record the H2 bias decision on one flow of a protected or personal column (plan §10).

        Args:
            flow_id: The flow.
            decision: Reproduce as-is, or reproduce and raise for a bias review after cut-over.
            reason: Why.
            reviewer: ``person:<name>`` or ``agent:<name>``.
            now: The decision time.

        Returns:
            The recorded decision.
        """
        if not reviewer.startswith(("person:", "agent:")):
            raise GateRefused(f"reviewer {reviewer!r} must be person:<name> or agent:<name>")
        record = FlowDecision(
            flow_id=flow_id,
            decision=decision,
            reason=reason,
            decided_by=reviewer,
            decided_at=now or datetime.now(UTC),
        )
        self._append("flow", record)
        return record

    def verify(self) -> list[str]:
        """
        Check the hash chain: every entry must carry the hash of the line before it.

        Returns:
            One message per broken link; empty when the log is intact.
        """
        problems = []
        previous: str | None = None
        for number, entry in enumerate(self.entries(), 1):
            if entry.prev_hash != previous:
                problems.append(f"entry {number}: the chain is broken (an entry before it changed)")
            previous = entry.line_hash
        return problems

    def _spot(self, decision_id: str) -> bool:
        """
        Pick an approval for random re-review, reproducibly from its id.
        """
        draw = int(hashlib.sha256(decision_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return draw < self.spot_rate

    def _append(
        self, kind: EntryKind, record: GateDecision | DefectDecision | FlowDecision
    ) -> None:
        """
        Append one entry, chained to the last line's hash.
        """
        entries = self.entries()
        prev = entries[-1].line_hash if entries else None
        # a gate decision's own prev_hash field carries the chain (the contract's Tier 2 field)
        data = {"entry": kind, **record.model_dump(mode="json"), "prev_hash": prev}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(data) + "\n")


def evidence(kind: str, ref: str, content: str | bytes) -> EvidenceRef:
    """
    Pin one piece of evidence by the hash of what was shown.

    Args:
        kind: The evidence kind, one of ``EvidenceRef.kind``'s values.
        ref: Its path or id.
        content: What was shown, as text or bytes.

    Returns:
        The evidence reference.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    return EvidenceRef(kind=kind, ref=ref, sha256=hashlib.sha256(data).hexdigest())
