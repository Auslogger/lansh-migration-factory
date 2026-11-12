"""
The evidence report: everything about one migrated job, for reviewers and the record (plan §8.10).

One :class:`~lansh.contracts.EvidenceReport` per job (``evidence.json``) and its Markdown
rendering (``evidence.md``): the legacy and migrated code with their hashes, the lineage,
the traps found, the contract and its tags, the suspected defects with their measured
impact and decisions, the flows of tagged columns, the reconciliation and heal history,
the tests, the Claude usage and every gate decision.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from lansh.config import REPO_ROOT
from lansh.contracts import EvidenceReport, LineageKind, PolicyKind, ReconStatus

_GATE_NAMES = {
    "H1": "Scope and lineage",
    "H2": "Contract and bug decisions",
    "H3": "Code review",
    "H4": "Evidence acceptance",
    "H5": "Cut-over",
}


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    """
    Render a Markdown table, escaping pipes in cells.
    """
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        out.append(
            "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in row) + " |"
        )
    return out


def render(report: EvidenceReport, *, migrated_code: str | None = None) -> str:
    """
    Render an evidence report as Markdown.

    Args:
        report: The report.
        migrated_code: The migrated module's source, shown beside the legacy code.

    Returns:
        The Markdown text.
    """
    from lansh.reconcile.job import report_markdown

    status = (
        "MATCH"
        if report.recon and all(r.status is ReconStatus.MATCH for r in report.recon)
        else (report.recon[-1].status.value if report.recon else "not reconciled")
    )
    if report.escalations:
        status = "ESCALATED"
    usage = report.llm_usage
    live = [u for u in usage if not u.replayed]
    lines = [
        f"# Evidence report: {report.job_id}",
        "",
        f"Generated {report.generated_at:%Y-%m-%d %H:%M} UTC. **Status: {status}.**",
        "",
        f"- Legacy code: `{report.legacy_path}` (SHA-256 `{report.legacy_sha256[:16]}…`)",
    ]
    if report.code:
        code = report.code
        model = f" ({code.model})" if code.model else ""
        lines.append(
            f"- Migrated module: `{code.module_path}` (SHA-256 `{code.code_sha256[:16]}…`), "
            f"written by {code.translator}{model}, heal attempt {code.attempt}"
        )
    passed_tests = sum(t.status == "pass" for t in report.tests)
    trap_ids = ", ".join(sorted({t.trap_id for t in report.traps}))
    tokens_in = sum(u.input_tokens + u.cache_read_tokens + u.cache_creation_tokens for u in usage)
    lines += [
        f"- Traps found: {len(report.traps)} ({trap_ids})",
        f"- Suspected defects: {len(report.defects)}; tests: {passed_tests}/{len(report.tests)} "
        f"passed; heal attempts: {len(report.heal)}",
        f"- Claude: {len(usage)} calls ({len(live)} live), {tokens_in:,} input and "
        f"{sum(u.output_tokens for u in usage):,} output tokens, "
        f"${sum(u.cost_usd_equivalent for u in usage):.2f} API-equivalent (not billed), "
        f"{sum(u.duration_ms for u in usage) / 1000:.0f} s of model time",
        "",
    ]

    lines += ["## Gate decisions", ""]
    lines += _table(
        ["Gate", "Outcome", "Reviewer", "Review time", "Flags", "Reason"],
        [
            [
                f"{g.gate.value} {_GATE_NAMES[g.gate.value]}",
                g.outcome.value,
                g.reviewer,
                f"{g.review_seconds:.0f} s",
                ", ".join(
                    f for f, on in (("fast", g.flagged_fast), ("spot-check", g.spot_check)) if on
                ),
                (g.reason or "")[:300],
            ]
            for g in report.gates
        ],
    )

    sandbox = [r for r in report.recon if not (r.run_id or "").endswith(":operate")]
    on_delta = [r for r in report.recon if (r.run_id or "").endswith(":operate")]
    lines += ["", "## Reconciliation (sandbox run, isolated inputs)", ""]
    for recon in sandbox:
        lines.append(report_markdown(recon))
    if on_delta:
        lines += ["## Operate (Delta lakehouse, reconciled again)", ""]
        for recon in on_delta:
            lines.append(report_markdown(recon))
    if report.heal:
        lines += ["## Heal history", ""]
        lines += _table(
            ["Attempt", "Kept", "Score before", "Score after", "Diagnosis"],
            [
                [h.attempt, h.kept, h.score_before, h.score_after, h.diagnosis[:400]]
                for h in report.heal
            ],
        )
        lines.append("")
    for esc in report.escalations:
        lines += [f"**Escalated** ({esc.reason}): {esc.diagnosis}", ""]

    lines += ["## Suspected legacy defects", ""]
    decisions = {d.defect_id: d for d in report.defect_decisions}
    lines += _table(
        ["Id", "Defect", "Lines", "Rows affected", "Amount", "Decision"],
        [
            [
                d.defect_id,
                d.title,
                f"{min(d.evidence_lines)}-{max(d.evidence_lines)}" if d.evidence_lines else "",
                d.impact.rows_affected if d.impact else "not measured",
                d.impact.amount_affected or "" if d.impact else "",
                f"{decisions[d.defect_id].decision.value} ({decisions[d.defect_id].decided_by})"
                if d.defect_id in decisions
                else "undecided",
            ]
            for d in report.defects
        ],
    )

    if report.flows:
        lines += ["", "## Flows of tagged columns", ""]
        flow_decisions = {f.flow_id: f for f in report.flow_decisions}
        lines += _table(
            ["Tag", "From", "Into", "Through", "Decision"],
            [
                [
                    f.tag.value,
                    f"{f.source.table}.{f.source.column}",
                    f"{f.output.table}.{f.output.column}",
                    ", ".join(f.job_ids),
                    flow_decisions[f.flow_id].decision
                    if f.flow_id in flow_decisions
                    else "undecided",
                ]
                for f in report.flows
            ],
        )

    lines += ["", "## Contract", ""]
    for c in report.contracts:
        lines.append(f"`{c.table}` ({c.layer.value}), from `{c.legacy_table}`. Grain: {c.grain}")
        lines.append(
            f"Key: {c.keys or 'none (multiset)'}; partitions: {c.partition_columns or 'none'}."
        )
        non_exact = [col for col in c.columns if col.policy.kind is not PolicyKind.EXACT]
        if non_exact:
            lines += _table(
                ["Column", "Policy", "Reason"],
                [[col.name, col.policy.kind.value, col.policy.reason] for col in non_exact],
            )
        else:
            lines.append("Every column is compared exactly.")
        tagged = [col for col in c.columns if col.tags]
        if tagged:
            lines.append(
                "Tagged: "
                + ", ".join(
                    f"{col.name} ({', '.join(t.value for t in col.tags)})" for col in tagged
                )
            )
        lines.append("")

    lines += ["## Traps found", ""]
    lines += _table(
        ["Trap", "Lines", "Found by", "Confidence", "Note"],
        [
            [
                t.trap_id,
                f"{t.line_start}-{t.line_end}",
                t.detector,
                f"{t.confidence:.2f}",
                (t.note or "")[:200],
            ]
            for t in report.traps
        ],
    )

    lines += ["", "## Lineage", ""]
    derives: dict[str, list[str]] = {}
    for e in report.lineage:
        if e.kind is LineageKind.DERIVES and e.output_column:
            source = (
                f"{e.input_table}.{e.input_column}"
                if e.input_kind == "column"
                else f"{e.input_kind} {e.input_column or ''}".strip()
            )
            derives.setdefault(e.output_column, []).append(source)
    agree = {e.output_column: e.agrees_with_sqlglot for e in report.lineage if e.output_column}
    lines += _table(
        ["Output column", "Derived from", "sqlglot agrees"],
        [
            [c, ", ".join(sorted(set(s))), {True: "yes", False: "no", None: "-"}[agree.get(c)]]
            for c, s in derives.items()
        ],
    )
    filters = sorted(
        {
            f"{e.input_table}.{e.input_column}"
            for e in report.lineage
            if e.kind is LineageKind.FILTERS and e.input_kind == "column"
        }
    )
    if filters:
        lines += ["", f"Rows are decided by: {', '.join(filters)}."]

    if report.tests:
        lines += ["", "## Tests", ""]
        lines += _table(
            ["Test", "Trap", "Expected from", "Status", "What it sets up"],
            [
                [t.test_id, t.trap_id or "", t.expected_source, t.status, t.description[:200]]
                for t in report.tests
            ],
        )

    if usage:
        lines += ["", "## Claude usage", ""]
        by_agent = Counter(u.agent for u in usage)
        lines += _table(
            ["Agent", "Calls", "Live", "Output tokens", "Model time", "API-equivalent"],
            [
                [
                    agent,
                    n,
                    sum(1 for u in usage if u.agent == agent and not u.replayed),
                    f"{sum(u.output_tokens for u in usage if u.agent == agent):,}",
                    f"{sum(u.duration_ms for u in usage if u.agent == agent) / 1000:.0f} s",
                    f"${sum(u.cost_usd_equivalent for u in usage if u.agent == agent):.3f}",
                ]
                for agent, n in sorted(by_agent.items())
            ],
        )

    legacy_code = (
        (REPO_ROOT / report.legacy_path).read_text(encoding="utf-8")
        if (REPO_ROOT / report.legacy_path).exists()
        else ""
    )
    lang = "sql" if report.legacy_path.endswith(".sql") else "sas"
    lines += [
        "",
        "## Code",
        "",
        "<details><summary>Legacy code</summary>",
        "",
        f"```{lang}",
        legacy_code.rstrip(),
        "```",
        "</details>",
        "",
    ]
    if migrated_code:
        lines += [
            "<details><summary>Migrated PySpark</summary>",
            "",
            "```python",
            migrated_code.rstrip(),
            "```",
            "</details>",
            "",
        ]
    return "\n".join(lines) + "\n"


def write(
    report: EvidenceReport, folder: Path, *, migrated_code: str | None = None
) -> tuple[Path, Path]:
    """
    Write a job's evidence report as JSON and Markdown.

    Args:
        report: The report.
        folder: The job's folder in the run.
        migrated_code: The migrated module's source.

    Returns:
        The JSON file and the Markdown file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "evidence.json"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path = folder / "evidence.md"
    md_path.write_text(render(report, migrated_code=migrated_code), encoding="utf-8")
    return json_path, md_path
