"""
The comparison runs: what LANSH's proof loop adds over simpler approaches (plan §9.5, step 3.10).

Each approach migrates the same development jobs, and every result goes through the same
reconciliation as the factory's, against the same golden outputs:

- **sqlglot alone.** The deterministic draft, made runnable without any judgement: every
  data statement sqlglot transpiles becomes a Spark SQL query over temporary views (inputs as
  ``stg_claims``, temp tables as themselves), ``SELECT @v = ...`` becomes a scalar parameter,
  and the final ``INSERT ... SELECT`` becomes the output. sqlglot's optimizer gets the input
  schemas, so it can type each query (T-SQL's ``+`` on text becomes ``CONCAT``). Anything else
  (``UPDATE``, ``MERGE``, a cursor, SAS) can't be drafted, and the job counts as not migrated.
- **One-shot Claude.** One translation per job with the same model and effort as the factory's
  Translator, but no trap cards, no sqlglot draft, no notes and no healing.
- **LANSH**, from the factory run: the full proof loop.

The guardrails still run on every one-shot module, and one they refuse is not run. The sqlglot
modules are deterministic, not agent-written: they pass the syntax-tree check, but they bind
the job's parameters into their SQL text at run time, which an agent's module may not do.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lansh.config import REPO_ROOT, RUNS_DIR
from lansh.contracts import (
    Approach,
    ColumnSpec,
    DataContract,
    EstateInventory,
    JobSpec,
    Language,
    ReconMode,
    ReconStatus,
)
from lansh.estate.golden import rel
from lansh.lakehouse import write_json

log = logging.getLogger(__name__)

_DATA = re.compile(r"^\s*(SELECT|INSERT|UPDATE|MERGE|DELETE|WITH)\b", re.I)
_UNSUPPORTED = re.compile(r"^\s*(UPDATE|MERGE|DELETE)\b|\bCURSOR\b|\bFETCH\b|\bWHILE\b", re.I)
_PARAM = re.compile(r"\$\{(\w+)\}")


class NotDraftable(Exception):
    """
    sqlglot alone can't express the job: a statement it can't parse, or one it can't run.
    """


def _rewrite_tables(tree: Any) -> Any:
    """
    Point every table at its temporary view: ``stg.claims`` as ``stg_claims``, ``#t`` as ``t``.
    """
    from sqlglot import exp

    for table in tree.find_all(exp.Table):
        db, name = table.db, table.name.lstrip("#")
        table.set("db", None)
        table.set("catalog", None)
        table.set("this", exp.to_identifier(f"{db}_{name}" if db else name))
    return tree


def _spark(tree: Any) -> str:
    """
    Write a statement as Spark SQL with ``:name`` parameter markers.
    """
    return _PARAM.sub(r":\1", tree.sql(dialect="spark"))


def _typed(query: Any, schema: Any) -> Any:
    """
    Let sqlglot's optimizer type a query and canonicalise it, or leave it as it is.

    With the column types known, sqlglot rewrites what depends on them, such as T-SQL's ``+``
    on text into ``CONCAT``. A query it can't qualify stays as parsed.
    """
    from sqlglot.errors import SqlglotError
    from sqlglot.optimizer.annotate_types import annotate_types
    from sqlglot.optimizer.canonicalize import canonicalize
    from sqlglot.optimizer.qualify import qualify

    try:
        typed = qualify(
            query.copy(),
            schema=schema,
            dialect="tsql",
            validate_qualify_columns=False,
            quote_identifiers=False,
        )
        return canonicalize(annotate_types(typed, schema=schema))
    except SqlglotError, KeyError, ValueError, TypeError, AttributeError:
        return query


def _register(schema: Any, view: str, query: Any) -> None:
    """
    Record a temporary table's columns and the types sqlglot inferred for them.
    """
    columns = {
        s.alias_or_name: (s.type.sql("spark") if s.type else "UNKNOWN") for s in query.selects
    }
    if all(columns):
        schema.add_table(view, columns, dialect="spark")


def sqlglot_module(
    job: JobSpec, text: str, schemas: dict[str, list[ColumnSpec]] | None = None
) -> str:
    """
    Turn a T-SQL job into a runnable module using sqlglot's translation alone.

    Given the input tables' schemas, sqlglot's own optimizer types every query, and the types
    it infers for each temporary table carry on to the statements that read it.

    Args:
        job: The job.
        text: Its legacy code.
        schemas: The input tables' columns, by legacy name.

    Returns:
        The module's source.

    Raises:
        NotDraftable: For a SAS job, or one with a statement sqlglot can't parse or run.
    """
    import sqlglot
    from sqlglot import exp
    from sqlglot.schema import MappingSchema

    from lansh.discover.split import split_code

    if job.language is not Language.TSQL:
        raise NotDraftable("sqlglot has no SAS dialect")
    schema = MappingSchema(
        {
            table.replace(".", "_"): {c.name: c.data_type for c in columns}
            for table, columns in (schemas or {}).items()
        },
        dialect="spark",
    )
    targets = {o.table for o in job.outputs}
    steps: list[str] = []
    outputs: dict[str, str] = {}
    for block in split_code(text, job.language):
        code = " ".join(block.code.split())
        if (
            block.kind != "statement"
            or not _DATA.match(code)
            or code.upper().startswith("SELECT @ERR")
        ):
            continue
        if _UNSUPPORTED.search(code):
            raise NotDraftable(
                f"lines {block.line_start}-{block.line_end}: {code[:40]}... has no draft"
            )
        if not block.sqlglot_parsed:
            raise NotDraftable(f"lines {block.line_start}-{block.line_end}: sqlglot can't parse it")
        tree = sqlglot.parse_one(block.code, read="tsql")
        if isinstance(tree, exp.Select) and all(
            isinstance(e, exp.EQ) and isinstance(e.this, exp.Parameter) for e in tree.expressions
        ):
            # SELECT @v = expr FROM ...: a scalar, passed on as a parameter
            for eq in tree.expressions:
                name = eq.this.name
                query = tree.copy()
                query.set("expressions", [eq.expression.copy().as_("v")])
                sql = _spark(_typed(_rewrite_tables(query), schema))
                steps.append(f"args[{name!r}] = spark.sql(_bind({sql!r}, args)).first()[0]")
            continue
        if isinstance(tree, exp.Select) and isinstance(tree.args.get("into"), exp.Into):
            view = tree.args["into"].this.name.lstrip("#")
            query = tree.copy()
            query.set("into", None)
            query = _typed(_rewrite_tables(query), schema)
            _register(schema, view, query)
            sql = _spark(query)
            steps.append(f"spark.sql(_bind({sql!r}, args)).createOrReplaceTempView({view!r})")
            continue
        if isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Select):
            into = tree.this
            table = into.this if isinstance(into, exp.Schema) else into
            name = ".".join(p for p in (table.db, table.name) if p).lower()
            select = tree.expression.copy()
            cols = [c.name for c in into.expressions] if isinstance(into, exp.Schema) else []
            if cols and len(cols) == len(select.expressions):
                select.set(
                    "expressions",
                    [p.unalias().as_(c) for p, c in zip(select.expressions, cols, strict=True)],
                )
            select = _typed(_rewrite_tables(select), schema)
            if name in targets:
                outputs[name] = _spark(select)
            else:
                view = name.split(".")[-1].lstrip("#")
                _register(schema, view, select)
                sql = _spark(select)
                steps.append(f"spark.sql(_bind({sql!r}, args)).createOrReplaceTempView({view!r})")
            continue
        if isinstance(tree, exp.Select):
            continue  # a bare SELECT returns rows to the caller; the job's output is elsewhere
        raise NotDraftable(f"lines {block.line_start}-{block.line_end}: no runnable draft")
    if set(outputs) != targets:
        raise NotDraftable(f"no INSERT ... SELECT fills {sorted(targets - set(outputs))}")
    body = "\n    ".join(steps)
    returns = ", ".join(f"{t!r}: spark.sql(_bind({q!r}, args))" for t, q in outputs.items())
    return f'''"""
{job.job_id}: sqlglot's translation alone, made runnable (a LANSH comparison run, plan §9.5).
"""


import datetime
import decimal


def _bind(sql, args):
    """Put each parameter's value into the SQL text as a literal, longest name first."""
    for name in sorted(args, key=len, reverse=True):
        value = args[name]
        if value is None:
            text = "NULL"
        elif isinstance(value, (int, float, decimal.Decimal)):
            text = str(value)
        elif isinstance(value, datetime.date):
            text = "DATE'" + value.isoformat()[:10] + "'"
        else:
            text = "'" + str(value).replace("'", "''") + "'"
        sql = sql.replace(":" + name, text)
    return sql


def run(spark, inputs, params):
    for name, frame in inputs.items():
        frame.createOrReplaceTempView(name.replace(".", "_"))
    args = dict(params)
    {body}
    return {{{returns}}}
'''


@dataclass
class BenchmarkResult:
    """
    One approach on one job.

    Attributes:
        status: MATCH, MISMATCH, ERROR, or NOT_MIGRATED when the approach produced no module.
        rows_differing: Value, missing and extra rows, across the job's outputs.
        note: Why there was no module, or what stopped it running.
    """

    job_id: str
    approach: str
    status: str
    rows_differing: int | None = None
    note: str = ""
    reports: list[str] = field(default_factory=list)


def run_approach(
    ctx: Any,
    approach: Approach,
    job_ids: list[str],
    contracts: dict[str, DataContract],
) -> list[BenchmarkResult]:
    """
    Migrate jobs one way and reconcile each against its golden outputs.

    Args:
        ctx: The pipeline's run context (its gateway and Spark session are used).
        approach: ``sqlglot_only`` or ``oneshot_claude``.
        job_ids: The jobs.
        contracts: The approved contracts by legacy table, so every approach is compared on
            the same keys and policies.

    Returns:
        One result per job.
    """
    from lansh.discover.traps import signature_lookup
    from lansh.generate.job import check, generate_job, job_provenance, write_module
    from lansh.lakehouse import input_schemas
    from lansh.reconcile.job import run_and_reconcile

    inventory: EstateInventory = ctx.inventory
    out = []
    for job_id in job_ids:
        job = inventory.job(job_id)
        folder = RUNS_DIR / ctx.run_id / "benchmark" / approach.value / job_id
        text = (REPO_ROOT / job.path).read_text(encoding="utf-8")
        job_contracts = [contracts[o.table] for o in job.outputs if o.table in contracts]
        try:
            if approach is Approach.SQLGLOT_ONLY:
                module = write_module(
                    sqlglot_module(job, text, input_schemas(inventory, job)),
                    folder / "jobs" / f"{job_id.lower()}.py",
                )
                guard = None
            else:
                inputs = input_schemas(inventory, job, contracts)
                generated = generate_job(
                    job,
                    inventory,
                    text,
                    [],
                    inputs,
                    job_contracts,
                    [],
                    "",
                    ctx.gateway,
                    folder / "jobs",
                    oneshot=True,
                )
                module, guard = generated.module, generated.guardrails
                if not guard.passed:
                    raise NotDraftable(
                        "refused by the guardrails: " + "; ".join(guard.violations)[:300]
                    )
            if guard is None:
                guard = check(
                    module, job_provenance(job, text, input_schemas(inventory, job), job_contracts)
                )
        except NotDraftable as exc:
            out.append(BenchmarkResult(job_id, approach.value, "NOT_MIGRATED", note=str(exc)))
            continue
        run = run_and_reconcile(
            ctx.spark,
            inventory,
            job,
            module,
            folder / "run",
            mode=ReconMode.ISOLATED,
            contracts={c.legacy_table: c for c in job_contracts},
            run_id=ctx.run_id,
            approach=approach,
            traps_for=signature_lookup(job.language),
        )
        paths = [
            rel(write_json(folder / f"{r.table}.recon.json", r.model_dump(mode="json")))
            for r in run.reports
        ]
        differing = sum(
            r.rows.differences for r in run.reports if r.status is not ReconStatus.ERROR
        )
        error = next((r.error for r in run.reports if r.status is ReconStatus.ERROR), None)
        out.append(
            BenchmarkResult(
                job_id,
                approach.value,
                run.status.value,
                rows_differing=None if error else differing,
                note=(error or "")[:300],
                reports=paths,
            )
        )
        log.info("benchmark %s %s: %s", approach.value, job_id, run.status.value)
    return out


def write_benchmark(run_id: str, results: list[BenchmarkResult]) -> Path:
    """
    Write the comparison runs' results, ``runs/<run>/benchmark.json``.

    Args:
        run_id: The run.
        results: Every approach's results.

    Returns:
        The file written.
    """
    path = RUNS_DIR / run_id / "benchmark.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    keep = [
        r
        for r in existing
        if (r["approach"], r["job_id"]) not in {(x.approach, x.job_id) for x in results}
    ]
    rows = keep + [r.__dict__ for r in results]
    return write_json(path, sorted(rows, key=lambda r: (r["approach"], r["job_id"])))


ONESHOT_HEALED = "oneshot_claude+heal"
"""The approach label of one-shot translations repaired by LANSH's heal loop alone."""


def heal_oneshot(
    ctx: Any, job_ids: list[str], contracts: dict[str, DataContract]
) -> list[BenchmarkResult]:
    """
    Repair each failed one-shot translation with LANSH's heal loop, and nothing else.

    This isolates what the diagnose-patch-rerun loop adds on its own. The starting code is the
    one-shot module. The fixer sees the reconciliation and the trap cards its diff signatures
    point at, but no trap findings from Discover. Every patch passes the same guardrails and
    reconciliation, with at most 3 attempts.

    Args:
        ctx: The pipeline's run context.
        job_ids: The jobs to consider; only those whose one-shot run gave MISMATCH or ERROR
            (in ``benchmark.json``) are healed.
        contracts: The approved contracts by legacy table.

    Returns:
        One result per job healed, labelled ``oneshot_claude+heal``.
    """
    from lansh.contracts import ReconReport
    from lansh.generate.job import job_provenance
    from lansh.lakehouse import input_schemas
    from lansh.reconcile.heal import heal

    inventory: EstateInventory = ctx.inventory
    done = json.loads((RUNS_DIR / ctx.run_id / "benchmark.json").read_text(encoding="utf-8"))
    failed = {
        r["job_id"]
        for r in done
        if r["approach"] == Approach.ONESHOT_CLAUDE.value and r["status"] in ("MISMATCH", "ERROR")
    }
    out = []
    for job_id in [j for j in job_ids if j in failed]:
        job = inventory.job(job_id)
        base = RUNS_DIR / ctx.run_id / "benchmark" / Approach.ONESHOT_CLAUDE.value / job_id
        module = base / "jobs" / f"{job_id.lower()}.py"
        reports = [
            ReconReport.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(base.glob("*.recon.json"))
        ]
        if not module.exists() or not reports:
            continue
        text = (REPO_ROOT / job.path).read_text(encoding="utf-8")
        inputs = input_schemas(inventory, job, contracts)
        job_contracts = [contracts[o.table] for o in job.outputs if o.table in contracts]
        result = heal(
            job, inventory, ctx.spark, module, reports,
            RUNS_DIR / ctx.run_id / "benchmark" / ONESHOT_HEALED / job_id / "attempts", ctx.gateway,
            legacy_text=text, inputs=inputs, contracts=job_contracts, traps=[],
            provenance=job_provenance(job, text, inputs, job_contracts), run_id=ctx.run_id,
        )  # fmt: skip
        status = result.status.value
        differing = sum(
            r.rows.differences for r in result.reports if r.status is not ReconStatus.ERROR
        )
        note = f"{len(result.attempts)} heal attempts" + (
            f"; escalated: {result.escalation.diagnosis[:200]}" if result.escalation else ""
        )
        folder = RUNS_DIR / ctx.run_id / "benchmark" / ONESHOT_HEALED / job_id
        paths = [
            rel(write_json(folder / f"{r.table}.recon.json", r.model_dump(mode="json")))
            for r in result.reports
        ]
        # the heal timeline, for the Control Tower: each attempt's diagnosis, patch and score
        write_json(
            folder / "heal.json",
            {
                "job_id": job_id,
                "status": status,
                "attempts": [a.model_dump(mode="json") for a in result.attempts],
                "escalation": (
                    result.escalation.model_dump(mode="json") if result.escalation else None
                ),
            },
        )
        out.append(BenchmarkResult(job_id, ONESHOT_HEALED, status, differing, note, reports=paths))
        log.info(
            "benchmark %s %s: %s after %d attempts",
            ONESHOT_HEALED,
            job_id,
            status,
            len(result.attempts),
        )
    return out
