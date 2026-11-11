"""
The estate inventory validates, and its declared dependencies give the plan's waves.
"""

from __future__ import annotations

import networkx as nx

from lansh.config import REPO_ROOT
from lansh.contracts import Language
from lansh.estate.inventory import load_inventory
from lansh.estate.labels import load_label


def test_inventory_validates_and_lists_the_tier1_development_jobs() -> None:
    inv = load_inventory()
    ids = [j.job_id for j in inv.jobs]
    assert ids == ["T01", "T02", "T03", "T04", "T05", "T06", "T08", "S01", "S03", "S04"]
    assert sum(j.language is Language.TSQL for j in inv.jobs) == 7
    assert not any(j.holdout for j in inv.jobs)


def test_declared_dependencies_give_the_plan_waves() -> None:
    inv = load_inventory()
    graph = nx.DiGraph()
    graph.add_nodes_from(j.job_id for j in inv.jobs)
    for job in inv.jobs:
        graph.add_edges_from((up, job.job_id) for up in inv.upstream(job.job_id))
    waves = [sorted(gen) for gen in nx.topological_generations(graph)]
    assert waves == [["S01", "T01", "T04", "T05", "T06"], ["T02", "T08"], ["T03"], ["S03"], ["S04"]]


def test_every_listed_job_has_code_and_labels() -> None:
    for job in load_inventory().jobs:
        assert (REPO_ROOT / job.path).exists(), job.path
        label = load_label(job.job_id)
        assert label.legacy_path == job.path
