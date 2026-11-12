"""
The reconciliation engine and its harness catch every kind of difference (plan step 2.1).

The planted-table tests in ``test_spark_recon_spike.py`` cover the policies, collations,
totals and datacompy on the spike's planted tables; they run against this same engine. This
module covers what step 2.1 added: case-insensitive names, masked samples, unpartnered-row
samples, explanations, diff signatures, double totals, the lakehouse staging, the worker,
and the whole harness on T04's real golden output with a deliberately naive candidate.
"""

from __future__ import annotations

import ast
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from pyspark.sql import SparkSession

from lansh.config import REPO_ROOT
from lansh.contracts import (
    ColumnSpec,
    ComparisonPolicy,
    DiffSignatureKind,
    PolicyKind,
    ReconMode,
    ReconStatus,
    RowCounts,
)
from lansh.estate.inventory import load_inventory
from lansh.generate.template import SIGNATURE, skeleton
from lansh.generate.worker import WorkerSpec, load_module, run_in_worker, worker_env
from lansh.lakehouse import (
    conform,
    delta_path,
    golden_table,
    lakehouse_name,
    layer_of,
    stage_inputs,
)
from lansh.reconcile.engine import (
    compare,
    datacompy_summary,
    disagreements,
    mask_value,
)
from lansh.reconcile.job import candidate_hash, report_markdown, run_and_reconcile
from lansh.reconcile.signatures import detect

pytestmark = pytest.mark.spark

NAIVE_T04 = REPO_ROOT / "tests" / "fixtures" / "t04_naive.py"
K = DiffSignatureKind


def kinds(result: Any) -> dict[tuple[DiffSignatureKind, str | None], int]:
    """
    Map each signature found to its row count, by kind and column.
    """
    return {(s.kind, s.column): s.n_rows for s in detect(result)}


### Names, samples and explanations


def test_names_match_case_insensitively(spark: SparkSession) -> None:
    legacy = spark.createDataFrame([(1, "a"), (2, "b")], "Claim_ID int, Status string")
    candidate = spark.createDataFrame([(1, "a"), (2, "B")], "claim_id int, STATUS string")
    ci = ComparisonPolicy(kind=PolicyKind.CI_RTRIM, reason="test")
    result = compare(legacy, candidate, ["CLAIM_ID"], {"status": ci}, partition_by=["status"])
    assert result.schema.ok  # a name differing only in case is the same column
    assert result.keys == ["Claim_ID"]
    assert result.rows == RowCounts(matched=2)
    with pytest.raises(ValueError, match="duplicate column names"):
        compare(spark.createDataFrame([(1, 2)], "a int, A int"), candidate, ["claim_id"])
    with pytest.raises(ValueError, match="not in the legacy output"):
        compare(legacy, candidate, ["nope"])


def test_pii_samples_are_masked_and_unpartnered_rows_sampled(spark: SparkSession) -> None:
    legacy = spark.createDataFrame(
        [(1, "Seán", 10), (2, "Aoife", 20), (3, "Ciara", 30)], "id int, name string, n int"
    )
    candidate = spark.createDataFrame(
        [(1, "Sean", 10), (2, "Aoife", 21), (4, "Niamh", 40)], "id int, name string, n int"
    )
    result = compare(legacy, candidate, ["id"], mask=["NAME"])
    samples = {d.column: d.samples for d in result.column_diffs}
    assert samples["name"] == [
        {"id": 1, "legacy": mask_value("Seán"), "candidate": mask_value("Sean")}
    ]
    assert samples["n"] == [{"id": 2, "legacy": 20, "candidate": 21}]
    assert result.missing_samples == [{"id": 3, "name": mask_value("Ciara"), "n": 30}]
    assert result.extra_samples == [{"id": 4, "name": mask_value("Niamh"), "n": 40}]
    assert mask_value(None) is None
    assert mask_value("Seán").startswith("pii:")
    assert "Seán" not in mask_value("Seán")
    none = compare(legacy, candidate, ["id"], sample_rows=0)
    assert none.missing_samples == []
    assert all(d.samples == [] for d in none.column_diffs)


def test_explanations_say_what_happened(spark: SparkSession) -> None:
    df = spark.createDataFrame([(1, "a")], "id int, v string")
    assert compare(df, df, ["id"]).explain().startswith("MATCH: all 1 rows agree")
    other = spark.createDataFrame([(1, "b"), (2, "c")], "id int, v string")
    text = compare(df, other, ["id"]).explain()
    assert text.startswith("MISMATCH: the legacy output has 1 rows and the candidate 2.")
    assert "v (1)" in text
    assert "1 candidate rows have none" in text


def test_double_totals_allow_only_summation_order_error(spark: SparkSession) -> None:
    """
    Identical doubles summed in a different order may differ in the last bits; nothing more.
    """
    values = [0.1, 0.2, 0.3, 1e-3, 7.7, 1e6, 3.3333333333333335]
    legacy = spark.createDataFrame(list(enumerate(values)), "id int, x double").repartition(1)
    candidate = spark.createDataFrame(
        list(reversed(list(enumerate(values)))), "id int, x double"
    ).repartition(3)
    result = compare(legacy, candidate, ["id"])
    assert result.is_match
    nudged = spark.createDataFrame(
        [(i, v * (1 + 1e-12)) for i, v in enumerate(values)], "id int, x double"
    )
    total = next(t for t in compare(legacy, nudged, ["id"]).totals if t.column == "x")
    assert not total.matches  # a real relative difference of 1e-12 is far above the bound


### Signatures


def test_value_signatures(spark: SparkSession) -> None:
    legacy = spark.createDataFrame(
        [
            (1, "OPEN", 3, Decimal("2.67"), 10.0, "2024-02-29", "ABCDEF"),
            (2, "Open", 7, Decimal("10.00"), 5.0, "2024-01-31", "XY"),
            (3, "x", 2, Decimal("5.00"), 1.0, "2025-12-31", None),
        ],
        "id int, s string, i int, d decimal(10,2), f double, dt string, t string",
    ).selectExpr("id", "s", "i", "d", "f", "to_date(dt) AS dt", "t")
    candidate = spark.createDataFrame(
        [
            (1, "OPEN ", 4, Decimal("2.68"), 10.000001, "2024-03-01", "ABC"),
            (2, "OPEN", 7, Decimal("20.00"), 5.5, "2024-02-29", "XY"),
            (3, None, 2, Decimal("5.40"), 1.0, "2025-12-31", None),
        ],
        "id int, s string, i int, d decimal(10,2), f double, dt string, t string",
    ).selectExpr("id", "s", "i", "d", "f", "to_date(dt) AS dt", "t")
    found = kinds(compare(legacy, candidate, ["id"]))
    assert found[(K.TRAILING_SPACE_SPLIT, "s")] == 1
    assert found[(K.CASE_SPLIT, "s")] == 1
    assert found[(K.NULL_VS_VALUE, "s")] == 1
    assert found[(K.OFF_BY_ONE_PERIOD, "i")] == 1
    assert found[(K.ROUNDING, "d")] == 1  # 2.67 vs 2.68: one unit in the last place
    assert found[(K.ROW_MULTIPLICITY, "d")] == 1  # 10.00 vs 20.00
    assert found[(K.INTEGER_TRUNCATION, "d")] == 1  # 5.00 vs 5.40
    assert found[(K.ROUNDING, "f")] == 1  # relative 1e-7
    assert found[(K.INTEGER_TRUNCATION, "f")] == 1  # 5.0 vs 5.5
    assert found[(K.OFF_BY_ONE_PERIOD, "dt")] == 2  # a day, and a month at month-end
    assert found[(K.TRUNCATED_STRING, "t")] == 1


def test_order_dependence_and_row_multiplicity(spark: SparkSession) -> None:
    legacy = spark.createDataFrame([(1, "a"), (2, "b"), (3, "c")], "id int, v string")
    shuffled = spark.createDataFrame([(1, "b"), (2, "c"), (3, "a")], "id int, v string")
    assert kinds(compare(legacy, shuffled, ["id"]))[(K.ORDER_DEPENDENCE, "v")] == 3
    fanned = spark.createDataFrame([(1, "a"), (1, "a"), (2, "b"), (3, "c")], "id int, v string")
    assert kinds(compare(legacy, fanned, ["id"]))[(K.ROW_MULTIPLICITY, None)] == 1


def test_filter_variant_signatures(spark: SparkSession) -> None:
    """
    Rows a case- or space-sensitive filter dropped are traced to their variant values.
    """
    legacy = spark.createDataFrame(
        [(1, "OPEN"), (2, "Open"), (3, "open"), (4, "OPEN "), (5, "CLOSED")],
        "id int, status string",
    )
    candidate = legacy.where("status IN ('OPEN', 'CLOSED')")
    found = kinds(compare(legacy, candidate, ["id"]))
    assert found[(K.CASE_SPLIT, "status")] == 2
    assert found[(K.TRAILING_SPACE_SPLIT, "status")] == 1


def test_match_has_no_signatures(spark: SparkSession) -> None:
    df = spark.createDataFrame([(1, "a")], "id int, v string")
    assert detect(compare(df, df, ["id"])) == []


### The lakehouse and the worker


def test_medallion_names() -> None:
    assert layer_of("stg.claims").value == "bronze"
    assert lakehouse_name("dw.dim_customer") == "silver.dim_customer"
    assert lakehouse_name("RPT.Claims_Summary") == "gold.claims_summary"
    assert delta_path("rpt.claims_summary", Path("/l")) == Path("/l/gold/claims_summary")


def test_sas_jobs_see_tsql_outputs_in_key_order(tmp_path: Path) -> None:
    inventory = load_inventory()
    s04 = inventory.job("S04")
    staged = stage_inputs(inventory, s04, "isolated", tmp_path)
    assert staged["dw.claims_enriched"].path == golden_table(inventory, "dw.claims_enriched").path
    customers = pq.read_table(staged["dw.dim_customer"].path)
    assert customers.column_names[-1] == "_row_seq"
    ids = customers.column("customer_id").to_pylist()
    seq = customers.column("_row_seq").to_pylist()
    assert [i for _, i in sorted(zip(seq, ids, strict=True))] == sorted(ids)
    t03 = inventory.job("T03")  # a T-SQL job reads a T-SQL output as it is, volatile included
    dim_policy = stage_inputs(inventory, t03, "isolated", tmp_path)["dw.dim_policy"]
    assert "load_ts" in pq.read_schema(dim_policy.path).names
    with pytest.raises(FileNotFoundError):
        stage_inputs(inventory, t03, "chained", tmp_path, lakehouse=tmp_path / "empty")


def test_conform_orders_casts_and_refuses_missing_columns(spark: SparkSession) -> None:
    df = spark.createDataFrame([("x", 3, "2.675")], "Extra string, N int, amount string")
    cols = [
        ColumnSpec(name="amount", data_type="decimal(14,2)"),
        ColumnSpec(name="n", data_type="double"),
    ]
    out = conform(df, cols)
    assert out.schema.simpleString() == "struct<amount:decimal(14,2),n:double>"
    assert out.first() == (Decimal("2.68"), 3.0)
    with pytest.raises(ValueError, match="lacks columns"):
        conform(df, [ColumnSpec(name="nope", data_type="int")])


def test_worker_env_strips_secrets() -> None:
    env = worker_env(
        {
            "PATH": "/bin",
            "JAVA_HOME": "/j",
            "MSSQL_SA_PASSWORD": "x",
            "ANTHROPIC_API_KEY": "k",
            "CLAUDE_CODE_OAUTH_TOKEN": "t",
            "GITHUB_TOKEN": "g",
        }
    )
    assert env == {"PATH": "/bin", "JAVA_HOME": "/j"}


def test_template_skeleton_parses() -> None:
    inventory = load_inventory()
    text = skeleton(inventory.job("T02"), inventory, legacy_sha256="0" * 64)
    ast.parse(text)
    assert SIGNATURE in text
    assert "Stateful" in text
    assert "policy_sk" in text


def test_worker_reports_a_failing_job(tmp_path: Path) -> None:
    module = tmp_path / "boom.py"
    module.write_text("def run(spark, inputs, params):\n    raise ValueError('boom')\n")
    no_run = tmp_path / "no_run.py"
    no_run.write_text("x = 1\n")
    with pytest.raises(ImportError, match="no run"):
        load_module(no_run)
    spec = WorkerSpec(
        job_id="T04",
        module=str(module),
        invocations=[{"params": {"AsOfDate": "2025-12-31"}}],
        inputs={},
        outputs={"rpt.x": [ColumnSpec(name="a", data_type="int")]},
        out_dir=str(tmp_path / "out"),
    )
    result = run_in_worker(spec)
    assert result.status == "error"
    assert result.error == "ValueError: boom"
    assert run_in_worker(spec, timeout_s=0.5).status == "timeout"


### The whole harness on T04's golden output


@pytest.fixture(scope="module")
def naive_t04(spark: SparkSession, tmp_path_factory: pytest.TempPathFactory) -> Any:
    """
    Run the deliberately naive T04 through the worker and reconcile it with T04's golden.
    """
    inventory = load_inventory()
    return run_and_reconcile(
        spark,
        inventory,
        inventory.job("T04"),
        NAIVE_T04,
        tmp_path_factory.mktemp("t04"),
        mode=ReconMode.CANDIDATE,
        keys=["claim_id"],
    )


def test_naive_t04_mistakes_are_caught_and_named(naive_t04: Any) -> None:
    assert naive_t04.worker.status == "ok"
    (report,) = naive_t04.reports
    assert report.status is ReconStatus.MISMATCH
    assert report.counts.legacy == 823
    assert report.counts.candidate == 763
    assert report.rows.missing == 60  # 49 case variants + 11 with a trailing space
    found = {(s.kind, s.column): s.n_rows for s in report.signatures}
    assert found[(K.CASE_SPLIT, "status")] == 49  # TSQL-01
    assert found[(K.TRAILING_SPACE_SPLIT, "status")] == 11  # TSQL-02
    assert found[(K.NULL_VS_VALUE, "claim_ref")] == 99  # TSQL-05, outside the 60 missing
    assert found[(K.ROW_MULTIPLICITY, "total_paid")] == 268  # BUG-03 "fixed"
    assert report.candidate_sha256 != report.golden_sha256
    text = report_markdown(report)
    assert "MISMATCH" in text
    assert "case_split" in text


def test_datacompy_agrees_on_t04(spark: SparkSession, naive_t04: Any) -> None:
    inventory = load_inventory()
    legacy = spark.read.parquet(str(golden_table(inventory, "rpt.claims_summary").path))
    candidate = spark.read.parquet(naive_t04.worker.outputs["rpt.claims_summary"])
    result = compare(legacy, candidate, ["claim_id"])
    assert disagreements(result, datacompy_summary(legacy, candidate, ["claim_id"])) == []


def test_golden_hashes_as_itself() -> None:
    inventory = load_inventory()
    golden = golden_table(inventory, "rpt.claims_summary")
    assert candidate_hash(golden.path, golden.path, []) == golden.output.content_sha256
    assert os.path.getsize(golden.path) > 0
