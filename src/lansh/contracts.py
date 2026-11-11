"""
Shared Pydantic v2 models: the contracts every part of LANSH uses (plan §8.1).

These models are **frozen at gate G1**. Changing one afterwards is a team decision
(AGENTS.md), because the gateway, the estate tooling, reconciliation, the gate log and the
evidence reports all exchange them.

Conventions:
- Every model forbids unknown fields, so typos in YAML fail loudly.
- **Records are not LLM answers.** These models carry factory-owned fields (ids, hashes,
  ``verified``, decisions). Agents answer in their own small models in ``lansh.llm.answers``,
  and factory code turns those answers into these records. Never pass a contract model to
  the Claude gateway as a response schema; it refuses any model in ``CONTRACT_MODELS``.
- Text is never stripped: trailing spaces are data in this project.
- Data values that are numbers (totals, impacts, metric values, test rows) are carried as
  canonical decimal text, never as floats.
- Identifiers compare case-insensitively, as in SQL Server, SAS and Spark. Table names are
  canonicalised to lower case (``[RPT].[Claims_Summary]`` -> ``rpt.claims_summary``); column
  names keep their spelling but are matched with ``casefold()``.
- Every timestamp is timezone-aware; store UTC.
- Patterns use ASCII classes only (``[0-9]``, not ``\\d``), so Pydantic and the JSON Schema
  validator in the ``claude`` CLI agree.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

### Shared building blocks


class Model(BaseModel):
    """
    Base class of every contract model: unknown fields are refused.

    Assignments are validated as well, and a refused one leaves the record exactly as it
    was, its value and ``model_fields_set`` included, whether a field's own constraints or a
    model validator refused it.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # hidden from type checkers, as Pydantic hides its own, so a misspelt field stays an error
    if not TYPE_CHECKING:

        def __setattr__(self, name: str, value: Any) -> None:
            """
            Assign an attribute, putting the record back as it was if the assignment fails.

            Pydantic stores the new value before it runs the model validators, so a value
            they refuse would otherwise stay (measured on Pydantic 2.14).
            """
            fields, fields_set = dict(self.__dict__), set(self.__pydantic_fields_set__)
            try:
                super().__setattr__(name, value)
            except Exception:
                object.__setattr__(self, "__dict__", fields)
                object.__setattr__(self, "__pydantic_fields_set__", fields_set)
                raise


def _canonical_table(value: Any) -> Any:
    """
    Canonicalise a table name: drop brackets, quotes and backticks, then lower-case it.

    Surrounding whitespace goes too, since a table name is an identifier, not data. A value
    that isn't a string passes through for Pydantic to refuse.
    """
    if isinstance(value, str):
        text = value.strip()
        for char in '[]"`':
            text = text.replace(char, "")
        return text.lower()
    return value


JobId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}[0-9]{1,3}$")]
"""A job identifier such as ``T04``, ``S01`` or ``X1``."""

TrapId = Annotated[str, StringConstraints(pattern=r"^(TSQL|SAS)-[0-9]{2}$")]
"""A trap-card identifier such as ``TSQL-01`` or ``SAS-11``."""

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lower-case hex SHA-256 digest."""

TableName = Annotated[
    str,
    BeforeValidator(_canonical_table),
    StringConstraints(pattern=r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$"),
]
"""A schema-qualified table name in lower case: ``stg.claims``, ``rpt.claims_summary``."""

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$")]
"""A number carried as canonical text so it never passes through a float."""

_LOGICAL_TYPE = re.compile(
    r"^(boolean|tinyint|smallint|int|bigint|float|double|string|binary|date|timestamp|"
    r"timestamp_ntz|decimal\(([0-9]{1,2}),([0-9]{1,2})\))$"
)
"""Logical (Spark-side) column types; groups 2 and 3 are a decimal's precision and scale."""


def _fold(name: str) -> str:
    """
    Fold an identifier so that names compare case-insensitively.
    """
    return name.casefold()


def _check_unique(names: list[str], what: str) -> None:
    """
    Refuse duplicate names, comparing them case-insensitively.

    Args:
        names: Names to check, in their original spelling.
        what: What the names are, for the error message, such as ``"column names"``.

    Raises:
        ValueError: If a name occurs twice. The message lists every spelling of it.
    """
    counts = Counter(_fold(n) for n in names)
    dupes = sorted(n for n in names if counts[_fold(n)] > 1)
    if dupes:
        raise ValueError(f"duplicate {what} (names compare case-insensitively): {dupes}")


def _missing(wanted: list[str], available: list[str]) -> list[str]:
    """
    List the wanted names that aren't available, comparing case-insensitively.

    The result keeps the order and spelling of ``wanted``.
    """
    have = {_fold(a) for a in available}
    return [w for w in wanted if _fold(w) not in have]


class Language(StrEnum):
    """
    The language a legacy job is written in.
    """

    TSQL = "tsql"
    SAS = "sas"


class Layer(StrEnum):
    """
    Medallion layer of a lakehouse table (plan §6.4).

    Bronze holds raw data as it arrived, silver cleaned and standardised data, and gold
    business-ready tables.
    """

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class ColumnTag(StrEnum):
    """
    Data-protection tags carried from the data dictionary into contracts.

    Every path from a tagged column into an output is shown at H2 for a human decision.
    ``pii`` columns are also masked in any sample rows Claude sees.
    """

    PII = "pii"
    PROTECTED = "protected"


class Stage(StrEnum):
    """
    The five product stages (plan §6.3).
    """

    DISCOVER = "discover"
    DESIGN = "design"
    GENERATE = "generate"
    RECONCILE = "reconcile"
    OPERATE = "operate"


class Gate(StrEnum):
    """
    The human gate that closes each stage.

    ``GATE_STAGE`` gives the stage each gate closes.
    """

    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"
    H5 = "H5"


GATE_STAGE: dict[Gate, Stage] = {
    Gate.H1: Stage.DISCOVER,
    Gate.H2: Stage.DESIGN,
    Gate.H3: Stage.GENERATE,
    Gate.H4: Stage.RECONCILE,
    Gate.H5: Stage.OPERATE,
}


class Approach(StrEnum):
    """
    Who or what produced a migrated job: LANSH, or a comparison run (plan §9.5).

    The comparison runs are sqlglot alone, one-shot Claude (no trap cards, no healing) and
    the manual baseline, migrated by hand without AI (plan §9.1).
    """

    LANSH = "lansh"
    SQLGLOT_ONLY = "sqlglot_only"
    ONESHOT_CLAUDE = "oneshot_claude"
    MANUAL = "manual"


class Effort(StrEnum):
    """
    Claude Code ``--effort`` levels.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ColumnRef(Model):
    """
    One column of one table.
    """

    table: TableName
    column: str = Field(min_length=1)


def _same_column(a: ColumnRef, b: ColumnRef) -> bool:
    """
    Tell whether two references name the same column, comparing column names case-insensitively.
    """
    return a.table == b.table and _fold(a.column) == _fold(b.column)


### Schemas and the estate inventory (estate/jobs.yaml)


class ColumnSpec(Model):
    """
    One column: its logical (Spark-side) type, its legacy type and its tags.
    """

    name: str = Field(min_length=1)
    data_type: str = Field(
        description="Logical type: int, bigint, decimal(p,s), double, string, date, "
        "timestamp_ntz, boolean, ..."
    )
    legacy_type: str | None = Field(
        default=None, description="Type in the legacy engine, e.g. VARCHAR(20) or SAS 'num 8'."
    )
    nullable: bool = True
    max_length: int | None = Field(default=None, ge=1, description="Legacy character length.")
    tags: list[ColumnTag] = Field(default_factory=list)
    description: str | None = None

    @model_validator(mode="after")
    def _check(self) -> ColumnSpec:
        """
        Check the logical type, a decimal's precision and scale, and that tags are unique.
        """
        match = _LOGICAL_TYPE.match(self.data_type)
        if not match:
            raise ValueError(f"unknown logical type {self.data_type!r}")
        if match.group(2):
            precision, scale = int(match.group(2)), int(match.group(3))
            if not 1 <= precision <= 38 or scale > precision:
                raise ValueError(
                    f"decimal needs 1 <= precision <= 38 and scale <= precision: {self.data_type!r}"
                )
        _check_unique([t.value for t in self.tags], "tags")
        return self


class TableSchema(Model):
    """
    A table's columns, key and (for inputs) the column recording original row order.
    """

    name: TableName
    layer: Layer | None = None
    description: str | None = None
    columns: list[ColumnSpec] = Field(min_length=1)
    primary_key: list[str] = Field(default_factory=list)
    row_order_column: str | None = Field(
        default=None, description="Column recording the original row order, e.g. _row_seq."
    )

    @model_validator(mode="after")
    def _check(self) -> TableSchema:
        """
        Check that column names are unique and that the key and row-order columns exist.
        """
        names = [c.name for c in self.columns]
        _check_unique(names, "column names")
        missing = _missing(self.primary_key, names)
        if missing:
            raise ValueError(f"primary key columns not in table: {missing}")
        if self.row_order_column and _missing([self.row_order_column], names):
            raise ValueError(f"row order column {self.row_order_column!r} not in table")
        return self

    def column(self, name: str) -> ColumnSpec:
        """
        Look up a column by name, ignoring case.

        Args:
            name: Column name, in any case.

        Returns:
            The column's spec.

        Raises:
            KeyError: If the table has no such column.
        """
        for col in self.columns:
            if _fold(col.name) == _fold(name):
                return col
        raise KeyError(f"{self.name} has no column {name!r}")

    def tagged(self, tag: ColumnTag) -> list[str]:
        """
        Name the columns that carry a tag.

        Args:
            tag: ``pii`` or ``protected``.

        Returns:
            The tagged columns' names, in table order.
        """
        return [c.name for c in self.columns if tag in c.tags]


class JobInvocation(Model):
    """
    One call of a legacy job, with its parameters.

    Most jobs have one. T02 has two, one per batch.

    Attributes:
        label: A name for the call, such as ``batch 1``.
        params: Parameter values by name, such as ``AsOfDate``.
    """

    label: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class JobOutput(Model):
    """
    A table a legacy job writes.
    """

    table: TableName
    volatile_columns: list[str] = Field(
        default_factory=list,
        description="Columns that change on every run, such as load timestamps. They are "
        "left out of the content hash that `make legacy-verify` checks.",
    )


class JobSpec(Model):
    """
    One legacy job, as listed in the estate inventory.

    Attributes:
        tier: The scope tier the job belongs to (plan §13).
        holdout: True for a sealed held-out job (plan §7.4).
        origin: Who wrote the job: the team, the isolated agent that writes the held-out
            jobs, or EXL.
    """

    job_id: JobId
    name: str = Field(min_length=1, description="Procedure or program name.")
    language: Language
    path: str = Field(min_length=1, description="Repository-relative path to the legacy code.")
    entrypoint: str | None = Field(
        default=None, description="Procedure to EXEC for T-SQL jobs; None for SAS programs."
    )
    description: str | None = None
    invocations: list[JobInvocation] = Field(
        min_length=1, description="Calls in run order. Stateful jobs carry state between them."
    )
    inputs: list[TableName] = Field(min_length=1)
    outputs: list[JobOutput] = Field(min_length=1)
    state_tables: list[TableName] = Field(
        default_factory=list,
        description="Outputs the job reads back as its previous state (T02's type-2 history). "
        "The first invocation starts from an empty state; each later one sees the previous "
        "invocation's output. Never also listed in inputs.",
    )
    tier: Literal[1, 2, 3] = 1
    holdout: bool = False
    origin: Literal["team", "isolated_agent", "exl"] = "team"

    @model_validator(mode="after")
    def _check(self) -> JobSpec:
        """
        Check the entrypoint, duplicate tables, the state tables and SAS name limits.
        """
        if self.language is Language.TSQL and not self.entrypoint:
            raise ValueError(f"{self.job_id}: T-SQL jobs need an entrypoint procedure")
        _check_unique(list(self.inputs), "inputs")
        outputs = [o.table for o in self.outputs]
        _check_unique(outputs, "outputs")
        if bad := [t for t in self.state_tables if t not in outputs]:
            raise ValueError(f"{self.job_id}: state tables must be outputs: {bad}")
        if bad := [t for t in self.state_tables if t in self.inputs]:
            raise ValueError(f"{self.job_id}: state tables are not inputs: {bad}")
        if self.language is Language.SAS:
            for table in [*self.inputs, *outputs]:
                libref, member = table.split(".", 1)
                if len(libref) > 8 or len(member) > 32:
                    raise ValueError(f"{self.job_id}: {table} breaks SAS name limits (8/32)")
        return self


class EstateInventory(Model):
    """
    The legacy estate inventory: the format of ``estate/jobs.yaml``.

    Every table has a single writer, one job or the source extracts, except the audit
    tables. Jobs read only sources, audit tables and jobs' outputs, and no jobs depend on
    each other in a cycle.

    Attributes:
        as_of_date: The reporting date every job runs as of.
        legacy_database: The SQL Server database the T-SQL jobs run in.
    """

    version: Literal[1] = 1
    as_of_date: date
    legacy_database: str = Field(min_length=1)
    sources: list[TableName] = Field(min_length=1, description="Source (bronze) tables.")
    audit_tables: list[TableName] = Field(
        default_factory=list,
        description="Tables every job writes to (e.g. etl.etl_log): exempt from the "
        "single-writer rule and never reconciled.",
    )
    jobs: list[JobSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> EstateInventory:
        """
        Check the ids, the single-writer rule, that inputs are known and that there's no cycle.
        """
        _check_unique([j.job_id for j in self.jobs], "job ids")
        _check_unique(list(self.sources), "sources")
        producers: dict[str, str] = {}
        for job in self.jobs:
            for out in job.outputs:
                if out.table in self.audit_tables:
                    continue
                if out.table in producers or out.table in self.sources:
                    raise ValueError(f"{out.table} is written by more than one job or source")
                producers[out.table] = job.job_id
        known = set(self.sources) | set(producers) | set(self.audit_tables)
        for job in self.jobs:
            unknown = [t for t in job.inputs if t not in known]
            if unknown:
                raise ValueError(f"{job.job_id} reads unknown tables {unknown}")
        self._check_acyclic()
        return self

    def _check_acyclic(self) -> None:
        """
        Refuse jobs that depend on each other in a cycle.
        """
        upstream = {j.job_id: set(self.upstream(j.job_id)) for j in self.jobs}
        remaining = dict(upstream)
        while remaining:
            ready = [j for j, ups in remaining.items() if not (ups & remaining.keys())]
            if not ready:
                raise ValueError(f"jobs depend on each other in a cycle: {sorted(remaining)}")
            for job_id in ready:
                del remaining[job_id]

    def job(self, job_id: str) -> JobSpec:
        """
        Look up a job by id.

        Args:
            job_id: Job id, such as ``T04``.

        Returns:
            The job's spec.

        Raises:
            KeyError: If the inventory has no such job.
        """
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        raise KeyError(job_id)

    def producers(self) -> dict[str, str]:
        """
        Map each output table to the job that writes it, leaving out audit tables.

        Returns:
            Job ids by table name.
        """
        return {
            o.table: j.job_id
            for j in self.jobs
            for o in j.outputs
            if o.table not in self.audit_tables
        }

    def upstream(self, job_id: str) -> list[str]:
        """
        List the other jobs whose outputs a job reads directly.

        Args:
            job_id: The downstream job.

        Returns:
            The upstream job ids, sorted.

        Raises:
            KeyError: If the inventory has no such job.
        """
        producers = self.producers()
        return sorted(
            {
                producers[t]
                for t in self.job(job_id).inputs
                if t in producers and producers[t] != job_id
            }
        )

    def merge(self, other: EstateInventory) -> EstateInventory:
        """
        Combine this inventory with another one's jobs, such as unsealed held-out jobs.

        Sources and audit tables are combined without duplicates. The as-of date and the
        legacy database are this inventory's; the other's are ignored.

        Args:
            other: The inventory whose jobs to add.

        Returns:
            A new inventory, validated again as a whole.

        Raises:
            pydantic.ValidationError: If the combination breaks a rule, such as a job id
                that both inventories list.
        """
        data = self.model_dump()
        data["jobs"] += other.model_dump()["jobs"]
        data["sources"] = list(dict.fromkeys([*self.sources, *other.sources]))
        data["audit_tables"] = list(dict.fromkeys([*self.audit_tables, *other.audit_tables]))
        return EstateInventory.model_validate(data)


### Discover: blocks, lineage, traps, flows of tagged data, waves


class CodeBlock(Model):
    """
    One statement (T-SQL) or step (SAS DATA/PROC/%macro) of a legacy job.

    Attributes:
        index: Position of the block in the job, from 0.
        line_start: First line of the block in the legacy file, from 1.
        line_end: Last line of the block, inclusive.
        sqlglot_parsed: Whether sqlglot could parse the statement; None for SAS.
    """

    job_id: JobId
    index: int = Field(ge=0)
    kind: Literal["statement", "data_step", "proc", "macro", "other"]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    sqlglot_parsed: bool | None = Field(default=None, description="T-SQL only.")

    @model_validator(mode="after")
    def _check(self) -> CodeBlock:
        """
        Refuse a block that ends before it starts.
        """
        if self.line_end < self.line_start:
            raise ValueError("line_end is before line_start")
        return self


class JobDiscovery(Model):
    """
    What Discover learned about one job; H1 needs every job parsed or flagged.
    """

    job_id: JobId
    status: Literal["parsed", "flagged"]
    flags: list[str] = Field(default_factory=list, description="Why a human must look.")
    blocks: list[CodeBlock] = Field(default_factory=list)
    reads: list[TableName] = Field(default_factory=list, description="Found in the code.")
    writes: list[TableName] = Field(default_factory=list, description="Found in the code.")

    @model_validator(mode="after")
    def _check(self) -> JobDiscovery:
        """
        Refuse a flagged job without a flag.
        """
        if self.status == "flagged" and not self.flags:
            raise ValueError("a flagged job needs at least one flag")
        return self


class LineageKind(StrEnum):
    """
    How an input influences an output.
    """

    DERIVES = "derives"  # its value flows into the output column
    FILTERS = "filters"  # it decides which rows appear (WHERE, JOIN, HAVING, IN=)
    RANKS = "ranks"  # it decides which row survives (ORDER BY in a ranking, NODUPKEY, FIRST.)


class LineageEdge(Model):
    """
    One column-level lineage edge from a job input to a job output.

    Attributes:
        input_kind: What the input is: a column, a job parameter, a constant in the code, or
            a generated value such as an IDENTITY key.
        source: Who found the edge: the Lineage agent, sqlglot's ``lineage()`` or a person.
        confidence: The finder's confidence, from 0 to 1, where it gave one.
        agrees_with_sqlglot: The sqlglot cross-check's verdict; None where it didn't run.
        evidence_lines: Lines of the legacy file that show the edge.
    """

    job_id: JobId
    output_table: TableName
    output_column: str | None = Field(
        default=None, description="None when the edge affects whole rows (filters, ranks)."
    )
    input_kind: Literal["column", "parameter", "constant", "generated"] = "column"
    input_table: TableName | None = None
    input_column: str | None = Field(
        default=None, description="The column, or the parameter name (e.g. @AsOfDate)."
    )
    kind: LineageKind
    transform: str | None = Field(default=None, description="Short description of the logic.")
    source: Literal["llm", "sqlglot", "manual"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool = Field(default=False, description="Every named column exists in a schema.")
    agrees_with_sqlglot: bool | None = None
    evidence_lines: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> LineageEdge:
        """
        Check that the edge names what its kinds need, and nothing they rule out.
        """
        if self.kind is LineageKind.DERIVES and self.output_column is None:
            raise ValueError("a 'derives' edge needs an output column")
        if self.input_kind == "column" and not (self.input_table and self.input_column):
            raise ValueError("a column edge needs input_table and input_column")
        if self.input_kind != "column" and self.input_table is not None:
            raise ValueError(f"a {self.input_kind} edge has no input table")
        if self.input_kind == "parameter" and not self.input_column:
            raise ValueError("a parameter edge names the parameter in input_column")
        return self


class TaggedFlow(Model):
    """
    A path from a tagged (pii or protected) source column into a job output (plan §10).

    Attributes:
        flow_id: The id that the :class:`FlowDecision` on this flow refers to.
    """

    flow_id: str = Field(min_length=1)
    tag: ColumnTag
    source: ColumnRef
    output: ColumnRef
    path: list[ColumnRef] = Field(min_length=2, description="From source to output, in order.")
    job_ids: list[JobId] = Field(min_length=1, description="Jobs the path passes through.")

    @model_validator(mode="after")
    def _check(self) -> TaggedFlow:
        """
        Check that the path starts at the source and ends at the output.

        Column names compare case-insensitively, as everywhere in the contracts.
        """
        if not (
            _same_column(self.path[0], self.source) and _same_column(self.path[-1], self.output)
        ):
            raise ValueError("the path must start at the source and end at the output")
        return self


class Wave(Model):
    """
    One topological generation of the estate DAG: jobs whose upstream jobs run earlier.

    Attributes:
        number: Position in run order, from 1.
    """

    number: int = Field(ge=1)
    job_ids: list[JobId] = Field(min_length=1)


class JobEdge(Model):
    """
    A dependency between two jobs in the estate DAG.

    Attributes:
        tables: The upstream job's outputs that the downstream job reads.
    """

    upstream: JobId
    downstream: JobId
    tables: list[TableName] = Field(min_length=1)


class EstatePlan(Model):
    """
    The estate DAG found by Discover and its waves (topological generations).
    """

    waves: list[Wave] = Field(min_length=1)
    edges: list[JobEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> EstatePlan:
        """
        Check that the waves are numbered 1, 2, 3, ... and that no job is in two of them.
        """
        numbers = [w.number for w in self.waves]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("waves are numbered 1, 2, 3, ... in order")
        _check_unique([j for w in self.waves for j in w.job_ids], "jobs across waves")
        return self


class TrapKind(StrEnum):
    """
    Semantic traps change results; construct traps change only the shape of the code.

    Each planted semantic trap gets a check query and a test. Running and reconciling the
    job covers construct traps (plan Appendix A).
    """

    SEMANTIC = "semantic"
    CONSTRUCT = "construct"


class DiffSignatureKind(StrEnum):
    """
    Patterns that a known trap leaves in a failed reconciliation (plan §8.6).
    """

    CASE_SPLIT = "case_split"
    TRAILING_SPACE_SPLIT = "trailing_space_split"
    INTEGER_TRUNCATION = "integer_truncation"
    OFF_BY_ONE_PERIOD = "off_by_one_period"
    NULL_VS_VALUE = "null_vs_value"
    ROUNDING = "rounding"
    ROW_MULTIPLICITY = "row_multiplicity"
    TRUNCATED_STRING = "truncated_string"
    ORDER_DEPENDENCE = "order_dependence"


class DetectionRule(Model):
    """
    A way to spot a trap in legacy code: a deterministic rule, or Claude for subtle cases.

    The deterministic kinds are regexes, sqlglot checks and type checks such as INT/INT
    (plan §8.3).
    """

    kind: Literal["regex", "sqlglot", "type_check", "llm"]
    pattern: str | None = None
    description: str = Field(min_length=1)


class TrapCard(Model):
    """
    A known difference between a legacy engine and Spark (plan Appendix A).

    Attributes:
        diff_signatures: The patterns the trap leaves in a failed reconciliation, which link
            a difference back to this card.
        example_legacy: Legacy code that sets the trap.
        example_spark: Spark code that reproduces the legacy behaviour.
        test_hint: What a test's inputs need in order to expose the trap.
    """

    trap_id: TrapId
    title: str = Field(min_length=1)
    language: Language
    kind: TrapKind
    legacy_behaviour: str = Field(min_length=1)
    spark_behaviour: str = Field(min_length=1)
    fix_guidance: str = Field(min_length=1)
    detection: list[DetectionRule] = Field(default_factory=list)
    diff_signatures: list[DiffSignatureKind] = Field(default_factory=list)
    allowed_literals: list[str] = Field(
        default_factory=list,
        description="Constants this card's fix introduces (e.g. 'UTF8_LCASE_RTRIM', "
        "'yyyyMMdd'); the literal check accepts them with provenance trap_card.",
    )
    example_legacy: str | None = None
    example_spark: str | None = None
    test_hint: str | None = None

    @model_validator(mode="after")
    def _check(self) -> TrapCard:
        """
        Check that the trap id's prefix matches the language.
        """
        prefix = "TSQL" if self.language is Language.TSQL else "SAS"
        if not self.trap_id.startswith(prefix + "-"):
            raise ValueError(f"{self.trap_id} does not match language {self.language}")
        return self


class TrapFinding(Model):
    """
    A trap spotted in one job, with the lines it occurs on.

    Attributes:
        snippet: The legacy code on those lines.
        detector: Whether a trap card's rule or Claude found it.
    """

    job_id: JobId
    trap_id: TrapId
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    snippet: str
    detector: Literal["rule", "llm"]
    confidence: float = Field(ge=0.0, le=1.0)
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> TrapFinding:
        """
        Refuse a finding that ends before it starts.
        """
        if self.line_end < self.line_start:
            raise ValueError("line_end is before line_start")
        return self


### Design: contracts, policies, defects and flow decisions


class PolicyKind(StrEnum):
    """
    How reconciliation compares one column (plan §8.4).
    """

    EXACT = "exact"
    CI_RTRIM = "ci_rtrim"  # SQL Server text under a case-insensitive collation
    RTRIM = "rtrim"  # SAS character values (blank padded)
    BLANK_IS_NULL = "blank_is_null"  # SAS: a blank character value is missing
    FLOAT_REL = "float_rel"  # SAS doubles only: relative tolerance <= 1e-9, optional abs floor
    SURROGATE = "surrogate"  # generated keys: rows matched on the business key, not compared
    SURROGATE_REF = "surrogate_ref"  # a foreign key to a surrogate: compared via its business key
    EXCLUDE = "exclude"  # audit columns such as load timestamps


MAX_FLOAT_REL_TOLERANCE = 1e-9
MAX_FLOAT_ABS_TOLERANCE = 1e-9
_TEXT_POLICIES = {PolicyKind.CI_RTRIM, PolicyKind.RTRIM, PolicyKind.BLANK_IS_NULL}


class ComparisonPolicy(Model):
    """
    How reconciliation compares one column of a contract, and why.

    Anything but ``exact`` needs a reason and H2 approval. Approval is not recorded here:
    it is a :class:`GateDecision` at H2 whose evidence carries the contract's hash, so a
    changed policy is unapproved again.

    Attributes:
        reason: Why the column can't be compared exactly; required unless ``exact``.
        rel_tolerance: ``float_rel`` only: the largest relative difference accepted.
    """

    kind: PolicyKind = PolicyKind.EXACT
    reason: str | None = None
    rel_tolerance: float | None = Field(default=None, gt=0.0)
    abs_tolerance: float | None = Field(
        default=None, gt=0.0, description="Absolute floor near zero: |a-b| <= max(rel*max, abs)."
    )
    references: ColumnRef | None = Field(
        default=None, description="surrogate_ref only: the surrogate column this key points at."
    )

    @model_validator(mode="after")
    def _check(self) -> ComparisonPolicy:
        """
        Check the reason, tolerances and reference that the policy's kind needs or rules out.
        """
        if self.kind is not PolicyKind.EXACT and not (self.reason and self.reason.strip()):
            raise ValueError(f"policy {self.kind} needs a reason")
        if self.kind is PolicyKind.FLOAT_REL:
            if self.rel_tolerance is None or self.rel_tolerance > MAX_FLOAT_REL_TOLERANCE:
                raise ValueError(f"float_rel needs 0 < rel_tolerance <= {MAX_FLOAT_REL_TOLERANCE}")
            if self.abs_tolerance is not None and self.abs_tolerance > MAX_FLOAT_ABS_TOLERANCE:
                raise ValueError(f"abs_tolerance must be <= {MAX_FLOAT_ABS_TOLERANCE}")
        elif self.rel_tolerance is not None or self.abs_tolerance is not None:
            raise ValueError("tolerances only apply to float_rel")
        if (self.kind is PolicyKind.SURROGATE_REF) != (self.references is not None):
            raise ValueError("references is required for surrogate_ref and only allowed there")
        return self

    @property
    def needs_approval(self) -> bool:
        """
        Whether the policy needs a reason and H2 approval, as anything but ``exact`` does.
        """
        return self.kind is not PolicyKind.EXACT


class ContractColumn(ColumnSpec):
    """
    A column in a data contract, with its comparison policy.
    """

    policy: ComparisonPolicy = Field(default_factory=ComparisonPolicy)


class SlaSpec(Model):
    """
    Operating limits checked on every run (plan §8.8).

    The runtime limit is the job's: for a job with several outputs, the smallest
    ``max_runtime_seconds`` across its outputs' contracts applies.

    Attributes:
        expected_rows: Rows the output should have.
        row_tolerance_pct: How far the row count may stray from ``expected_rows``, in per
            cent, before it counts as a breach.
    """

    max_runtime_seconds: float = Field(gt=0)
    expected_rows: int = Field(ge=0)
    row_tolerance_pct: float = Field(default=10.0, ge=0)


class DataContract(Model):
    """
    The written promise about one output table: grain, keys, types, policies, tags.

    Attributes:
        legacy_table: The legacy table this output reproduces, such as
            ``rpt.claims_summary``.
        partition_columns: Columns that split the output into partitions; reconciliation
            also compares row counts per partition.
    """

    job_id: JobId
    table: TableName = Field(description="Lakehouse name, e.g. gold.claims_summary.")
    legacy_table: TableName
    layer: Layer
    grain: str = Field(min_length=1, description="What one row represents.")
    keys: list[str] = Field(
        default_factory=list, description="Business key; empty means compare as a multiset."
    )
    columns: list[ContractColumn] = Field(min_length=1)
    partition_columns: list[str] = Field(default_factory=list)
    sla: SlaSpec | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check(self) -> DataContract:
        """
        Check the column names, keys and partition columns, and that each policy suits its column.
        """
        names = [c.name for c in self.columns]
        _check_unique(names, "contract columns")
        for group, cols in (("keys", self.keys), ("partition columns", self.partition_columns)):
            missing = _missing(cols, names)
            if missing:
                raise ValueError(f"{group} not in contract: {missing}")
        keys = {_fold(k) for k in self.keys}
        for col in self.columns:
            kind = col.policy.kind
            if _fold(col.name) in keys and kind in (
                PolicyKind.SURROGATE,
                PolicyKind.SURROGATE_REF,
                PolicyKind.EXCLUDE,
            ):
                raise ValueError(f"key column {col.name!r} cannot be {kind}")
            if kind is PolicyKind.FLOAT_REL and col.data_type not in ("double", "float"):
                raise ValueError(f"float_rel is for doubles, not {col.name}: {col.data_type}")
            if kind in _TEXT_POLICIES and col.data_type != "string":
                raise ValueError(f"{kind} is for text, not {col.name}: {col.data_type}")
            if kind is PolicyKind.SURROGATE and not self.keys:
                raise ValueError(f"surrogate {col.name!r} needs a business key to match rows on")
        return self

    def column(self, name: str) -> ContractColumn:
        """
        Look up a column by name, ignoring case.

        Args:
            name: Column name, in any case.

        Returns:
            The column with its policy.

        Raises:
            KeyError: If the contract has no such column.
        """
        for col in self.columns:
            if _fold(col.name) == _fold(name):
                return col
        raise KeyError(f"{self.table} has no column {name!r}")

    def non_exact(self) -> list[ContractColumn]:
        """
        List the columns whose policy needs a reason and H2 approval.

        Returns:
            The columns with any policy but ``exact``, in contract order.
        """
        return [c for c in self.columns if c.policy.needs_approval]


class DefectImpact(Model):
    """
    A suspected bug's measured impact on golden data.

    Attributes:
        rows_affected: Golden rows the bug changes.
        amount_affected: Total of ``amount_column`` over those rows, as decimal text.
        query: The query that measured the impact.
    """

    rows_affected: int = Field(ge=0)
    amount_affected: DecimalText | None = None
    amount_column: str | None = None
    measured_on: str = Field(min_length=1, description="What was queried, e.g. golden:T04.")
    query: str = Field(min_length=1)


class SuspectedDefect(Model):
    """
    A possible bug in legacy logic.

    LANSH reproduces it and asks a human to decide what happens to it.

    Attributes:
        intended_behaviour: What the code was probably meant to do.
        evidence_lines: Lines of the legacy file that show the bug.
        impact_query: A query that measures the bug's effect on golden data.
        impact: What ``impact_query`` found, once it has run.
        source: How the bug was found: a ``# LANSH-DEFECT`` marker in the migrated code,
            the Defect reviewer agent, or a person.
    """

    defect_id: str = Field(min_length=1, description="Factory-assigned, e.g. T04-D1.")
    job_id: JobId
    title: str = Field(min_length=1)
    description: str = Field(min_length=1, description="What the legacy code does.")
    intended_behaviour: str | None = None
    evidence_lines: list[int] = Field(default_factory=list)
    impact_query: str | None = None
    impact: DefectImpact | None = None
    source: Literal["marker", "llm", "manual"]
    confidence: float = Field(ge=0.0, le=1.0)


class DefectDecisionKind(StrEnum):
    """
    What a human decided to do about a suspected defect.
    """

    REPRODUCE = "reproduce"  # the default: keep legacy behaviour through cut-over
    FIX_AFTER_CUTOVER = "fix_after_cutover"  # reproduce now, fix later as a separate change
    NOT_A_DEFECT = "not_a_defect"  # a false alarm: behaviour is reproduced; register only


class DefectDecision(Model):
    """
    A human decision on one suspected defect, taken at H2 or H4.
    """

    defect_id: str = Field(min_length=1)
    job_id: JobId
    decision: DefectDecisionKind
    reason: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)
    decided_at: AwareDatetime
    gate: Literal[Gate.H2, Gate.H4]


class FlowDecision(Model):
    """
    A human decision on one flow of a protected or personal column into an output (H2).
    """

    flow_id: str = Field(min_length=1)
    decision: Literal["reproduce_accepted", "reproduce_flagged"] = Field(
        description="Reproduce as-is; 'flagged' also raises it for a bias review after cut-over."
    )
    reason: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)
    decided_at: AwareDatetime
    gate: Literal[Gate.H2] = Gate.H2


### Generate: artifacts, literals and tests


class LiteralFinding(Model):
    """
    A literal in a migrated job, where it comes from, and any human acceptance (plan §8.5).

    A literal found nowhere else (provenance ``none``) blocks H3 until a reviewer accepts it
    with a reason. This stops a fixer from hard-coding its way to a MATCH.

    Attributes:
        value: The literal as written in the job.
        line: Line in the migrated module.
        provenance: Where else the literal appears: the legacy code, the contract, the job's
            parameters or a trap card's allowed literals.
        accepted_by: The reviewer who accepted a literal found nowhere else.
        decision_id: The gate decision that accepted it.
    """

    value: str
    line: int = Field(ge=1)
    provenance: Literal["legacy", "contract", "params", "trap_card", "none"]
    accepted_by: str | None = None
    reason: str | None = None
    decision_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> LiteralFinding:
        """
        Refuse an accepted literal without a reason.
        """
        if self.accepted_by and not (self.reason and self.reason.strip()):
            raise ValueError("accepting an unexplained literal needs a reason")
        return self

    @property
    def blocks_h3(self) -> bool:
        """
        Whether the literal blocks H3: it is found nowhere else and nobody has accepted it.
        """
        return self.provenance == "none" and not self.accepted_by


class MigrationArtifact(Model):
    """
    A migrated job module and where it came from.

    Attributes:
        module_path: Repository-relative path of the migrated module.
        legacy_path: Repository-relative path of the legacy code it replaces.
        model: The Claude model that wrote it, when Claude did.
        attempt: The heal attempt that produced this version; 0 for the first translation.
        guardrail_violations: What the guardrails refused; empty when they all passed.
    """

    job_id: JobId
    module_path: str = Field(min_length=1)
    code_sha256: Sha256
    legacy_path: str = Field(min_length=1)
    legacy_sha256: Sha256
    approach: Approach = Approach.LANSH
    translator: Literal["sqlglot", "claude", "oneshot_claude", "fixer", "manual"] = Field(
        description="The last writer of this version of the code."
    )
    model: str | None = None
    attempt: int = Field(default=0, ge=0)
    traps_handled: list[TrapId] = Field(default_factory=list)
    defects_reproduced: list[str] = Field(
        default_factory=list, description="Defect ids marked # LANSH-DEFECT in the code."
    )
    guardrail_violations: list[str] = Field(default_factory=list)
    literals: list[LiteralFinding] = Field(default_factory=list)
    created_at: AwareDatetime

    def blocking_literals(self) -> list[LiteralFinding]:
        """
        List the literals that still block H3.

        Returns:
            The literals found nowhere else that nobody has accepted.
        """
        return [lit for lit in self.literals if lit.blocks_h3]


class TableRows(Model):
    """
    Rows of one table as canonical text: plain decimals, ISO dates, NULL as null.
    """

    table: TableName
    columns: list[str] = Field(min_length=1)
    rows: list[list[str | None]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> TableRows:
        """
        Check that column names are unique and that every row has one value per column.
        """
        _check_unique(self.columns, "columns")
        width = len(self.columns)
        if bad := [i for i, row in enumerate(self.rows) if len(row) != width]:
            raise ValueError(f"rows {bad[:5]} do not have {width} values")
        return self


class TestCase(Model):
    """
    A small trap-focused test: inputs, and expected outputs from the legacy engine.

    Attributes:
        expected: The expected outputs; None when the test checks the contract instead.
        expected_source: ``legacy_engine`` when the legacy engine produced ``expected``;
            ``contract`` when SAS was unavailable and the test checks the schema, keys and
            row counts instead (plan §8.7).
        status: The result of the latest run; ``pending`` until the test has run.
    """

    __test__ = False  # not a pytest test class

    test_id: str = Field(min_length=1)
    job_id: JobId
    trap_id: TrapId | None = None
    description: str = Field(min_length=1)
    inputs: list[TableRows] = Field(min_length=1)
    expected: list[TableRows] | None = None
    expected_source: Literal["legacy_engine", "contract"]
    path: str | None = Field(default=None, description="Generated pytest file.")
    status: Literal["pending", "pass", "fail", "error"] = "pending"


### Reconcile: reports, heal attempts and escalations


class ReconMode(StrEnum):
    """
    How a reconciliation is set up (plan §8.6).
    """

    ISOLATED = "isolated"  # inputs are the upstream golden outputs
    CHAINED = "chained"  # inputs are the upstream migrated outputs
    CANDIDATE = "candidate"  # a hand-written job is checked (manual baseline)


class ReconStatus(StrEnum):
    """
    The verdict of one reconciliation.

    ERROR means the comparison couldn't be completed; the report's ``error`` says why.
    """

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


class TypeMismatch(Model):
    """
    A column whose type differs between the legacy output and the candidate.
    """

    column: str
    legacy_type: str
    candidate_type: str


class SchemaDiff(Model):
    """
    How the candidate's columns differ from the legacy output's.

    Attributes:
        missing_columns: Legacy columns the candidate lacks.
        extra_columns: Candidate columns the legacy output lacks.
    """

    missing_columns: list[str] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list)
    type_mismatches: list[TypeMismatch] = Field(default_factory=list)

    @property
    def issues(self) -> int:
        """
        The number of schema problems of every kind.
        """
        return len(self.missing_columns) + len(self.extra_columns) + len(self.type_mismatches)

    @property
    def ok(self) -> bool:
        """
        Whether the schemas agree.
        """
        return self.issues == 0


class PartitionCount(Model):
    """
    Row counts on each side for one partition.

    Attributes:
        partition: The partition's column values, as text.
    """

    partition: str
    legacy: int = Field(ge=0)
    candidate: int = Field(ge=0)


class CountCheck(Model):
    """
    Row counts on each side, in total and per partition.
    """

    legacy: int = Field(ge=0)
    candidate: int = Field(ge=0)
    by_partition: list[PartitionCount] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """
        Whether the counts agree in total and in every partition.
        """
        return self.legacy == self.candidate and all(
            p.legacy == p.candidate for p in self.by_partition
        )


class TotalCheck(Model):
    """
    One numeric column's total on each side, and the rule that judged them.

    Totals are decimal text, or None when a side has no total (when every value is NULL,
    say). The tolerances are those of a ``float_rel`` policy.
    """

    column: str
    legacy: DecimalText | None
    candidate: DecimalText | None
    matches: bool
    policy: PolicyKind = PolicyKind.EXACT
    rel_tolerance: float | None = None
    abs_tolerance: float | None = None


class KeyIntegrity(Model):
    """
    Key problems on each side.

    Duplicates count distinct duplicated key values, not surplus rows. NULL keys count rows
    whose key has a NULL part.
    """

    legacy_duplicate_keys: int = Field(default=0, ge=0)
    candidate_duplicate_keys: int = Field(default=0, ge=0)
    legacy_null_keys: int = Field(default=0, ge=0)
    candidate_null_keys: int = Field(default=0, ge=0)


class RowCounts(Model):
    """
    Status of every row after the full outer join on the keys.

    Attributes:
        matched: Rows on both sides whose values all agree under their policies.
        value_diff: Rows on both sides with at least one value that differs.
    """

    matched: int = Field(default=0, ge=0)
    value_diff: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0, description="In legacy only.")
    extra: int = Field(default=0, ge=0, description="In the candidate only.")

    @property
    def differences(self) -> int:
        """
        Rows that differ in any way: value differences, missing rows and extra rows.
        """
        return self.value_diff + self.missing + self.extra


class ColumnDiff(Model):
    """
    The differences in one column, judged under its comparison policy.

    Attributes:
        n_rows: Rows whose values differ in this column.
    """

    column: str
    policy: PolicyKind
    n_rows: int = Field(ge=0)
    samples: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5, description="Masked sample rows (pii hashed)."
    )


class DiffSignature(Model):
    """
    A recognised pattern in the differences, linked to the traps that cause it.

    Attributes:
        column: The column showing the pattern; None for a row-level pattern such as row
            multiplicity.
        n_rows: Rows that show the pattern.
        explanation: A plain-English account of the pattern.
    """

    kind: DiffSignatureKind
    column: str | None = None
    n_rows: int = Field(ge=0)
    explanation: str = Field(min_length=1)
    suspected_traps: list[TrapId] = Field(default_factory=list)


Score = tuple[int, int, int, int]
"""(error, schema issues, |count difference|, row differences): smaller is better."""


class ReconReport(Model):
    """
    The result of reconciling one output table against its golden output.

    The candidate is the output of the job being checked. The status must agree with the
    findings: MATCH means nothing differs and no error is recorded, MISMATCH that something
    differs. ERROR needs an error message, and is the only status that may leave out the
    counts.

    Attributes:
        keys: The business key the rows were joined on; empty means compared as a multiset.
        explanation: A plain-English account of what went wrong.
        error: What stopped the comparison, or went wrong during it.
    """

    job_id: JobId
    table: TableName
    mode: ReconMode
    status: ReconStatus
    run_id: str | None = None
    approach: Approach = Approach.LANSH
    code_sha256: Sha256 | None = Field(default=None, description="The candidate job's code.")
    keys: list[str] = Field(default_factory=list)
    schema_diff: SchemaDiff = Field(default_factory=SchemaDiff)
    counts: CountCheck | None = Field(default=None, description="Required unless ERROR.")
    totals: list[TotalCheck] = Field(default_factory=list)
    key_integrity: KeyIntegrity = Field(default_factory=KeyIntegrity)
    rows: RowCounts = Field(default_factory=RowCounts)
    column_diffs: list[ColumnDiff] = Field(default_factory=list)
    missing_samples: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5, description="Masked rows only in legacy."
    )
    extra_samples: list[dict[str, Any]] = Field(
        default_factory=list, max_length=5, description="Masked rows only in the candidate."
    )
    signatures: list[DiffSignature] = Field(default_factory=list)
    explanation: str = ""
    contract_sha256: Sha256 | None = Field(
        default=None, description="The data contract (keys and policies) the comparison used."
    )
    golden_sha256: Sha256 | None = Field(
        default=None, description="Content hash of the golden output (lansh.estate.fingerprint)."
    )
    candidate_sha256: Sha256 | None = Field(
        default=None, description="Content hash of the candidate output."
    )
    started_at: AwareDatetime
    duration_seconds: float = Field(ge=0)
    error: str | None = None

    def _problems(self) -> list[str]:
        """
        List what differs, as short phrases for the status check's error message.
        """
        problems = []
        if not self.schema_diff.ok:
            problems.append("schema differs")
        if self.counts is not None and not self.counts.ok:
            problems.append("counts differ")
        if self.rows.differences:
            problems.append(f"{self.rows.differences} row differences")
        if any(not t.matches for t in self.totals):
            problems.append("totals differ")
        if any(d.n_rows for d in self.column_diffs):
            problems.append("column differences")
        return problems

    @model_validator(mode="after")
    def _check(self) -> ReconReport:
        """
        Check that the status agrees with the findings.
        """
        if self.status is ReconStatus.ERROR:
            if not self.error:
                raise ValueError("status ERROR needs an error message")
            return self
        if self.counts is None:
            raise ValueError("counts are required unless the status is ERROR")
        problems = self._problems()
        if self.status is ReconStatus.MATCH and (problems or self.error):
            found = ", ".join(problems + (["error recorded"] if self.error else []))
            raise ValueError(f"status MATCH contradicts the report: {found}")
        if self.status is ReconStatus.MISMATCH and not problems:
            raise ValueError("status MISMATCH but nothing differs")
        return self

    @property
    def unexplained_differences(self) -> int:
        """
        Rows that still differ; H4 needs this to be zero.
        """
        return self.rows.differences

    @property
    def score(self) -> Score:
        """
        How far the report is from MATCH, for the heal loop.

        Scores compare as tuples, so an error outweighs any number of schema issues, a
        schema issue any count difference, and so on. MATCH scores (0, 0, 0, 0).
        """
        count_delta = abs(self.counts.legacy - self.counts.candidate) if self.counts else 0
        return (
            int(self.status is ReconStatus.ERROR),
            self.schema_diff.issues,
            count_delta,
            self.rows.differences,
        )


def total_score(reports: list[ReconReport]) -> Score:
    """
    Add up a job's scores across all its outputs.

    Args:
        reports: One report per output table of the job.

    Returns:
        The element-wise sum of the scores.

    Raises:
        ValueError: If ``reports`` is empty: a job with nothing reconciled would otherwise
            score (0, 0, 0, 0), like a clean MATCH.
    """
    if not reports:
        raise ValueError("no reports to score: a job with nothing reconciled is not a MATCH")
    parts = [r.score for r in reports]
    return (
        sum(p[0] for p in parts),
        sum(p[1] for p in parts),
        sum(p[2] for p in parts),
        sum(p[3] for p in parts),
    )


class HealAttempt(Model):
    """
    One diagnose-patch-rerun cycle of the heal loop.

    Attributes:
        attempt: The attempt number; the loop escalates after the third.
        diagnosis: The Diagnoser's account of what went wrong.
        patch_summary: What the patch changed.
        score_after: The score after the re-run; None if the patched job never ran.
        llm_call_ids: The gateway calls the attempt made.
    """

    job_id: JobId
    attempt: int = Field(ge=1, le=3)
    diagnosis: str = Field(min_length=1)
    suspected_traps: list[TrapId] = Field(default_factory=list)
    patch_summary: str = Field(min_length=1)
    code_sha256_before: Sha256
    code_sha256_after: Sha256
    score_before: Score
    score_after: Score | None = None
    report_before: str = Field(min_length=1, description="Path or id of the report before.")
    report_after: str | None = None
    guardrails_passed: bool
    kept: bool = Field(description="Kept only if the score strictly improved.")
    recon_status_after: ReconStatus | None = None
    llm_call_ids: list[str] = Field(default_factory=list)
    started_at: AwareDatetime
    duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> HealAttempt:
        """
        Refuse a kept patch that didn't strictly improve the score.
        """
        if self.kept and (self.score_after is None or not self.score_after < self.score_before):
            raise ValueError("a patch is kept only if the score strictly improves")
        return self


class Escalation(Model):
    """
    A job handed to a person, with the diagnosis and (later) how it was resolved.

    Attributes:
        reason: Why the factory gave up: the heal loop ran out of attempts, Claude's answer
            stayed invalid, a guardrail refused the code, the lineage was rejected, the
            subscription's usage limit was hit, or another error.
        attempts: Heal attempts made before escalating.
        human_minutes: Minutes a person spent resolving it (plan §9.2).
    """

    escalation_id: str = Field(min_length=1)
    job_id: JobId
    stage: Stage
    reason: Literal[
        "heal_exhausted", "llm_invalid", "guardrail", "lineage_rejected", "usage_limit", "error"
    ]
    diagnosis: str = Field(min_length=1)
    attempts: int = Field(default=0, ge=0)
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    resolution: str | None = None
    human_minutes: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check(self) -> Escalation:
        """
        Refuse a resolved escalation that doesn't say how it was resolved.
        """
        if self.resolved_at and not self.resolution:
            raise ValueError("a resolved escalation says how it was resolved")
        return self


### Governance


class GateOutcome(StrEnum):
    """
    A reviewer's verdict at a gate.
    """

    APPROVE = "approve"
    APPROVE_WITH_CHANGES = "approve_with_changes"
    REJECT = "reject"


class EvidenceRef(Model):
    """
    One piece of evidence shown before a decision, pinned by its hash.

    Attributes:
        sha256: Hash of the evidence as shown, so that a later change can be detected.
    """

    kind: Literal[
        "lineage",
        "traps",
        "contract",
        "defects",
        "flows",
        "code",
        "tests",
        "recon_report",
        "heal",
        "schedule",
        "sla",
        "other",
    ]
    ref: str = Field(min_length=1, description="Path or id.")
    sha256: Sha256 | None = None


class GateDecision(Model):
    """
    One recorded human decision at a product gate (plan §8.9).

    ``job_ids`` lists exactly the jobs the decision covers: one job, or the jobs of a wave
    approved together under risk-based gating. A decision with warnings, or with any outcome
    but a plain approval, needs a written reason.

    Attributes:
        wave: The wave decided on; required at H5, where cut-over is per wave.
        warnings: Warnings shown with the evidence, such as non-exact policies.
        flagged_fast: True when the decision came faster than the review-time threshold.
        prev_hash: Hash of the previous decision in the log, which chains the log (Tier 2).
    """

    decision_id: str = Field(min_length=1)
    gate: Gate
    stage: Stage
    job_ids: list[JobId] = Field(min_length=1)
    wave: int | None = Field(default=None, ge=1)
    outcome: GateOutcome
    reviewer: str = Field(min_length=1)
    reason: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    shown_at: AwareDatetime = Field(description="When the evidence was put in front of them.")
    decided_at: AwareDatetime
    flagged_fast: bool = False
    spot_check: bool = Field(default=False, description="Picked for random re-review.")
    re_review_of: str | None = Field(default=None, description="The decision re-examined.")
    prev_hash: Sha256 | None = Field(default=None, description="Tier 2 hash chain.")

    @model_validator(mode="after")
    def _check(self) -> GateDecision:
        """
        Check the gate's stage, the job ids, the wave, the timing and the reason.
        """
        if GATE_STAGE[self.gate] is not self.stage:
            raise ValueError(f"gate {self.gate} closes stage {GATE_STAGE[self.gate]}")
        _check_unique(list(self.job_ids), "job ids")
        if self.gate is Gate.H5 and self.wave is None:
            raise ValueError("an H5 cut-over decision is per wave")
        if self.decided_at < self.shown_at:
            raise ValueError("decided before the evidence was shown")
        needs_reason = self.warnings or self.outcome is not GateOutcome.APPROVE
        if needs_reason and not (self.reason and self.reason.strip()):
            raise ValueError("a written reason is required with warnings or a non-approval")
        return self

    @property
    def review_seconds(self) -> float:
        """
        Seconds from showing the evidence to deciding.
        """
        return (self.decided_at - self.shown_at).total_seconds()


### Operate and metrics


class WaveSchedule(Model):
    """
    One wave's schedule file (maps to one Databricks Workflows job).
    """

    wave: int = Field(ge=1)
    job_ids: list[JobId] = Field(min_length=1)
    depends_on_waves: list[int] = Field(default_factory=list)
    trigger: str = Field(min_length=1, description="e.g. 'after wave 1' or a cron expression.")


class SlaCheck(Model):
    """
    One job run checked against its SLA.

    Attributes:
        table: The output checked; None for a check of the whole job.
        rows: Rows the output had, where counted.
        breaches: The limits the run broke.
    """

    job_id: JobId
    table: TableName | None = None
    runtime_seconds: float = Field(ge=0)
    rows: int | None = Field(default=None, ge=0)
    max_runtime_seconds: float | None = Field(default=None, gt=0)
    expected_rows: int | None = Field(default=None, ge=0)
    row_tolerance_pct: float | None = Field(default=None, ge=0)
    breaches: list[Literal["runtime", "rows"]] = Field(default_factory=list)


class RunStatus(StrEnum):
    """
    How a job's run ended: a reconciliation status, or ESCALATED once handed to a person.
    """

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"
    ESCALATED = "ESCALATED"


class LLMUsage(Model):
    """
    Usage of one Claude call through the gateway, live or replayed.

    Attributes:
        model_requested: The ``--model`` value asked for, such as ``opus``.
        models_used: The models that actually answered, from ``modelUsage``.
        cli_version: The Claude Code version that ran the call.
        request_sha256: The request hash, which keys the recorded answer.
        attempt: 1 for the first try, 2 for the one retry after an invalid answer.
        num_turns: The turns Claude Code reported.
        replayed: True when the answer came from a recording, not a live call.
    """

    call_id: str = Field(min_length=1)
    run_id: str | None = None
    agent: str = Field(min_length=1)
    job_id: JobId | None = None
    stage: Stage | None = None
    model_requested: str
    models_used: list[str] = Field(default_factory=list)
    effort: Effort | None = None
    cli_version: str | None = None
    request_sha256: Sha256
    outcome: Literal["ok", "schema_invalid", "refusal", "usage_limit", "error"] = "ok"
    attempt: int = Field(default=1, ge=1)
    num_turns: int | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_creation_tokens: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    cost_usd_equivalent: float = Field(default=0.0, ge=0, description="API-equivalent; not billed.")
    replayed: bool = False


class RunMetrics(Model):
    """
    Measurements for one job (or the whole run) in one stage or end to end.

    Attributes:
        job_id: The job measured; None for the whole run.
        stage: The stage measured; None for end to end.
        llm_calls: Claude calls made, live or replayed.
        llm_live_calls: The calls among ``llm_calls`` that ran live.
        cost_usd_equivalent: What the calls would cost at API prices; nothing is billed.
        reviewer_seconds: Time reviewers spent on gate decisions.
    """

    run_id: str = Field(min_length=1)
    job_id: JobId | None = None
    wave: int | None = Field(default=None, ge=1)
    stage: Stage | None = None
    approach: Approach = Approach.LANSH
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    llm_live_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd_equivalent: float = Field(default=0.0, ge=0)
    heal_attempts: int = Field(default=0, ge=0)
    reviewer_seconds: float = Field(default=0.0, ge=0)
    status: RunStatus | None = None
    sla: list[SlaCheck] = Field(default_factory=list)


class ArtifactRef(Model):
    """
    A file pinned by its hash: a run artifact a number came from, or a golden sidecar.
    """

    path: str = Field(min_length=1)
    sha256: Sha256


class Metric(Model):
    """
    A scorecard number, traceable to the artifacts it was computed from (plan step 4.3).

    Attributes:
        unit: The unit, such as ``minutes``; None for a plain count.
    """

    name: str = Field(min_length=1)
    value: DecimalText
    unit: str | None = None
    sources: list[ArtifactRef] = Field(min_length=1)


### Ground truth: fingerprints and golden manifests


class TableFingerprint(Model):
    """
    Identity of one table's data: file hash plus an order-independent content hash.

    Attributes:
        table: The table's name, such as ``stg.claims``.
        path: Repository-relative path of the data file.
    """

    table: str = Field(min_length=1)
    path: str = Field(min_length=1)
    rows: int = Field(ge=0)
    file_sha256: Sha256
    content_sha256: Sha256 = Field(
        description="Hash of the typed values, independent of row order and file format."
    )


class GoldenOutput(Model):
    """
    One output table captured from a legacy engine.

    Attributes:
        columns: The output's columns, typed as the engine wrote them.
        volatile_columns: Columns left out of ``content_sha256``, such as load timestamps.
    """

    table: TableName
    rows: int = Field(ge=0)
    columns: list[ColumnSpec] = Field(min_length=1)
    raw_path: str = Field(min_length=1, description="The engine's own export (CSV).")
    raw_sha256: Sha256
    parquet_path: str = Field(min_length=1, description="Typed Parquet copy.")
    parquet_sha256: Sha256
    content_sha256: Sha256 = Field(description="Excludes volatile columns.")
    volatile_columns: list[str] = Field(default_factory=list)
    sidecars: list[ArtifactRef] = Field(
        default_factory=list,
        description="Other files the engine wrote: for SAS, the exact HEX16. numbers, the "
        "PROC CONTENTS metadata and the log.",
    )


class GoldenManifest(Model):
    """
    Everything needed to trust and re-check one job's golden outputs (plan §7.3).

    Attributes:
        engine_version: The engine and its version, such as ``SQL Server 16.0.4305.5``.
        legacy_path: Repository-relative path of the legacy code that ran.
        invocations: The calls made, in order, with their parameters.
        inputs: Fingerprints of what the job read: source extracts and upstream golden
            outputs.
        log_excerpt: The tail of the run's log: the job's ``etl.etl_log`` rows for T-SQL,
            or the SAS log's notes.
        capture_seconds: How long the capture took.
        lansh_version: The LANSH version that made the capture.
    """

    job_id: JobId
    engine: Literal["mssql", "sas"]
    engine_version: str = Field(min_length=1)
    legacy_path: str = Field(min_length=1)
    legacy_sha256: Sha256
    invocations: list[JobInvocation] = Field(min_length=1)
    inputs: list[TableFingerprint] = Field(default_factory=list)
    outputs: list[GoldenOutput] = Field(min_length=1)
    log_excerpt: str = ""
    captured_at: AwareDatetime
    capture_seconds: float = Field(ge=0)
    lansh_version: str


### The evidence report (plan §8.10)


class EvidenceReport(Model):
    """
    Everything about one migrated job, composed from the other records.
    """

    job_id: JobId
    generated_at: AwareDatetime
    legacy_path: str = Field(min_length=1)
    legacy_sha256: Sha256
    discovery: JobDiscovery | None = None
    code: MigrationArtifact | None = None
    lineage: list[LineageEdge] = Field(default_factory=list)
    traps: list[TrapFinding] = Field(default_factory=list)
    contracts: list[DataContract] = Field(default_factory=list)
    defects: list[SuspectedDefect] = Field(default_factory=list)
    defect_decisions: list[DefectDecision] = Field(default_factory=list)
    flows: list[TaggedFlow] = Field(default_factory=list)
    flow_decisions: list[FlowDecision] = Field(default_factory=list)
    recon: list[ReconReport] = Field(default_factory=list)
    heal: list[HealAttempt] = Field(default_factory=list)
    tests: list[TestCase] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    llm_usage: list[LLMUsage] = Field(default_factory=list)
    gates: list[GateDecision] = Field(default_factory=list)


# every contract model, for schema export and round-trip tests
CONTRACT_MODELS: tuple[type[Model], ...] = (
    ColumnRef,
    ColumnSpec,
    TableSchema,
    JobInvocation,
    JobOutput,
    JobSpec,
    EstateInventory,
    CodeBlock,
    JobDiscovery,
    LineageEdge,
    TaggedFlow,
    Wave,
    JobEdge,
    EstatePlan,
    DetectionRule,
    TrapCard,
    TrapFinding,
    ComparisonPolicy,
    ContractColumn,
    SlaSpec,
    DataContract,
    DefectImpact,
    SuspectedDefect,
    DefectDecision,
    FlowDecision,
    LiteralFinding,
    MigrationArtifact,
    TableRows,
    TestCase,
    TypeMismatch,
    SchemaDiff,
    PartitionCount,
    CountCheck,
    TotalCheck,
    KeyIntegrity,
    RowCounts,
    ColumnDiff,
    DiffSignature,
    ReconReport,
    HealAttempt,
    Escalation,
    EvidenceRef,
    GateDecision,
    WaveSchedule,
    SlaCheck,
    LLMUsage,
    RunMetrics,
    ArtifactRef,
    Metric,
    TableFingerprint,
    GoldenOutput,
    GoldenManifest,
    EvidenceReport,
)
