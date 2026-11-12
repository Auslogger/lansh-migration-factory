"""
Generate's draft, guardrails, translator request and test generation (plan step 2.6).

The translation tests replay Claude's recorded answer for T04 (``runs/cassettes/``).
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from lansh.config import REPO_ROOT
from lansh.contracts import ColumnSpec, Language
from lansh.discover.split import split_code
from lansh.discover.traps import allowed_literals
from lansh.generate.draft import make_draft
from lansh.generate.guardrails import (
    check_literals,
    check_module,
    check_strings,
    check_tree,
    parse_sql,
    provenance_for,
)
from lansh.generate.testgen import table_rows, typed_table

T04 = REPO_ROOT / "estate" / "tsql" / "T04_usp_build_claims_summary.sql"
PROVENANCE = provenance_for(
    "SELECT status FROM stg.claims WHERE status IN ('OPEN') AND n > 30 -- 365",
    ["stg.claims", "status", "n", "claim_id"],
    {"AsOfDate": "2025-12-31"},
    allowed_literals(),
)


def tree(source: str) -> ast.Module:
    """
    Parse a module's source.
    """
    return ast.parse(source)


### 1. the syntax tree


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("import os\ndef run(s, i, p): pass", "import os"),
        ("from subprocess import run as r\ndef run(s, i, p): pass", "from subprocess"),
        ("def run(s, i, p): return s.read.parquet('x')", ".read"),
        ("def run(s, i, p): return i['a'].write", ".write"),
        ("def run(s, i, p): return s.sparkContext", ".sparkContext"),
        ("def run(s, i, p): return s._jvm", "._jvm"),
        ("def run(s, i, p): return i['a'].rdd", ".rdd"),
        ("def run(s, i, p): return i['a'].cache()", ".cache"),
        ("def run(s, i, p): s.conf.set('spark.sql.ansi.enabled', 'false')", ".conf"),
        ("def run(s, i, p): return eval('1')", "eval()"),
        ("def run(s, i, p): return getattr(s, '_jvm')", "getattr()"),
        ("def run(s, i, p): return s.__class__", "dunder"),
        ("from pyspark.sql import functions as F\ndef run(s, i, p): return F.udf(len)", ".udf"),
        ("def other(): pass", "no run"),
    ],
)
def test_tree_refusals(source: str, found: str) -> None:
    assert any(found in v for v in check_tree(tree(source))), check_tree(tree(source))


def test_allowed_module_passes_the_tree_check() -> None:
    ok = (
        "from __future__ import annotations\n"
        "import math, re, datetime, decimal, functools, typing\n"
        "from pyspark.sql import DataFrame, Window, functions as F\n"
        "def run(spark, inputs, params):\n"
        "    return {'rpt.x': inputs['stg.y'].select(F.col('a'))}\n"
    )
    assert check_tree(tree(ok)) == []


### 2. SQL strings


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TRANSFORM(a) USING 'cat /etc/passwd' FROM t",
        "SELECT reflect('java.lang.Runtime', 'getRuntime')",
        "SELECT java_method('java.lang.System', 'exit', 0)",
        "SELECT * FROM csv.`/etc/passwd`",
        "ADD JAR /tmp/evil.jar",
        "CREATE FUNCTION f AS 'Evil'",
        "LOAD DATA LOCAL INPATH '/x' INTO TABLE t",
        "SET spark.sql.ansi.enabled = false",
    ],
)
def test_sql_strings_are_scanned(sql: str) -> None:
    source = f"def run(spark, inputs, params):\n    return {{'rpt.x': spark.sql({sql!r})}}\n"
    found, _ = check_strings(tree(source))
    assert found, sql


def test_sql_must_be_a_plain_literal_and_queries_parse() -> None:
    found, _ = check_strings(tree("def run(s, i, p):\n    return s.sql(f\"SELECT {p['x']}\")"))
    assert any("f-string" in f for f in found)
    assert parse_sql("SELECT a FROM t WHERE b = 'x'") == []
    assert parse_sql("upper(rtrim(status)) IN ('OPEN')") == []  # an expression, as F.expr takes


### 3. the literal check


def literals(body: str) -> dict[str, str]:
    """
    Map each data literal in a run() body to its provenance.
    """
    source = (
        "from pyspark.sql import functions as F\n"
        f"def run(spark, inputs, params):\n    df = inputs['stg.claims']\n    {body}\n"
        "    return {'rpt.x': df}\n"
    )
    t = tree(source)
    _, sql = check_strings(t)
    return {f.value: f.provenance for f in check_literals(t, PROVENANCE, sql)}


def test_literals_need_provenance() -> None:
    found = literals(
        "df = df.where(F.col('status') == 'OPEN').withColumn('n2', F.lit(300035))"
        ".withColumn('f', F.date_format('d', 'dd/MM/yyyy')).withColumn('k', F.lit(365))"
    )
    assert found["OPEN"] == "legacy"
    assert found["300035"] == "none"  # a hard-coded data value blocks H3
    assert found["dd/MM/yyyy"] == "trap_card"  # TSQL-16's fix brings the format
    assert found["365"] == "legacy"  # numbers in comments still count as legacy text
    assert "status" not in found  # names are not data
    assert "n2" not in found


def test_short_strings_need_a_whole_literal_or_word() -> None:
    assert literals("df = df.withColumn('x', F.lit('Q'))")["Q"] == "none"
    assert literals("df = df.withColumn('x', F.lit('IN'))")["IN"] == "legacy"


def test_sql_text_literals_are_checked_one_by_one() -> None:
    found = literals("df = df.where(\"status = 'OPEN' AND n > 30 AND claim_id <> 777\")")
    assert found == {"OPEN": "legacy", "30": "legacy", "777": "none"}


def test_check_module_on_the_naive_fixture() -> None:
    report = check_module(REPO_ROOT / "tests" / "fixtures" / "t04_naive.py", PROVENANCE)
    assert report.passed
    assert {lit.value for lit in report.literals} >= {"OPEN", "REOPENED", "/", "yyyyMM"}


### the draft


def test_draft_transpiles_statements_with_their_traps() -> None:
    from lansh.contracts import TrapFinding

    text = T04.read_text()
    trap = TrapFinding(
        job_id="T04",
        trap_id="TSQL-01",
        line_start=73,
        line_end=73,
        snippet="",
        detector="rule",
        confidence=0.5,
    )
    draft = make_draft(Language.TSQL, split_code(text, Language.TSQL), [trap])
    assert "-- lines 63-74; traps: TSQL-01 (line 73)" in draft
    assert "CREATE TEMPORARY TABLE" in draft  # SELECT ... INTO #open_claims, as Spark SQL
    assert "usp_log_step" not in draft  # logging is the harness's business
    assert "INSERT INTO rpt.claims_summary" in draft


### typed test rows


def test_typed_rows_round_trip_with_fillers_and_row_seq() -> None:
    columns = [
        ColumnSpec(name="id", data_type="int", nullable=False),
        ColumnSpec(name="amount", data_type="decimal(12,2)"),
        ColumnSpec(name="d", data_type="date", nullable=False),
        ColumnSpec(name="_row_seq", data_type="int", nullable=False),
    ]
    table = typed_table([{"id": "7", "amount": "1.5"}, {"ID": "8", "amount": None}], columns)
    assert table.column("amount").to_pylist() == [Decimal("1.50"), None]
    assert table.column("_row_seq").to_pylist() == [1, 2]
    rows = table_rows("stg.x", table)
    assert rows.rows[0] == ["7", "1.50", "1900-01-01", "1"]
    with pytest.raises(ValueError, match="unknown columns"):
        typed_table([{"nope": "1"}], columns)


def test_t04_translation_replays_and_passes_the_guardrails(tmp_path: Path) -> None:
    from lansh.design.contract import build_contract
    from lansh.discover.job import discover_job
    from lansh.estate.inventory import load_inventory
    from lansh.generate.job import defects_marked, generate_job
    from lansh.lakehouse import input_schemas
    from lansh.llm.gateway import ClaudeGateway

    inventory = load_inventory()
    job = inventory.job("T04")
    gateway = ClaudeGateway(mode="replay")
    found = discover_job(job, inventory, gateway)
    inputs = input_schemas(inventory, job)
    contracts = [
        build_contract(
            job, inventory, "rpt.claims_summary", found.lineage, inputs, found.traps, gateway
        ).contract
    ]
    notes = next(w.split(": ", 1)[1] for w in found.warnings if w.startswith("lineage agent notes"))
    text = T04.read_text()
    result = generate_job(
        job,
        inventory,
        text,
        split_code(text, Language.TSQL),
        inputs,
        contracts,
        found.traps,
        notes,
        gateway,
        tmp_path,
    )
    assert result.guardrails.passed
    assert result.guardrails.blocking_literals == []
    assert {"TSQL-01", "TSQL-02", "TSQL-05", "TSQL-16"} <= set(result.artifact.traps_handled)
    assert defects_marked(result.module)  # BUG-03's fan-out is reproduced and marked
    assert result.artifact.defects_reproduced


def test_names_built_from_parts_are_names() -> None:
    found = literals(
        "df = df.withColumn('d' + str(1), F.lit(0)).select(F.col('d' + str(1)), F.col(f'x{1}'))"
        ".withColumn('y', F.lit('QZ' + 'Q'))"
    )
    assert "d" not in found  # part of a column name
    assert "x" not in found
    assert found["QZ"] == "none"  # data built from parts is still data


def test_exception_messages_are_not_data() -> None:
    found = literals(
        "df = df.withColumn('z', F.lit(1))\n"
        "    if df.isEmpty():\n"
        "        raise RuntimeError('a MERGE hit the same row twice')"
    )
    assert "a MERGE hit the same row twice" not in found


def test_like_patterns_translated_by_the_card_derive_from_legacy() -> None:
    provenance = provenance_for(
        "WHERE reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'", ["reg"], {}, allowed_literals()
    )
    assert provenance.of("(?is)^[0-9][0-9].*-[A-Z].*-[0-9]") == "trap_card"
    assert provenance.of("^300035$") == "none"  # a hard-coded value leaves a foreign piece


def test_python_re_patterns_are_not_data() -> None:
    found = literals(
        "import re\n    if re.fullmatch(r'-?[0-9]+', params['AsOfDate']):\n        pass\n"
        "    df = df.where(F.col('status').rlike('^777$'))"
    )
    assert "-?[0-9]+" not in found  # parses the job's own parameter text
    assert found["^777$"] == "none"  # a Spark pattern touches data, so it is still checked


def test_a_types_precision_and_scale_are_not_data() -> None:
    source = (
        "from pyspark.sql import functions as F\n"
        "def _trunc(c, scale):\n"
        "    return F.floor(c, scale)\n"
        "def run(spark, inputs, params):\n"
        "    df = inputs['stg.claims']\n"
        "    df = df.withColumn('q', F.expr('CAST(n AS DECIMAL(38,10)) * 30 + 777'))\n"
        "    df = df.withColumn('r', _trunc(F.col('n').cast('decimal(36,13)'), 13))\n"
        "    df = df.withColumn('s', F.round(F.col('n'), 13))\n"
        "    df = df.where(F.col('n') == 13)\n"
        "    df = df.withColumn('t', _trunc(F.col('n'), 17))\n"
        "    return {'rpt.x': df}\n"
    )
    t = tree(source)
    _, sql = check_strings(t)
    found = {(f.line, f.value): f.provenance for f in check_literals(t, PROVENANCE, sql)}
    assert (6, "38") not in found  # a SQL type's parameters
    assert found[(6, "777")] == "none"  # a number beside them is still data
    assert found[(7, "13")] == "trap_card"  # the scale T-SQL's type rules give, declared
    assert found[(8, "13")] == "trap_card"
    assert found[(9, "13")] == "none"  # compared with data, it is data
    assert found[(10, "17")] == "none"  # a scale the module never declares in a decimal type
