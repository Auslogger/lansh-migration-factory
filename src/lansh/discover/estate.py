"""
The estate: its job DAG, its waves and the flows of tagged columns across jobs (plan §8.3).

The DAG comes from what each job reads and writes (``estate/jobs.yaml``): an edge runs from
the job that writes a table to every job that reads it. The waves are the DAG's topological
generations: wave 1 holds the jobs that read only sources, and each later wave the jobs whose
upstream jobs all run earlier.

A *tagged flow* is a path from a ``pii`` or ``protected`` source column, through the lineage
of one or more jobs, into a job's output. Each one is shown at H2 for a decision (plan §10):
S04's risk score, for instance, uses age, which comes from T01's date of birth.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import networkx as nx

from lansh.contracts import (
    ColumnRef,
    ColumnTag,
    EstateInventory,
    EstatePlan,
    JobEdge,
    LineageEdge,
    LineageKind,
    TaggedFlow,
    Wave,
)


def job_graph(inventory: EstateInventory) -> nx.DiGraph:
    """
    Build the estate's job DAG, each edge labelled with the tables it carries.

    Args:
        inventory: The estate inventory.

    Returns:
        A directed graph with one node per job.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(j.job_id for j in inventory.jobs)
    producers = inventory.producers()
    for job in inventory.jobs:
        for table in job.inputs:
            up = producers.get(table)
            if up and up != job.job_id:
                if graph.has_edge(up, job.job_id):
                    graph.edges[up, job.job_id]["tables"].append(table)
                else:
                    graph.add_edge(up, job.job_id, tables=[table])
    return graph


def waves(inventory: EstateInventory) -> list[list[str]]:
    """
    Group the jobs into waves: the topological generations of the DAG.

    Args:
        inventory: The estate inventory.

    Returns:
        Each wave's job ids, sorted, in run order.
    """
    return [sorted(g) for g in nx.topological_generations(job_graph(inventory))]


def estate_plan(inventory: EstateInventory) -> EstatePlan:
    """
    Give the contract's record of the DAG and its waves.

    Args:
        inventory: The estate inventory.

    Returns:
        The plan: waves numbered from 1, and every edge with its tables.
    """
    graph = job_graph(inventory)
    return EstatePlan(
        waves=[Wave(number=i, job_ids=w) for i, w in enumerate(waves(inventory), 1)],
        edges=[
            JobEdge(upstream=u, downstream=d, tables=sorted(data["tables"]))
            for u, d, data in sorted(graph.edges(data=True))
        ],
    )


def wave_of(inventory: EstateInventory, job_id: str) -> int:
    """
    Give the wave a job runs in.

    Args:
        inventory: The estate inventory.
        job_id: The job.

    Returns:
        Its wave number, from 1.

    Raises:
        KeyError: If the job isn't in the inventory.
    """
    for number, wave in enumerate(waves(inventory), 1):
        if job_id in wave:
            return number
    raise KeyError(job_id)


def _flow_id(path: list[ColumnRef]) -> str:
    """
    Name a flow by a short hash of its path, so the same path keeps its id from run to run.
    """
    text = "|".join(f"{c.table}.{c.column.casefold()}" for c in path)
    return "F-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def tagged_flows(
    tagged_sources: dict[tuple[str, str], list[ColumnTag]],
    lineage: Iterable[LineageEdge],
) -> list[TaggedFlow]:
    """
    Trace every tagged source column through the jobs' lineage to the outputs it feeds.

    Only ``derives`` edges carry a value forward. A column fed by another job's output is
    followed through that job's lineage, so a flow can cross several jobs.

    Args:
        tagged_sources: The tags of each source column, by (table, column) in lower case.
        lineage: The verified lineage of every job.

    Returns:
        One flow per tag and per path from a tagged source to an output column.
    """
    edges = [e for e in lineage if e.kind is LineageKind.DERIVES and e.input_kind == "column"]
    by_input: dict[tuple[str, str], list[LineageEdge]] = {}
    for e in edges:
        by_input.setdefault((e.input_table or "", (e.input_column or "").casefold()), []).append(e)
    flows: list[TaggedFlow] = []
    seen: set[tuple[str, str]] = set()

    def walk(
        node: tuple[str, str], path: list[ColumnRef], jobs: list[str], tags: list[ColumnTag]
    ) -> None:
        """
        Follow one column downstream, recording a flow at every output it reaches.
        """
        for e in by_input.get(node, []):
            out = ColumnRef(table=e.output_table, column=e.output_column or "")
            new_path = [*path, out]
            new_jobs = jobs if e.job_id in jobs else [*jobs, e.job_id]
            for tag in tags:
                key = (_flow_id(new_path), tag.value)
                if key in seen:
                    continue
                seen.add(key)
                flows.append(
                    TaggedFlow(
                        flow_id=f"{_flow_id(new_path)}-{tag.value}",
                        tag=tag,
                        source=new_path[0],
                        output=out,
                        path=new_path,
                        job_ids=new_jobs,
                    )
                )
            if len(new_path) < 8:  # an estate DAG is shallow; this bounds any cycle in bad lineage
                walk((out.table, out.column.casefold()), new_path, new_jobs, tags)

    for (table, column), tags in sorted(tagged_sources.items()):
        if tags:
            walk((table, column), [ColumnRef(table=table, column=column)], [], list(tags))
    return sorted(flows, key=lambda f: (f.output.table, f.output.column, f.flow_id))
