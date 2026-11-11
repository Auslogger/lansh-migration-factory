"""
Golden outputs: run every legacy job on its real engine and freeze its outputs (plan §7.3).

A golden pack per job in ``estate/golden/<JOB>/``:

- ``<table>.csv``: the rows exactly as the engine returned them (raw export);
- ``<table>.parquet``: a typed copy (decimals stay decimals, dates stay dates);
- ``manifest.json``: a :class:`lansh.contracts.GoldenManifest` with the engine version,
  parameters, row counts, SHA-256 hashes, input fingerprints and a log excerpt.

Golden outputs are immutable: a change means a fresh capture approved at a gate.
``verify`` rebuilds the legacy database from scratch, re-runs the T-SQL jobs and checks that
every output reproduces its content hash (volatile audit columns excluded).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path
from typing import Any

import networkx as nx
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from lansh import __version__
from lansh.config import DATA_DIR, GOLDEN_DIR, REPO_ROOT
from lansh.contracts import (
    EstateInventory,
    GoldenManifest,
    GoldenOutput,
    JobSpec,
    Language,
    TableFingerprint,
)
from lansh.engines import mssql
from lansh.estate.fingerprint import canonical, content_sha256, file_sha256
from lansh.estate.inventory import load_inventory
from lansh.estate.legacy import LEGACY_DATABASE, load_database
from lansh.estate.runner import run_tsql_job

log = logging.getLogger(__name__)


def dependency_graph(inventory: EstateInventory) -> nx.DiGraph:
    """
    Build the job dependency graph: an edge runs from each job to every job reading its outputs.

    Args:
        inventory: The estate inventory.

    Returns:
        A directed graph with one node per job id.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(j.job_id for j in inventory.jobs)
    for job in inventory.jobs:
        graph.add_edges_from((up, job.job_id) for up in inventory.upstream(job.job_id))
    return graph


def job_order(inventory: EstateInventory, graph: nx.DiGraph | None = None) -> list[str]:
    """
    Put the jobs in dependency order: T-SQL first, then SAS.

    Within each group the jobs keep their lexicographic topological order. Putting T-SQL
    first is valid only while no T-SQL job reads a SAS output, which is checked.

    Args:
        inventory: The estate inventory.
        graph: Its :func:`dependency_graph`, if the caller has built it already.

    Returns:
        Job ids in run order.

    Raises:
        ValueError: A T-SQL job reads a SAS output.
    """
    graph = dependency_graph(inventory) if graph is None else graph
    order = list(nx.lexicographical_topological_sort(graph))
    tsql = [j for j in order if inventory.job(j).language is Language.TSQL]
    sas = [j for j in order if inventory.job(j).language is Language.SAS]
    for job_id in tsql:
        if any(inventory.job(u).language is Language.SAS for u in inventory.upstream(job_id)):
            raise ValueError(f"{job_id} reads a SAS output; T-SQL-first order is invalid")
    return tsql + sas


def sorted_rows(table: pa.Table) -> pa.Table:
    """
    Sort a table's rows into a canonical order, so files are byte-stable across captures.

    Rows sort by the canonical text of their values (see
    :func:`~lansh.estate.fingerprint.canonical`), so the order is stable but not natural:
    the number 10 sorts before 9.

    Args:
        table: Rows in the order the engine returned them.

    Returns:
        The same rows in canonical order.
    """
    columns = [table.column(i).to_pylist() for i in range(table.num_columns)]
    keys = ["\x1f".join(canonical(v) for v in row) for row in zip(*columns, strict=True)]
    order = sorted(range(len(keys)), key=keys.__getitem__)
    return table.take(pa.array(order, type=pa.int64()))


def rel(path: Path) -> str:
    """
    Give a path relative to the repository root, as manifests record paths.

    Args:
        path: An absolute path.

    Returns:
        The repository-relative path, or the path unchanged when it is outside the
        repository (such as a temporary folder).
    """
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def write_output(
    job_dir: Path, table_name: str, data: pa.Table, columns: list[Any], volatile: list[str]
) -> GoldenOutput:
    """
    Write the raw CSV and typed Parquet for one output and describe them.

    Rows are put in canonical order first, so both files are byte-stable across captures.

    Args:
        job_dir: The job's golden pack folder.
        table_name: The output table, which also names the files.
        data: The output's rows.
        columns: The output's column specs.
        volatile: Columns left out of the content hash.

    Returns:
        The manifest entry for the output, with paths, row count and hashes.
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    data = sorted_rows(data)
    csv_path = job_dir / f"{table_name}.csv"
    parquet_path = job_dir / f"{table_name}.parquet"
    pacsv.write_csv(data, csv_path)
    pq.write_table(data, parquet_path, compression="zstd", write_statistics=True)
    return GoldenOutput(
        table=table_name,
        rows=data.num_rows,
        columns=columns,
        raw_path=rel(csv_path),
        raw_sha256=file_sha256(csv_path),
        parquet_path=rel(parquet_path),
        parquet_sha256=file_sha256(parquet_path),
        content_sha256=content_sha256(data, exclude=volatile),
        volatile_columns=volatile,
    )


def input_fingerprints(job: JobSpec) -> list[TableFingerprint]:
    """
    Fingerprint what the job read: committed extracts and upstream golden outputs.

    Upstream outputs are looked up in the golden manifests under ``estate/golden``, so the
    jobs a job reads from must be captured before it.

    Args:
        job: The job whose inputs to fingerprint.

    Returns:
        One fingerprint per input, in the job's input order.

    Raises:
        RuntimeError: An input is neither a committed extract nor a captured golden output.
    """
    data_manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    extracts = {t["table"]: TableFingerprint.model_validate(t) for t in data_manifest["tables"]}
    upstream: dict[str, TableFingerprint] = {}
    for manifest_path in sorted(GOLDEN_DIR.glob("*/manifest.json")):
        manifest = GoldenManifest.model_validate_json(manifest_path.read_text())
        for out in manifest.outputs:
            upstream[out.table] = TableFingerprint(
                table=out.table,
                path=out.parquet_path,
                rows=out.rows,
                file_sha256=out.parquet_sha256,
                content_sha256=out.content_sha256,
            )
    found = []
    for table in job.inputs:
        if table in extracts:
            found.append(extracts[table])
        elif table in upstream:
            found.append(upstream[table])
        else:
            raise RuntimeError(f"{job.job_id}: no fingerprint for input {table}")
    return found


def tsql_log_excerpt(conn: Any, since_id: int) -> str:
    """
    Summarise the ``etl.etl_log`` rows a job wrote, for its golden manifest.

    Args:
        conn: Open connection to the legacy database.
        since_id: The highest ``log_id`` before the job ran.

    Returns:
        The last 40 log lines, one per row: status, step, row count and message.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT step_name, status, rows_affected, message FROM etl.etl_log "
        "WHERE log_id > %d ORDER BY log_id",
        (since_id,),
    )
    lines = []
    for step, status, rows, message in cur.fetchall():
        parts = [status, step or "", "" if rows is None else f"rows={rows}", message or ""]
        lines.append(" ".join(p for p in parts if p))
    return "\n".join(lines[-40:])


def capture_tsql(job: JobSpec, conn: Any, golden_dir: Path = GOLDEN_DIR) -> GoldenManifest:
    """
    Run one T-SQL job and freeze its outputs into a golden pack.

    The jobs it reads from must already have run in the same database.

    Args:
        job: The T-SQL job to capture.
        conn: Open connection to the loaded legacy database.
        golden_dir: Folder holding one golden pack per job.

    Returns:
        The manifest, also written to ``<golden_dir>/<JOB>/manifest.json``.
    """
    started = time.perf_counter()
    since = int(mssql.scalar(conn, "SELECT ISNULL(MAX(log_id), 0) FROM etl.etl_log"))
    run_tsql_job(job, conn)
    job_dir = golden_dir / job.job_id
    outputs = []
    for out in job.outputs:
        cols, data = mssql.fetch_table(conn, out.table)
        specs = [c.to_spec() for c in cols]
        outputs.append(write_output(job_dir, out.table, data, specs, list(out.volatile_columns)))
    legacy = REPO_ROOT / job.path
    manifest = GoldenManifest(
        job_id=job.job_id,
        engine="mssql",
        engine_version=f"SQL Server {mssql.server_version(conn)}",
        legacy_path=job.path,
        legacy_sha256=file_sha256(legacy),
        invocations=job.invocations,
        inputs=input_fingerprints(job),
        outputs=outputs,
        log_excerpt=tsql_log_excerpt(conn, since),
        captured_at=dt.datetime.now(dt.UTC),
        capture_seconds=round(time.perf_counter() - started, 3),
        lansh_version=__version__,
    )
    (job_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    log.info("captured %s: %s", job.job_id, ", ".join(f"{o.table} {o.rows} rows" for o in outputs))
    return manifest


def capture(
    job_ids: list[str] | None = None, database: str = LEGACY_DATABASE, reload: bool = True
) -> list[GoldenManifest]:
    """
    Capture golden outputs for the given jobs (default: all), in dependency order.

    The legacy database is rebuilt first. Upstream T-SQL jobs that are not being captured are
    still run, so every captured job sees exactly what it would in production. Upstream SAS
    jobs run too, without being frozen.

    Args:
        job_ids: The jobs to capture; None captures every job.
        database: The legacy database to run in.
        reload: Rebuild and reload the legacy database first.

    Returns:
        A manifest per captured job: T-SQL jobs first, then SAS jobs.
    """
    inventory = load_inventory()
    graph = dependency_graph(inventory)
    order = job_order(inventory, graph)
    wanted = set(job_ids or order)
    needed: set[str] = set()
    for job_id in wanted:
        needed |= nx.ancestors(graph, job_id) | {job_id}
    if reload:
        load_database(database)
    manifests = []
    with mssql.connect(database) as conn:
        for job_id in order:
            job = inventory.job(job_id)
            if job_id not in needed or job.language is not Language.TSQL:
                continue
            if job_id in wanted:
                manifests.append(capture_tsql(job, conn))
            else:
                run_tsql_job(job, conn)
    sas_jobs = [j for j in order if j in needed and inventory.job(j).language is Language.SAS]
    if sas_jobs:
        from lansh.estate.golden_sas import capture_sas_jobs

        manifests += capture_sas_jobs(sas_jobs, capture=[j for j in sas_jobs if j in wanted])
    return manifests


def verify(database: str = LEGACY_DATABASE) -> dict[str, list[tuple[str, bool, str]]]:
    """
    Rebuild the legacy database, re-run every T-SQL job and compare content hashes.

    Nothing in ``estate/golden`` is written. An output matches when its row count and its
    content hash (volatile columns excluded) both equal the golden ones.

    Args:
        database: The legacy database to rebuild and run in.

    Returns:
        ``{job_id: [(table, matches, detail), ...]}`` for every T-SQL job. The detail gives
        the row count and the start of the content hash, and the golden ones on a mismatch.
    """
    inventory = load_inventory()
    load_database(database)
    results: dict[str, list[tuple[str, bool, str]]] = {}
    with mssql.connect(database) as conn:
        for job_id in job_order(inventory):
            job = inventory.job(job_id)
            if job.language is not Language.TSQL:
                continue
            manifest = GoldenManifest.model_validate_json(
                (GOLDEN_DIR / job_id / "manifest.json").read_text()
            )
            run_tsql_job(job, conn)
            checks = []
            for out in manifest.outputs:
                _, data = mssql.fetch_table(conn, out.table)
                actual = content_sha256(data, exclude=out.volatile_columns)
                ok = actual == out.content_sha256 and data.num_rows == out.rows
                detail = f"{data.num_rows} rows, content {actual[:12]}"
                if not ok:
                    detail += f" (golden {out.rows} rows, {out.content_sha256[:12]})"
                checks.append((out.table, ok, detail))
            results[job_id] = checks
            log.info("%s: %s", job_id, "reproduced" if all(c[1] for c in checks) else "DIFFERS")
    return results


def verify_sas() -> dict[str, list[tuple[str, bool, str]]]:
    """
    Re-run the SAS jobs from their frozen inputs and compare with the golden hashes.

    Needs SAS OnDemand. The outputs go to a temporary folder; nothing in ``estate/golden``
    is written. On the SAS server, though, the ``golden`` libraries are cleared and
    rewritten, as in a capture.

    Returns:
        ``{job_id: [(table, matches, detail), ...]}`` for every SAS job, as :func:`verify`.
    """
    import tempfile

    from lansh.estate.golden_sas import capture_sas_jobs

    inventory = load_inventory()
    sas_jobs = [j for j in job_order(inventory) if inventory.job(j).language is Language.SAS]
    with tempfile.TemporaryDirectory(prefix="lansh-sas-verify-") as tmp:
        again = {
            o.table: o for m in capture_sas_jobs(sas_jobs, golden_dir=Path(tmp)) for o in m.outputs
        }
    results: dict[str, list[tuple[str, bool, str]]] = {}
    for job_id in sas_jobs:
        manifest = GoldenManifest.model_validate_json(
            (GOLDEN_DIR / job_id / "manifest.json").read_text()
        )
        checks = []
        for out in manifest.outputs:
            new = again[out.table]
            ok = new.content_sha256 == out.content_sha256 and new.rows == out.rows
            detail = f"{new.rows} rows, content {new.content_sha256[:12]}"
            if not ok:
                detail += f" (golden {out.rows} rows, {out.content_sha256[:12]})"
            checks.append((out.table, ok, detail))
        results[job_id] = checks
    return results
