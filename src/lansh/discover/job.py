"""
Discover one job: blocks, tables, traps and lineage, with the evidence and warnings for H1.

H1 (scope and lineage) needs every job parsed or flagged and every lineage column to exist
(plan §6.3). Refused lineage edges are dropped, so what remains names only real columns; the
refusals, columns with no lineage, sqlglot disagreements and tables the code uses but the
inventory doesn't list become warnings for the reviewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lansh.config import REPO_ROOT
from lansh.contracts import (
    EstateInventory,
    JobDiscovery,
    JobSpec,
    Language,
    LineageEdge,
    Stage,
    TrapFinding,
)
from lansh.discover.lineage import (
    cross_check,
    lineage_request,
    missing_lineage,
    sqlglot_lineage,
    verify_lineage,
)
from lansh.discover.split import Block, split_code
from lansh.discover.traps import scan
from lansh.lakehouse import input_schemas, output_columns

_TABLE = r"((?:\[?[A-Za-z_][\w]*\]?\.)\[?[A-Za-z_]\w*\]?)"
_TSQL_WRITES = re.compile(
    rf"\b(?:INSERT\s+INTO|TRUNCATE\s+TABLE|MERGE(?:\s+INTO)?|UPDATE|INTO|CREATE\s+TABLE)\s+{_TABLE}",
    re.IGNORECASE,
)
_TSQL_READS = re.compile(rf"\b(?:FROM|JOIN|USING|APPLY)\s+{_TABLE}", re.IGNORECASE)
_SAS_WRITES = re.compile(
    rf"(?:^|;)\s*data\s+{_TABLE}|\bcreate\s+table\s+{_TABLE}|\bout\s*=\s*{_TABLE}", re.I | re.M
)
_SAS_READS = re.compile(rf"\b(?:set|merge|from|join)\s+{_TABLE}|\bdata\s*=\s*{_TABLE}", re.I)
_IGNORED_SCHEMAS = {"work", "etl", "tempdb", "sys"}


@dataclass
class DiscoveryResult:
    """
    Everything Discover found about one job.

    Attributes:
        discovery: The contract's record: status, flags, blocks, tables read and written.
        lineage: The verified lineage edges.
        traps: The trap findings.
        warnings: What the H1 reviewer must read before approving.
        blockers: What stops H1 being approved.
        stats: Counts for the evidence report, such as rule candidates.
    """

    job_id: str
    discovery: JobDiscovery
    lineage: list[LineageEdge]
    traps: list[TrapFinding]
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def tables_in(text: str, language: Language) -> tuple[list[str], list[str]]:
    """
    Find the tables a job's code reads and writes, outside comments.

    Work data sets, temp tables, ``etl.`` logging and system schemas are left out.

    Args:
        text: The code, with comments already blanked.
        language: Its language.

    Returns:
        The tables read and the tables written, canonical lower case, sorted.
    """
    writes_re, reads_re = (
        (_TSQL_WRITES, _TSQL_READS) if language is Language.TSQL else (_SAS_WRITES, _SAS_READS)
    )

    def found(pattern: re.Pattern[str]) -> set[str]:
        """
        Collect the canonical names one pattern matches.
        """
        names = set()
        for match in pattern.finditer(text):
            for group in match.groups():
                if not group:
                    continue
                name = group.replace("[", "").replace("]", "").lower()
                if name.split(".", 1)[0] not in _IGNORED_SCHEMAS:
                    names.add(name)
        return names

    writes = found(writes_re)
    reads = found(reads_re) - writes
    return sorted(reads), sorted(writes)


def discover_job(job: JobSpec, inventory: EstateInventory, gateway: Any | None) -> DiscoveryResult:
    """
    Run Discover on one job.

    Args:
        job: The job.
        inventory: The estate inventory.
        gateway: The Claude gateway, or None to run the deterministic passes only (the
            trap rules; no lineage).

    Returns:
        The job's discovery, lineage, traps and H1 warnings and blockers.
    """
    text = (REPO_ROOT / job.path).read_text(encoding="utf-8")
    blocks: list[Block] = split_code(text, job.language)
    code = "".join(b.code + "\n" for b in blocks)
    reads, writes = tables_in(code, job.language)
    inputs = input_schemas(inventory, job)
    outputs = {o.table: output_columns(inventory, o.table) for o in job.outputs}
    warnings: list[str] = []
    blockers: list[str] = []
    flags = []
    unparsed = [b for b in blocks if b.kind == "statement" and b.sqlglot_parsed is False]
    if unparsed:
        lines = ", ".join(f"{b.line_start}-{b.line_end}" for b in unparsed)
        flags.append(
            f"{len(unparsed)} statements sqlglot can't parse (lines {lines}); the translator "
            "works from the code itself"
        )
    expected_reads = set(job.inputs) | set(job.state_tables)
    expected_writes = {o.table for o in job.outputs}
    if extra := sorted(set(reads) - expected_reads - expected_writes):
        flags.append(f"the code reads {extra}, which jobs.yaml doesn't list as inputs")
    if missing := sorted(expected_writes - set(writes)):
        flags.append(f"the code doesn't visibly write {missing}")
    discovery = JobDiscovery(
        job_id=job.job_id,
        status="flagged" if flags else "parsed",
        flags=flags,
        blocks=[b.record(job.job_id) for b in blocks],
        reads=reads,
        writes=writes,
    )
    warnings += [f"flagged: {f}" for f in flags]

    traps, notes, n_candidates = scan(job, text, blocks, inputs, outputs, gateway)
    warnings += notes

    lineage: list[LineageEdge] = []
    traced_columns = 0
    if gateway is None:
        blockers.append("no lineage: the Lineage agent did not run")
    else:
        answer = gateway.ask(lineage_request(job, text, inputs, outputs), Stage.DISCOVER).output
        lineage, refused = verify_lineage(job, answer, inputs, outputs)
        warnings += [f"lineage edge refused: {r}" for r in refused]
        if not lineage:
            blockers.append("no verified lineage edges")
        if job.language is Language.TSQL:
            traced = sqlglot_lineage(blocks, inputs, outputs)
            traced_columns = len(traced)
            lineage, disagreements = cross_check(lineage, traced)
            warnings += disagreements
        if gaps := missing_lineage(lineage, outputs):
            warnings.append(f"no lineage for {len(gaps)} output columns: {gaps}")
        if answer.notes.strip():
            warnings.append(f"lineage agent notes: {answer.notes.strip()}")
    stats = {
        "blocks": len(blocks),
        "statements_unparsed": len(unparsed),
        "rule_candidates": n_candidates,
        "trap_findings": len(traps),
        "lineage_edges": len(lineage),
        "sqlglot_traced_columns": traced_columns,
        "sqlglot_agreeing_columns": len(
            {(e.output_table, e.output_column) for e in lineage if e.agrees_with_sqlglot}
        ),
    }
    return DiscoveryResult(job.job_id, discovery, lineage, traps, warnings, blockers, stats)
