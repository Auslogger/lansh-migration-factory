"""
Generate one job: draft, translate, write the module and run the guardrails (plan §8.5).

The module is written into the run's folder; only once H3 and H4 approve it is it copied into
``migrated/jobs/``. :func:`check` runs the guardrails on any version of a module, so the heal
loop applies exactly the same checks to every patch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lansh.contracts import (
    Approach,
    ColumnSpec,
    DataContract,
    EstateInventory,
    JobSpec,
    MigrationArtifact,
    Stage,
    SuspectedDefect,
    TrapFinding,
)
from lansh.discover.split import Block
from lansh.discover.traps import allowed_literals
from lansh.estate.fingerprint import file_sha256
from lansh.generate.draft import make_draft
from lansh.generate.guardrails import GuardrailReport, Provenance, check_module, provenance_for
from lansh.generate.template import DEFECT_MARKER
from lansh.generate.translator import oneshot_request, translation_request
from lansh.llm.answers import TranslationAnswer

_TRAP_ID = re.compile(r"\b(TSQL|SAS)-[0-9]{2}\b")


@dataclass
class GenerateResult:
    """
    A generated module and what the guardrails made of it.

    Attributes:
        module: The module file.
        artifact: The contract's record of it.
        guardrails: The guardrail report.
        answer: The translator's answer (code, traps handled, defects, notes).
        draft: The sqlglot draft the translator was given.
    """

    module: Path
    artifact: MigrationArtifact
    guardrails: GuardrailReport
    answer: TranslationAnswer
    draft: str


def job_provenance(
    job: JobSpec,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
) -> Provenance:
    """
    Gather what the literal check accepts for one job: legacy code, names, params, cards.

    Args:
        job: The job.
        text: Its legacy code.
        inputs: Its input tables' columns.
        contracts: Its outputs' contracts.

    Returns:
        The provenance.
    """
    names = [*inputs, *[c.legacy_table for c in contracts], *[c.table for c in contracts]]
    names += [col.name for cols in inputs.values() for col in cols]
    names += [col.name for c in contracts for col in c.columns]
    params = {k: v for inv in job.invocations for k, v in inv.params.items()}
    return provenance_for(text, names, params, allowed_literals())


def write_module(code: str, path: Path) -> Path:
    """
    Write a module's code with Unix line endings and a final newline.

    Args:
        code: The module's source.
        path: Where to write it.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = code.replace("\r\n", "\n").rstrip("\n") + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def defects_marked(path: Path) -> list[str]:
    """
    Read the ``# LANSH-DEFECT`` markers in a module, one short text per marked line.

    Args:
        path: The module file.

    Returns:
        The text after each marker, in line order.
    """
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if DEFECT_MARKER in line:
            out.append(line.split(DEFECT_MARKER, 1)[1].lstrip(" :").strip() or "(no text)")
    return out


def check(path: Path, provenance: Provenance) -> GuardrailReport:
    """
    Run the guardrails on one version of a module.

    Args:
        path: The module.
        provenance: What the literal check accepts.

    Returns:
        The report.
    """
    return check_module(path, provenance)


def artifact_for(
    job: JobSpec,
    path: Path,
    report: GuardrailReport,
    *,
    translator: str,
    approach: Approach,
    model: str | None,
    attempt: int,
    traps_handled: list[str],
) -> MigrationArtifact:
    """
    Record one version of a migrated module.

    Args:
        job: The job.
        path: The module.
        report: Its guardrail report.
        translator: Who wrote this version: ``claude``, ``oneshot_claude``, ``fixer``...
        approach: The approach that produced it.
        model: The model that wrote it.
        attempt: The heal attempt that produced it; 0 for the first translation.
        traps_handled: The trap ids it handles.

    Returns:
        The artifact record.
    """
    from lansh.config import REPO_ROOT
    from lansh.estate.golden import rel

    return MigrationArtifact(
        job_id=job.job_id,
        module_path=rel(path),
        code_sha256=file_sha256(path),
        legacy_path=job.path,
        legacy_sha256=file_sha256(REPO_ROOT / job.path),
        approach=approach,
        translator=translator,
        model=model,
        attempt=attempt,
        traps_handled=sorted({t for t in traps_handled if _TRAP_ID.fullmatch(t)}),
        defects_reproduced=[f"{job.job_id}-M{i}" for i, _ in enumerate(defects_marked(path), 1)],
        guardrail_violations=list(report.violations),
        literals=list(report.literals),
        created_at=datetime.now(UTC),
    )


def generate_job(
    job: JobSpec,
    inventory: EstateInventory,
    text: str,
    blocks: list[Block],
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
    traps: list[TrapFinding],
    notes: str,
    gateway: Any,
    out_dir: Path,
    *,
    oneshot: bool = False,
    defects: list[SuspectedDefect] | None = None,
) -> GenerateResult:
    """
    Draft and translate one job, write the module and run the guardrails.

    Args:
        job: The job.
        inventory: The estate inventory.
        text: Its legacy code.
        blocks: Its blocks.
        inputs: Its input tables' columns.
        contracts: Its outputs' approved contracts.
        traps: Its trap findings.
        notes: The Lineage agent's notes.
        gateway: The Claude gateway.
        out_dir: Where the module is written.
        oneshot: Translate in one shot, without cards, draft or notes (a comparison run).
        defects: The suspected legacy bugs Design found, which the translator reproduces.

    Returns:
        The module, its artifact record and guardrail report.
    """
    del inventory  # the inputs and contracts already carry what the translator needs
    from lansh.config import REPO_ROOT

    legacy_sha = file_sha256(REPO_ROOT / job.path)
    draft = "" if oneshot else make_draft(job.language, blocks, traps)
    if oneshot:
        request = oneshot_request(job, text, legacy_sha, inputs, contracts)
    else:
        request = translation_request(
            job, text, legacy_sha, inputs, contracts, traps, draft, notes, defects
        )
    result = gateway.ask(request, Stage.GENERATE)
    answer: TranslationAnswer = result.output
    path = write_module(answer.code, out_dir / f"{job.job_id.lower()}.py")
    report = check(path, job_provenance(job, text, inputs, contracts))
    models = sorted({m for u in result.usage for m in u.models_used})
    artifact = artifact_for(
        job,
        path,
        report,
        translator="oneshot_claude" if oneshot else "claude",
        approach=Approach.ONESHOT_CLAUDE if oneshot else Approach.LANSH,
        model=", ".join(models) or request.model,
        attempt=0,
        traps_handled=answer.traps_handled,
    )
    return GenerateResult(path, artifact, report, answer, draft)
