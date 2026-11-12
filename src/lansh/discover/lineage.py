"""
Column-level lineage: the Lineage agent, its verification, and the sqlglot cross-check (plan §8.3).

The Lineage agent reads the whole job and lists, for every output column, the input columns
its value derives from, plus the columns that decide which rows appear (filters) or which row
survives (ranks). Nothing it says is trusted until checked:

- **Verification.** Every table and column it names must exist in the job's input or output
  schemas, compared case-insensitively. An edge naming anything else is refused and reported
  at H1; the lineage that remains names only real columns.
- **Cross-check.** For T-SQL, sqlglot parses each statement it can and traces each projected
  column to its sources. Composing those per-statement results through ``SELECT ... INTO #temp``
  tables gives an independent lineage of every output column a parsed ``INSERT ... SELECT``
  fills. An output column agrees when every agent ``derives`` edge is among sqlglot's sources
  and every sqlglot source is named by the agent (as a derivation or a filter). Columns written
  through cursors, MERGE or UPDATE get no cross-check (``agrees_with_sqlglot`` stays None):
  there is no hand-built tracing through them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from lansh.contracts import (
    ColumnSpec,
    Effort,
    JobSpec,
    Language,
    LineageEdge,
    LineageKind,
)
from lansh.discover.split import Block, numbered
from lansh.llm.answers import LineageAnswer
from lansh.llm.request import ClaudeRequest

log = logging.getLogger(__name__)

Source = tuple[str, str]
"""An input column as (table, column), both folded to lower case."""

LINEAGE_SYSTEM = """\
You are the lineage agent of LANSH, a factory that migrates legacy {language} jobs to PySpark \
and proves each migrated output matches the legacy output record for record.

Map the job's column-level lineage, from its input tables to its output tables:
- for every output column, list every input column whose value flows into it (derives), \
tracing through temp tables, variables, cursors, work data sets and macros back to the job's \
INPUT tables (never name a temp table or work data set as an input);
- list the input columns that decide which rows appear in an output (filters: WHERE, JOIN ON, \
HAVING, IN= and subsetting IF conditions) and which row survives (ranks: the ORDER BY of a \
ROW_NUMBER, NODUPKEY, FIRST./LAST.), with output_column null;
- a job parameter (@AsOfDate, &as_of) is a parameter edge; a literal value is a constant edge; \
an IDENTITY key or load timestamp is a generated edge;
- name only tables and columns listed in the schemas; give the lines that show each edge.
"""


def _fold(text: str) -> str:
    """
    Fold a name for comparison: lower case, without brackets or quotes.
    """
    for char in '[]"`':
        text = text.replace(char, "")
    return text.strip().casefold()


def _schema_text(schemas: dict[str, list[ColumnSpec]]) -> str:
    """
    List tables and their columns with legacy types, one table per line.
    """
    return "\n".join(
        f"- {t}: " + ", ".join(f"{c.name} {c.legacy_type or c.data_type}" for c in cols)
        for t, cols in schemas.items()
    )


def lineage_request(
    job: JobSpec,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
) -> ClaudeRequest[LineageAnswer]:
    """
    Build the Lineage agent's request for one job.

    Args:
        job: The job.
        text: Its legacy code.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.

    Returns:
        The request.
    """
    params = sorted({k for inv in job.invocations for k in inv.params})
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    prompt = (
        f"Job {job.job_id}: {job.name} ({job.language.value}), file {job.path}.\n"
        f"{job.description or ''}\nParameters: {', '.join(params) or 'none'}"
        f"{' (in SAS, the macro variable &as_of)' if job.language is Language.SAS else ''}.\n\n"
        f"Code:\n{numbered(text)}\n\n"
        f"Input tables:\n{_schema_text(inputs)}\n\n"
        f"Output tables:\n{_schema_text(outputs)}\n"
    )
    return ClaudeRequest(
        agent="lineage",
        job_id=job.job_id,
        system_prompt=LINEAGE_SYSTEM.format(language=language),
        prompt=prompt,
        response_model=LineageAnswer,
        effort=Effort.MEDIUM.value,
    )


def verify_lineage(
    job: JobSpec,
    answer: LineageAnswer,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
) -> tuple[list[LineageEdge], list[str]]:
    """
    Check every edge the agent named against the schemas and keep only those that hold.

    Args:
        job: The job.
        answer: The Lineage agent's answer.
        inputs: The job's input tables' columns.
        outputs: Its output tables' columns.

    Returns:
        The verified edges (spelt as the schemas spell them), and one message per refused
        edge.
    """
    in_cols = {_fold(t): (t, {_fold(c.name): c.name for c in cols}) for t, cols in inputs.items()}
    out_cols = {_fold(t): (t, {_fold(c.name): c.name for c in cols}) for t, cols in outputs.items()}
    params = {_fold(k) for inv in job.invocations for k in inv.params} | {"as_of"}
    edges, refused = [], []
    for e in answer.edges:
        where = f"{e.output_table}.{e.output_column or '*'} <- {e.input_table}.{e.input_column}"
        out = out_cols.get(_fold(e.output_table))
        if out is None:
            refused.append(f"{where}: {e.output_table} is not an output of {job.job_id}")
            continue
        out_table, out_names = out
        out_column = None
        if e.output_column is not None:
            out_column = out_names.get(_fold(e.output_column))
            if out_column is None:
                refused.append(f"{where}: {out_table} has no column {e.output_column!r}")
                continue
        in_table = in_column = None
        if e.input_kind == "column":
            found = in_cols.get(_fold(e.input_table or ""))
            if found is None:
                refused.append(f"{where}: {e.input_table} is not an input of {job.job_id}")
                continue
            in_table, names = found
            in_column = names.get(_fold(e.input_column or ""))
            if in_column is None:
                refused.append(f"{where}: {in_table} has no column {e.input_column!r}")
                continue
        elif e.input_kind == "parameter":
            name = _fold((e.input_column or "").lstrip("@&"))
            if name not in params:
                refused.append(f"{where}: {e.input_column!r} is not a parameter of the job")
                continue
            in_column = e.input_column
        kind = LineageKind(e.kind)
        if kind is LineageKind.DERIVES and out_column is None:
            refused.append(f"{where}: a derives edge needs an output column")
            continue
        edges.append(
            LineageEdge(
                job_id=job.job_id,
                output_table=out_table,
                output_column=out_column,
                input_kind=e.input_kind,
                input_table=in_table,
                input_column=in_column,
                kind=kind,
                transform=e.transform or None,
                source="llm",
                confidence=e.confidence,
                verified=True,
                evidence_lines=sorted({n for n in e.lines if n >= 1}),
            )
        )
    return edges, refused


def missing_lineage(
    edges: Iterable[LineageEdge], outputs: dict[str, list[ColumnSpec]]
) -> list[str]:
    """
    Name the output columns no edge feeds, for the H1 reviewer.

    Args:
        edges: The verified edges.
        outputs: The output tables' columns.

    Returns:
        ``table.column`` for each output column without a derives edge of any input kind.
    """
    fed = {(e.output_table, _fold(e.output_column)) for e in edges if e.output_column}
    return [
        f"{t}.{c.name}"
        for t, cols in outputs.items()
        for c in cols
        if (t, _fold(c.name)) not in fed
    ]


### sqlglot cross-check


def _source(node: object) -> Source | None:
    """
    Read a lineage leaf as (table, column), or None for a leaf that isn't a table column.
    """
    from sqlglot import exp

    source = getattr(node, "source", None)
    expression = getattr(node, "expression", None)
    if not isinstance(source, exp.Table):
        return None
    column = expression.name if isinstance(expression, exp.Column) else None
    if column is None:
        name = getattr(node, "name", "")
        column = name.split(".")[-1] if name else None
    if not column:
        return None
    table = ".".join(p for p in (source.db, source.name) if p)
    return _fold(table), _fold(column)


def _leaves(column: str, select_sql: str, schema: dict) -> set[Source] | None:
    """
    Trace one projected column of a SELECT to the table columns it comes from.
    """
    from sqlglot.lineage import lineage

    try:
        root = lineage(column, select_sql, schema=schema, dialect="tsql")
    except Exception:  # sqlglot can't trace every statement; no cross-check then
        return None
    found = set()
    for node in root.walk():
        if node.downstream:
            continue
        src = _source(node)
        if src is not None:
            found.add(src)
    return found


def sqlglot_lineage(
    blocks: list[Block],
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
) -> dict[tuple[str, str], set[Source]]:
    """
    Trace output columns to input columns with sqlglot, composing through temp tables.

    Args:
        blocks: The job's T-SQL blocks.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.

    Returns:
        For each (output table, output column) that a parsed ``INSERT ... SELECT`` fills, the
        input columns it derives from; columns sqlglot couldn't trace are left out.
    """
    import sqlglot
    from sqlglot import exp

    schema: dict[str, dict[str, dict[str, str]]] = {}
    for table, cols in inputs.items():
        db, name = table.split(".", 1)
        schema.setdefault(db, {})[name] = {c.name: (c.legacy_type or "VARCHAR") for c in cols}
    temps: dict[str, dict[str, set[Source]]] = {}
    out: dict[tuple[str, str], set[Source]] = {}
    sqlglot_log = logging.getLogger("sqlglot")
    level = sqlglot_log.level
    sqlglot_log.setLevel(logging.ERROR)
    try:
        for block in blocks:
            if block.kind != "statement" or not block.sqlglot_parsed:
                continue
            try:
                tree = sqlglot.parse_one(block.code, read="tsql")
            except Exception:  # unparseable after all: skip it
                continue
            target: str | None = None
            select: exp.Select | None = None
            names: list[str] = []
            if isinstance(tree, exp.Select) and isinstance(tree.args.get("into"), exp.Into):
                target = _fold(tree.args["into"].this.name).lstrip("#")
                select = tree.copy()
                select.set("into", None)
                names = [p.alias_or_name for p in select.expressions]
            elif isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Select):
                into = tree.this
                table = into.this if isinstance(into, exp.Schema) else into
                if not isinstance(table, exp.Table):
                    continue
                target = _fold(".".join(p for p in (table.db, table.name) if p))
                select = tree.expression.copy()
                listed = [c.name for c in into.expressions] if isinstance(into, exp.Schema) else []
                names = listed or [p.alias_or_name for p in select.expressions]
                if len(names) != len(select.expressions):
                    continue
                select.set(
                    "expressions",
                    [
                        exp.alias_(p.unalias(), n)
                        for p, n in zip(select.expressions, names, strict=False)
                    ],
                )
            if target is None or select is None:
                continue
            temp_schema = {
                **schema,
                "": {f"#{t}": {c: "VARCHAR" for c in cols} for t, cols in temps.items()},
            }
            sql = select.sql(dialect="tsql")
            traced: dict[str, set[Source]] = {}
            for name in names:
                leaves = _leaves(name, sql, temp_schema)
                if leaves is None:
                    continue
                composed: set[Source] = set()
                for table, column in leaves:
                    temp = temps.get(table.lstrip("#"))
                    if temp is not None:
                        composed |= temp.get(column, set())
                    else:
                        composed.add((table, column))
                traced[_fold(name)] = composed
            if target in {_fold(t) for t in outputs}:
                for name, sources in traced.items():
                    out[(target, name)] = sources
            else:
                temps[target] = traced
    finally:
        sqlglot_log.setLevel(level)
    return out


def cross_check(
    edges: list[LineageEdge], traced: dict[tuple[str, str], set[Source]]
) -> tuple[list[LineageEdge], list[str]]:
    """
    Mark each edge with the sqlglot verdict on its output column, and list disagreements.

    Args:
        edges: The verified edges.
        traced: sqlglot's lineage, from :func:`sqlglot_lineage`.

    Returns:
        The edges with ``agrees_with_sqlglot`` set where sqlglot traced the column, and one
        message per output column on which the two disagree.
    """
    row_level = {
        (e.output_table, _fold(e.input_table or ""), _fold(e.input_column or ""))
        for e in edges
        if e.output_column is None and e.input_kind == "column"
    }
    verdicts: dict[tuple[str, str], bool] = {}
    problems = []
    for (table, column), sources in sorted(traced.items()):
        derives = {
            (_fold(e.input_table or ""), _fold(e.input_column or ""))
            for e in edges
            if e.output_table == table
            and e.output_column
            and _fold(e.output_column) == column
            and e.input_kind == "column"
        }
        named = derives | {(t, c) for (o, t, c) in row_level if o == table}
        extra = derives - sources
        unnamed = sources - named
        agrees = not extra and not unnamed
        verdicts[(table, column)] = agrees
        if not agrees:
            bits = []
            if extra:
                bits.append(f"agent only: {sorted('.'.join(s) for s in extra)}")
            if unnamed:
                bits.append(f"sqlglot only: {sorted('.'.join(s) for s in unnamed)}")
            problems.append(
                f"lineage of {table}.{column} disagrees with sqlglot ({'; '.join(bits)})"
            )
    out = []
    for e in edges:
        key = (e.output_table, _fold(e.output_column)) if e.output_column else None
        if key in verdicts:
            e = e.model_copy(update={"agrees_with_sqlglot": verdicts[key]})
        out.append(e)
    return out, problems
