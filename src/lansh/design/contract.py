"""
Data contracts: keys, layer, types, comparison policies and tags for each output (plan §8.4).

A contract is built in three passes, deterministic first:

1. **From the legacy code and the golden output.** Types are the golden output's logical
   types (INT to int, DECIMAL(p,s) to decimal(p,s), DATETIME2 to timestamp_ntz, a SAS numeric
   to double, or date when it carries a date format). Candidate keys are the DDL's primary key
   and every small column set that is unique and never NULL in the golden output; an IDENTITY
   primary key gives way to a business key. The layer follows the schema (``dw`` silver,
   ``rpt`` gold).
2. **Default policies.** ``exact`` everywhere, except: volatile audit columns
   (``jobs.yaml``) are ``exclude``; a SAS double is ``float_rel`` 1e-9 and a SAS character
   column ``blank_is_null``, because SAS stores numbers as doubles and has no empty string.
   Each carries its reason. Tags (``pii``, ``protected``) follow the lineage from tagged
   inputs.
3. **The Contract agent** writes the grain, picks the key among the candidates and names
   partition columns. Its key must be a candidate.

:func:`validate` is what H2 enforces before approval: the keys are unique in the golden
output, and every policy other than ``exact`` is justified by the engine, not by a wish to
match. A text tolerance on a T-SQL output is refused unless the job sorts text under its
collation (trap TSQL-19): SQL Server stores and returns the value exactly, so a migrated job
can and must reproduce it. ``exclude`` needs a volatile column, ``surrogate`` an IDENTITY
column and ``float_rel`` a SAS job.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from lansh.config import REPO_ROOT
from lansh.contracts import (
    ColumnSpec,
    ColumnTag,
    ComparisonPolicy,
    ContractColumn,
    DataContract,
    Effort,
    EstateInventory,
    JobSpec,
    Language,
    LineageEdge,
    LineageKind,
    PolicyKind,
    SlaSpec,
    TrapFinding,
)
from lansh.lakehouse import golden_table, lakehouse_name, layer_of
from lansh.llm.answers import ContractAnswer
from lansh.llm.request import ClaudeRequest

SAS_DOUBLE_TOLERANCE = 1e-9
# at most this many columns in a candidate key, and this many columns tried for one
_MAX_KEY_SIZE = 3
_KEY_SEARCH_COLUMNS = 12
_DEFAULT_RUNTIME_LIMIT = 600.0

_SAS_DOUBLE_REASON = (
    "SAS stores every number as an 8-byte double and adds them in input order; a migrated sum "
    "or ratio may differ in the last bits, so values agree within a relative 1e-9"
)
_SAS_TEXT_REASON = (
    "SAS character values are blank-padded and SAS has no empty string: trailing blanks are "
    "padding and a blank value is missing, so blank and NULL are the same value"
)
_VOLATILE_REASON = "volatile audit column (estate/jobs.yaml): it changes on every run"


### Reading the legacy DDL


def _create_table(text: str, table: str) -> str | None:
    """
    Find the body of a table's CREATE TABLE statement in a T-SQL script.
    """
    schema, name = table.split(".", 1)
    pattern = re.compile(
        rf"CREATE\s+TABLE\s+\[?{re.escape(schema)}\]?\.\[?{re.escape(name)}\]?\s*\(",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
    return text[m.end() : i - 1]


def ddl_primary_key(text: str, table: str) -> list[str]:
    """
    Read a table's primary key from its CREATE TABLE statement.

    Args:
        text: The T-SQL deployment script.
        table: The table, such as ``rpt.claims_summary``.

    Returns:
        The key columns in order; empty when the table or its key isn't declared.
    """
    body = _create_table(text, table)
    if body is None:
        return []
    m = re.search(r"PRIMARY\s+KEY(?:\s+(?:CLUSTERED|NONCLUSTERED))?\s*\(([^)]*)\)", body, re.I)
    if m:
        return [c.strip().strip("[]").split()[0] for c in m.group(1).split(",") if c.strip()]
    inline = re.search(r"^\s*\[?(\w+)\]?\s+[^,\n]*\bPRIMARY\s+KEY\b", body, re.I | re.M)
    return [inline.group(1)] if inline else []


def identity_columns(text: str, table: str) -> list[str]:
    """
    Name a table's IDENTITY columns from its CREATE TABLE statement.

    Args:
        text: The T-SQL deployment script.
        table: The table.

    Returns:
        The IDENTITY columns, in table order.
    """
    body = _create_table(text, table) or ""
    return re.findall(r"^\s*\[?(\w+)\]?\s+\w+\s+IDENTITY\s*\(", body, re.I | re.M)


### Profiling the golden output


@dataclass
class Profile:
    """
    What the golden output looks like, for choosing keys and partitions.

    Attributes:
        distinct: Distinct values per column.
        nulls: NULL values per column.
        candidate_keys: Column sets, smallest first, that are unique and never NULL.
    """

    rows: int
    distinct: dict[str, int] = field(default_factory=dict)
    nulls: dict[str, int] = field(default_factory=dict)
    candidate_keys: list[list[str]] = field(default_factory=list)


def is_unique(data: pa.Table, columns: list[str]) -> bool:
    """
    Tell whether a column set identifies every row: no NULL in it and no repeated value.

    Args:
        data: The rows.
        columns: The column set.

    Returns:
        True for a key.
    """
    if not columns:
        return False
    for name in columns:
        if data.column(name).null_count:
            return False
    counts = data.group_by(columns).aggregate([([], "count_all")])
    return counts.num_rows == data.num_rows


def _keyable(column: pa.ChunkedArray) -> bool:
    """
    Tell whether a column can be part of a key: not an amount, and not a fractional double.

    A decimal with a scale is an amount, unique only by chance. SAS stores ids as doubles, so a
    double holding only whole numbers can still be a key.
    """
    if pa.types.is_decimal(column.type):
        return column.type.scale == 0
    if not pa.types.is_floating(column.type):
        return True
    values = pc.drop_null(column)
    return len(values) == 0 or pc.all(pc.equal(values, pc.floor(values))).as_py()


def profile(data: pa.Table, *, preferred: list[str] = (), skip: list[str] = ()) -> Profile:  # type: ignore[assignment]
    """
    Profile a golden output: distinct and NULL counts, and its candidate keys.

    Args:
        data: The golden output.
        preferred: A key to try first, such as the DDL's primary key.
        skip: Columns never used in a key (volatile or IDENTITY ones).

    Returns:
        The profile.
    """
    result = Profile(rows=data.num_rows)
    for name in data.column_names:
        col = data.column(name)
        result.nulls[name] = col.null_count
        result.distinct[name] = pc.count_distinct(col, mode="all").as_py()
    keys: list[list[str]] = []
    if preferred and is_unique(data, list(preferred)):
        keys.append(list(preferred))
    usable = [
        c
        for c in data.column_names
        if c not in skip and not result.nulls[c] and _keyable(data.column(c))
    ]
    for size in range(1, _MAX_KEY_SIZE + 1):
        # every single column and pair; triples only among the first columns
        pool = usable if size < _MAX_KEY_SIZE else usable[:_KEY_SEARCH_COLUMNS]
        for combo in itertools.combinations(pool, size):
            if any(set(k) <= set(combo) for k in keys):
                continue  # a superset of a key is never minimal
            if is_unique(data, list(combo)):
                keys.append(list(combo))
        if keys and size >= len(keys[0]):
            break
    result.candidate_keys = keys
    return result


### Tags and policies


def column_tags(
    lineage: list[LineageEdge], inputs: dict[str, list[ColumnSpec]], table: str
) -> dict[str, list[ColumnTag]]:
    """
    Carry ``pii`` and ``protected`` tags from tagged input columns to the outputs they feed.

    Args:
        lineage: The job's verified lineage.
        inputs: Its input tables' columns, with their tags.
        table: The output table.

    Returns:
        Tags by output column, for the columns that derive from a tagged input.
    """
    tagged = {(t, c.name.casefold()): c.tags for t, cols in inputs.items() for c in cols if c.tags}
    out: dict[str, set[ColumnTag]] = {}
    for e in lineage:
        if e.output_table != table or e.kind is not LineageKind.DERIVES or not e.output_column:
            continue
        tags = tagged.get((e.input_table or "", (e.input_column or "").casefold()))
        if tags:
            out.setdefault(e.output_column, set()).update(tags)
    return {c: sorted(t, key=lambda tag: tag.value) for c, t in out.items()}


def default_policy(job: JobSpec, column: ColumnSpec, volatile: list[str]) -> ComparisonPolicy:
    """
    Give a column's default comparison policy, with its reason when it isn't ``exact``.

    Args:
        job: The job.
        column: The output column.
        volatile: The output's volatile columns.

    Returns:
        The policy.
    """
    if column.name in volatile:
        return ComparisonPolicy(kind=PolicyKind.EXCLUDE, reason=_VOLATILE_REASON)
    if job.language is Language.SAS:
        if column.data_type == "double":
            return ComparisonPolicy(
                kind=PolicyKind.FLOAT_REL,
                rel_tolerance=SAS_DOUBLE_TOLERANCE,
                reason=_SAS_DOUBLE_REASON,
            )
        if column.data_type == "string":
            return ComparisonPolicy(kind=PolicyKind.BLANK_IS_NULL, reason=_SAS_TEXT_REASON)
    return ComparisonPolicy()


def _key_safe(policy: ComparisonPolicy, is_key: bool) -> ComparisonPolicy:
    """
    Keep a key column comparable: rows are joined on it, so it can't be a tolerance.

    A SAS id is a double, whose default is ``float_rel``; as a key it compares exactly (ids are
    whole numbers). A text key keeps ``blank_is_null``, which joins as well as it compares.
    """
    if is_key and policy.kind is PolicyKind.FLOAT_REL:
        return ComparisonPolicy()
    return policy


### The Contract agent

CONTRACT_SYSTEM = """\
You are the contract agent of LANSH, a factory that migrates legacy jobs to PySpark and proves \
every output matches the legacy output record for record. For one output table, say what one \
row represents (the grain), choose its business key from the candidate keys you are given \
(prefer a meaningful business key to a generated one), and name at most two \
low-cardinality columns worth counting rows by. Comparison policies are not yours to choose.
"""


def contract_request(
    job: JobSpec, table: str, columns: list[ColumnSpec], prof: Profile, legacy_text: str
) -> ClaudeRequest[ContractAnswer]:
    """
    Build the Contract agent's request for one output.

    Args:
        job: The job.
        table: The output table.
        columns: Its columns.
        prof: The golden output's profile.
        legacy_text: The legacy code, for what the columns mean.

    Returns:
        The request.
    """
    shown = "\n".join(
        f"- {c.name} {c.legacy_type or c.data_type}: {prof.distinct.get(c.name, 0)} distinct, "
        f"{prof.nulls.get(c.name, 0)} NULL"
        for c in columns
    )
    keys = "\n".join(f"- {k}" for k in prof.candidate_keys) or "- (none: compare as a multiset)"
    prompt = (
        f"Job {job.job_id}: {job.name}. {job.description or ''}\n"
        f"Output table {table}, {prof.rows} rows in the legacy output.\n\n"
        f"Columns:\n{shown}\n\nCandidate keys (unique and never NULL):\n{keys}\n\n"
        f"Legacy code:\n{legacy_text}\n"
    )
    return ClaudeRequest(
        agent="contract",
        job_id=job.job_id,
        system_prompt=CONTRACT_SYSTEM,
        prompt=prompt,
        response_model=ContractAnswer,
        effort=Effort.LOW.value,
    )


@dataclass
class ContractDraft:
    """
    A proposed contract with what H2 must see about it.

    Attributes:
        contract: The proposed contract.
        profile: The golden output's profile.
        identity: The output's IDENTITY columns.
        blockers: What stops H2 being approved.
        warnings: What the H2 reviewer must read.
    """

    contract: DataContract
    profile: Profile
    identity: list[str]
    blockers: list[str]
    warnings: list[str]


def build_contract(
    job: JobSpec,
    inventory: EstateInventory,
    table: str,
    lineage: list[LineageEdge],
    inputs: dict[str, list[ColumnSpec]],
    traps: list[TrapFinding],
    gateway: object | None = None,
) -> ContractDraft:
    """
    Propose one output's contract and check it as H2 will.

    Args:
        job: The job.
        inventory: The estate inventory.
        table: The output table.
        lineage: The job's verified lineage.
        inputs: Its input tables' columns, with tags.
        traps: Its trap findings (TSQL-19 justifies a text tolerance).
        gateway: The Claude gateway for the Contract agent; deterministic choices without.

    Returns:
        The draft, validated.
    """
    from lansh.contracts import Stage

    golden = golden_table(inventory, table)
    data = pq.read_table(golden.path)
    legacy_text = (REPO_ROOT / job.path).read_text(encoding="utf-8")
    identity = identity_columns(legacy_text, table) if job.language is Language.TSQL else []
    volatile = list(golden.output.volatile_columns)
    pk = ddl_primary_key(legacy_text, table) if job.language is Language.TSQL else []
    preferred = [] if set(pk) & set(identity) else pk
    prof = profile(data, preferred=preferred, skip=[*volatile, *identity])
    columns = list(golden.output.columns)
    grain = f"one row of {table}"
    keys = prof.candidate_keys[0] if prof.candidate_keys else []
    partitions: list[str] = []
    notes: dict[str, str] = {}
    warnings: list[str] = []
    if gateway is not None:
        request = contract_request(job, table, columns, prof, legacy_text)
        answer = gateway.ask(request, Stage.DESIGN).output  # type: ignore[attr-defined]
        grain = answer.grain
        if answer.keys in prof.candidate_keys:
            keys = list(answer.keys)
        elif answer.keys:
            warnings.append(
                f"the Contract agent's key {answer.keys} is not a candidate key; kept {keys}"
            )
        names = {c.name.casefold(): c.name for c in columns}
        partitions = [
            names[p.casefold()] for p in answer.partition_columns[:2] if p.casefold() in names
        ]
        partitions = [p for p in partitions if p not in keys]
        notes = {
            names[k.casefold()]: v for k, v in answer.column_notes.items() if k.casefold() in names
        }
    tags = column_tags(lineage, inputs, table)
    contract = DataContract(
        job_id=job.job_id,
        table=lakehouse_name(table),
        legacy_table=table,
        layer=layer_of(table),
        grain=grain,
        keys=keys,
        columns=[
            ContractColumn(
                **c.model_dump(exclude={"tags", "description"}),
                tags=sorted(set(c.tags) | set(tags.get(c.name, [])), key=lambda t: t.value),
                description=notes.get(c.name) or c.description,
                policy=_key_safe(default_policy(job, c, volatile), c.name in keys),
            )
            for c in columns
        ],
        partition_columns=partitions,
        sla=SlaSpec(
            max_runtime_seconds=_DEFAULT_RUNTIME_LIMIT,
            expected_rows=golden.output.rows,
            row_tolerance_pct=10.0,
        ),
    )
    blockers, more = validate(
        contract, job, data, volatile=volatile, identity=identity, traps=traps
    )
    return ContractDraft(contract, prof, identity, blockers, warnings + more)


def validate(
    contract: DataContract,
    job: JobSpec,
    data: pa.Table,
    *,
    volatile: list[str],
    identity: list[str],
    traps: list[TrapFinding],
) -> tuple[list[str], list[str]]:
    """
    Check a contract as H2 does before approval (plan §6.3).

    Args:
        contract: The contract.
        job: Its job.
        data: The golden output.
        volatile: The output's volatile columns.
        identity: The output's IDENTITY columns.
        traps: The job's trap findings.

    Returns:
        The blockers (H2 refuses approval while any remains) and the warnings (each
        non-exact policy, which needs the reviewer's reason).
    """
    blockers, warnings = [], []
    if contract.keys and not is_unique(data, list(contract.keys)):
        blockers.append(f"key {contract.keys} is not unique (or has NULLs) in the golden output")
    if not contract.keys:
        warnings.append("no key: the output is compared as a multiset")
    collation_order = any(t.trap_id == "TSQL-19" for t in traps)
    for col in contract.columns:
        kind, where = col.policy.kind, f"{contract.legacy_table}.{col.name}"
        if kind is PolicyKind.EXACT:
            continue
        refused = None
        if kind in (PolicyKind.CI_RTRIM, PolicyKind.RTRIM, PolicyKind.BLANK_IS_NULL):
            if job.language is Language.TSQL and not collation_order:
                refused = (
                    f"{kind.value} on {where} is a tolerance with no reason: SQL Server stores "
                    "and returns the value exactly, so the migrated job must reproduce it"
                )
        elif kind is PolicyKind.FLOAT_REL and job.language is not Language.SAS:
            refused = f"float_rel on {where}: only SAS doubles may be compared within a tolerance"
        elif kind is PolicyKind.EXCLUDE and col.name not in volatile:
            refused = f"exclude on {where}: only volatile audit columns may be left out"
        elif kind is PolicyKind.SURROGATE and col.name not in identity:
            refused = f"surrogate on {where}: only IDENTITY (generated) keys are surrogates"
        if refused:
            blockers.append(refused)
        else:
            warnings.append(f"{kind.value} on {where}: {col.policy.reason}")
    return blockers, warnings


def save_contract(contract: DataContract, root: Path) -> Path:
    """
    Write a contract as JSON, named after its legacy table.

    Args:
        contract: The contract.
        root: The contracts folder.

    Returns:
        The file written.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{contract.legacy_table}.json"
    path.write_text(contract.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
