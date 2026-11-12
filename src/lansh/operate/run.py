"""
Run accepted jobs on the local Delta lakehouse: chained reconciliation, SLAs, lineage, schedules.

Plan §8.8 and steps 2.9 and 3.9. Each accepted module runs in the worker and writes its
outputs to ``lakehouse/<layer>/<table>`` as Delta tables. In *chained* mode its inputs are the
upstream jobs' Delta tables, not their golden outputs, so a wave proves the migrated estate
works end to end; every output is reconciled against its golden output again.

Each run also gets:

- an **SLA check** against its contract: runtime against ``max_runtime_seconds`` and rows
  against ``expected_rows`` within ``row_tolerance_pct``;
- an **OpenLineage** ``RunEvent`` (``runs/<run>/openlineage/<job>.json``) with the input and
  output datasets, their schemas and the column lineage from Discover;
- per wave, a **schedule file** that maps to one Databricks Workflows job, with a task per job
  and the dependencies between them.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from lansh.config import LAKEHOUSE_DIR
from lansh.contracts import (
    DataContract,
    EstateInventory,
    JobSpec,
    LineageEdge,
    LineageKind,
    ReconMode,
    ReconReport,
    ReconStatus,
    SlaCheck,
    WaveSchedule,
)
from lansh.lakehouse import delta_path, lakehouse_name, output_columns, stage_inputs, write_json

log = logging.getLogger(__name__)

OPENLINEAGE_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent"
PRODUCER = "https://github.com/Auslogger/Agentic-Data-Platform-Modernisation"
NAMESPACE = "lansh-lakehouse"


@dataclass
class OperateResult:
    """
    One job's run on the lakehouse.

    Attributes:
        reports: The reconciliation of each output against its golden output.
        sla: One SLA check per output.
        seconds: The worker's wall time.
        error: Why the job didn't run, if it didn't.
        lineage_event: Where the OpenLineage event was written.
    """

    job_id: str
    reports: list[ReconReport] = field(default_factory=list)
    sla: list[SlaCheck] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None
    lineage_event: Path | None = None

    @property
    def status(self) -> ReconStatus:
        """
        MATCH when the job ran and every output matched; ERROR when it didn't run.
        """
        if self.error or any(r.status is ReconStatus.ERROR for r in self.reports):
            return ReconStatus.ERROR
        if any(r.status is ReconStatus.MISMATCH for r in self.reports) or not self.reports:
            return ReconStatus.MISMATCH
        return ReconStatus.MATCH


def sla_check(
    job_id: str, table: str, seconds: float, rows: int | None, contract: DataContract | None
) -> SlaCheck:
    """
    Check one output's run against its contract's SLA.

    Args:
        job_id: The job.
        table: The output table.
        seconds: The job's runtime.
        rows: The rows written.
        contract: The output's contract, which holds the SLA.

    Returns:
        The check, with any breaches.
    """
    sla = contract.sla if contract else None
    breaches: list[str] = []
    if sla is not None:
        if seconds > sla.max_runtime_seconds:
            breaches.append("runtime")
        if rows is not None and sla.expected_rows:
            drift = abs(rows - sla.expected_rows) * 100.0 / sla.expected_rows
            if drift > sla.row_tolerance_pct:
                breaches.append("rows")
    return SlaCheck(
        job_id=job_id,
        table=table,
        runtime_seconds=round(seconds, 3),
        rows=rows,
        max_runtime_seconds=sla.max_runtime_seconds if sla else None,
        expected_rows=sla.expected_rows if sla else None,
        row_tolerance_pct=sla.row_tolerance_pct if sla else None,
        breaches=breaches,  # type: ignore[arg-type]
    )


def lineage_event(
    job: JobSpec,
    inventory: EstateInventory,
    lineage: list[LineageEdge],
    *,
    run_id: str,
    started: datetime,
    ended: datetime,
    status: ReconStatus,
) -> dict[str, Any]:
    """
    Build the OpenLineage ``RunEvent`` of one job run, with column lineage.

    Args:
        job: The job.
        inventory: The estate inventory.
        lineage: The job's verified lineage.
        run_id: The LANSH run.
        started: When the job started.
        ended: When it ended.
        status: How its reconciliation ended.

    Returns:
        The event as JSON-ready data.
    """
    from lansh.lakehouse import input_schemas

    facet = {"_producer": PRODUCER}
    inputs = []
    for table, cols in input_schemas(inventory, job).items():
        inputs.append(
            {
                "namespace": NAMESPACE,
                "name": lakehouse_name(table),
                "facets": {
                    "schema": {
                        **facet,
                        "_schemaURL": "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json",
                        "fields": [{"name": c.name, "type": c.data_type} for c in cols],
                    }
                },
            }
        )
    outputs = []
    for out in job.outputs:
        cols = output_columns(inventory, out.table)
        fields: dict[str, Any] = {}
        for e in lineage:
            if e.output_table != out.table or not e.output_column or e.input_kind != "column":
                continue
            entry = fields.setdefault(e.output_column, {"inputFields": []})
            entry["inputFields"].append(
                {
                    "namespace": NAMESPACE,
                    "name": lakehouse_name(e.input_table or ""),
                    "field": e.input_column,
                    "transformations": [
                        {
                            "type": "DIRECT" if e.kind is LineageKind.DERIVES else "INDIRECT",
                            "subtype": "TRANSFORMATION"
                            if e.kind is LineageKind.DERIVES
                            else e.kind.value.upper(),
                            "description": e.transform or "",
                        }
                    ],
                }
            )
        outputs.append(
            {
                "namespace": NAMESPACE,
                "name": lakehouse_name(out.table),
                "facets": {
                    "schema": {
                        **facet,
                        "_schemaURL": "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json",
                        "fields": [{"name": c.name, "type": c.data_type} for c in cols],
                    },
                    "columnLineage": {
                        **facet,
                        "_schemaURL": "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json",
                        "fields": fields,
                    },
                },
            }
        )
    return {
        "eventType": "COMPLETE" if status is ReconStatus.MATCH else "FAIL",
        "eventTime": ended.isoformat(),
        "run": {
            "runId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}/{job.job_id}")),
            "facets": {
                "nominalTime": {
                    **facet,
                    "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/NominalTimeRunFacet.json",
                    "nominalStartTime": started.isoformat(),
                    "nominalEndTime": ended.isoformat(),
                }
            },
        },
        "job": {"namespace": "lansh", "name": f"{job.job_id}.{job.name}"},
        "inputs": inputs,
        "outputs": outputs,
        "producer": PRODUCER,
        "schemaURL": OPENLINEAGE_SCHEMA,
    }


def operate_job(
    spark: Any,
    inventory: EstateInventory,
    job: JobSpec,
    module: Path,
    run_dir: Path,
    *,
    run_id: str,
    contracts: dict[str, DataContract],
    lineage: list[LineageEdge],
    lakehouse: Path = LAKEHOUSE_DIR,
    chained: bool = True,
) -> OperateResult:
    """
    Run one accepted job on the lakehouse and reconcile what it wrote.

    Args:
        spark: The parent's Spark session.
        inventory: The estate inventory.
        job: The job.
        module: Its accepted module.
        run_dir: Where the run's staging, events and logs go.
        run_id: The run.
        contracts: The approved contracts by legacy table.
        lineage: The job's verified lineage, for its OpenLineage event.
        lakehouse: The lakehouse root.
        chained: Read upstream outputs from the lakehouse (else from their golden outputs).

    Returns:
        The reports, SLA checks and lineage event of the run.
    """
    from lansh.discover.traps import signature_lookup
    from lansh.generate.worker import run_in_worker, spec_for
    from lansh.reconcile.job import compare_output, error_report

    mode = ReconMode.CHAINED if chained else ReconMode.ISOLATED
    started = datetime.now(UTC)
    clock = time.perf_counter()
    result = OperateResult(job.job_id)
    staged = stage_inputs(
        inventory,
        job,
        "chained" if chained else "isolated",
        run_dir / "staging",
        lakehouse=lakehouse,
        spark=spark,
    )
    outputs = {o.table: output_columns(inventory, o.table) for o in job.outputs}
    paths = {o.table: delta_path(o.table, lakehouse) for o in job.outputs}
    spec = spec_for(
        job, module, staged, outputs, run_dir / "outputs", write="delta", delta_paths=paths
    )
    worker = run_in_worker(spec)
    result.seconds = worker.seconds
    for out in job.outputs:
        contract = contracts.get(out.table)
        if worker.status != "ok":
            result.error = worker.error or worker.status
            result.reports.append(error_report(job, out.table, mode, result.error, run_id=run_id))
            continue
        result.reports.append(
            compare_output(
                spark,
                inventory,
                job,
                out.table,
                paths[out.table],
                mode=mode,
                contract=contract,
                run_id=run_id,
                traps_for=signature_lookup(job.language),
            )
        )
        result.sla.append(
            sla_check(
                job.job_id, out.table, worker.job_seconds, worker.rows.get(out.table), contract
            )
        )
    ended = datetime.now(UTC)
    event = lineage_event(
        job, inventory, lineage, run_id=run_id, started=started, ended=ended, status=result.status
    )
    result.lineage_event = write_json(run_dir.parent / "openlineage" / f"{job.job_id}.json", event)
    log.info(
        "%s operated on Delta in %.1fs: %s",
        job.job_id,
        time.perf_counter() - clock,
        result.status.value,
    )
    return result


def wave_schedules(waves: list[list[str]], inventory: EstateInventory) -> list[WaveSchedule]:
    """
    Make one schedule per wave: wave 1 runs nightly, each later wave after the one before it.

    Args:
        waves: The job ids of each wave, in order.
        inventory: The estate inventory.

    Returns:
        The schedules.
    """
    del inventory
    out = []
    for number, job_ids in enumerate(waves, 1):
        out.append(
            WaveSchedule(
                wave=number,
                job_ids=list(job_ids),
                depends_on_waves=[number - 1] if number > 1 else [],
                trigger="cron: 0 2 * * *" if number == 1 else f"after wave {number - 1}",
            )
        )
    return out


def write_schedule(schedule: WaveSchedule, inventory: EstateInventory, folder: Path) -> Path:
    """
    Write a wave's schedule file, with the Databricks Workflows job it maps to.

    Args:
        schedule: The wave's schedule.
        inventory: The estate inventory, for the jobs' dependencies.
        folder: Where schedule files go.

    Returns:
        The file written.
    """
    in_wave = set(schedule.job_ids)
    tasks = []
    for job_id in schedule.job_ids:
        ups = [u for u in inventory.upstream(job_id) if u in in_wave]
        tasks.append(
            {
                "task_key": job_id,
                "python_wheel_task": {
                    "package_name": "lansh",
                    "entry_point": "lansh",
                    "parameters": ["operate", "run", "--job", job_id],
                },
                "depends_on": [{"task_key": u} for u in ups],
            }
        )
    data = {
        **schedule.model_dump(mode="json"),
        "databricks_workflow": {
            "name": f"lansh-wave-{schedule.wave}",
            "schedule": (
                {"quartz_cron_expression": "0 0 2 * * ?", "timezone_id": "Europe/Dublin"}
                if schedule.wave == 1
                else None
            ),
            "trigger_after": f"lansh-wave-{schedule.wave - 1}" if schedule.wave > 1 else None,
            "tasks": tasks,
        },
    }
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"wave-{schedule.wave}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
