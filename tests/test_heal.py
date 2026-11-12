"""
The heal loop turns a deliberately broken T04 back into a MATCH (plan step 2.7's "done when").

``tests/fixtures/t04_broken.py`` is the factory's own T04 translation with two traps undone:
the open-status filter compares case-sensitively (TSQL-01, TSQL-02) and the dd/mm/yyyy text
uses mm/dd/yyyy (TSQL-16). The Fixer's answer is replayed from ``runs/cassettes/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lansh.config import REPO_ROOT
from lansh.contracts import ReconStatus
from lansh.design.contract import build_contract
from lansh.discover.job import discover_job
from lansh.discover.traps import signature_lookup
from lansh.estate.inventory import load_inventory
from lansh.generate.job import job_provenance
from lansh.lakehouse import input_schemas
from lansh.llm.gateway import ClaudeGateway
from lansh.reconcile.heal import heal
from lansh.reconcile.job import run_and_reconcile

pytestmark = pytest.mark.spark

BROKEN = REPO_ROOT / "tests" / "fixtures" / "t04_broken.py"


def test_broken_t04_heals_to_match(spark, tmp_path: Path) -> None:
    inventory = load_inventory()
    job = inventory.job("T04")
    gateway = ClaudeGateway(mode="replay")
    found = discover_job(job, inventory, gateway)
    inputs = input_schemas(inventory, job)
    contracts = [
        build_contract(
            job, inventory, o.table, found.lineage, inputs, found.traps, gateway
        ).contract
        for o in job.outputs
    ]
    text = (REPO_ROOT / job.path).read_text()
    first = run_and_reconcile(
        spark,
        inventory,
        job,
        BROKEN,
        tmp_path / "first",
        contracts={c.legacy_table: c for c in contracts},
        traps_for=signature_lookup(job.language),
    )
    assert first.status is ReconStatus.MISMATCH
    assert first.reports[0].rows.missing == 60
    result = heal(
        job,
        inventory,
        spark,
        BROKEN,
        first.reports,
        tmp_path / "heal",
        gateway,
        legacy_text=text,
        inputs=inputs,
        contracts=contracts,
        traps=found.traps,
        provenance=job_provenance(job, text, inputs, contracts),
    )
    assert result.status is ReconStatus.MATCH
    assert result.escalation is None
    (attempt,) = result.attempts
    assert attempt.kept
    assert attempt.guardrails_passed
    assert attempt.score_after == (0, 0, 0, 0)
    assert attempt.score_before[2] == 60  # 60 rows missing before the patch
    assert result.module != BROKEN
    assert result.reports[0].candidate_sha256 == result.reports[0].golden_sha256
