"""
The factory's pipeline: one job through Discover, Design, Generate, Reconcile and Operate.

Plan §6.3 and step 2.10. Each stage writes its evidence into the run's folder
(``runs/<run>/<job>/``), and each gate shows that evidence, pinned by hashes, before a decision
is recorded in the run's gate log (``runs/<run>/gates.jsonl``):

=====  ====================  ====================================================================
Gate   After                 Refused (blockers) while
=====  ====================  ====================================================================
H1     Discover              there is no verified lineage
H2     Design                a key isn't unique, a tolerance has no reason, a suspected defect or a
                             tagged flow has no decision
H3     Generate              a guardrail is broken, a literal is unexplained, or a test fails
H4     Reconcile (and heal)  the status isn't MATCH, or a defect found while healing is undecided
H5     Operate               the job's Delta output doesn't reconcile, or its SLA is broken
=====  ====================  ====================================================================

**Who approves.** ``reviewer`` names a person (``person:<name>``) or an agent
(``agent:<name>``). An agent approves every gate that has no blockers, with a reason that lists
the warnings it read, and its decisions are recorded as the agent's: development runs never
stand for a person's sign-off. A person is asked in the terminal (``interactive``), or the run
stops at the gate with its evidence saved as pending, for ``lansh approve`` or the Control
Tower; running the job again in the same run resumes, reusing every decision whose evidence
hasn't changed. A decision made on different evidence (the code was healed, a contract
changed) is not reused.

Accepted work is copied into ``migrated/``: the module (``jobs/``), its tests (``tests/``) and
its contracts (``contracts/``).
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lansh.config import REPO_ROOT, RUNS_DIR
from lansh.contracts import (
    DataContract,
    DefectDecisionKind,
    Escalation,
    EstateInventory,
    EvidenceRef,
    EvidenceReport,
    Gate,
    GateDecision,
    GateOutcome,
    JobSpec,
    Language,
    ReconMode,
    ReconStatus,
    RunMetrics,
    RunStatus,
    Stage,
    SuspectedDefect,
    TaggedFlow,
    TestCase,
)
from lansh.estate.fingerprint import file_sha256
from lansh.generate.template import DEFECT_MARKER
from lansh.governance.gatelog import GateLog, GateRefused, Shown
from lansh.lakehouse import write_json

log = logging.getLogger(__name__)

MIGRATED_DIR = REPO_ROOT / "migrated"
AGENT_REVIEWER = "agent:lansh-dev"


class AwaitingApproval(Exception):
    """
    A gate needs a person's decision; the run stops here and resumes once it is recorded.
    """

    def __init__(self, job_id: str, gate: Gate, pending: Path) -> None:
        """
        Name the job, the gate and the file holding the evidence shown.
        """
        super().__init__(f"{job_id} awaits a decision at {gate.value} ({pending})")
        self.job_id, self.gate, self.pending = job_id, gate, pending


class GateBlocked(Exception):
    """
    A gate has blockers: it can't be approved until they are fixed.
    """

    def __init__(self, job_id: str, gate: Gate, blockers: list[str]) -> None:
        """
        Name the job, the gate and the blockers.
        """
        super().__init__(f"{job_id} is blocked at {gate.value}: " + "; ".join(blockers))
        self.job_id, self.gate, self.blockers = job_id, gate, blockers


@dataclass
class Context:
    """
    What every stage of one run shares.

    Attributes:
        run_id: The run, which names its folder in ``runs/``.
        inventory: The estate inventory.
        gateway: The Claude gateway (its usage goes to the run's ``llm_usage.jsonl``).
        reviewer: Who decides at the gates: ``agent:<name>`` or ``person:<name>``.
        interactive: Ask a person in the terminal instead of stopping at each gate.
        contracts: Approved contracts by legacy table, shared across jobs (for tags).
        lakehouse: The lakehouse root.
    """

    run_id: str
    inventory: EstateInventory
    gateway: Any
    reviewer: str = AGENT_REVIEWER
    interactive: bool = False
    contracts: dict[str, DataContract] = field(default_factory=dict)
    lakehouse: Path | None = None
    _spark: Any = None

    @property
    def run_dir(self) -> Path:
        """
        The run's folder.
        """
        return RUNS_DIR / self.run_id

    @property
    def gatelog(self) -> GateLog:
        """
        The run's gate log.
        """
        return GateLog(self.run_dir / "gates.jsonl")

    @property
    def spark(self) -> Any:
        """
        The shared Spark session, started on first use.
        """
        if self._spark is None:
            from lansh.spark import get_spark

            self._spark = get_spark()
        return self._spark


def open_run(
    run_id: str,
    inventory: EstateInventory,
    *,
    mode: str | None = None,
    reviewer: str = AGENT_REVIEWER,
    interactive: bool = False,
    max_live_calls: int | None = None,
) -> Context:
    """
    Open a run, new or resumed, with its gateway logging usage into the run's folder.

    Args:
        run_id: The run.
        inventory: The estate inventory.
        mode: The gateway's mode (``replay``, ``auto``, ``live``); ``LANSH_LLM_MODE`` if None.
        reviewer: Who decides at the gates.
        interactive: Ask a person in the terminal.
        max_live_calls: The live-call cap (D5's 150 by default).

    Returns:
        The run's context.
    """
    from lansh.llm.gateway import ClaudeGateway

    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    gateway = ClaudeGateway(
        mode=mode,
        run_id=run_id,
        usage_file=run_dir / "llm_usage.jsonl",
        max_live_calls=max_live_calls,
    )
    return Context(run_id, inventory, gateway, reviewer=reviewer, interactive=interactive)


### Gates


# fields that change on every run without changing what the evidence says
_VOLATILE_KEYS = frozenset(
    {
        "started_at", "duration_seconds", "seconds", "job_seconds", "runtime_seconds",
        "generated_at", "created_at", "recorded_at", "decided_at", "shown_at", "duration_ms",
        "lineage_event",
    }
)  # fmt: skip


def _stable(value: Any) -> Any:
    """
    Drop the run-specific fields from JSON evidence, recursively.
    """
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _pin(path: Path, kind: str) -> EvidenceRef:
    """
    Pin one evidence file by a hash of what it says.

    JSON evidence is hashed without its timings and timestamps, so running a stage again on the
    same inputs gives the same hash and a decision on it is reused; any change to what the
    evidence says gives a new hash, and the decision must be made again.
    """
    from lansh.estate.fingerprint import text_sha256
    from lansh.estate.golden import rel

    if path.suffix == ".json":
        data = _stable(json.loads(path.read_text(encoding="utf-8")))
        digest = text_sha256(json.dumps(data, sort_keys=True, separators=(",", ":")))
    else:
        digest = file_sha256(path)
    return EvidenceRef(kind=kind, ref=rel(path), sha256=digest)  # type: ignore[arg-type]


def _same_evidence(a: list[EvidenceRef], b: list[EvidenceRef]) -> bool:
    """
    Tell whether two evidence lists pin the same files with the same hashes.
    """
    return {(e.ref, e.sha256) for e in a} == {(e.ref, e.sha256) for e in b}


def pass_gate(
    ctx: Context,
    gate: Gate,
    job_ids: list[str],
    evidence: list[EvidenceRef],
    *,
    warnings: list[str],
    blockers: list[str],
    wave: int | None = None,
    summary: str = "",
) -> GateDecision:
    """
    Show a gate's evidence and get a decision: reused, by the agent, by a person, or pending.

    Args:
        ctx: The run.
        gate: The gate.
        job_ids: The jobs it decides.
        evidence: The evidence, pinned by hashes.
        warnings: What the reviewer must read; approving needs a written reason.
        blockers: What stops approval.
        wave: The wave, for H5.
        summary: A few lines of the evidence, for a person in the terminal.

    Returns:
        The approval.

    Raises:
        GateBlocked: If there are blockers.
        AwaitingApproval: If a person must decide and isn't being asked in the terminal.
        GateRefused: If a person rejects.
    """
    log_ = ctx.gatelog
    for decision in reversed(log_.decisions()):
        if decision.gate is gate and set(job_ids) <= set(decision.job_ids):
            reusable = (
                decision.outcome is not GateOutcome.REJECT
                and _same_evidence(decision.evidence, evidence)
                and all(log_.passed(j, gate) for j in job_ids)
            )
            if reusable:
                return decision
            break
    if blockers:
        raise GateBlocked(",".join(job_ids), gate, blockers)
    shown = log_.show(gate, job_ids, evidence, warnings=warnings, blockers=blockers, wave=wave)
    if ctx.reviewer.startswith("agent:"):
        reason = "development run, approved by the agent (not a person's sign-off)"
        if warnings:
            reason += "; warnings read: " + "; ".join(w[:160] for w in warnings[:12])
        return log_.decide(shown, GateOutcome.APPROVE, ctx.reviewer, reason)
    if ctx.interactive:
        return _ask_in_terminal(ctx, shown, summary)
    pending = write_json(
        ctx.run_dir / "pending" / f"{'-'.join(job_ids)}-{gate.value}.json",
        {
            "gate": gate.value,
            "job_ids": job_ids,
            "wave": wave,
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "warnings": warnings,
            "shown_at": shown.shown_at.isoformat(),
            "summary": summary,
        },
    )
    raise AwaitingApproval(",".join(job_ids), gate, pending)


def _ask_in_terminal(ctx: Context, shown: Shown, summary: str) -> GateDecision:
    """
    Put the evidence in front of a person in the terminal and record their decision.
    """
    import typer

    typer.echo(f"\n=== {shown.gate.value} for {', '.join(shown.job_ids)} ===\n{summary}")
    for e in shown.evidence:
        typer.echo(f"  evidence: {e.ref} ({(e.sha256 or '')[:12]})")
    for w in shown.warnings:
        typer.echo(f"  WARNING: {w}")
    approve = typer.confirm("Approve?", default=False)
    reason = typer.prompt("Reason", default="" if not shown.warnings and approve else None) or None
    outcome = GateOutcome.APPROVE if approve else GateOutcome.REJECT
    decision = ctx.gatelog.decide(shown, outcome, ctx.reviewer, reason)
    if not approve:
        raise GateRefused(f"{shown.gate.value} rejected by {ctx.reviewer}: {reason}")
    return decision


def approve_pending(
    run_id: str, pending: Path, reviewer: str, reason: str | None, *, approve: bool
) -> GateDecision:
    """
    Record a person's decision on a pending gate (``lansh approve``, or the Control Tower).

    Args:
        run_id: The run.
        pending: The pending gate's file.
        reviewer: ``person:<name>``.
        reason: Why; required with warnings or a rejection.
        approve: Approve, or reject.

    Returns:
        The decision.
    """
    data = json.loads(pending.read_text(encoding="utf-8"))
    log_ = GateLog(RUNS_DIR / run_id / "gates.jsonl")
    shown = Shown(
        gate=Gate(data["gate"]),
        job_ids=tuple(data["job_ids"]),
        evidence=tuple(EvidenceRef.model_validate(e) for e in data["evidence"]),
        warnings=tuple(data["warnings"]),
        blockers=(),
        wave=data["wave"],
        shown_at=datetime.fromisoformat(data["shown_at"]),
    )
    decision = log_.decide(
        shown, GateOutcome.APPROVE if approve else GateOutcome.REJECT, reviewer, reason
    )
    pending.unlink()
    return decision


### One job


@dataclass
class JobOutcome:
    """
    How one job's run ended.

    Attributes:
        status: MATCH, MISMATCH, ERROR or ESCALATED.
        stopped_at: The gate a run is waiting at or blocked at, if any.
        message: Why it stopped, if it did.
        evidence: The evidence report's Markdown file.
    """

    job_id: str
    status: RunStatus
    stopped_at: Gate | None = None
    message: str = ""
    evidence: Path | None = None
    metrics: RunMetrics | None = None
    report: EvidenceReport | None = None
    module_text: str | None = None


def _decide_defects(
    ctx: Context, job: JobSpec, defects: list[SuspectedDefect], gate: Gate
) -> list[str]:
    """
    Record the default decision (reproduce) on every undecided defect for an agent reviewer.

    Returns:
        For a person, one blocker per undecided defect; for an agent, none.
    """
    decided = {d.defect_id for d in ctx.gatelog.defect_decisions(job.job_id)}
    undecided = [d for d in defects if d.defect_id not in decided]
    if not ctx.reviewer.startswith("agent:"):
        if ctx.interactive:
            for d in undecided:
                _ask_defect(ctx, job, d, gate)
            return []
        return [f"suspected defect {d.defect_id} ({d.title}) has no decision" for d in undecided]
    for d in undecided:
        ctx.gatelog.decide_defect(
            d.defect_id,
            job.job_id,
            DefectDecisionKind.REPRODUCE,
            "development run default: reproduce the legacy behaviour; a person decides at the "
            "showcase run",
            ctx.reviewer,
            gate=gate,
        )
    return []


def _decide_flows(ctx: Context, flows: list[TaggedFlow]) -> list[str]:
    """
    Record the default decision on every undecided tagged flow for an agent reviewer.

    Returns:
        For a person, one blocker per undecided flow; for an agent, none.
    """
    decided = {f.flow_id for f in ctx.gatelog.flow_decisions()}
    undecided = [f for f in flows if f.flow_id not in decided]
    if not ctx.reviewer.startswith("agent:"):
        if ctx.interactive:
            for f in undecided:
                _ask_flow(ctx, f)
            return []
        return [
            f"flow {f.flow_id}: {f.tag.value} {f.source.table}.{f.source.column} into "
            f"{f.output.table}.{f.output.column} has no decision"
            for f in undecided
        ]
    for f in undecided:
        decision = "reproduce_flagged" if f.tag.value == "protected" else "reproduce_accepted"
        ctx.gatelog.decide_flow(
            f.flow_id,
            decision,
            "development run default: reproduce as-is; a protected attribute is flagged for a "
            "bias review after cut-over",
            ctx.reviewer,
        )
    return []


def _ask_defect(ctx: Context, job: JobSpec, defect: SuspectedDefect, gate: Gate) -> None:
    """
    Ask a person in the terminal what to do about one suspected defect, and record it.
    """
    import typer

    impact = defect.impact
    typer.echo(f"\n--- suspected defect {defect.defect_id}: {defect.title}")
    typer.echo(f"    {defect.description}")
    if impact:
        amount = (
            f", {impact.amount_affected} in {impact.amount_column}"
            if impact.amount_affected
            else ""
        )
        typer.echo(f"    impact on the legacy output: {impact.rows_affected} rows{amount}")
    choice = typer.prompt(
        "    decision: [r]eproduce, [f]ix after cut-over, [n]ot a defect", default="r"
    )
    kind = {"f": DefectDecisionKind.FIX_AFTER_CUTOVER, "n": DefectDecisionKind.NOT_A_DEFECT}.get(
        choice.strip().lower()[:1], DefectDecisionKind.REPRODUCE
    )
    reason = typer.prompt("    reason")
    ctx.gatelog.decide_defect(defect.defect_id, job.job_id, kind, reason, ctx.reviewer, gate=gate)


def _ask_flow(ctx: Context, flow: TaggedFlow) -> None:
    """
    Ask a person in the terminal for the bias decision on one flow of a tagged column.
    """
    import typer

    typer.echo(
        f"\n--- {flow.tag.value} column {flow.source.table}.{flow.source.column} flows into "
        f"{flow.output.table}.{flow.output.column} (through {', '.join(flow.job_ids)})"
    )
    flag = typer.confirm("    flag it for a bias review after cut-over?", default=True)
    reason = typer.prompt("    reason")
    decision = "reproduce_flagged" if flag else "reproduce_accepted"
    ctx.gatelog.decide_flow(flow.flow_id, decision, reason, ctx.reviewer)


def run_job(
    ctx: Context, job_id: str, *, operate: bool = True, chained: bool = False
) -> JobOutcome:
    """
    Take one job through the five stages and their gates.

    Args:
        ctx: The run.
        job_id: The job.
        operate: Run Operate (Delta and H5) after H4.
        chained: Operate on the upstream jobs' Delta outputs instead of their golden outputs.

    Returns:
        How the job ended; an :class:`AwaitingApproval` or :class:`GateBlocked` stop is
        reported in the outcome, not raised.
    """
    started = datetime.now(UTC)
    clock = time.perf_counter()
    job = ctx.inventory.job(job_id)
    folder = ctx.run_dir / job_id
    folder.mkdir(parents=True, exist_ok=True)
    report = EvidenceReport(
        job_id=job_id,
        generated_at=started,
        legacy_path=job.path,
        legacy_sha256=file_sha256(REPO_ROOT / job.path),
    )
    outcome = JobOutcome(job_id, RunStatus.ERROR)
    module_text: str | None = None
    try:
        module_text = _stages(ctx, job, folder, report, operate=operate, chained=chained)
        recon_ok = report.recon and all(r.status is ReconStatus.MATCH for r in report.recon)
        outcome.status = RunStatus.MATCH if recon_ok else RunStatus.MISMATCH
    except AwaitingApproval as stop:
        outcome.stopped_at, outcome.message = stop.gate, str(stop)
        outcome.status = RunStatus.MISMATCH if report.recon else RunStatus.ERROR
    except GateBlocked as stop:
        outcome.stopped_at, outcome.message = stop.gate, str(stop)
        outcome.status = RunStatus.ESCALATED if report.escalations else RunStatus.ERROR
        # a gate waiting only for a person's decisions on defects or flows isn't an escalation
        waiting = all(b.endswith("has no decision") for b in stop.blockers)
        if not report.escalations and not waiting:
            report.escalations.append(
                Escalation(
                    escalation_id=f"{job_id}-E{len(report.escalations) + 1}",
                    job_id=job_id,
                    stage=_stage_of(stop.gate),
                    reason="guardrail" if stop.gate is Gate.H3 else "error",
                    diagnosis="; ".join(stop.blockers)[:2000],
                    created_at=datetime.now(UTC),
                )
            )
    except Exception as exc:  # any failure in a stage: escalate it, keep the evidence so far
        from lansh.llm.errors import UsageLimitError, ValidationFailedError

        reason = (
            "usage_limit"
            if isinstance(exc, UsageLimitError)
            else "llm_invalid"
            if isinstance(exc, ValidationFailedError)
            else "error"
        )
        log.exception("%s failed", job_id)
        outcome.message = f"{type(exc).__name__}: {exc}"
        report.escalations.append(
            Escalation(
                escalation_id=f"{job_id}-E{len(report.escalations) + 1}",
                job_id=job_id,
                stage=Stage.DISCOVER,
                reason=reason,  # type: ignore[arg-type]
                diagnosis=outcome.message[:2000],
                created_at=datetime.now(UTC),
            )
        )
        outcome.status = RunStatus.ESCALATED
    report.gates = [d for d in ctx.gatelog.decisions() if job_id in d.job_ids]
    report.defect_decisions = ctx.gatelog.defect_decisions(job_id)
    flow_ids = {f.flow_id for f in report.flows}
    report.flow_decisions = [f for f in ctx.gatelog.flow_decisions() if f.flow_id in flow_ids]
    report.llm_usage = [u for u in ctx.gateway.usage_log if u.job_id == job_id]
    from lansh import evidence

    _, outcome.evidence = evidence.write(report, folder, migrated_code=module_text)
    outcome.report, outcome.module_text = report, module_text
    usage = report.llm_usage
    outcome.metrics = RunMetrics(
        run_id=ctx.run_id,
        job_id=job_id,
        started_at=started,
        ended_at=datetime.now(UTC),
        duration_seconds=round(time.perf_counter() - clock, 3),
        llm_calls=len(usage),
        llm_live_calls=sum(not u.replayed for u in usage),
        input_tokens=sum(
            u.input_tokens + u.cache_read_tokens + u.cache_creation_tokens for u in usage
        ),
        output_tokens=sum(u.output_tokens for u in usage),
        cost_usd_equivalent=round(sum(u.cost_usd_equivalent for u in usage), 4),
        heal_attempts=len(report.heal),
        reviewer_seconds=round(sum(g.review_seconds for g in report.gates), 3),
        status=outcome.status,
    )
    write_json(folder / "metrics.json", outcome.metrics.model_dump(mode="json"))
    return outcome


def _stage_of(gate: Gate) -> Stage:
    """
    Give the stage a gate closes.
    """
    from lansh.contracts import GATE_STAGE

    return GATE_STAGE[gate]


def _stages(
    ctx: Context,
    job: JobSpec,
    folder: Path,
    report: EvidenceReport,
    *,
    operate: bool,
    chained: bool,
) -> str | None:
    """
    Run the five stages for one job, filling the evidence report as it goes.

    Returns:
        The accepted module's source.
    """
    from lansh.design.contract import build_contract, save_contract
    from lansh.design.defects import review
    from lansh.discover.estate import tagged_flows
    from lansh.discover.job import discover_job
    from lansh.discover.split import split_code
    from lansh.discover.traps import signature_lookup
    from lansh.generate.job import defects_marked, generate_job, job_provenance
    from lansh.generate.testgen import build_suite, run_suite, write_suite
    from lansh.lakehouse import input_schemas, output_columns
    from lansh.reconcile.heal import heal
    from lansh.reconcile.job import report_markdown, run_and_reconcile

    inv, gw = ctx.inventory, ctx.gateway
    text = (REPO_ROOT / job.path).read_text(encoding="utf-8")
    blocks = split_code(text, job.language)

    # 1. Discover -> H1
    found = discover_job(job, inv, gw)
    report.discovery, report.lineage, report.traps = found.discovery, found.lineage, found.traps
    discovery_file = write_json(
        folder / "discovery.json",
        {
            "discovery": found.discovery.model_dump(mode="json"),
            "stats": found.stats,
            "warnings": found.warnings,
        },
    )
    lineage_file = write_json(
        folder / "lineage.json", [e.model_dump(mode="json") for e in found.lineage]
    )
    traps_file = write_json(folder / "traps.json", [t.model_dump(mode="json") for t in found.traps])
    pass_gate(
        ctx,
        Gate.H1,
        [job.job_id],
        [_pin(discovery_file, "other"), _pin(lineage_file, "lineage"), _pin(traps_file, "traps")],
        warnings=found.warnings,
        blockers=found.blockers,
        summary=f"{len(found.lineage)} lineage edges, {len(found.traps)} traps, "
        f"status {found.discovery.status}",
    )

    # 2. Design -> H2
    inputs = input_schemas(inv, job, ctx.contracts)
    outputs = {o.table: output_columns(inv, o.table) for o in job.outputs}
    blockers: list[str] = []
    warnings: list[str] = []
    contracts: list[DataContract] = []
    contract_files = []
    for out in job.outputs:
        draft = build_contract(job, inv, out.table, found.lineage, inputs, found.traps, gw)
        contracts.append(draft.contract)
        blockers += draft.blockers
        warnings += draft.warnings
        contract_files.append(save_contract(draft.contract, folder / "contracts"))
    report.contracts = contracts
    listed = review(job, inv, ctx.spark, text, inputs, outputs, [], gw, folder / "staging")
    report.defects = listed.defects
    warnings += listed.notes
    defects_file = write_json(
        folder / "defects.json", [d.model_dump(mode="json") for d in listed.defects]
    )
    sources = {
        (t, c.name.casefold()): list(c.tags) for t, cols in inputs.items() for c in cols if c.tags
    }
    report.flows = [f for f in tagged_flows(sources, found.lineage) if job.job_id in f.job_ids]
    flows_file = write_json(
        folder / "flows.json", [f.model_dump(mode="json") for f in report.flows]
    )
    blockers += _decide_defects(ctx, job, listed.defects, Gate.H2)
    blockers += _decide_flows(ctx, report.flows)
    warnings += [
        f"{d.defect_id} suspected defect: {d.title}"
        + (f" ({d.impact.rows_affected} rows)" if d.impact else "")
        for d in listed.defects
    ]
    warnings += [
        f"{f.tag.value} column {f.source.table}.{f.source.column} flows into "
        f"{f.output.table}.{f.output.column}"
        for f in report.flows
    ]
    pass_gate(
        ctx,
        Gate.H2,
        [job.job_id],
        [
            *(_pin(p, "contract") for p in contract_files),
            _pin(defects_file, "defects"),
            _pin(flows_file, "flows"),
        ],
        warnings=warnings,
        blockers=blockers,
        summary=f"contracts {[c.table for c in contracts]}, "
        f"{len(listed.defects)} suspected defects",
    )
    for c in contracts:
        ctx.contracts[c.legacy_table] = c

    # 3. Generate -> H3
    notes = next(
        (w.split(": ", 1)[1] for w in found.warnings if w.startswith("lineage agent notes")), ""
    )
    generated = generate_job(
        job,
        inv,
        text,
        blocks,
        inputs,
        contracts,
        found.traps,
        notes,
        gw,
        folder / "jobs",
        defects=listed.defects,
    )
    suite = build_suite(
        job,
        inv,
        text,
        inputs,
        outputs,
        contracts,
        found.traps,
        gw,
        legacy=job.language is Language.TSQL,
    )
    provenance = job_provenance(job, text, inputs, contracts)
    translator_notes = generated.answer.notes.strip()

    def code_gate(module: Path, guard: Any, label: str) -> list[TestCase]:
        """
        Write and run the tests against one version of the module, then decide H3 on it.
        """
        current = folder / "jobs" / f"{job.job_id.lower()}.py"
        if module.resolve() != current.resolve():
            shutil.copyfile(module, current)  # the tests run the module in ../jobs/
        cases_file, test_file = write_suite(suite, folder / "tests")
        passed, failed, output = run_suite(test_file) if suite.cases else (0, 0, "no cases")
        statuses = _case_statuses(output, [c.test_id for c in suite.cases], passed + failed)
        tests = [
            c.model_copy(update={"status": statuses[c.test_id], "path": str(test_file.name)})
            for c in suite.cases
        ]
        tests_file = write_json(
            folder / "tests.json",
            {
                "passed": passed,
                "failed": failed,
                "output": output,
                "cases": [t.model_dump(mode="json") for t in tests],
            },
        )
        guard_file = write_json(
            folder / "guardrails.json",
            {
                "violations": guard.violations,
                "literals": [lit.model_dump(mode="json") for lit in guard.literals],
            },
        )
        h3_blockers = list(guard.violations)
        accepted = accepted_literals(folder, file_sha256(current))
        h3_blockers += [
            f"line {lit.line}: literal {lit.value!r} has no provenance"
            for lit in guard.blocking_literals
            if (lit.value, lit.line) not in accepted
        ]
        accepted_notes = [
            f"literal {value!r} on line {line} accepted by {who}: {why}"
            for (value, line), (who, why) in sorted(accepted.items())
        ]
        h3_blockers += [f"{failed} of {passed + failed} trap tests fail"] if failed else []
        pass_gate(
            ctx,
            Gate.H3,
            [job.job_id],
            [
                _pin(folder / "jobs" / f"{job.job_id.lower()}.py", "code"),
                _pin(guard_file, "other"),
                _pin(tests_file, "tests"),
                _pin(cases_file, "tests"),
            ],
            warnings=[*suite.notes, *accepted_notes]
            + ([f"translator notes: {translator_notes}"] if translator_notes else []),
            blockers=h3_blockers,
            summary=f"{label}: guardrails {'passed' if guard.passed else 'FAILED'}, "
            f"tests {passed} passed, {failed} failed",
        )
        return tests

    report.code = generated.artifact
    report.tests = code_gate(generated.module, generated.guardrails, "translation")

    # 4. Reconcile (and heal) -> H4
    contract_map = {c.legacy_table: c for c in contracts}
    first = run_and_reconcile(
        ctx.spark,
        inv,
        job,
        generated.module,
        folder / "reconcile",
        mode=ReconMode.ISOLATED,
        contracts=contract_map,
        run_id=ctx.run_id,
        traps_for=signature_lookup(job.language),
    )
    reports, module = first.reports, generated.module
    if first.status is not ReconStatus.MATCH:
        healed = heal(
            job,
            inv,
            ctx.spark,
            generated.module,
            first.reports,
            folder / "heal",
            gw,
            legacy_text=text,
            inputs=inputs,
            contracts=contracts,
            traps=found.traps,
            provenance=provenance,
            run_id=ctx.run_id,
        )
        report.heal = healed.attempts
        reports, module = healed.reports, healed.module
        if healed.escalation:
            report.escalations.append(healed.escalation)
        if module != generated.module:
            from lansh.generate.job import artifact_for, check

            guard = check(module, provenance)
            last = healed.attempts[-1] if healed.attempts else None
            report.code = artifact_for(
                job,
                module,
                guard,
                translator="fixer",
                approach=generated.artifact.approach,
                model=generated.artifact.model,
                attempt=last.attempt if last else 0,
                traps_handled=[
                    *generated.artifact.traps_handled,
                    *(t for a in healed.attempts for t in a.suspected_traps),
                ],
            )
            report.tests = code_gate(module, guard, f"healed (attempt {report.code.attempt})")
    report.recon = reports
    recon_files = []
    for r in reports:
        recon_files.append(
            write_json(folder / "recon" / f"{r.table}.json", r.model_dump(mode="json"))
        )
        (folder / "recon" / f"{r.table}.md").write_text(report_markdown(r), encoding="utf-8")
    heal_file = write_json(folder / "heal.json", [h.model_dump(mode="json") for h in report.heal])
    # suspected defects the code marks that Design didn't list are decided at H4
    marked = defects_marked(module)
    known_ids = {d.defect_id for d in report.defects}
    for i, text_ in enumerate(marked, 1):
        if not any(k in text_ for k in known_ids):
            report.defects.append(
                SuspectedDefect(
                    defect_id=f"{job.job_id}-M{i}",
                    job_id=job.job_id,
                    title=text_[:120],
                    description=f"Marked {DEFECT_MARKER} in the migrated code: {text_}",
                    source="marker",
                    confidence=0.6,
                )
            )
    h4_blockers = [
        f"{r.table} is {r.status.value}: {r.explanation[:300]}"
        for r in reports
        if r.status is not ReconStatus.MATCH
    ]
    h4_blockers += _decide_defects(ctx, job, report.defects, Gate.H4)
    pass_gate(
        ctx,
        Gate.H4,
        [job.job_id],
        [*(_pin(p, "recon_report") for p in recon_files), _pin(heal_file, "heal")],
        warnings=[f"healed in {len(report.heal)} attempts"] if report.heal else [],
        blockers=h4_blockers,
        summary="; ".join(f"{r.table} {r.status.value}" for r in reports),
    )
    accepted = _accept(job, folder, module, contracts)
    accepted_text = accepted.read_text(encoding="utf-8")
    if not operate:
        return accepted_text

    # 5. Operate -> H5, for this job on its own
    cut_over(ctx, [job.job_id], {job.job_id: (report, found.lineage)}, chained=chained)
    return accepted_text


def operate_one(
    ctx: Context, job: JobSpec, report: EvidenceReport, lineage: list[Any], *, chained: bool
) -> tuple[Any, Path]:
    """
    Run one accepted job on the lakehouse, reconcile what it wrote, and keep the evidence.

    Returns:
        The operate result and its evidence file.
    """
    from lansh.operate.run import operate_job

    folder = ctx.run_dir / job.job_id
    lake = ctx.lakehouse or (ctx.run_dir / "lakehouse")
    module = MIGRATED_DIR / "jobs" / f"{job.job_id.lower()}.py"
    contracts = {c.legacy_table: c for c in report.contracts}
    result = operate_job(
        ctx.spark,
        ctx.inventory,
        job,
        module,
        folder / "operate",
        run_id=ctx.run_id,
        contracts=contracts,
        lineage=lineage,
        lakehouse=lake,
        chained=chained,
    )
    operate_file = write_json(
        folder / "operate.json",
        {
            "status": result.status.value,
            "mode": "chained" if chained else "isolated",
            "seconds": result.seconds,
            "error": result.error,
            "reports": [r.model_dump(mode="json") for r in result.reports],
            "sla": [s.model_dump(mode="json") for s in result.sla],
            "lineage_event": str(result.lineage_event) if result.lineage_event else None,
        },
    )
    # the Delta re-run's reports are told apart by their run id
    sandbox = [r for r in report.recon if not (r.run_id or "").endswith(":operate")]
    report.recon = [
        *sandbox,
        *(r.model_copy(update={"run_id": f"{ctx.run_id}:operate"}) for r in result.reports),
    ]
    return result, operate_file


def cut_over(
    ctx: Context,
    job_ids: list[str],
    reports: dict[str, tuple[EvidenceReport, list[Any]]],
    *,
    chained: bool,
    wave: int | None = None,
) -> GateDecision:
    """
    Operate accepted jobs on the lakehouse and decide H5 for them together.

    Args:
        ctx: The run.
        job_ids: The jobs, all past H4, in run order.
        reports: Each job's evidence report and lineage, updated with the Delta results.
        chained: Read upstream outputs from the lakehouse.
        wave: The wave number; the first job's wave when not given.

    Returns:
        The H5 decision.
    """
    from lansh.discover.estate import wave_of

    evidence: list[EvidenceRef] = []
    blockers: list[str] = []
    summaries = []
    for job_id in job_ids:
        job = ctx.inventory.job(job_id)
        report, lineage = reports[job_id]
        try:
            result, operate_file = operate_one(ctx, job, report, lineage, chained=chained)
        except FileNotFoundError as exc:
            # an upstream job of this one hasn't been cut over: its Delta table is missing
            blockers.append(f"{job_id} can't run on the lakehouse yet: {exc}")
            summaries.append(f"{job_id} waiting for its upstream jobs")
            continue
        evidence.append(_pin(operate_file, "sla"))
        blockers += [
            f"{job_id} {r.table} on Delta is {r.status.value}"
            for r in result.reports
            if r.status is not ReconStatus.MATCH
        ]
        blockers += [
            f"{job_id} {s.table}: SLA breached ({', '.join(s.breaches)})"
            for s in result.sla
            if s.breaches
        ]
        summaries.append(f"{job_id} Delta {result.status.value}")
    number = wave if wave is not None else wave_of(ctx.inventory, job_ids[0])
    return pass_gate(
        ctx,
        Gate.H5,
        job_ids,
        evidence,
        warnings=[],
        blockers=blockers,
        wave=number,
        summary=f"wave {number}: " + ", ".join(summaries),
    )


def accepted_literals(folder: Path, code_sha256: str) -> dict[tuple[str, int], tuple[str, str]]:
    """
    Read the literals a person accepted for this exact version of a job's module (plan §8.5).

    An acceptance names the module's hash, so a patched module needs its literals accepted
    again.

    Args:
        folder: The job's folder in the run.
        code_sha256: The module's hash.

    Returns:
        (reviewer, reason) by (literal, line).
    """
    path = folder / "accepted_literals.json"
    if not path.exists():
        return {}
    return {
        (a["value"], a["line"]): (a["reviewer"], a["reason"])
        for a in json.loads(path.read_text(encoding="utf-8"))
        if a["code_sha256"] == code_sha256
    }


def accept_literal(
    run_id: str, job_id: str, value: str, line: int, reviewer: str, reason: str
) -> Path:
    """
    Record a person's acceptance of an unexplained literal in a job's current module.

    Args:
        run_id: The run.
        job_id: The job.
        value: The literal, as the guardrails report it.
        line: Its line in the module.
        reviewer: ``person:<name>``: an agent never accepts its own literals.
        reason: Why the literal is legitimate.

    Returns:
        The acceptances file.

    Raises:
        GateRefused: If the reviewer isn't a person, or the reason is empty.
    """
    if not reviewer.startswith("person:"):
        raise GateRefused("only a person can accept an unexplained literal")
    if not reason.strip():
        raise GateRefused("accepting an unexplained literal needs a reason")
    folder = RUNS_DIR / run_id / job_id
    module = folder / "jobs" / f"{job_id.lower()}.py"
    path = folder / "accepted_literals.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(
        {
            "value": value,
            "line": line,
            "reviewer": reviewer,
            "reason": reason,
            "code_sha256": file_sha256(module),
            "accepted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    return write_json(path, entries)


def _case_statuses(output: str, test_ids: list[str], ran: int) -> dict[str, str]:
    """
    Read each case's result from pytest's output: a case named on a FAILED or ERROR line failed.

    Args:
        output: The tail of pytest's output.
        test_ids: The cases.
        ran: How many tests pytest reports as passed or failed; 0 means the run broke.

    Returns:
        ``pass``, ``fail`` or ``error`` per case.
    """
    if not ran:
        return dict.fromkeys(test_ids, "error")
    bad = [line for line in output.splitlines() if line.startswith(("FAILED", "ERROR"))]
    return {t: "fail" if any(f"[{t}]" in line for line in bad) else "pass" for t in test_ids}


def _accept(job: JobSpec, folder: Path, module: Path, contracts: list[DataContract]) -> Path:
    """
    Copy an accepted job's module, tests and contracts into ``migrated/``.

    Returns:
        The accepted module in ``migrated/jobs/``.
    """
    stem = job.job_id.lower()
    target = MIGRATED_DIR / "jobs" / f"{stem}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(module, target)
    tests = folder / "tests"
    if (tests / f"test_{stem}.py").exists():
        (MIGRATED_DIR / "tests" / "cases").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tests / f"test_{stem}.py", MIGRATED_DIR / "tests" / f"test_{stem}.py")
        shutil.copyfile(
            tests / "cases" / f"{stem}.json", MIGRATED_DIR / "tests" / "cases" / f"{stem}.json"
        )
    from lansh.design.contract import save_contract

    for contract in contracts:
        save_contract(contract, MIGRATED_DIR / "contracts")
    return target


### The estate


@dataclass
class EstateOutcome:
    """
    How an estate run ended.

    Attributes:
        jobs: Each job's outcome.
        waves: The waves, as run.
        cut_over: The waves that passed H5.
    """

    jobs: dict[str, JobOutcome] = field(default_factory=dict)
    waves: list[list[str]] = field(default_factory=list)
    cut_over: list[int] = field(default_factory=list)


def _refresh_evidence(ctx: Context, outcome: JobOutcome) -> None:
    """
    Rewrite a job's evidence report after its wave's cut-over, with the latest gate decisions.
    """
    from lansh import evidence

    report = outcome.report
    if report is None:
        return
    report.gates = [d for d in ctx.gatelog.decisions() if outcome.job_id in d.job_ids]
    report.defect_decisions = ctx.gatelog.defect_decisions(outcome.job_id)
    evidence.write(report, ctx.run_dir / outcome.job_id, migrated_code=outcome.module_text)


def run_estate(
    ctx: Context, job_ids: list[str] | None = None, *, operate: bool = True
) -> EstateOutcome:
    """
    Take the estate through the factory wave by wave, then cut each wave over together.

    Each job in a wave goes through H1–H4 on isolated inputs; the wave's accepted jobs then run
    on the lakehouse on chained inputs (their upstream jobs' Delta outputs), are reconciled
    again, and are cut over together at H5. A job blocked or escalated before H4 doesn't stop
    the others; a downstream job whose upstream wasn't cut over can't run chained, so its H5 is
    blocked.

    Args:
        ctx: The run.
        job_ids: The jobs to run; every development job when None (held-out jobs run only
            when named, so their one run is reported apart).
        operate: Cut the waves over (Operate and H5).

    Returns:
        Every job's outcome and the waves cut over.
    """
    from lansh.discover.estate import estate_plan, waves
    from lansh.operate.run import wave_schedules, write_schedule

    inventory = ctx.inventory
    plan = estate_plan(inventory)
    write_json(ctx.run_dir / "estate.json", plan.model_dump(mode="json"))
    selected = set(job_ids or [j.job_id for j in inventory.jobs if not j.holdout])
    result = EstateOutcome(waves=[[j for j in w if j in selected] for w in waves(inventory)])
    for number, wave in enumerate(result.waves, 1):
        for job_id in wave:
            log.info("wave %d: %s", number, job_id)
            result.jobs[job_id] = run_job(ctx, job_id, operate=False)
        accepted = [j for j in wave if ctx.gatelog.passed(j, Gate.H4)]
        if not (operate and accepted):
            continue
        reports = {
            j: (result.jobs[j].report, result.jobs[j].report.lineage)  # type: ignore[union-attr]
            for j in accepted
        }
        try:
            cut_over(ctx, accepted, reports, chained=True, wave=number)  # type: ignore[arg-type]
            result.cut_over.append(number)
        except (AwaitingApproval, GateBlocked) as stop:
            log.warning("wave %d not cut over: %s", number, stop)
        for j in accepted:
            _refresh_evidence(ctx, result.jobs[j])
    # the schedules cover the whole estate, whichever jobs this run took through
    schedules = wave_schedules(waves(inventory), inventory)
    for schedule in schedules:
        write_schedule(schedule, inventory, ctx.run_dir / "schedules")
    write_register(ctx, result)
    return result


def write_register(ctx: Context, result: EstateOutcome | None = None) -> None:
    """
    Write the estate's defect register and tagged flows from the run's evidence reports.

    Args:
        ctx: The run.
        result: Unused; the register is rebuilt from the evidence files, so it can be written
            again for any finished run (``lansh register``).
    """
    del result
    register(ctx.run_dir)


def register(run_dir: Path) -> tuple[Path, Path]:
    """
    Build a run's defect register (JSON and Markdown) and its estate-wide tagged flows.

    The flows are traced through every job's lineage at once, so a path that crosses jobs
    (``stg.customers.date_of_birth`` through T01 into S04's age loading) is one flow.

    Args:
        run_dir: The run's folder.

    Returns:
        The register's JSON and Markdown files.
    """
    from lansh.contracts import LineageEdge
    from lansh.discover.estate import tagged_flows
    from lansh.estate.generate import load_dictionary

    reports = [
        EvidenceReport.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(run_dir.glob("*/evidence.json"))
    ]
    rows, lineage = [], []
    for report in reports:
        decisions = {d.defect_id: d for d in report.defect_decisions}
        lineage += report.lineage
        for d in report.defects:
            decided = decisions.get(d.defect_id)
            rows.append(
                {
                    **d.model_dump(mode="json"),
                    "decision": decided.model_dump(mode="json") if decided else None,
                }
            )
    json_path = write_json(run_dir / "defect_register.json", rows)
    lines = [
        "# Defect register",
        "",
        "Suspected legacy bugs across the estate. LANSH reproduces each one exactly (the migrated "
        "job matches the legacy output, bug included) and asks a person to decide what happens "
        "next. Impacts are measured on the legacy output by the reviewer's impact query.",
        "",
        "| Defect | Job | What the legacy code does | Rows affected | Amount | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(
        rows, key=lambda r: (-(r.get("impact") or {}).get("rows_affected", 0), r["defect_id"])
    ):
        impact = r.get("impact") or {}
        decided = r.get("decision") or {}
        amount = (
            f"{impact['amount_affected']} ({impact.get('amount_column')})"
            if impact.get("amount_affected")
            else ""
        )
        lines.append(
            f"| {r['defect_id']} {r['title']} | {r['job_id']} | {r['description'][:180]} | "
            f"{impact.get('rows_affected', 'not measured')} | {amount} | "
            f"{decided.get('decision', 'undecided')} |"
        )
    md_path = run_dir / "defect_register.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sources = {
        (s.name, c.name.casefold()): list(c.tags)
        for s in load_dictionary()
        for c in s.columns
        if c.tags
    }
    flows = tagged_flows(sources, [LineageEdge.model_validate(e.model_dump()) for e in lineage])
    write_json(run_dir / "tagged_flows.json", [f.model_dump(mode="json") for f in flows])
    return json_path, md_path
