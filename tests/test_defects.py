"""
Suspected defects come from the markers and the Defect reviewer, measured on golden data.

Plan step 2.8's "done when": BUG-03 is listed. The agents' answers replay from
``runs/cassettes/``; the impact queries run in a local Spark session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lansh.config import REPO_ROOT
from lansh.design.contract import build_contract
from lansh.design.defects import measure, review, view_name
from lansh.discover.job import discover_job
from lansh.discover.split import split_code
from lansh.estate.inventory import load_inventory
from lansh.generate.job import generate_job
from lansh.lakehouse import input_schemas, output_columns
from lansh.llm.gateway import ClaudeGateway

pytestmark = pytest.mark.spark


def test_view_names() -> None:
    assert view_name("stg.claims") == "stg_claims"
    assert view_name("rpt.claims_summary", golden=True) == "golden_rpt_claims_summary"


def test_impact_queries_are_guarded(spark) -> None:
    spark.range(3).createOrReplaceTempView("t")
    impact = measure(
        spark, "SELECT COUNT(*) AS rows_affected, 12.345 AS amount_affected FROM t", "test", "x"
    )
    assert (impact.rows_affected, impact.amount_affected) == (3, "12.35")
    for bad in (
        "SELECT reflect('java.lang.Runtime', 'getRuntime') AS rows_affected",
        "SELECT * FROM csv.`/etc/passwd`",
        "DROP TABLE t",
        "SELECT 1 AS rows_affected; SELECT 2",
    ):
        with pytest.raises(ValueError, match="refused"):
            measure(spark, bad, "test", None)


def test_bug_03_is_listed_with_its_measured_impact(spark, tmp_path: Path) -> None:
    inventory = load_inventory()
    job = inventory.job("T04")
    gateway = ClaudeGateway(mode="replay")
    found = discover_job(job, inventory, gateway)
    inputs = input_schemas(inventory, job)
    outputs = {o.table: output_columns(inventory, o.table) for o in job.outputs}
    contracts = [
        build_contract(
            job, inventory, o.table, found.lineage, inputs, found.traps, gateway
        ).contract
        for o in job.outputs
    ]
    text = (REPO_ROOT / job.path).read_text()
    notes = next(w.split(": ", 1)[1] for w in found.warnings if w.startswith("lineage agent notes"))
    generated = generate_job(
        job,
        inventory,
        text,
        split_code(text, job.language),
        inputs,
        contracts,
        found.traps,
        notes,
        gateway,
        tmp_path,
    )
    listed = review(
        job,
        inventory,
        spark,
        text,
        inputs,
        outputs,
        generated.answer.defects,
        gateway,
        tmp_path / "staging",
    )
    fan_out = next(d for d in listed.defects if "fan-out" in d.title.lower())
    # the reviewer's impact query, run on the golden output, measures BUG-03 exactly
    assert fan_out.impact is not None
    assert (fan_out.impact.rows_affected, fan_out.impact.amount_affected) == (289, "1288029.36")
    assert "Also marked in the migrated code" in fan_out.description  # both sources found it
    assert 103 in fan_out.evidence_lines
