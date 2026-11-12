"""
The agents' answer models: what each LANSH agent returns from Claude (plan §6.6, §8.2).

Agents never answer in contract records (``lansh.contracts``): those carry factory-owned
fields such as ids, hashes, ``verified`` flags and decisions. Each agent answers in one of
these small models instead, and factory code turns the answer into records, checking it on
the way: every column it names must exist, every trap id must be a known card, every line
must be in the file.

**Don't edit these models casually.** Each model's JSON schema, docstrings and field
descriptions included, is part of the hash that finds a recorded answer, so a change makes
every answer recorded with the old model unreachable (the AGENTS.md "Code style" rule). Patterns
use ASCII classes only, so Pydantic and the CLI's JSON Schema validator agree.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TrapIdText = Annotated[str, StringConstraints(pattern=r"^(TSQL|SAS)-[0-9]{2}$")]
"""A trap card id, such as ``TSQL-01``."""


class Answer(BaseModel):
    """Base of every answer model: unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")


### Discover: lineage


class LineageEdgeAnswer(Answer):
    """One way an input influences an output of the job."""

    output_table: str = Field(
        description="The job's output table, schema-qualified, e.g. rpt.claims_summary."
    )
    output_column: str | None = Field(
        description="The output column the edge feeds; null for an edge that decides which "
        "rows appear (a filter) or which row survives (a ranking)."
    )
    input_kind: Literal["column", "parameter", "constant", "generated"] = Field(
        description="column: a column of one of the job's input tables; parameter: a job "
        "parameter such as @AsOfDate; constant: a literal in the code; generated: a value the "
        "engine makes, such as an IDENTITY key or a load timestamp."
    )
    input_table: str | None = Field(
        description="For a column edge, the job INPUT table it belongs to, schema-qualified "
        "(trace through temp tables and work data sets back to the job's inputs); else null."
    )
    input_column: str | None = Field(
        description="For a column edge, the input column; for a parameter edge, the parameter "
        "name such as @AsOfDate; else null."
    )
    kind: Literal["derives", "filters", "ranks"] = Field(
        description="derives: the input's value flows into the output column; filters: it "
        "decides which rows appear (WHERE, JOIN ON, HAVING, IN=, subsetting IF); ranks: it "
        "decides which row survives (ORDER BY in a ROW_NUMBER, NODUPKEY, FIRST./LAST.)."
    )
    transform: str = Field(description="A few words on the logic, e.g. 'UPPER(RTRIM(lob_code))'.")
    lines: list[int] = Field(description="Line numbers in the legacy file that show the edge.")
    confidence: float = Field(ge=0.0, le=1.0)


class LineageAnswer(Answer):
    """Column-level lineage of one legacy job, traced back to the job's input tables."""

    edges: list[LineageEdgeAnswer] = Field(
        description="Every derives edge for every output column, plus the filters and ranks "
        "that decide the output's rows."
    )
    notes: str = Field(
        description="Anything a reviewer should know, such as a column whose "
        "lineage is uncertain. Empty when there is nothing to add."
    )


### Discover: the trap scan's subtle cases


class TrapFindingAnswer(Answer):
    """One place where a known engine difference (a trap card) affects this job."""

    trap_id: TrapIdText
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    note: str = Field(description="Why the trap matters at these lines, in one or two sentences.")


class TrapScanAnswer(Answer):
    """The traps a careful reviewer finds in the job, beyond those the rules already found."""

    findings: list[TrapFindingAnswer]


### Generate: the translation


class DefectMarkerAnswer(Answer):
    """A suspected legacy bug that the translation reproduces on purpose."""

    title: str = Field(description="A short name for the suspected bug.")
    legacy_lines: list[int] = Field(description="Lines of the legacy file that show it.")
    what_it_does: str = Field(description="What the legacy code actually does.")
    intended: str = Field(description="What it was probably meant to do.")


class TranslationAnswer(Answer):
    """A migrated job module in the LANSH job template, reproducing the legacy job exactly."""

    code: str = Field(
        description="The complete Python module: docstring, imports, and "
        "run(spark, inputs, params) returning a dict of output DataFrames."
    )
    traps_handled: list[str] = Field(
        description="Trap card ids the code handles deliberately, e.g. ['TSQL-01']."
    )
    defects: list[DefectMarkerAnswer] = Field(
        description="Every suspected legacy bug the code reproduces, each also marked with a "
        "'# LANSH-DEFECT' comment on the line that reproduces it."
    )
    notes: str = Field(description="Anything a code reviewer should check. Empty if nothing.")


### Reconcile: diagnose and fix


class FixAnswer(Answer):
    """A diagnosis of a failed reconciliation and a corrected module."""

    diagnosis: str = Field(description="What makes the migrated output differ, and why.")
    suspected_traps: list[str] = Field(description="Trap card ids behind the differences.")
    patch_summary: str = Field(description="What the corrected code changes.")
    code: str = Field(description="The complete corrected module, not a diff.")


### Generate: trap-focused tests


class TestTableAnswer(Answer):
    """Rows of one input table for a test, every value written as text."""

    __test__ = False  # not a pytest test class

    table: str = Field(description="The input table, schema-qualified, e.g. stg.claims.")
    rows: list[dict[str, str | None]] = Field(
        description="5 to 20 rows. Each row maps column names to values as text: dates as "
        "YYYY-MM-DD, numbers as plain decimals, null for NULL. Columns left out are NULL."
    )


class TestCaseAnswer(Answer):
    """A small input set that shows one trap changing the job's result."""

    __test__ = False  # not a pytest test class

    trap_id: TrapIdText
    description: str = Field(
        description="What the rows set up, and what a naive translation would get wrong on them."
    )
    tables: list[TestTableAnswer] = Field(
        description="Rows for every input table the job needs to produce a non-empty result."
    )


class TestAuthorAnswer(Answer):
    """Test inputs, one case per semantic trap found in the job."""

    __test__ = False  # not a pytest test class

    cases: list[TestCaseAnswer]


### Design: suspected legacy bugs


class DefectAnswer(Answer):
    """A suspected bug in the legacy logic, with a query that measures its impact."""

    title: str = Field(description="A short name for the suspected bug.")
    description: str = Field(description="What the legacy code does.")
    intended_behaviour: str = Field(description="What it was probably meant to do.")
    evidence_lines: list[int] = Field(description="Lines of the legacy file that show the bug.")
    impact_query: str = Field(
        description="One Spark SQL SELECT over the views listed in the prompt that returns "
        "exactly one row with rows_affected (the output rows the bug changes) and, where the "
        "bug changes an amount, amount_affected (the total change)."
    )
    amount_column: str | None = Field(
        description="The output column whose amount the bug changes; null if none."
    )
    confidence: float = Field(ge=0.0, le=1.0)


class DefectReviewAnswer(Answer):
    """The suspected legacy bugs in one job; an empty list when it looks correct."""

    defects: list[DefectAnswer]


### Design: the contract's descriptions


class ContractAnswer(Answer):
    """The parts of a data contract that need judgement: what a row is, and why."""

    grain: str = Field(description="What one row of the output represents, in one sentence.")
    keys: list[str] = Field(
        description="The output's business key: the smallest set of columns that identifies a "
        "row. Choose from the candidate keys listed in the prompt."
    )
    partition_columns: list[str] = Field(
        description="At most two low-cardinality columns worth counting rows by, e.g. lob_code; "
        "may be empty."
    )
    column_notes: dict[str, str] = Field(
        description="Optional one-line descriptions of non-obvious output columns, by name."
    )


ANSWER_MODELS: tuple[type[Answer], ...] = (
    LineageAnswer,
    TrapScanAnswer,
    TranslationAnswer,
    FixAnswer,
    TestAuthorAnswer,
    DefectReviewAnswer,
    ContractAnswer,
)
"""Every top-level answer model, for schema tests."""
