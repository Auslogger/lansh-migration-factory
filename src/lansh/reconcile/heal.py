"""
The heal loop: diagnose a failed reconciliation, patch the job, re-check and re-run (plan §8.6).

Each attempt:

1. The Diagnoser/Fixer agent reads the legacy code, the current module, the reconciliation
   reports (explanations, diff signatures, masked sample rows) with the trap cards the
   signatures point at, and every earlier attempt. It returns a diagnosis and the complete
   corrected module.
2. The guardrails and the literal check run again. A patch that fails them, or brings a
   literal found nowhere else, is not run: a fixer can't hard-code its way to a MATCH.
3. The patched job runs in the worker and is reconciled. The patch is kept only if the job's
   score strictly improves (an error outweighs a schema issue, which outweighs a count
   difference, which outweighs row differences).

The loop stops at MATCH, or escalates after three attempts. Every attempt is recorded as a
:class:`~lansh.contracts.HealAttempt`. The prompt holds nothing that changes from run to run
(no times, paths or run ids), so the same failure asks the same question and replays.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lansh.contracts import (
    ColumnSpec,
    DataContract,
    Effort,
    Escalation,
    EstateInventory,
    HealAttempt,
    JobSpec,
    ReconMode,
    ReconReport,
    ReconStatus,
    Stage,
    TrapFinding,
    total_score,
)
from lansh.discover.split import numbered
from lansh.discover.traps import load_cards, signature_lookup
from lansh.estate.fingerprint import file_sha256
from lansh.generate.guardrails import Provenance
from lansh.generate.job import check, write_module
from lansh.generate.translator import _system
from lansh.llm.answers import FixAnswer
from lansh.llm.request import ClaudeRequest

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

FIX_TASK = """\

You are now the diagnoser and fixer. A migrated module failed reconciliation against the \
legacy engine's output. Work out exactly what makes the outputs differ, using the reports, \
their diff signatures and sample rows, and return the complete corrected module (not a diff). \
Keep everything that already matches. Reproduce the legacy behaviour, bugs included: never fix \
a legacy bug to make numbers look right, and never hard-code values from the sample rows.
"""


def _report_text(report: ReconReport) -> str:
    """
    Describe one reconciliation report for the fixer, with nothing run-specific in it.
    """
    lines = [f"Output {report.table}: {report.status.value}. {report.explanation}"]
    if report.error:
        lines.append(f"Error: {report.error}")
    for diff in report.column_diffs:
        lines.append(
            f"- {diff.column} ({diff.policy.value}) differs on {diff.n_rows} rows; samples:"
        )
        lines += [f"    {json.dumps(s, sort_keys=True, default=str)}" for s in diff.samples]
    if report.missing_samples:
        lines.append("- rows only in the legacy output:")
        lines += [
            f"    {json.dumps(s, sort_keys=True, default=str)}" for s in report.missing_samples
        ]
    if report.extra_samples:
        lines.append("- rows only in the migrated output:")
        lines += [f"    {json.dumps(s, sort_keys=True, default=str)}" for s in report.extra_samples]
    for sig in report.signatures:
        traps = f" (suspected: {', '.join(sig.suspected_traps)})" if sig.suspected_traps else ""
        lines.append(f"- signature {sig.kind.value}{traps}: {sig.explanation}")
    return "\n".join(lines)


def _cards_text(trap_ids: set[str]) -> str:
    """
    Give the full cards of the suspected traps.
    """
    cards = load_cards()
    return "\n".join(
        f"### {c.trap_id}: {c.title}\nLegacy: {' '.join(c.legacy_behaviour.split())}\n"
        f"Spark: {' '.join(c.spark_behaviour.split())}\nFix: {' '.join(c.fix_guidance.split())}"
        for t in sorted(trap_ids)
        if (c := cards.get(t))
    )


def fix_request(
    job: JobSpec,
    legacy_text: str,
    module_text: str,
    reports: list[ReconReport],
    traps: list[TrapFinding],
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
    history: list[str],
) -> ClaudeRequest[FixAnswer]:
    """
    Build the Diagnoser/Fixer agent's request for one heal attempt.

    Args:
        job: The job.
        legacy_text: Its legacy code.
        module_text: The current migrated module.
        reports: Its latest reconciliation reports.
        traps: Its trap findings.
        inputs: Its input tables' columns.
        contracts: Its outputs' contracts.
        history: One line per earlier attempt: its diagnosis and what happened.

    Returns:
        The request.
    """
    suspected = {t for r in reports for s in r.signatures for t in s.suspected_traps}
    suspected |= {t.trap_id for t in traps}
    schemas = "\n".join(
        f"- {t}: " + ", ".join(f"{c.name} {c.data_type}" for c in cols)
        for t, cols in inputs.items()
    )
    outputs = "\n".join(
        f"- {c.legacy_table} (key {c.keys or 'none'}): "
        + ", ".join(f"{col.name} {col.data_type} [{col.policy.kind.value}]" for col in c.columns)
        for c in contracts
    )
    prompt = (
        f"Job {job.job_id}: {job.name} ({job.language.value}).\n\n"
        f"Legacy code:\n{numbered(legacy_text)}\n\n"
        f"Current migrated module:\n{module_text}\n\n"
        f"Reconciliation:\n" + "\n\n".join(_report_text(r) for r in reports) + "\n\n"
        f"Trap findings: {', '.join(sorted({t.trap_id for t in traps})) or 'none'}\n"
        f"Trap cards for the suspected traps:\n{_cards_text(suspected)}\n\n"
        f"Input tables:\n{schemas}\n\nOutput tables (type [policy]):\n{outputs}\n\n"
        f"Earlier attempts:\n{chr(10).join(history) or '(none)'}\n"
    )
    return ClaudeRequest(
        agent="fixer",
        job_id=job.job_id,
        system_prompt=_system(job) + FIX_TASK,
        prompt=prompt,
        response_model=FixAnswer,
        effort=Effort.HIGH.value,
    )


@dataclass
class HealResult:
    """
    How the heal loop ended.

    Attributes:
        module: The best module found: the healed one, or the original if nothing improved.
        reports: Its reconciliation reports.
        attempts: Every attempt, in order.
        escalation: Set when the loop gave up.
    """

    module: Path
    reports: list[ReconReport]
    attempts: list[HealAttempt] = field(default_factory=list)
    escalation: Escalation | None = None

    @property
    def status(self) -> ReconStatus:
        """
        MATCH when every output matches, otherwise the worst status among the reports.
        """
        statuses = {r.status for r in self.reports}
        for status in (ReconStatus.ERROR, ReconStatus.MISMATCH):
            if status in statuses:
                return status
        return ReconStatus.MATCH


def heal(
    job: JobSpec,
    inventory: EstateInventory,
    spark: Any,
    module: Path,
    reports: list[ReconReport],
    work_dir: Path,
    gateway: Any,
    *,
    legacy_text: str,
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
    traps: list[TrapFinding],
    provenance: Provenance,
    mode: ReconMode = ReconMode.ISOLATED,
    run_id: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> HealResult:
    """
    Run the heal loop until the job matches or the attempts run out.

    Args:
        job: The job.
        inventory: The estate inventory.
        spark: The parent's Spark session.
        module: The module that failed.
        reports: Its reconciliation reports.
        work_dir: Where each attempt's module and run go (``attempt-N/``).
        gateway: The Claude gateway.
        legacy_text: The legacy code.
        inputs: The job's input tables' columns.
        contracts: Its outputs' contracts.
        traps: Its trap findings.
        provenance: What the literal check accepts.
        mode: How the job's inputs are staged.
        run_id: The run.
        max_attempts: Attempts before escalating (3 in the plan).

    Returns:
        The best module, its reports, every attempt and any escalation.
    """
    from lansh.reconcile.job import run_and_reconcile

    contract_map = {c.legacy_table: c for c in contracts}
    best = HealResult(module, list(reports))
    history: list[str] = []
    for number in range(1, max_attempts + 1):
        if best.status is ReconStatus.MATCH:
            break
        started, clock = datetime.now(UTC), time.perf_counter()
        score_before = total_score(best.reports)
        request = fix_request(
            job,
            legacy_text,
            best.module.read_text(encoding="utf-8"),
            best.reports,
            traps,
            inputs,
            contracts,
            history,
        )
        result = gateway.ask(request, Stage.RECONCILE)
        answer: FixAnswer = result.output
        attempt_dir = work_dir / f"attempt-{number}"
        patched = write_module(answer.code, attempt_dir / "jobs" / f"{job.job_id.lower()}.py")
        report = check(patched, provenance)
        problems = list(report.violations) + [
            f"line {lit.line}: literal {lit.value!r} appears nowhere in the legacy code, contract, "
            "parameters or trap cards"
            for lit in report.blocking_literals
        ]
        score_after = None
        new_reports: list[ReconReport] = []
        status_after = None
        if not problems:
            run = run_and_reconcile(
                spark,
                inventory,
                job,
                patched,
                attempt_dir / "run",
                mode=mode,
                contracts=contract_map,
                run_id=run_id,
                traps_for=signature_lookup(job.language),
            )
            new_reports = run.reports
            score_after = total_score(new_reports)
            status_after = run.status
        kept = score_after is not None and score_after < score_before
        attempt = HealAttempt(
            job_id=job.job_id,
            attempt=number,
            diagnosis=answer.diagnosis,
            suspected_traps=[t for t in answer.suspected_traps if t in load_cards()],
            patch_summary=answer.patch_summary,
            code_sha256_before=file_sha256(best.module),
            code_sha256_after=file_sha256(patched),
            score_before=score_before,
            score_after=score_after,
            report_before=f"attempt-{number - 1}" if number > 1 else "translation",
            report_after=f"attempt-{number}" if new_reports else None,
            guardrails_passed=not problems,
            kept=kept,
            recon_status_after=status_after,
            llm_call_ids=[u.call_id for u in result.usage],
            started_at=started,
            duration_seconds=round(time.perf_counter() - clock, 3),
        )
        best.attempts.append(attempt)
        outcome = (
            f"refused by the guardrails: {'; '.join(problems)[:600]}"
            if problems
            else f"re-ran: {status_after.value if status_after else '?'}, score {score_after} "
            f"(was {score_before}); {'kept' if kept else 'not kept: it did not improve'}"
        )
        history.append(f"- attempt {number}: {answer.diagnosis[:400]} -> {outcome}")
        log.info("%s heal attempt %d: %s", job.job_id, number, outcome)
        if kept:
            best = HealResult(patched, new_reports, best.attempts)
    if best.status is not ReconStatus.MATCH:
        last = best.attempts[-1].diagnosis if best.attempts else "no attempt was made"
        best.escalation = Escalation(
            escalation_id=f"{job.job_id}-E{len(best.attempts)}",
            job_id=job.job_id,
            stage=Stage.RECONCILE,
            reason="heal_exhausted",
            diagnosis=last,
            attempts=len(best.attempts),
            created_at=datetime.now(UTC),
        )
    return best
