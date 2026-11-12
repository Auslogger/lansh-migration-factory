"""
Run a migrated job module in its own process, with a timeout (plan §8.5, guardrail 4).

The parent stages the inputs and writes a :class:`WorkerSpec`; the worker starts its own Spark
session, reads the inputs, imports the module from its file, calls ``run`` once per
invocation, conforms each output to its table's columns and writes it out. The parent reads
the outputs back and reconciles them in its own process, so code under test never shares a
process with the checks that judge it.

The worker gets a stripped environment (no SQL Server password, no Claude credentials) and
runs in the run folder. It can't block network access; plan §10 states that limitation.

Stateful jobs (``JobSpec.state_tables``, such as T02's type-2 history): the first invocation
receives an empty state table; each later one receives the previous invocation's output.

Entry point: ``python -m lansh.generate.worker <spec.json>``.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lansh.contracts import ColumnSpec, JobInvocation

log = logging.getLogger(__name__)

# seconds a job may run before it is killed; Spark's start-up takes about five of them
DEFAULT_TIMEOUT_S = 600.0

# environment variables a job never sees
_SECRET_MARKERS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "APIKEY", "CREDENTIAL")
_STRIPPED_PREFIXES = ("ANTHROPIC_", "CLAUDE", "MSSQL_", "LANSH_LLM", "SAS")


class _Spec(BaseModel):
    """
    Base of the worker's own records: unknown fields are refused.
    """

    model_config = ConfigDict(extra="forbid")


class WorkerInput(_Spec):
    """
    One staged input: where it is and how to read it.
    """

    path: str
    format: Literal["parquet", "delta"] = "parquet"


class WorkerSpec(_Spec):
    """
    Everything the worker needs to run one job once through all its invocations.

    Attributes:
        module: Absolute path of the migrated module.
        inputs: The staged inputs by legacy table name.
        state_tables: Outputs read back as the previous state between invocations.
        outputs: Each output table's columns, which the output is conformed to.
        out_dir: Where outputs and ``result.json`` are written.
        write: ``parquet`` for a sandbox run, ``delta`` to write the lakehouse.
        delta_paths: Where each output's Delta table goes, when ``write`` is ``delta``.
    """

    job_id: str
    module: str
    invocations: list[JobInvocation] = Field(min_length=1)
    inputs: dict[str, WorkerInput]
    state_tables: list[str] = Field(default_factory=list)
    outputs: dict[str, list[ColumnSpec]]
    out_dir: str
    write: Literal["parquet", "delta"] = "parquet"
    delta_paths: dict[str, str] = Field(default_factory=dict)


class WorkerResult(_Spec):
    """
    How a worker run ended.

    Attributes:
        status: ``ok``, ``error`` (the job raised, or its output didn't conform) or
            ``timeout``.
        outputs: Where each output was written.
        rows: Each output's row count.
        seconds: Wall time of the whole run, Spark's start-up included.
        job_seconds: Time spent in the job's invocations and writing their outputs.
        error: The error's last line, for reports and the Diagnoser.
        traceback: The full traceback, for people.
    """

    status: Literal["ok", "error", "timeout"]
    outputs: dict[str, str] = Field(default_factory=dict)
    rows: dict[str, int] = Field(default_factory=dict)
    seconds: float = 0.0
    job_seconds: float = 0.0
    error: str | None = None
    traceback: str | None = None


def worker_env(parent: dict[str, str] | None = None) -> dict[str, str]:
    """
    Build the worker's environment: the parent's, minus secrets and Claude and SAS settings.

    Args:
        parent: The environment to start from; ``os.environ`` when not given.

    Returns:
        A new dict without any variable whose name looks like a secret or starts with a
        stripped prefix.
    """
    source = dict(os.environ if parent is None else parent)
    return {
        name: value
        for name, value in source.items()
        if not name.upper().startswith(_STRIPPED_PREFIXES)
        and not any(marker in name.upper() for marker in _SECRET_MARKERS)
    }


def load_module(path: Path) -> Any:
    """
    Import a migrated job module from its file, without adding its folder to ``sys.path``.

    Args:
        path: The module file.

    Returns:
        The imported module.

    Raises:
        ImportError: If the file can't be loaded as a module.
    """
    spec = importlib.util.spec_from_file_location(f"lansh_migrated_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "run", None)):
        raise ImportError(f"{path.name} has no run(spark, inputs, params) function")
    return module


def _execute(spec: WorkerSpec) -> WorkerResult:
    """
    Run the job in this process: the worker's side of the protocol.
    """
    from lansh.lakehouse import conform, empty_frame
    from lansh.reconcile.engine import plain_strings, refuse_collated
    from lansh.spark import get_spark

    started = time.perf_counter()
    spark = get_spark(f"lansh-worker-{spec.job_id}")
    frames = {
        table: spark.read.format(staged.format).load(staged.path)
        for table, staged in spec.inputs.items()
    }
    for table in spec.state_tables:
        frames[table] = empty_frame(spark, spec.outputs[table])
    module = load_module(Path(spec.module))
    job_started = time.perf_counter()
    outputs: dict[str, Any] = {}
    for i, invocation in enumerate(spec.invocations):
        params = {k: str(v) for k, v in invocation.params.items()}
        got = module.run(spark, dict(frames), params)
        if not isinstance(got, dict):
            raise TypeError(f"run() returned {type(got).__name__}, not a dict of DataFrames")
        found = {name.lower(): df for name, df in got.items()}
        missing = [t for t in spec.outputs if t not in found]
        if missing:
            raise ValueError(f"run() returned no output for {missing}")
        outputs = {t: plain_strings(conform(found[t], cols)) for t, cols in spec.outputs.items()}
        if i < len(spec.invocations) - 1:
            for table in spec.state_tables:
                # materialise the state, so the next batch reads this one's rows, not a plan
                # that recomputes them
                state = outputs[table].localCheckpoint(eager=True)
                frames[table] = state
    out_dir = Path(spec.out_dir)
    written: dict[str, str] = {}
    rows: dict[str, int] = {}
    for table, df in outputs.items():
        refuse_collated(df, table)
        if spec.write == "delta":
            path = spec.delta_paths[table]
            df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(path)
            rows[table] = spark.read.format("delta").load(path).count()
        else:
            path = str(out_dir / f"{table}.parquet")
            df.write.mode("overwrite").parquet(path)
            rows[table] = spark.read.parquet(path).count()
        written[table] = path
    end = time.perf_counter()
    return WorkerResult(
        status="ok",
        outputs=written,
        rows=rows,
        seconds=round(end - started, 3),
        job_seconds=round(end - job_started, 3),
    )


def main(argv: list[str] | None = None) -> int:
    """
    Run the worker: read the spec, run the job, write ``result.json``.

    Args:
        argv: The command-line arguments; ``sys.argv[1:]`` when not given.

    Returns:
        0 when the job ran, 1 when it failed (the result says why).
    """
    args = sys.argv[1:] if argv is None else argv
    spec = WorkerSpec.model_validate_json(Path(args[0]).read_text(encoding="utf-8"))
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        result = _execute(spec)
    except BaseException as exc:  # the job's own errors are the result, not a crash
        last = (traceback.format_exception_only(exc)[-1]).strip()
        result = WorkerResult(
            status="error",
            seconds=round(time.perf_counter() - started, 3),
            error=last[:2000],
            traceback=traceback.format_exc()[-8000:],
        )
    (out_dir / "result.json").write_text(result.model_dump_json(indent=2) + "\n", "utf-8")
    return 0 if result.status == "ok" else 1


def run_in_worker(spec: WorkerSpec, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> WorkerResult:
    """
    Run a job in a fresh worker process and wait for it, up to the timeout.

    Args:
        spec: What to run; written to ``<out_dir>/spec.json``.
        timeout_s: Seconds before the worker is killed.

    Returns:
        The worker's result, or a ``timeout`` or ``error`` result when it didn't finish or
        wrote none.
    """
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2) + "\n", "utf-8")
    result_path = out_dir / "result.json"
    result_path.unlink(missing_ok=True)
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "lansh.generate.worker", str(spec_path)],
            cwd=out_dir,
            env=worker_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return WorkerResult(
            status="timeout",
            seconds=round(time.perf_counter() - started, 3),
            error=f"the job did not finish within {timeout_s:.0f} s and was stopped",
        )
    (out_dir / "worker.log").write_text(proc.stdout + proc.stderr, "utf-8")
    if not result_path.exists():
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        return WorkerResult(
            status="error",
            seconds=round(time.perf_counter() - started, 3),
            error=f"the worker exited with code {proc.returncode} and no result: "
            + " | ".join(tail),
        )
    return WorkerResult.model_validate_json(result_path.read_text(encoding="utf-8"))


def spec_for(
    job: Any,
    module: Path,
    staged: dict[str, Any],
    outputs: dict[str, list[ColumnSpec]],
    out_dir: Path,
    *,
    write: Literal["parquet", "delta"] = "parquet",
    delta_paths: dict[str, Path] | None = None,
) -> WorkerSpec:
    """
    Build the worker's spec for one job from its inventory entry and staged inputs.

    Args:
        job: The job's ``JobSpec``.
        module: The migrated module.
        staged: The staged inputs, from ``lansh.lakehouse.stage_inputs``.
        outputs: Each output table's columns.
        out_dir: Where the worker writes.
        write: ``parquet`` for a sandbox run, ``delta`` for the lakehouse.
        delta_paths: Each output's Delta folder, when writing Delta.

    Returns:
        The spec.
    """
    return WorkerSpec(
        job_id=job.job_id,
        module=str(Path(module).resolve()),
        invocations=list(job.invocations),
        inputs={
            t: WorkerInput(path=str(Path(s.path).resolve()), format=s.format)
            for t, s in staged.items()
        },
        state_tables=list(job.state_tables),
        outputs=outputs,
        out_dir=str(out_dir.resolve()),
        write=write,
        delta_paths={t: str(Path(p).resolve()) for t, p in (delta_paths or {}).items()},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
