"""
Reconcile a whole job: run its module in a worker, then compare every output with its golden.

This is what ``lansh reconcile --job ID --candidate FILE`` runs (plan step 2.1), and what the
factory's Reconcile stage and the comparison runs call for each attempt. The comparison uses
the output's approved data contract when one exists (``migrated/contracts/``); otherwise
every column is compared exactly, as a multiset unless keys are given, with the job's
volatile audit columns excluded.

The candidate's content hash is computed the way the golden one was
(:func:`lansh.estate.fingerprint.content_sha256`), so a MATCH under all-``exact`` policies also
shows as two identical hashes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from lansh.config import REPO_ROOT, RUNS_DIR
from lansh.contracts import (
    Approach,
    ComparisonPolicy,
    DataContract,
    EstateInventory,
    JobSpec,
    PolicyKind,
    ReconMode,
    ReconReport,
    ReconStatus,
)
from lansh.estate.fingerprint import content_sha256, file_sha256
from lansh.lakehouse import golden_table, output_columns, stage_inputs
from lansh.reconcile.engine import compare
from lansh.reconcile.signatures import TrapLookup, attach

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from lansh.generate.worker import WorkerResult

log = logging.getLogger(__name__)

CONTRACTS_DIR = REPO_ROOT / "migrated" / "contracts"


def contract_path(table: str, root: Path = CONTRACTS_DIR) -> Path:
    """
    Give the file an output table's approved data contract is kept in.

    Args:
        table: The legacy output table, such as ``rpt.claims_summary``.
        root: The contracts folder.

    Returns:
        ``<root>/<table>.json``.
    """
    return root / f"{table}.json"


def load_contract(table: str, root: Path = CONTRACTS_DIR) -> DataContract | None:
    """
    Read an output table's data contract, if Design has written one.

    Args:
        table: The legacy output table.
        root: The contracts folder.

    Returns:
        The contract, or None when there is none yet.
    """
    path = contract_path(table, root)
    if not path.exists():
        return None
    return DataContract.model_validate_json(path.read_text(encoding="utf-8"))


def default_policies(job: JobSpec, table: str) -> dict[str, ComparisonPolicy]:
    """
    Give the policies used without a contract: exact, except volatile audit columns.

    Args:
        job: The job that writes the table.
        table: The output table.

    Returns:
        ``exclude`` for each column ``jobs.yaml`` marks volatile, with the reason.
    """
    out = next(o for o in job.outputs if o.table == table)
    return {
        c: ComparisonPolicy(
            kind=PolicyKind.EXCLUDE,
            reason="volatile audit column (estate/jobs.yaml): it changes on every run",
        )
        for c in out.volatile_columns
    }


def candidate_hash(candidate: Path | pa.Table, golden_path: Path, exclude: list[str]) -> str | None:
    """
    Hash a candidate output's content exactly as its golden output was hashed.

    The candidate is cast to the golden output's Arrow schema first, so a ``decimal(14,2)``
    or an ``int32`` read back from Spark hashes as the legacy engine's own did.

    Args:
        candidate: The candidate's Parquet file or folder, or its rows (a Delta table is read
            through Spark, since its folder also holds files of earlier versions).
        golden_path: The golden output's Parquet file.
        exclude: Columns left out of both hashes (volatile ones).

    Returns:
        The content hash, or None when the candidate can't take the golden schema.
    """
    golden_schema = pq.read_schema(golden_path)
    data = candidate if isinstance(candidate, pa.Table) else pq.read_table(candidate)
    try:
        names = [f.name for f in golden_schema]
        data = data.select(names).cast(pa.schema([golden_schema.field(n) for n in names]))
    except KeyError, pa.ArrowInvalid, pa.ArrowNotImplementedError, ValueError:
        return None
    return content_sha256(data, exclude=exclude)


def contract_sha256(contract: DataContract) -> str:
    """
    Hash a contract's canonical JSON, which pins what an approval approved.

    Args:
        contract: The data contract.

    Returns:
        The SHA-256 of the contract's JSON.
    """
    from lansh.estate.fingerprint import text_sha256

    return text_sha256(contract.model_dump_json())


def compare_output(
    spark: SparkSession,
    inventory: EstateInventory,
    job: JobSpec,
    table: str,
    candidate: Path,
    *,
    mode: ReconMode,
    contract: DataContract | None = None,
    keys: list[str] | None = None,
    run_id: str | None = None,
    approach: Approach = Approach.LANSH,
    code_sha256: str | None = None,
    traps_for: TrapLookup | None = None,
    sample_rows: int = 5,
) -> ReconReport:
    """
    Compare one candidate output with its golden output and report.

    Args:
        spark: The parent's Spark session.
        inventory: The estate inventory.
        job: The job that writes the table.
        table: The output table.
        candidate: The candidate output's Parquet file or folder, or its Delta table.
        mode: How the run was set up.
        contract: The output's data contract; without one, exact policies apply.
        keys: Keys to join on when there is no contract; a multiset comparison without.
        run_id: The run the comparison belongs to.
        approach: Who or what produced the candidate.
        code_sha256: The candidate module's hash.
        traps_for: Links signatures to trap cards.
        sample_rows: Sample rows per difference (0 to 5).

    Returns:
        The report.
    """
    golden = golden_table(inventory, table)
    legacy_df = spark.read.parquet(str(golden.path))
    is_delta = (Path(candidate) / "_delta_log").is_dir()
    candidate_df = spark.read.format("delta" if is_delta else "parquet").load(str(candidate))
    if contract is not None:
        from lansh.reconcile.engine import contract_inputs

        settings = contract_inputs(contract)
    else:
        settings = {
            "keys": keys or [],
            "policies": default_policies(job, table),
            "partition_by": [],
            "mask": [],
        }
    result = compare(legacy_df, candidate_df, **settings, sample_rows=sample_rows)
    attach(result, traps_for)
    volatile = list(golden.output.volatile_columns)
    return result.to_report(
        job.job_id,
        table,
        mode,
        run_id=run_id,
        approach=approach,
        code_sha256=code_sha256,
        contract_sha256=contract_sha256(contract) if contract is not None else None,
        golden_sha256=golden.output.content_sha256,
        candidate_sha256=candidate_hash(
            candidate_df.toArrow() if is_delta else candidate, golden.path, volatile
        ),
    )


def error_report(
    job: JobSpec,
    table: str,
    mode: ReconMode,
    error: str,
    *,
    run_id: str | None = None,
    approach: Approach = Approach.LANSH,
    code_sha256: str | None = None,
) -> ReconReport:
    """
    Report an output that couldn't be compared, because the job failed to run.

    Args:
        job: The job.
        table: The output table.
        mode: How the run was set up.
        error: What went wrong.
        run_id: The run.
        approach: Who or what produced the candidate.
        code_sha256: The candidate module's hash.

    Returns:
        An ERROR report.
    """
    return ReconReport(
        job_id=job.job_id,
        table=table,
        mode=mode,
        status=ReconStatus.ERROR,
        run_id=run_id,
        approach=approach,
        code_sha256=code_sha256,
        explanation=f"The job did not produce its outputs: {error}",
        started_at=datetime.now(UTC),
        duration_seconds=0.0,
        error=error,
    )


@dataclass
class JobRun:
    """
    One run of a job module and the reconciliation of its outputs.

    Attributes:
        worker: How the worker run ended.
        reports: One report per output table, in the job's output order.
        run_dir: Where the run's files are.
    """

    job_id: str
    worker: WorkerResult
    reports: list[ReconReport]
    run_dir: Path

    @property
    def status(self) -> ReconStatus:
        """
        The job's verdict: ERROR if any output errored, MISMATCH if any differs, else MATCH.
        """
        statuses = {r.status for r in self.reports}
        if ReconStatus.ERROR in statuses:
            return ReconStatus.ERROR
        if ReconStatus.MISMATCH in statuses:
            return ReconStatus.MISMATCH
        return ReconStatus.MATCH


def run_and_reconcile(
    spark: SparkSession,
    inventory: EstateInventory,
    job: JobSpec,
    module: Path,
    run_dir: Path,
    *,
    mode: ReconMode = ReconMode.ISOLATED,
    contracts: dict[str, DataContract] | None = None,
    keys: list[str] | None = None,
    run_id: str | None = None,
    approach: Approach = Approach.LANSH,
    traps_for: TrapLookup | None = None,
    timeout_s: float | None = None,
    sample_rows: int = 5,
    on_worker: Callable[[WorkerResult], None] | None = None,
) -> JobRun:
    """
    Run a job module in a worker on staged inputs, then reconcile each of its outputs.

    Args:
        spark: The parent's Spark session.
        inventory: The estate inventory.
        job: The job.
        module: The migrated (or hand-written) module.
        run_dir: Where this run's staging, outputs and reports go.
        mode: ``isolated`` or ``candidate`` read golden upstream outputs; ``chained`` reads
            the lakehouse.
        contracts: Approved contracts by output table; ``load_contract`` is tried for any
            table missing from it.
        keys: Keys for a comparison without a contract.
        run_id: The run.
        approach: Who or what produced the module.
        traps_for: Links signatures to trap cards.
        timeout_s: The worker's timeout; the worker's default when not given.
        sample_rows: Sample rows per difference (0 to 5).
        on_worker: Called with the worker's result before reconciling, for logging.

    Returns:
        The worker's result and one report per output.
    """
    from lansh.generate.worker import DEFAULT_TIMEOUT_S, run_in_worker, spec_for

    input_mode = "chained" if mode is ReconMode.CHAINED else "isolated"
    staged = stage_inputs(inventory, job, input_mode, run_dir / "staging", spark=spark)
    outputs = {o.table: output_columns(inventory, o.table) for o in job.outputs}
    spec = spec_for(job, module, staged, outputs, run_dir / "outputs")
    worker = run_in_worker(spec, timeout_s=timeout_s or DEFAULT_TIMEOUT_S)
    if on_worker:
        on_worker(worker)
    code = file_sha256(module)
    reports = []
    for out in job.outputs:
        if worker.status != "ok":
            reports.append(
                error_report(
                    job,
                    out.table,
                    mode,
                    worker.error or worker.status,
                    run_id=run_id,
                    approach=approach,
                    code_sha256=code,
                )
            )
            continue
        contract = (contracts or {}).get(out.table) or load_contract(out.table)
        reports.append(
            compare_output(
                spark,
                inventory,
                job,
                out.table,
                Path(worker.outputs[out.table]),
                mode=mode,
                contract=contract,
                keys=keys,
                run_id=run_id,
                approach=approach,
                code_sha256=code,
                traps_for=traps_for,
                sample_rows=sample_rows,
            )
        )
    return JobRun(job.job_id, worker, reports, run_dir)


def new_run_id(tag: str) -> str:
    """
    Name a new run: the UTC time, then a tag.

    Args:
        tag: What the run is, such as ``candidate`` or ``dev``.

    Returns:
        Text such as ``20261112T0130Z-candidate``.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{tag}"


def run_dir_for(run_id: str, *parts: str) -> Path:
    """
    Give a folder inside a run's folder in ``runs/``.

    Args:
        run_id: The run.
        parts: Sub-folders, such as the job id.

    Returns:
        ``runs/<run_id>/<parts...>``.
    """
    return RUNS_DIR.joinpath(run_id, *parts)


def report_markdown(report: ReconReport) -> str:
    """
    Render a reconciliation report as Markdown for people: the verdict first, then each check.

    Args:
        report: The report.

    Returns:
        The Markdown text.
    """
    lines = [f"### {report.table}: {report.status.value}", "", report.explanation, ""]
    if report.error and report.status is ReconStatus.ERROR:
        return "\n".join(lines)
    counts = report.counts
    assert counts is not None
    same_hash = bool(report.candidate_sha256) and report.candidate_sha256 == report.golden_sha256
    schema = "ok" if report.schema_diff.ok else f"{report.schema_diff.issues} issues"
    lines += [
        "| Check | Legacy | Candidate | Result |",
        "|---|---|---|---|",
        f"| Schema | | | {schema} |",
        f"| Rows | {counts.legacy:,} | {counts.candidate:,} | "
        f"{'ok' if counts.legacy == counts.candidate else 'differ'} |",
    ]
    for total in report.totals:
        lines.append(
            f"| Total of `{total.column}` | {total.legacy} | {total.candidate} | "
            f"{'ok' if total.matches else 'differ'} |"
        )
    rows = report.rows
    lines += [
        f"| Records matched | | | {rows.matched:,} |",
        f"| Records differing | | | {rows.value_diff:,} value, {rows.missing:,} missing, "
        f"{rows.extra:,} extra |",
        f"| Content hash | `{(report.golden_sha256 or '')[:12]}` | "
        f"`{(report.candidate_sha256 or '')[:12]}` | {'identical' if same_hash else '-'} |",
        "",
        f"Keys: {report.keys or 'none (multiset)'}.",
    ]
    for diff in report.column_diffs:
        lines.append(f"- `{diff.column}` ({diff.policy.value}): {diff.n_rows:,} rows differ")
        lines += [f"  - `{sample}`" for sample in diff.samples]
    if report.missing_samples:
        lines.append(f"- Only in legacy (first {len(report.missing_samples)}):")
        lines += [f"  - `{sample}`" for sample in report.missing_samples]
    if report.extra_samples:
        lines.append(f"- Only in the candidate (first {len(report.extra_samples)}):")
        lines += [f"  - `{sample}`" for sample in report.extra_samples]
    for sig in report.signatures:
        traps = (
            f" Suspected traps: {', '.join(sig.suspected_traps)}." if sig.suspected_traps else ""
        )
        lines.append(f"- Signature `{sig.kind.value}`: {sig.explanation}{traps}")
    return "\n".join(lines) + "\n"
