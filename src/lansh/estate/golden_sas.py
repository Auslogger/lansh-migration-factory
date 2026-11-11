"""
Run legacy SAS jobs through saspy, and capture their golden outputs (plan §7.3).

Librefs ``stg``, ``dw`` and ``rpt`` point at folders under ``~/lansh/<root>/`` on the SAS
server: ``dev`` for development runs, ``golden`` for captures (cleared first). Inputs are
staged before the program runs:

- ``stg.*`` from the committed extracts, which carry ``_row_seq``;
- outputs of T-SQL jobs from their golden Parquet (or, in development before a capture, from
  SQL Server). They get ``_row_seq`` in **key order**: sorted by their first column, then the
  others, which is how a SAS ``libname`` read of the clustered warehouse table sees them;
- outputs of SAS jobs are read where the upstream SAS job wrote them, as native data sets.

The program runs after ``options mprint;`` and ``%let as_of = '31DEC2025'd;``. Outputs come
back exactly (see :mod:`lansh.engines.sas`), with the raw export, its PROC CONTENTS metadata
and the SAS log kept in the golden pack.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from lansh import __version__
from lansh.config import DATA_DIR, GOLDEN_DIR, LABELS_DIR, REPO_ROOT
from lansh.contracts import (
    ArtifactRef,
    ColumnSpec,
    EstateInventory,
    GoldenManifest,
    JobSpec,
    Language,
)
from lansh.engines import sas as sase
from lansh.estate.fingerprint import file_sha256
from lansh.estate.generate import load_dictionary
from lansh.estate.golden import input_fingerprints, rel, write_output
from lansh.estate.inventory import load_inventory
from lansh.estate.legacy import LEGACY_DATABASE

log = logging.getLogger(__name__)

LIBS = ("stg", "dw", "rpt")
"""The librefs every run assigns, each a folder under ``~/lansh/<root>/``."""

Mode = Literal["dev", "golden"]
"""Which folder tree a run uses on the SAS server: ``dev`` or ``golden`` (captures)."""

# SAS date literals take English month names; strftime's %b would follow the locale
_SAS_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def sas_date_literal(iso: str) -> str:
    """
    Turn an ISO date into a SAS date literal, such as ``'31DEC2025'd``.

    The month comes from a fixed English table, so the literal is the same on every machine,
    whatever its locale.

    Args:
        iso: A date as ``YYYY-MM-DD``.

    Returns:
        The SAS date literal.
    """
    day = dt.date.fromisoformat(iso)
    return f"'{day.day:02d}{_SAS_MONTHS[day.month - 1]}{day.year:04d}'d"


def prelude(job: JobSpec) -> str:
    """
    Build the SAS code run before a job: ``options mprint;`` and the ``as_of`` date.

    The date is the first invocation's ``AsOfDate`` parameter, or 2025-12-31 without one.

    Args:
        job: The SAS job about to run.

    Returns:
        The SAS code.
    """
    as_of = str(job.invocations[0].params.get("AsOfDate", "2025-12-31"))
    return f"options mprint;\n%let as_of = {sas_date_literal(as_of)};\n"


def lib_code(session: sase.SasSession, root: str, clear: bool) -> str:
    """
    Build the libname statements for ``stg``, ``dw`` and ``rpt`` under ``~/lansh/<root>/``.

    Building them already creates any missing folder on the SAS server.

    Args:
        session: Open SAS session.
        root: The folder tree: ``dev`` or ``golden``.
        clear: Also delete every data set in the three libraries.

    Returns:
        The SAS code.
    """
    lines = []
    for lib in LIBS:
        folder = session.remote_path("lansh", root, lib)
        session.ensure_dir(folder)
        lines.append(f"libname {lib} '{folder}';")
    if clear:
        lines += [f"proc datasets lib={lib} kill nolist nowarn; quit;" for lib in LIBS]
    return "\n".join(lines) + "\n"


def char_lengths(columns: list[ColumnSpec]) -> dict[str, int]:
    """
    Work out SAS byte lengths for character columns from their legacy types.

    Only string columns with a width, such as ``VARCHAR(40)``, get a length; ``MAX`` types
    and types without a width are left out.

    Args:
        columns: Column specs with legacy SQL Server types.

    Returns:
        Bytes per column name.
    """
    lengths = {}
    for col in columns:
        legacy = (col.legacy_type or "").upper()
        if col.data_type != "string" or "(" not in legacy or "MAX" in legacy:
            continue
        width = int(legacy.split("(")[1].split(")")[0])
        # widths of NVARCHAR and NCHAR count characters, and a fada takes two bytes in UTF-8
        lengths[col.name] = width * 2 if legacy.startswith("N") else width
    return lengths


def fitted_lengths(data: pa.Table, columns: list[ColumnSpec]) -> dict[str, int]:
    """
    Size character columns for SAS: legacy widths, raised where the UTF-8 bytes need more.

    A fada takes two bytes, so a ``VARCHAR(n)`` value with accents can need more than n
    bytes once it is UTF-8.

    Args:
        data: The rows to upload.
        columns: Their column specs, with legacy types.

    Returns:
        Bytes per character column.
    """
    lengths = char_lengths(columns)
    for name in lengths:
        if name in data.column_names:
            values = data.column(name).to_pylist()
            longest = max((len(v.encode("utf-8")) for v in values if v), default=1)
            lengths[name] = max(lengths[name], longest)
    return lengths


def with_key_order_row_seq(table: pa.Table) -> pa.Table:
    """
    Add ``_row_seq`` in key order: by the first column, then the others.

    Values sort by type (numbers numerically, text by code point, which is Spark's binary
    order too), NULLs first, so a migrated job can reproduce the order exactly.

    Args:
        table: An upstream T-SQL output, without its volatile columns.

    Returns:
        The table with a 1-based ``_row_seq`` column added; the rows don't move.
    """
    columns = [table.column(i).to_pylist() for i in range(table.num_columns)]

    def key(i: int) -> list[tuple[int, Any]]:
        """
        Sort key for row ``i``: each value tagged so that NULL sorts before anything else.
        """
        return [(0, 0) if col[i] is None else (1, col[i]) for col in columns]

    order = sorted(range(table.num_rows), key=key)
    seq = [0] * table.num_rows
    for position, i in enumerate(order, 1):
        seq[i] = position
    return table.append_column("_row_seq", pa.array(seq, type=pa.int32()))


def input_table(
    name: str,
    inventory: EstateInventory,
    mode: Mode,
) -> tuple[pa.Table, list[ColumnSpec]] | None:
    """
    Find the data to stage for one input, or None when SAS already has it (SAS outputs).

    A T-SQL output comes from its golden Parquet, without volatile columns and with
    ``_row_seq`` in key order. In ``dev`` mode, before that job is captured, it is read from
    SQL Server instead.

    Args:
        name: The input table, such as ``stg.claims``.
        inventory: The estate inventory.
        mode: ``dev`` or ``golden``; only ``dev`` may fall back to SQL Server.

    Returns:
        The rows and their column specs, or None for an output of a SAS job.

    Raises:
        RuntimeError: In ``golden`` mode, a T-SQL input has no golden output yet.
    """
    producers = inventory.producers()
    if name in inventory.sources:
        schema = next(s for s in load_dictionary() if s.name == name)
        return pq.read_table(DATA_DIR / f"{name.split('.', 1)[1]}.parquet"), schema.columns
    producer = inventory.job(producers[name])
    if producer.language is Language.SAS:
        return None
    golden = GOLDEN_DIR / producer.job_id / f"{name}.parquet"
    if golden.exists():
        manifest = GoldenManifest.model_validate_json(
            (GOLDEN_DIR / producer.job_id / "manifest.json").read_text()
        )
        out = next(o for o in manifest.outputs if o.table == name)
        data = pq.read_table(golden)
        if out.volatile_columns:
            data = data.drop_columns(out.volatile_columns)
        cols = [c for c in out.columns if c.name not in out.volatile_columns]
        return with_key_order_row_seq(data), cols
    if mode == "golden":
        raise RuntimeError(f"{name} has no golden output yet: capture {producer.job_id} first")
    from lansh.engines import mssql

    with mssql.connect(LEGACY_DATABASE) as conn:
        sql_cols, data = mssql.fetch_table(conn, name)
    vol = next(o.volatile_columns for o in producer.outputs if o.table == name)
    data = data.drop_columns(vol) if vol else data
    cols = [c.to_spec() for c in sql_cols if c.name not in vol]
    return with_key_order_row_seq(data), cols


def stage_inputs(
    session: sase.SasSession,
    job: JobSpec,
    inventory: EstateInventory,
    mode: Mode,
    root: str,
    local_dir: Path,
) -> list[str]:
    """
    Upload a job's inputs to SAS, except outputs of SAS jobs, which are already there.

    Args:
        session: Open SAS session with the librefs assigned.
        job: The SAS job about to run.
        inventory: The estate inventory.
        mode: ``dev`` or ``golden``, as for :func:`input_table`.
        root: The folder tree on the SAS server.
        local_dir: Local folder for the CSV files being uploaded.

    Returns:
        A note per uploaded input: its name and row count.
    """
    staged = []
    remote_dir = session.remote_path("lansh", root, "incoming")
    session.ensure_dir(remote_dir)
    for name in job.inputs:
        found = input_table(name, inventory, mode)
        if found is None:
            rows = session.nobs(name)
            log.info("%s: %s already in SAS (%d rows)", job.job_id, name, rows)
            continue
        data, cols = found
        uploaded = sase.upload_table(
            session,
            data,
            name,
            remote_dir=remote_dir,
            local_dir=local_dir,
            stem=name.replace(".", "_"),
            lengths=fitted_lengths(data, cols),
        )
        staged.append(f"{name} ({uploaded.rows} rows)")
        log.info("%s: staged %s, %d rows", job.job_id, name, uploaded.rows)
    return staged


def column_specs(table: sase.SasTable) -> list[ColumnSpec]:
    """
    Describe an exported SAS data set's columns for its golden manifest.

    Character variables become strings, date and datetime variables become dates and
    timestamps, and every other numeric variable a double. The legacy type records the SAS
    type, length and format.

    Args:
        table: The exported data set.

    Returns:
        One column spec per variable, in data set order.
    """
    specs = []
    for var in table.contents.variables:
        data_type = {"char": "string", "date": "date", "datetime": "timestamp_ntz"}.get(
            var.category.value, "double"
        )
        legacy = f"{var.type} {var.length}" + (f" format={var.format}" if var.format else "")
        specs.append(
            ColumnSpec(
                name=var.name,
                data_type=data_type,
                legacy_type=legacy,
                max_length=var.length if var.type == "char" else None,
            )
        )
    return specs


def typed_arrow(table: sase.SasTable) -> pa.Table:
    """
    Convert an exported SAS data set to Arrow, with the types :func:`column_specs` reports.

    Missing values become NULL, for numbers as well as text (never NaN).

    Args:
        table: The exported data set.

    Returns:
        The typed table, in variable order.
    """
    frame = table.frame
    arrays, fields = [], []
    for var in table.contents.variables:
        values = frame[var.name]
        if var.type == "char":
            present = values.notna().tolist()
            arr = pa.array(
                [str(v) if ok else None for v, ok in zip(values, present, strict=True)],
                type=pa.string(),
            )
        elif var.category.value == "date":
            arr = pa.array(values, type=pa.date32(), from_pandas=True)
        elif var.category.value == "datetime":
            arr = pa.array(values, type=pa.timestamp("us"), from_pandas=True)
        else:
            arr = pa.array(values, type=pa.float64(), from_pandas=True)
        arrays.append(arr)
        fields.append(pa.field(var.name, arr.type))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def run_program(session: sase.SasSession, job: JobSpec) -> sase.SubmitLog:
    """
    Submit a job's SAS program after its prelude.

    Args:
        session: Open SAS session, with the librefs assigned and the inputs staged.
        job: The SAS job to run.

    Returns:
        The run's log entry.
    """
    program = (REPO_ROOT / job.path).read_text(encoding="utf-8")
    return session.submit(prelude(job) + program, label=f"run {job.job_id}")


def run_sas_job(
    job_id: str,
    mode: Mode = "dev",
    session: sase.SasSession | None = None,
    golden_dir: Path = GOLDEN_DIR,
    freeze: bool | None = None,
) -> dict[str, Any]:
    """
    Stage inputs, run one SAS job and bring its outputs back.

    In ``golden`` mode the job's outputs are frozen into ``golden_dir`` unless ``freeze`` is
    False (an upstream SAS job that only has to run so that a later one can read it).

    Args:
        job_id: A SAS job in the inventory, such as ``S01``.
        mode: ``dev`` or ``golden``: the folder tree on the SAS server.
        session: Open session to reuse. Without one, a session is opened and closed here.
        golden_dir: Folder holding one golden pack per job.
        freeze: Whether to write a golden pack; None means only in ``golden`` mode.

    Returns:
        A summary with ``job_id``, the ``staged`` inputs, the log's ``warnings`` and
        ``data_notes``, rows per output table under ``outputs`` and, when frozen, the
        ``manifest``.

    Raises:
        ValueError: The job is not a SAS job.
    """
    freeze = (mode == "golden") if freeze is None else freeze
    inventory = load_inventory()
    job = inventory.job(job_id)
    if job.language is not Language.SAS:
        raise ValueError(f"{job_id} is not a SAS job")
    own = session is None
    session = session or sase.SasSession()
    if own:
        session.open()
    started = time.perf_counter()
    first_log = len(session.logs)
    try:
        root = mode
        with tempfile.TemporaryDirectory(prefix=f"lansh-{job_id}-") as tmp:
            tmp_dir = Path(tmp)
            session.submit(lib_code(session, root, clear=False), label="libnames")
            staged = stage_inputs(session, job, inventory, mode, root, tmp_dir / "in")
            run_log = run_program(session, job)
            export_dir = session.remote_path("lansh", root, "export")
            session.ensure_dir(export_dir)
            results: dict[str, Any] = {
                "job_id": job_id,
                "staged": staged,
                "warnings": run_log.warnings,
                "data_notes": run_log.data_notes,
                "outputs": {},
            }
            outputs = []
            for out in job.outputs:
                exported = sase.export_table(
                    session,
                    out.table,
                    remote_dir=export_dir,
                    local_dir=tmp_dir / "out",
                    stem=out.table.replace(".", "_"),
                )
                results["outputs"][out.table] = exported.contents.nobs
                if freeze:
                    outputs.append(_freeze(job, out.table, exported, golden_dir))
            if freeze:
                log_text = "\n\n".join(e.log for e in session.logs[first_log:])
                job_dir = golden_dir / job_id
                log_path = job_dir / "sas.log"
                log_path.write_text(log_text + "\n", encoding="utf-8")
                log_ref = ArtifactRef(path=rel(log_path), sha256=file_sha256(log_path))
                outputs = [
                    o.model_copy(update={"sidecars": [*o.sidecars, log_ref]}) for o in outputs
                ]
                notes = [
                    line
                    for e in session.logs[first_log:]
                    for line in e.log.splitlines()
                    if line.startswith(("NOTE: The data set", "WARNING", "NOTE: There were"))
                ]
                manifest = GoldenManifest(
                    job_id=job_id,
                    engine="sas",
                    engine_version=f"SAS {session.version}",
                    legacy_path=job.path,
                    legacy_sha256=file_sha256(REPO_ROOT / job.path),
                    invocations=job.invocations,
                    inputs=input_fingerprints(job),
                    outputs=outputs,
                    log_excerpt="\n".join(notes[-40:]),
                    captured_at=dt.datetime.now(dt.UTC),
                    capture_seconds=round(time.perf_counter() - started, 3),
                    lansh_version=__version__,
                )
                (job_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
                results["manifest"] = manifest
            return results
    finally:
        if own:
            session.close()


def _freeze(job: JobSpec, table: str, exported: sase.SasTable, golden_dir: Path) -> Any:
    """
    Copy one exported SAS output into the job's golden pack and describe it.

    Returns:
        The output's :class:`~lansh.contracts.GoldenOutput`, with SAS's own export as its
        raw CSV and the PROC CONTENTS and HEX16 files as sidecars.
    """
    job_dir = golden_dir / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    # keep SAS's own files: the raw export, the exact HEX16 sidecar and PROC CONTENTS
    sidecars = []
    contents = job_dir / f"{table}.contents.csv"
    shutil.copyfile(exported.contents_path, contents)
    sidecars.append(contents)
    if exported.hex_path:
        hex_copy = job_dir / f"{table}.hex.csv"
        shutil.copyfile(exported.hex_path, hex_copy)
        sidecars.append(hex_copy)
    golden = write_output(job_dir, table, typed_arrow(exported), column_specs(exported), [])
    raw = job_dir / f"{table}.csv"
    shutil.copyfile(exported.csv_path, raw)  # the raw export replaces the re-serialised CSV
    return golden.model_copy(
        update={
            "raw_path": rel(raw),
            "raw_sha256": file_sha256(raw),
            "sidecars": [ArtifactRef(path=rel(p), sha256=file_sha256(p)) for p in sidecars],
        }
    )


def capture_sas_jobs(
    job_ids: list[str], capture: list[str] | None = None, golden_dir: Path = GOLDEN_DIR
) -> list[GoldenManifest]:
    """
    Run SAS jobs in one session, from cleared golden libraries, and freeze their outputs.

    The jobs run in the order given, which must be dependency order, so that a later job can
    read what an earlier one wrote.

    Args:
        job_ids: The SAS jobs to run, in dependency order.
        capture: The jobs whose outputs to freeze; None freezes them all.
        golden_dir: Folder holding one golden pack per job.

    Returns:
        A manifest per frozen job, in run order.
    """
    wanted = set(job_ids if capture is None else capture)
    manifests = []
    with sase.SasSession() as session:
        session.submit(lib_code(session, "golden", clear=True), label="clear golden libraries")
        for job_id in job_ids:
            result = run_sas_job(job_id, "golden", session, golden_dir, freeze=job_id in wanted)
            if job_id in wanted:
                manifests.append(result["manifest"])
    return manifests


def run_sas_checks(job_id: str) -> list[Any]:
    """
    Run a SAS job's answer-key checks against the dev libraries (evaluation only).

    The job must already have run in ``dev`` mode. The check program writes one observation
    per check to ``work._lansh_checks``, which is exported and read back.

    Args:
        job_id: The SAS job whose ``checks/<JOB>.sas`` to run.

    Returns:
        One :class:`~lansh.estate.labels.CheckResult` per observation.

    Raises:
        RuntimeError: The checks that ran are not the ones the program declares.
    """
    # imported here, so loading this module doesn't load the answer key
    from lansh.estate.labels import CheckResult, sas_check_ids

    inventory = load_inventory()
    job = inventory.job(job_id)
    code = (LABELS_DIR / "checks" / f"{job_id}.sas").read_text(encoding="utf-8")
    declared = sas_check_ids(code)
    with sase.SasSession() as session, tempfile.TemporaryDirectory() as tmp:
        session.submit(lib_code(session, "dev", clear=False), label="libnames")
        session.submit(prelude(job) + code, label=f"checks {job_id}")
        export_dir = session.remote_path("lansh", "dev", "export")
        session.ensure_dir(export_dir)
        exported = sase.export_table(
            session, "work._lansh_checks", remote_dir=export_dir, local_dir=Path(tmp), stem="checks"
        )
    results = []
    for row in exported.frame.itertuples(index=False):
        detail = getattr(row, "detail", None)
        results.append(
            CheckResult(
                job_id=job_id,
                check_id=str(row.check_id).strip(),
                affected=int(row.affected or 0),
                detail=None if detail is None or detail != detail else str(detail).strip(),
                engine="sas",
            )
        )
    got = [r.check_id for r in results]
    if sorted(got) != sorted(declared):
        raise RuntimeError(f"{job_id}: declared checks {declared} but got {got}")
    return results
