"""
Suspected legacy defects: found in two ways, measured on golden data, decided by a person.

Plan §8.4 and steps 2.8 and 3.7. A suspected bug reaches the register in two ways:

- **Markers.** The Translator reproduces anything that looks like a bug and marks the line
  ``# LANSH-DEFECT``, listing each one in its answer.
- **The Defect reviewer agent** reads the legacy code and lists suspected bugs, each with an
  *impact query*: one Spark SQL ``SELECT`` over the job's inputs and its golden output that
  measures the rows (and the amount) the bug changes.

The impact query is Claude's SQL, so it gets the guardrails' SQL checks (one ``SELECT``, parsed
by sqlglot, none of the dangerous constructs) and runs read-only against temporary views:
``stg_claims`` for ``stg.claims``, and ``golden_rpt_claims_summary`` for the job's golden
output. A defect both sources report (overlapping lines) becomes one entry. The default
decision at H2 is *reproduce*; the alternative is *fix after cut-over*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from lansh.contracts import (
    ColumnSpec,
    DefectImpact,
    Effort,
    EstateInventory,
    JobSpec,
    Language,
    Stage,
    SuspectedDefect,
)
from lansh.discover.split import numbered
from lansh.generate.guardrails import parse_sql, scan_sql_text
from lansh.lakehouse import golden_table, read_staged, stage_inputs
from lansh.llm.answers import DefectMarkerAnswer, DefectReviewAnswer
from lansh.llm.request import ClaudeRequest

log = logging.getLogger(__name__)

DEFECT_SYSTEM = """\
You are the defect reviewer agent of LANSH, a factory that migrates legacy {language} jobs to \
PySpark. LANSH reproduces every legacy behaviour exactly, bugs included, and asks a person to \
decide what to do about each suspected bug, so finding them matters.

Read the job and list the places where the code most likely does not do what its author \
intended: wrong comparisons or boundaries, joins that multiply rows, gaps or overlaps in bands, \
wrong date columns, missing values handled wrongly, truncation, hard-coded constants that \
should vary. Ignore style, performance and things that are merely unusual. For each, write one \
Spark SQL SELECT over the views listed that measures the impact on the legacy output: it must \
return exactly one row with rows_affected (the output rows the bug changes) and, when the bug \
changes an amount, amount_affected (the total change, positive). Compare what the legacy output \
holds with what the intended logic would give. Use only the views and columns listed.
"""


def view_name(table: str, *, golden: bool = False) -> str:
    """
    Name the temporary view an impact query reads a table through.

    Args:
        table: A legacy table name, such as ``stg.claims``.
        golden: Whether it is the job's golden output.

    Returns:
        ``stg_claims``, or ``golden_rpt_claims_summary`` for a golden output.
    """
    name = table.replace(".", "_")
    return f"golden_{name}" if golden else name


def defect_request(
    job: JobSpec,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
    markers: list[DefectMarkerAnswer],
) -> ClaudeRequest[DefectReviewAnswer]:
    """
    Build the Defect reviewer agent's request.

    Args:
        job: The job.
        text: Its legacy code.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.
        markers: The suspected bugs the Translator marked, which the reviewer may confirm.

    Returns:
        The request.
    """
    views = [
        f"- {view_name(t)} ({t}): " + ", ".join(f"{c.name} {c.data_type}" for c in cols)
        for t, cols in inputs.items()
    ]
    views += [
        f"- {view_name(t, golden=True)} (the legacy output {t}): "
        + ", ".join(f"{c.name} {c.data_type}" for c in cols)
        for t, cols in outputs.items()
    ]
    marked = "\n".join(f"- {m.title} (lines {m.legacy_lines}): {m.what_it_does}" for m in markers)
    params = "; ".join(", ".join(f"{k}={v}" for k, v in i.params.items()) for i in job.invocations)
    prompt = (
        f"Job {job.job_id}: {job.name}. {job.description or ''}\nParameters: {params}.\n\n"
        f"Code:\n{numbered(text)}\n\nViews for impact queries:\n" + "\n".join(views) + "\n\n"
        f"Suspected bugs the translator marked while reproducing them:\n{marked or '(none)'}\n"
    )
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    return ClaudeRequest(
        agent="defect_reviewer",
        job_id=job.job_id,
        system_prompt=DEFECT_SYSTEM.format(language=language),
        prompt=prompt,
        response_model=DefectReviewAnswer,
        effort=Effort.HIGH.value,
    )


def measure(spark: Any, query: str, measured_on: str, amount_column: str | None) -> DefectImpact:
    """
    Run one impact query, after the guardrails' SQL checks.

    Args:
        spark: The Spark session, with the job's views registered.
        query: The impact query.
        measured_on: What it ran on, such as ``golden:T04``.
        amount_column: The output column whose amount the bug changes, if any.

    Returns:
        The measured impact.

    Raises:
        ValueError: If the query is refused or returns no row.
    """
    problems = scan_sql_text(query) + parse_sql(query)
    if problems:
        raise ValueError("impact query refused: " + "; ".join(problems))
    import sqlglot
    from sqlglot import exp

    trees = sqlglot.parse(query, read="spark")
    if len(trees) != 1 or not isinstance(trees[0], exp.Query):
        raise ValueError("impact query refused: it must be a single SELECT")
    row = spark.sql(query).first()
    if row is None:
        raise ValueError("the impact query returned no row")
    values = {k.lower(): v for k, v in row.asDict().items()}
    rows = int(values.get("rows_affected") or 0)
    amount = values.get("amount_affected")
    amount_text = None
    if amount is not None:
        # money to the cent; the sign is the direction, which the description already gives
        amount_text = format(
            abs(Decimal(str(amount))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"
        )
    return DefectImpact(
        rows_affected=max(rows, 0),
        amount_affected=amount_text,
        amount_column=amount_column,
        measured_on=measured_on,
        query=query,
    )


def register_views(
    spark: Any, inventory: EstateInventory, job: JobSpec, staging_dir: Any
) -> dict[str, str]:
    """
    Register the job's inputs and golden outputs as temporary views for impact queries.

    Args:
        spark: The Spark session.
        inventory: The estate inventory.
        job: The job.
        staging_dir: Where re-ordered inputs are staged.

    Returns:
        View name by table.
    """
    names = {}
    for table, staged in stage_inputs(inventory, job, "isolated", staging_dir).items():
        read_staged(spark, staged).createOrReplaceTempView(view_name(table))
        names[table] = view_name(table)
    for out in job.outputs:
        golden = golden_table(inventory, out.table)
        spark.read.parquet(str(golden.path)).createOrReplaceTempView(
            view_name(out.table, golden=True)
        )
        names[f"golden:{out.table}"] = view_name(out.table, golden=True)
    return names


@dataclass
class DefectList:
    """
    A job's suspected defects, measured where possible.

    Attributes:
        defects: The register entries for the job.
        notes: Impact queries that failed or were refused, for the H2 reviewer.
    """

    job_id: str
    defects: list[SuspectedDefect] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _overlaps(a: list[int], b: list[int]) -> bool:
    """
    Tell whether two sets of evidence lines touch the same stretch of code (within 3 lines).
    """
    if not a or not b:
        return False
    return min(a) <= max(b) + 3 and min(b) <= max(a) + 3


def review(
    job: JobSpec,
    inventory: EstateInventory,
    spark: Any,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
    markers: list[DefectMarkerAnswer],
    gateway: Any,
    staging_dir: Any,
) -> DefectList:
    """
    List a job's suspected defects from the markers and the reviewer, and measure each one.

    Args:
        job: The job.
        inventory: The estate inventory.
        spark: The Spark session for impact queries.
        text: The legacy code.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.
        markers: The Translator's marked defects.
        gateway: The Claude gateway.
        staging_dir: Where impact-query inputs are staged.

    Returns:
        The job's defects, reviewer findings first, then markers nobody else reported.
    """
    found = DefectList(job.job_id)
    answer = gateway.ask(defect_request(job, text, inputs, outputs, markers), Stage.DESIGN).output
    register_views(spark, inventory, job, staging_dir)
    lines_in_file = len(text.splitlines())
    used_markers: set[int] = set()
    for i, d in enumerate(answer.defects, 1):
        lines = sorted({n for n in d.evidence_lines if 1 <= n <= lines_in_file})
        confirming = [j for j, m in enumerate(markers) if _overlaps(lines, m.legacy_lines)]
        used_markers.update(confirming)
        impact = None
        try:
            impact = measure(spark, d.impact_query, f"golden:{job.job_id}", d.amount_column)
        except Exception as exc:  # Claude's query may not run; the defect still stands
            found.notes.append(
                f"{job.job_id}-D{i}: impact not measured: {str(exc).splitlines()[0][:200]}"
            )
        found.defects.append(
            SuspectedDefect(
                defect_id=f"{job.job_id}-D{i}",
                job_id=job.job_id,
                title=d.title,
                description=d.description
                + (" Also marked in the migrated code." if confirming else ""),
                intended_behaviour=d.intended_behaviour,
                evidence_lines=lines,
                impact_query=d.impact_query,
                impact=impact,
                source="llm",
                confidence=max([d.confidence, *([0.9] if confirming else [])]),
            )
        )
    for j, m in enumerate(markers):
        if j in used_markers:
            continue
        found.defects.append(
            SuspectedDefect(
                defect_id=f"{job.job_id}-D{len(found.defects) + 1}",
                job_id=job.job_id,
                title=m.title,
                description=m.what_it_does,
                intended_behaviour=m.intended,
                evidence_lines=sorted({n for n in m.legacy_lines if 1 <= n <= lines_in_file}),
                source="marker",
                confidence=0.6,
            )
        )
    return found
