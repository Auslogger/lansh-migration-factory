"""
Deploy and run legacy T-SQL jobs on SQL Server, and run answer-key checks.

Running a job means: run its deployment script (output table and procedure), then EXEC the
entry point once per invocation listed in ``estate/jobs.yaml``. Checks are evaluation
tooling: they read ``estate/labels/`` and must never be called from factory code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lansh.config import LABELS_DIR, REPO_ROOT
from lansh.contracts import JobSpec, Language
from lansh.engines import mssql
from lansh.estate.inventory import load_inventory
from lansh.estate.legacy import LEGACY_DATABASE

log = logging.getLogger(__name__)


@dataclass
class TsqlRun:
    """
    What one run of a T-SQL job did.

    Attributes:
        seconds: Elapsed time of each invocation, in inventory order.
        output_rows: Row count of each output table after the last invocation.
    """

    job_id: str
    seconds: list[float]
    output_rows: dict[str, int]


def deploy(conn: Any, job: JobSpec) -> None:
    """
    Create the job's output table(s) and (re)create its procedure.

    Args:
        conn: Open connection to the legacy database.
        job: The job, whose ``path`` is its deployment script.
    """
    mssql.run_script(conn, (REPO_ROOT / job.path).read_text(encoding="utf-8"))


def run_tsql_job(job: JobSpec, conn: Any) -> TsqlRun:
    """
    Deploy a T-SQL job, then EXEC its entry point once per invocation, in order.

    Args:
        job: The job to run.
        conn: Open connection to a loaded legacy database.

    Returns:
        The time each invocation took and the row count of each output table.

    Raises:
        ValueError: The job is not a T-SQL job with an entry point.
    """
    if job.language is not Language.TSQL or not job.entrypoint:
        raise ValueError(f"{job.job_id} is not a T-SQL job")
    deploy(conn, job)
    seconds = []
    for invocation in job.invocations:
        seconds.append(mssql.exec_proc(conn, job.entrypoint, dict(invocation.params)))
        log.info("%s %s %s: %.1fs", job.job_id, job.entrypoint, invocation.params, seconds[-1])
    rows = {
        out.table: int(
            mssql.scalar(conn, f"SELECT COUNT_BIG(*) FROM {mssql.quote_table(out.table)}")
        )
        for out in job.outputs
    }
    return TsqlRun(job.job_id, seconds, rows)


def run_job(job_id: str, database: str = LEGACY_DATABASE) -> TsqlRun:
    """
    Deploy and run one T-SQL job against an already loaded legacy database.

    Args:
        job_id: A job in the inventory, such as ``T04``.
        database: The legacy database to run in.

    Returns:
        The time each invocation took and the row count of each output table.
    """
    job = load_inventory().job(job_id)
    with mssql.connect(database) as conn:
        return run_tsql_job(job, conn)


def run_tsql_checks(job_id: str, database: str = LEGACY_DATABASE) -> list[Any]:
    """
    Run a T-SQL job's answer-key checks (evaluation only).

    The job must already have run in ``database``. Batches without a ``-- check:`` line are
    setup and just run; each check batch must return exactly one row.

    Args:
        job_id: The job whose ``checks/<JOB>.sql`` to run.
        database: The legacy database the job ran in.

    Returns:
        One :class:`~lansh.estate.labels.CheckResult` per check.

    Raises:
        RuntimeError: A check returned other than one row, or the checks that ran are not
            the ones the file declares.
    """
    # imported here, so loading the runner doesn't load the answer key
    from lansh.estate.labels import CheckResult, is_check_batch, tsql_check_ids

    text = (LABELS_DIR / "checks" / f"{job_id}.sql").read_text(encoding="utf-8")
    batches = mssql.split_batches(text)
    declared = tsql_check_ids(text)
    results = []
    with mssql.connect(database) as conn:
        cur = conn.cursor(as_dict=True)
        for batch in batches:
            if not is_check_batch(batch):
                cur.execute(batch)
                continue
            cur.execute(batch)
            rows = cur.fetchall()
            while cur.nextset():
                pass
            if len(rows) != 1:
                raise RuntimeError(f"{job_id}: a check returned {len(rows)} rows, not 1")
            row = rows[0]
            results.append(
                CheckResult(
                    job_id=job_id,
                    check_id=row["check_id"],
                    affected=int(row["affected"] or 0),
                    detail=None if row.get("detail") is None else str(row["detail"]),
                    engine="mssql",
                )
            )
    got = [r.check_id for r in results]
    if sorted(got) != sorted(declared):
        raise RuntimeError(f"{job_id}: declared checks {declared} but got {got}")
    return results
