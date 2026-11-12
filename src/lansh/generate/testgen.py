"""
Trap-focused tests: inputs from the Test author agent, expected values from the legacy engine.

Plan §8.7. For every semantic trap Discover found, the Test author agent writes a small input
set (5 to 20 rows per table) on which a naive translation would go wrong. The inputs are then
run through the **legacy job itself**, in a scratch SQL Server database (``LanshTest``) with the
real collation, so the expected values come from the legacy engine and never from Claude.
Construct traps need no test of their own: running and reconciling the job covers them.

Each job's cases are written as one self-contained JSON file (the input and output schemas,
the contract's keys and policies, the invocations and the cases) beside a short pytest file
that runs the migrated module on each case and reconciles it with the expected rows, under the
contract's policies. The files live in the run folder and, once H3 and H4 approve the job, in
``migrated/tests/``.

SAS jobs: running each case through SAS OnDemand is slow, so their tests check the contract
instead (``expected_source="contract"``): the module must run on the inputs and produce the
contract's columns with unique keys (plan §8.7's fallback when saspy isn't used).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa

from lansh.config import RUNS_DIR
from lansh.contracts import (
    ColumnSpec,
    DataContract,
    Effort,
    EstateInventory,
    JobSpec,
    Language,
    Stage,
    TableRows,
    TestCase,
    TrapFinding,
    TrapKind,
)
from lansh.discover.split import numbered
from lansh.discover.traps import load_cards
from lansh.llm.answers import TestAuthorAnswer
from lansh.llm.request import ClaudeRequest

log = logging.getLogger(__name__)

TEST_DATABASE = "LanshTest"
MAX_ROWS = 20
# the legacy engine's answers to test inputs, recorded so tests replay without SQL Server
LEGACY_RESULTS_DIR = RUNS_DIR / "cassettes" / "legacy"

TEST_AUTHOR_SYSTEM = """\
You are the test author agent of LANSH, a factory that migrates legacy {language} jobs to \
PySpark and must reproduce their output exactly. For each semantic trap you are given, write \
one small input set (5 to 20 rows per table) on which a naive translation of this job would \
give a different result from the legacy engine, while the job still produces output rows.

- Use only the job's input tables and their columns; respect each column's legacy type and \
length (a VARCHAR(5) value has at most 5 characters) and fill every NOT NULL column.
- Write every value as text: dates YYYY-MM-DD, datetimes YYYY-MM-DDTHH:MM:SS, numbers as plain \
decimals; use null for NULL. Leave _row_seq out: the rows' order is their _row_seq.
- Include the related rows the job needs to produce output (for example, a claim's payments) and \
rows on both sides of the trap (the variant that a naive translation mishandles, and the \
canonical value).
- The expected output is computed by running the legacy job itself on your rows, so never \
state expected values.
"""


def test_author_request(
    job: JobSpec,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    traps: list[TrapFinding],
) -> ClaudeRequest[TestAuthorAnswer]:
    """
    Build the Test author agent's request: one case per semantic trap found in the job.

    Args:
        job: The job.
        text: Its legacy code.
        inputs: Its input tables' columns.
        traps: Its trap findings; only semantic ones get a case.

    Returns:
        The request.
    """
    cards = load_cards()
    semantic = [t for t in traps if cards[t.trap_id].kind is TrapKind.SEMANTIC]
    findings = "\n".join(
        f"- {t.trap_id} ({cards[t.trap_id].title}) at lines {t.line_start}-{t.line_end}: "
        f"{t.note or ''}"
        for t in semantic
    )
    shown = "\n".join(
        f"- {t}: "
        + ", ".join(
            f"{c.name} {c.legacy_type or c.data_type}{'' if c.nullable else ' NOT NULL'}"
            for c in cols
            if c.name != "_row_seq"
        )
        for t, cols in inputs.items()
    )
    calls = "; ".join(
        ", ".join(f"{k}={v}" for k, v in inv.params.items()) for inv in job.invocations
    )
    prompt = (
        f"Job {job.job_id}: {job.name}. Parameters per run, in order: {calls}.\n\n"
        f"Code:\n{numbered(text)}\n\nInput tables:\n{shown}\n\n"
        f"Semantic traps to test (one case per distinct trap id):\n{findings or '(none)'}\n"
    )
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    return ClaudeRequest(
        agent="test_author",
        job_id=job.job_id,
        system_prompt=TEST_AUTHOR_SYSTEM.format(language=language),
        prompt=prompt,
        response_model=TestAuthorAnswer,
        effort=Effort.MEDIUM.value,
    )


### Typed rows


def _parse(value: str | None, data_type: str) -> Any:
    """
    Turn one text value into the Python value of a logical type.

    Raises:
        ValueError: If the text doesn't fit the type.
    """
    if value is None:
        return None
    if data_type in ("int", "bigint", "smallint", "tinyint"):
        return int(Decimal(value))
    if data_type.startswith("decimal("):
        scale = int(data_type[8:-1].split(",")[1])
        try:
            return Decimal(value).quantize(Decimal(1).scaleb(-scale))
        except InvalidOperation as exc:
            raise ValueError(f"{value!r} is not a decimal") from exc
    if data_type in ("double", "float"):
        return float(value)
    if data_type == "date":
        return dt.date.fromisoformat(value[:10])
    if data_type in ("timestamp_ntz", "timestamp"):
        return dt.datetime.fromisoformat(value.replace(" ", "T"))
    if data_type == "boolean":
        return value.strip().lower() in ("1", "true", "y", "yes")
    return value


def _default(data_type: str) -> Any:
    """
    Give a NOT NULL column's filler value when a test row leaves it out.
    """
    if data_type.startswith("decimal(") or data_type in ("int", "bigint", "smallint", "tinyint"):
        return "0"
    if data_type in ("double", "float"):
        return "0"
    if data_type == "date":
        return "1900-01-01"
    if data_type.startswith("timestamp"):
        return "1900-01-01T00:00:00"
    return ""


def typed_table(rows: list[dict[str, str | None]], columns: list[ColumnSpec]) -> pa.Table:
    """
    Build a typed Arrow table from text rows, in the table's column order.

    Columns a row leaves out are NULL, or a filler when the column is NOT NULL; ``_row_seq`` is
    the row's position when not given.

    Args:
        rows: The rows, as the Test author wrote them.
        columns: The table's columns.

    Returns:
        The table.

    Raises:
        ValueError: If a value doesn't fit its column's type, or a row names an unknown column.
    """
    from lansh.estate.generate import arrow_type

    names = {c.name.casefold(): c for c in columns}
    for row in rows:
        unknown = [k for k in row if k.casefold() not in names]
        if unknown:
            raise ValueError(f"unknown columns {unknown}")
    arrays = []
    for col in columns:
        values = []
        for i, row in enumerate(rows, 1):
            given = {k.casefold(): v for k, v in row.items()}
            if col.name == "_row_seq" and given.get("_row_seq") is None:
                raw: str | None = str(i)
            else:
                raw = given.get(col.name.casefold())
            if raw is None and not col.nullable:
                raw = _default(col.data_type)
            values.append(_parse(raw, col.data_type))
        arrays.append(pa.array(values, type=arrow_type(col.data_type)))
    return pa.Table.from_arrays(arrays, names=[c.name for c in columns])


def _text(value: Any) -> str | None:
    """
    Write one value as canonical text: plain decimals, ISO dates, NULL as None.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def table_rows(table: str, data: pa.Table) -> TableRows:
    """
    Write a table's rows as canonical text, for a test case.

    Args:
        table: The table's name.
        data: Its rows.

    Returns:
        The rows as the contract's ``TableRows``.
    """
    columns = data.column_names
    lists = [data.column(c).to_pylist() for c in columns]
    rows = [[_text(v) for v in row] for row in zip(*lists, strict=True)]
    return TableRows(table=table, columns=columns, rows=rows)


### Expected values from the legacy engine


def legacy_outputs(
    job: JobSpec,
    inventory: EstateInventory,
    tables: dict[str, pa.Table],
    database: str = TEST_DATABASE,
) -> dict[str, pa.Table]:
    """
    Run the legacy T-SQL job on a test's inputs in a scratch database, and read its outputs.

    Every source table is created (empty unless the test fills it); an upstream output the test
    fills is created by deploying its producer's script first.

    Args:
        job: The T-SQL job.
        inventory: The estate inventory.
        tables: The test's input rows by table.
        database: The scratch database, dropped and recreated.

    Returns:
        Each output's rows, as SQL Server returns them.
    """
    from lansh.config import REPO_ROOT
    from lansh.engines import mssql
    from lansh.estate.legacy import BASE_DDL, STG_DDL
    from lansh.estate.runner import run_tsql_job

    mssql.recreate_database(database)
    with mssql.connect(database) as conn:
        mssql.run_script(conn, BASE_DDL.read_text(encoding="utf-8"))
        mssql.run_script(conn, STG_DDL.read_text(encoding="utf-8"))
        producers = inventory.producers()
        for table in job.inputs:
            if table in inventory.sources:
                continue
            upstream = inventory.job(producers[table])
            mssql.run_script(conn, (REPO_ROOT / upstream.path).read_text(encoding="utf-8"))
        for table, data in tables.items():
            if not data.num_rows:
                continue
            identity = _identity_columns(inventory, table)
            if identity:
                # a test row gives the generated key explicitly, as the upstream job made it
                conn.cursor().execute(f"SET IDENTITY_INSERT {mssql.quote_table(table)} ON")
            mssql.load_table(conn, table, data)
            if identity:
                conn.cursor().execute(f"SET IDENTITY_INSERT {mssql.quote_table(table)} OFF")
        run_tsql_job(job, conn)
        return {o.table: mssql.fetch_table(conn, o.table)[1] for o in job.outputs}


def legacy_key(job: JobSpec, legacy_sha256: str, tables: dict[str, pa.Table]) -> str:
    """
    Key one test's legacy result: the legacy code's hash, the invocations and the input rows.
    """
    from lansh.estate.fingerprint import content_sha256, text_sha256

    parts = [legacy_sha256, json.dumps([i.model_dump(mode="json") for i in job.invocations])]
    parts += [f"{t}:{content_sha256(data)}" for t, data in sorted(tables.items())]
    return text_sha256("|".join(parts))


def recorded_outputs(
    job: JobSpec,
    inventory: EstateInventory,
    tables: dict[str, pa.Table],
    *,
    store: Path = LEGACY_RESULTS_DIR,
) -> list[TableRows]:
    """
    Give a test's expected outputs: recorded if this exact test ran before, else from SQL Server.

    A fresh result is recorded at once, so the suite replays offline later (``make demo`` needs
    no Docker), and a result recorded for other code or other rows is never reused.

    Args:
        job: The T-SQL job.
        inventory: The estate inventory.
        tables: The test's input rows by table.
        store: Where legacy results are recorded.

    Returns:
        The expected rows of each output.
    """
    from lansh.config import REPO_ROOT
    from lansh.estate.fingerprint import file_sha256

    key = legacy_key(job, file_sha256(REPO_ROOT / job.path), tables)
    path = store / f"{key}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return [TableRows.model_validate(r) for r in data["outputs"]]
    got = legacy_outputs(job, inventory, tables)
    rows = [table_rows(t, data) for t, data in got.items()]
    store.mkdir(parents=True, exist_ok=True)
    record = {"job_id": job.job_id, "outputs": [r.model_dump(mode="json") for r in rows]}
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rows


def _identity_columns(inventory: EstateInventory, table: str) -> list[str]:
    """
    Name a T-SQL output's IDENTITY columns, from the deployment script of the job that writes it.
    """
    from lansh.config import REPO_ROOT
    from lansh.design.contract import identity_columns

    if table in inventory.sources:
        return []
    producer = inventory.job(inventory.producers()[table])
    if producer.language is not Language.TSQL:
        return []
    return identity_columns((REPO_ROOT / producer.path).read_text(encoding="utf-8"), table)


### Cases and their files


@dataclass
class TestSuite:
    """
    A job's trap-focused tests, ready to write and run.

    Attributes:
        cases: The test cases with their expected outputs.
        schemas: Every input table's columns.
        outputs: Every output table's columns.
        notes: Cases dropped, and why.
    """

    __test__ = False  # not a pytest test class

    job_id: str
    cases: list[TestCase]
    schemas: dict[str, list[ColumnSpec]]
    outputs: dict[str, list[ColumnSpec]]
    contracts: list[DataContract]
    invocations: list[dict[str, Any]]
    state_tables: list[str]
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """
        Give the suite as the JSON its pytest file reads.
        """
        return {
            "job_id": self.job_id,
            "schemas": {
                t: [c.model_dump(mode="json") for c in cols] for t, cols in self.schemas.items()
            },
            "outputs": {
                t: [c.model_dump(mode="json") for c in cols] for t, cols in self.outputs.items()
            },
            "contracts": [c.model_dump(mode="json") for c in self.contracts],
            "invocations": self.invocations,
            "state_tables": self.state_tables,
            "cases": [c.model_dump(mode="json") for c in self.cases],
        }


def build_suite(
    job: JobSpec,
    inventory: EstateInventory,
    text: str,
    inputs: dict[str, list[ColumnSpec]],
    outputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
    traps: list[TrapFinding],
    gateway: Any,
    *,
    legacy: bool = True,
) -> TestSuite:
    """
    Ask the Test author for inputs and compute each case's expected output with the legacy engine.

    Args:
        job: The job.
        inventory: The estate inventory.
        text: Its legacy code.
        inputs: Its input tables' columns.
        outputs: Its output tables' columns.
        contracts: Its outputs' contracts.
        traps: Its trap findings.
        gateway: The Claude gateway.
        legacy: Run T-SQL cases on SQL Server for their expected values (False keeps contract
            checks only, as for SAS).

    Returns:
        The suite; cases whose inputs don't fit the schema or whose legacy run fails are
        dropped, with a note.
    """
    answer = gateway.ask(test_author_request(job, text, inputs, traps), Stage.GENERATE).output
    suite = TestSuite(
        job_id=job.job_id,
        cases=[],
        schemas=inputs,
        outputs=outputs,
        contracts=contracts,
        invocations=[inv.model_dump(mode="json") for inv in job.invocations],
        state_tables=list(job.state_tables),
    )
    use_legacy = legacy and job.language is Language.TSQL
    known = {t.casefold(): t for t in inputs}
    for number, case in enumerate(answer.cases, 1):
        test_id = f"{job.job_id}-{case.trap_id}-{number}"
        try:
            tables = {}
            for given in case.tables:
                table = known.get(given.table.casefold())
                if table is None or table in job.state_tables:
                    raise ValueError(f"{given.table} is not an input of {job.job_id}")
                tables[table] = typed_table(given.rows[:MAX_ROWS], inputs[table])
            expected = None
            if use_legacy:
                expected = recorded_outputs(job, inventory, tables)
        except Exception as exc:  # a case that doesn't fit, or that the legacy job refuses
            suite.notes.append(f"{test_id} dropped: {str(exc).splitlines()[0][:200]}")
            continue
        suite.cases.append(
            TestCase(
                test_id=test_id,
                job_id=job.job_id,
                trap_id=case.trap_id,
                description=case.description,
                inputs=[table_rows(t, data) for t, data in tables.items()],
                expected=expected,
                expected_source="legacy_engine" if use_legacy else "contract",
            )
        )
    return suite


TEST_FILE = '''"""
Trap-focused tests of the migrated {job_id} module (generated by LANSH, plan §8.7).

Inputs come from the Test author agent; expected outputs come from running the legacy job on
the same inputs ({source}). Each case runs the migrated module and reconciles its output with
the expected rows under the output contract's policies.
"""

import json
from pathlib import Path

import pytest

from lansh.generate.testgen import run_case

CASES = Path(__file__).with_name("cases") / "{stem}.json"
MODULE = Path(__file__).parents[1] / "jobs" / "{stem}.py"


@pytest.mark.parametrize("test_id", [c["test_id"] for c in json.loads(CASES.read_text())["cases"]])
def test_trap_case(test_id: str) -> None:
    run_case(CASES, MODULE, test_id)
'''


def write_suite(suite: TestSuite, tests_dir: Path) -> tuple[Path, Path]:
    """
    Write a suite's cases file and its pytest file.

    Args:
        suite: The suite.
        tests_dir: The ``tests`` folder beside the ``jobs`` folder holding the module.

    Returns:
        The cases file and the test file.
    """
    stem = suite.job_id.lower()
    cases = tests_dir / "cases" / f"{stem}.json"
    cases.parent.mkdir(parents=True, exist_ok=True)
    cases.write_text(json.dumps(suite.to_json(), indent=2) + "\n", encoding="utf-8")
    source = (
        "SQL Server, in a scratch database"
        if any(c.expected_source == "legacy_engine" for c in suite.cases)
        else "contract checks: SAS isn't run per case"
    )
    test_file = tests_dir / f"test_{stem}.py"
    test_file.write_text(TEST_FILE.format(job_id=suite.job_id, stem=stem, source=source), "utf-8")
    return cases, test_file


### Running a case (called by the generated test files)


def run_case(cases_path: Path, module_path: Path, test_id: str) -> None:
    """
    Run the migrated module on one case and check its output.

    Args:
        cases_path: The suite's JSON file.
        module_path: The migrated module.
        test_id: The case to run.

    Raises:
        AssertionError: With the reconciliation's explanation, if an output differs from the
            legacy engine's, or breaks its contract.
    """
    from pyspark.sql import functions as F

    from lansh.generate.worker import load_module
    from lansh.lakehouse import conform, empty_frame
    from lansh.reconcile.engine import compare, contract_inputs
    from lansh.spark import get_spark

    data = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    case = TestCase.model_validate(next(c for c in data["cases"] if c["test_id"] == test_id))
    schemas = {
        t: [ColumnSpec.model_validate(c) for c in cols] for t, cols in data["schemas"].items()
    }
    outputs = {
        t: [ColumnSpec.model_validate(c) for c in cols] for t, cols in data["outputs"].items()
    }
    contracts = {c["legacy_table"]: DataContract.model_validate(c) for c in data["contracts"]}
    spark = get_spark()
    given = {r.table: r for r in case.inputs}
    frames = {}
    for table, cols in schemas.items():
        if table in data["state_tables"]:
            continue
        rows = given.get(table)
        if rows is None:
            frames[table] = empty_frame(spark, cols)
            continue
        dicts = [dict(zip(rows.columns, r, strict=True)) for r in rows.rows]
        frames[table] = spark.createDataFrame(typed_table(dicts, cols).to_pandas(), _ddl(cols))
    for table in data["state_tables"]:
        frames[table] = empty_frame(spark, outputs[table])
    module = load_module(Path(module_path))
    result: dict[str, Any] = {}
    for invocation in data["invocations"]:
        params = {k: str(v) for k, v in invocation["params"].items()}
        got = {k.lower(): v for k, v in module.run(spark, dict(frames), params).items()}
        result = {t: conform(got[t], cols) for t, cols in outputs.items()}
        for table in data["state_tables"]:
            frames[table] = result[table].localCheckpoint(eager=True)
    for table, actual in result.items():
        contract = contracts.get(table)
        settings = contract_inputs(contract) if contract else {}
        if case.expected is None:
            keys = settings.get("keys") or []
            assert set(actual.columns) == {c.name for c in outputs[table]}
            if keys:
                dupes = actual.groupBy(*keys).count().where(F.col("count") > 1).count()
                assert dupes == 0, f"{table}: {dupes} duplicate keys"
            continue
        rows = next(r for r in case.expected if r.table == table)
        dicts = [dict(zip(rows.columns, r, strict=True)) for r in rows.rows]
        cols = outputs[table]
        expected = (
            spark.createDataFrame(typed_table(dicts, cols).to_pandas(), _ddl(cols))
            if dicts
            else empty_frame(spark, cols)
        )
        recon = compare(expected, actual, **settings)
        assert recon.is_match, f"{test_id} {table}: {recon.explain()}"


def _ddl(columns: list[ColumnSpec]) -> str:
    """
    Give a Spark DDL schema for columns.
    """
    from lansh.lakehouse import schema_ddl

    return schema_ddl(columns)


def run_suite(test_file: Path, *, timeout_s: float = 900.0) -> tuple[int, int, str]:
    """
    Run a generated test file in its own pytest process.

    Args:
        test_file: The pytest file.
        timeout_s: Seconds before the run is stopped.

    Returns:
        Tests passed, tests failed (errors included) and the tail of pytest's output.
    """
    import re

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
             str(test_file)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return 0, 1, f"the tests did not finish within {timeout_s:.0f} s"
    # pytest's timing changes on every run; the evidence shouldn't
    out = re.sub(r" in [0-9.]+s( \([0-9:]+\))?", "", proc.stdout + proc.stderr)
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", out))
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", out))
    if proc.returncode not in (0, 1) and not failed:
        failed = 1
    return passed, failed, "\n".join(out.strip().splitlines()[-25:])
