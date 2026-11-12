"""
The trap library and the trap scan (plan §8.3, Appendix A).

The library is ``trap_cards.yaml``: one :class:`~lansh.contracts.TrapCard` per known engine
difference. The scan finds where a job meets them, in two passes:

1. **Rules.** Each card's regexes run line by line over the code with comments blanked out.
   Hits in logging and declaration statements (``EXEC``, ``DECLARE``, ``PRINT``, ``THROW``)
   are skipped. A construct trap becomes one finding spanning its first to last hit; a
   semantic hit becomes a *candidate*.
2. **Claude.** The trap-scan agent sees the code, the cards, the input schemas and the
   candidates. It confirms the candidates that are real (a text comparison arms TSQL-01 only
   if the column is text), drops the rest, and adds subtle cases. Every finding it returns is
   checked: the trap id must be a card of the job's language and the lines must be in the file;
   the snippet is taken from the file, never from the answer.

Without a recorded or live answer the scan falls back to the rules alone, every candidate kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lansh.contracts import (
    ColumnSpec,
    DiffSignatureKind,
    Effort,
    JobSpec,
    Language,
    Stage,
    TrapCard,
    TrapFinding,
    TrapKind,
)
from lansh.discover.split import Block, numbered
from lansh.estate.inventory import parse_yaml
from lansh.llm.answers import TrapScanAnswer
from lansh.llm.request import ClaudeRequest

CARDS_PATH = Path(__file__).with_name("trap_cards.yaml")

# statements that log, declare or raise: their string comparisons are parameters, not data
_SKIPPED_STATEMENTS = re.compile(r"^\s*(EXEC|EXECUTE|DECLARE|PRINT|RAISERROR|THROW)\b", re.I)
_SNIPPET_CHARS = 300


### The library


@cache
def load_cards(path: Path = CARDS_PATH) -> dict[str, TrapCard]:
    """
    Read the trap library.

    Args:
        path: The cards file.

    Returns:
        Every card, by trap id, in file order.

    Raises:
        pydantic.ValidationError: If a card doesn't fit :class:`TrapCard`.
        ValueError: If two cards share an id.
    """
    data = parse_yaml(path.read_text(encoding="utf-8"))
    cards: dict[str, TrapCard] = {}
    for raw in data["cards"]:
        card = TrapCard.model_validate(raw)
        if card.trap_id in cards:
            raise ValueError(f"trap card {card.trap_id} is defined twice")
        cards[card.trap_id] = card
    return cards


def cards_for(language: Language) -> list[TrapCard]:
    """
    List the cards for one language.

    Args:
        language: T-SQL or SAS.

    Returns:
        The cards in library order.
    """
    return [c for c in load_cards().values() if c.language is language]


def traps_for(language: Language) -> dict[DiffSignatureKind, list[str]]:
    """
    Map each diff signature to the cards of a language that leave it.

    Args:
        language: T-SQL or SAS.

    Returns:
        Trap ids by signature kind.
    """
    out: dict[DiffSignatureKind, list[str]] = {}
    for card in cards_for(language):
        for kind in card.diff_signatures:
            out.setdefault(kind, []).append(card.trap_id)
    return out


def signature_lookup(language: Language):
    """
    Give the function reconciliation uses to link a signature to the cards that leave it.

    Args:
        language: The job's language.

    Returns:
        A function from a signature kind to trap ids.
    """
    table = traps_for(language)
    return lambda kind: list(table.get(kind, []))


def allowed_literals() -> set[str]:
    """
    Every constant a card says a correct fix may introduce, for the literal check (plan §8.5).
    """
    return {lit for card in load_cards().values() for lit in card.allowed_literals}


### Pass 1: rules


@dataclass(frozen=True)
class Candidate:
    """
    A rule's hit on one line, before the trap-scan agent has judged it.
    """

    trap_id: str
    line: int
    block: int
    rule: str


def _snippet(lines: list[str], start: int, end: int) -> str:
    """
    Give lines ``start`` to ``end`` (1-based, inclusive) of the file, cut to 300 characters.
    """
    text = "\n".join(lines[start - 1 : end]).strip()
    return text if len(text) <= _SNIPPET_CHARS else text[: _SNIPPET_CHARS - 1] + "…"


def rule_scan(blocks: list[Block], language: Language) -> list[Candidate]:
    """
    Run every card's regex rules over each block's comment-blanked code, line by line.

    Args:
        blocks: The job's blocks, from :mod:`lansh.discover.split`.
        language: The job's language.

    Returns:
        One candidate per card, rule and line that matched, in line order.
    """
    rules = [
        (card.trap_id, rule.description, re.compile(rule.pattern, re.IGNORECASE | re.MULTILINE))
        for card in cards_for(language)
        for rule in card.detection
        if rule.kind == "regex" and rule.pattern
    ]
    found: dict[tuple[str, int], Candidate] = {}
    for block in blocks:
        if language is Language.TSQL and _SKIPPED_STATEMENTS.match(block.code):
            continue
        for offset, line in enumerate(block.code.split("\n")):
            number = block.line_start + offset
            for trap_id, description, pattern in rules:
                if pattern.search(line) and (trap_id, number) not in found:
                    found[(trap_id, number)] = Candidate(trap_id, number, block.index, description)
    return sorted(found.values(), key=lambda c: (c.line, c.trap_id))


def rule_findings(job_id: str, text: str, candidates: Iterable[Candidate]) -> list[TrapFinding]:
    """
    Turn rule hits into findings: one per construct trap, one per semantic hit.

    A construct trap (temp tables, cursors, MERGE...) is reported once, spanning its first to
    last hit, because it shapes the whole job. Semantic hits are reported line by line, with a
    rule's confidence of 0.5.

    Args:
        job_id: The job.
        text: The legacy code, for snippets.
        candidates: The rule hits.

    Returns:
        The findings, in line order.
    """
    lines = text.splitlines()
    cards = load_cards()
    by_trap: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_trap.setdefault(c.trap_id, []).append(c)
    out = []
    for trap_id, hits in by_trap.items():
        if cards[trap_id].kind is TrapKind.CONSTRUCT:
            start, end = min(h.line for h in hits), max(h.line for h in hits)
            spans = [(start, end, hits[0].rule)]
        else:
            spans = [(h.line, h.line, h.rule) for h in hits]
        for start, end, rule in spans:
            out.append(
                TrapFinding(
                    job_id=job_id,
                    trap_id=trap_id,
                    line_start=start,
                    line_end=end,
                    snippet=_snippet(lines, start, end),
                    detector="rule",
                    confidence=0.5,
                    note=rule,
                )
            )
    return sorted(out, key=lambda f: (f.line_start, f.trap_id))


### Pass 2: the trap-scan agent

TRAP_SCAN_SYSTEM = """\
You are the trap-scan agent of LANSH, a factory that migrates legacy {language} jobs to \
PySpark 4.2 and must reproduce every legacy output exactly, bugs included.

A trap is a place where the legacy engine and Spark behave differently. A semantic trap \
changes the result if the code is translated naively (a case-insensitive text comparison, \
integer division, a NULL concatenation). A construct trap is a construct Spark lacks (a \
cursor, a temp table, a MERGE, a macro loop) that changes only the shape of the code.

You get the job's code with line numbers, the schemas of its inputs and output, the trap \
cards (the known engine differences) and candidate findings from deterministic rules.

Return every trap occurrence in this job that a translator must handle:
- confirm the candidates that are real, using the schemas: a comparison arms a text trap \
only if the column is text; integer division only if both operands are integers;
- leave out candidates that are not real (they are dropped);
- add occurrences the rules missed, such as joins on text columns, NULL propagation in \
loops, or variables whose length a first assignment fixes;
- report each occurrence at the narrowest line range that shows it, and the same trap at \
different places separately; include latent occurrences that today's data may not trigger;
- use only trap ids from the cards; set confidence to how sure you are that it is real.
"""


def _schema_text(schemas: dict[str, list[ColumnSpec]]) -> str:
    """
    List tables and their columns with types and legacy types, one table per line.
    """
    return "\n".join(
        f"- {table}: " + ", ".join(f"{c.name} {c.legacy_type or c.data_type}" for c in columns)
        for table, columns in schemas.items()
    )


def _cards_text(language: Language) -> str:
    """
    Describe the language's cards compactly for a prompt.
    """
    return "\n".join(
        f"- {c.trap_id} ({c.kind.value}) {c.title}. Legacy: {' '.join(c.legacy_behaviour.split())} "
        f"Spark: {' '.join(c.spark_behaviour.split())}"
        for c in cards_for(language)
    )


def trap_scan_request(
    job: JobSpec,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
    candidates: list[Candidate],
) -> ClaudeRequest[TrapScanAnswer]:
    """
    Build the trap-scan agent's request for one job.

    Args:
        job: The job.
        text: Its legacy code.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.
        candidates: The rule hits to confirm or reject.

    Returns:
        The request; its hash finds a recorded answer.
    """
    lines = text.splitlines()
    shown = "\n".join(
        f"- {c.trap_id} line {c.line}: {lines[c.line - 1].strip()[:160]}" for c in candidates
    )
    prompt = (
        f"Job {job.job_id}: {job.name} ({job.language.value}), file {job.path}.\n"
        f"{job.description or ''}\n\n"
        f"Code:\n{numbered(text)}\n\n"
        f"Input tables:\n{_schema_text(inputs)}\n\n"
        f"Output tables:\n{_schema_text(outputs)}\n\n"
        f"Trap cards:\n{_cards_text(job.language)}\n\n"
        f"Rule candidates:\n{shown or '(none)'}\n"
    )
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    return ClaudeRequest(
        agent="trap_scan",
        job_id=job.job_id,
        system_prompt=TRAP_SCAN_SYSTEM.format(language=language),
        prompt=prompt,
        response_model=TrapScanAnswer,
        effort=Effort.MEDIUM.value,
    )


def verify_findings(
    job: JobSpec, text: str, answer: TrapScanAnswer
) -> tuple[list[TrapFinding], list[str]]:
    """
    Check the agent's findings and turn them into records, with snippets from the file.

    Args:
        job: The job.
        text: Its legacy code.
        answer: The trap-scan agent's answer.

    Returns:
        The accepted findings, and one message per finding refused (unknown trap id, a card
        of the other language, or lines outside the file).
    """
    lines = text.splitlines()
    known = {c.trap_id for c in cards_for(job.language)}
    accepted, refused = [], []
    for f in answer.findings:
        if f.trap_id not in known:
            refused.append(f"{f.trap_id} at {f.line_start}: not a {job.language.value} trap card")
            continue
        if not 1 <= f.line_start <= f.line_end <= len(lines):
            refused.append(f"{f.trap_id} at {f.line_start}-{f.line_end}: lines outside the file")
            continue
        accepted.append(
            TrapFinding(
                job_id=job.job_id,
                trap_id=f.trap_id,
                line_start=f.line_start,
                line_end=f.line_end,
                snippet=_snippet(lines, f.line_start, f.line_end),
                detector="llm",
                confidence=f.confidence,
                note=f.note,
            )
        )
    return accepted, refused


def merge_findings(rules: list[TrapFinding], agent: list[TrapFinding]) -> list[TrapFinding]:
    """
    Combine the two passes: the agent's findings, plus rule findings for construct traps it missed.

    A semantic rule hit the agent left out was rejected by it and is dropped. A construct trap
    the rules found (they are reliable for constructs) is kept unless the agent reported the
    same trap at overlapping lines.

    Args:
        rules: Findings from the rules alone.
        agent: The agent's verified findings.

    Returns:
        The findings, in line order, without exact duplicates.
    """
    cards = load_cards()
    out = list(agent)
    for f in rules:
        if cards[f.trap_id].kind is not TrapKind.CONSTRUCT:
            continue
        overlaps = any(
            a.trap_id == f.trap_id and a.line_start <= f.line_end and f.line_start <= a.line_end
            for a in agent
        )
        if not overlaps:
            out.append(f)
    unique = {(f.trap_id, f.line_start, f.line_end): f for f in out}
    return sorted(unique.values(), key=lambda f: (f.line_start, f.trap_id))


def scan(
    job: JobSpec,
    text: str,
    blocks: list[Block],
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
    gateway: object | None,
) -> tuple[list[TrapFinding], list[str], int]:
    """
    Run both passes of the trap scan on one job.

    Args:
        job: The job.
        text: Its legacy code.
        blocks: Its blocks.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.
        gateway: A :class:`~lansh.llm.gateway.ClaudeGateway`, or None for the rules alone.

    Returns:
        The findings, notes for the H1 reviewer (refused agent findings, or that only the
        rules ran), and the number of rule candidates.
    """
    candidates = rule_scan(blocks, job.language)
    rules = rule_findings(job.job_id, text, candidates)
    if gateway is None:
        return rules, ["trap scan: rules only (no trap-scan agent)"], len(candidates)
    semantic = [c for c in candidates if load_cards()[c.trap_id].kind is TrapKind.SEMANTIC]
    request = trap_scan_request(job, text, inputs, outputs, semantic)
    result = gateway.ask(request, Stage.DISCOVER)  # type: ignore[attr-defined]
    agent, refused = verify_findings(job, text, result.output)
    notes = [f"trap scan refused: {r}" for r in refused]
    return merge_findings(rules, agent), notes, len(candidates)
