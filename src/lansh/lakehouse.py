"""
The local lakehouse and the data a migrated job reads and writes (plan §6.4, §8.8).

Legacy schemas map onto medallion layers: ``stg`` (source extracts) is bronze, ``dw``
(warehouse) is silver and ``rpt`` (reporting) is gold, so ``rpt.claims_summary`` lives at
``lakehouse/gold/claims_summary`` as a Delta table.

A migrated job never does its own I/O. The harness stages its inputs and hands them over as
DataFrames:

- source tables come from the committed extracts in ``estate/data``;
- an upstream job's output comes from its golden Parquet (*isolated* mode) or from the
  migrated upstream job's Delta table (*chained* mode);
- a SAS job sees a T-SQL job's output as SAS saw it during golden capture: without its
  volatile audit columns, and with ``_row_seq`` in key order (``estate/README.md``).

Outputs are conformed to their contract's column order and logical types, as the legacy
engine's typed target table would have converted them on insert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from lansh.config import DATA_DIR, GOLDEN_DIR, LAKEHOUSE_DIR
from lansh.contracts import (
    ColumnSpec,
    EstateInventory,
    GoldenManifest,
    GoldenOutput,
    JobSpec,
    Language,
    Layer,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

InputMode = Literal["isolated", "chained"]
"""Where upstream outputs come from: their golden outputs, or the migrated upstream jobs."""

SCHEMA_LAYER = {"stg": Layer.BRONZE, "dw": Layer.SILVER, "rpt": Layer.GOLD}
"""The medallion layer of each legacy schema."""


def layer_of(table: str) -> Layer:
    """
    Give the medallion layer a legacy table belongs to.

    Args:
        table: A schema-qualified legacy table name, such as ``rpt.claims_summary``.

    Returns:
        Bronze for ``stg``, silver for ``dw`` and gold for ``rpt``; silver for any other
        schema, such as a held-out job's.
    """
    return SCHEMA_LAYER.get(table.split(".", 1)[0].lower(), Layer.SILVER)


def lakehouse_name(table: str) -> str:
    """
    Give the lakehouse name of a legacy table: its layer, then its name.

    Args:
        table: A legacy table name, such as ``rpt.claims_summary``.

    Returns:
        The lakehouse name, such as ``gold.claims_summary``.
    """
    return f"{layer_of(table).value}.{table.split('.', 1)[1].lower()}"


def delta_path(table: str, root: Path = LAKEHOUSE_DIR) -> Path:
    """
    Give the folder of a legacy table's Delta table in the lakehouse.

    Args:
        table: A legacy table name.
        root: The lakehouse root.

    Returns:
        ``<root>/<layer>/<name>``.
    """
    layer, name = lakehouse_name(table).split(".", 1)
    return root / layer / name


def source_path(table: str) -> Path:
    """
    Give the committed extract of a source table.

    Args:
        table: A source table, such as ``stg.claims``.

    Returns:
        ``estate/data/<name>.parquet``.
    """
    return DATA_DIR / f"{table.split('.', 1)[1]}.parquet"


@dataclass(frozen=True)
class GoldenTable:
    """
    One golden output: its manifest entry and the job that wrote it.
    """

    job_id: str
    output: GoldenOutput

    @property
    def path(self) -> Path:
        """
        The typed Parquet copy of the golden output.
        """
        return GOLDEN_DIR / self.job_id / f"{self.output.table}.parquet"


def golden_manifest(job_id: str) -> GoldenManifest:
    """
    Read a job's golden manifest.

    Args:
        job_id: The job, such as ``T04``.

    Returns:
        The validated manifest.
    """
    return GoldenManifest.model_validate_json(
        (GOLDEN_DIR / job_id / "manifest.json").read_text(encoding="utf-8")
    )


def golden_table(inventory: EstateInventory, table: str) -> GoldenTable:
    """
    Find the golden output of a table some job writes.

    Args:
        inventory: The estate inventory.
        table: An output table, such as ``dw.dim_customer``.

    Returns:
        The golden output and its job.

    Raises:
        KeyError: If no job writes the table, or its golden pack lacks it.
    """
    job_id = inventory.producers()[table]
    manifest = golden_manifest(job_id)
    for out in manifest.outputs:
        if out.table == table:
            return GoldenTable(job_id, out)
    raise KeyError(f"{job_id}'s golden pack has no {table}")


def output_columns(inventory: EstateInventory, table: str) -> list[ColumnSpec]:
    """
    Give an output table's columns, as its legacy table defines them.

    They come from the golden manifest, which records the engine's own column metadata.

    Args:
        inventory: The estate inventory.
        table: An output table.

    Returns:
        The columns in table order.
    """
    return list(golden_table(inventory, table).output.columns)


def with_key_order_row_seq(table: pa.Table) -> pa.Table:
    """
    Add ``_row_seq`` in key order: by the first column, then the others, NULLs first.

    It's how SAS saw a T-SQL output during golden capture, so a migrated SAS job must see
    the same order. The implementation is the capture's own, so the two can't drift.

    Args:
        table: A T-SQL output, without its volatile columns.

    Returns:
        The table with a 1-based ``_row_seq`` column added; the rows don't move.
    """
    from lansh.estate.golden_sas import with_key_order_row_seq as capture_order

    return capture_order(table)


@dataclass(frozen=True)
class StagedInput:
    """
    Where one input of a job is, ready for the worker to read.

    Attributes:
        table: The legacy table name the job reads it as.
        path: A Parquet file or folder, or a Delta table folder.
        format: ``parquet`` or ``delta``.
    """

    table: str
    path: Path
    format: Literal["parquet", "delta"]


def stage_inputs(
    inventory: EstateInventory,
    job: JobSpec,
    mode: InputMode,
    staging_dir: Path,
    *,
    lakehouse: Path = LAKEHOUSE_DIR,
    spark: SparkSession | None = None,
) -> dict[str, StagedInput]:
    """
    Stage every input of a job for the worker, as the legacy engine saw it.

    Args:
        inventory: The estate inventory.
        job: The job about to run.
        mode: ``isolated`` (upstream golden outputs) or ``chained`` (upstream migrated
            outputs, from the lakehouse).
        staging_dir: Where re-ordered copies are written; created when needed.
        lakehouse: The lakehouse root, for chained mode.
        spark: A session for reading upstream Delta tables; needed only in chained mode
            when a SAS job reads a T-SQL job's output.

    Returns:
        One staged input per input table, in the job's input order.

    Raises:
        KeyError: If an input is neither a source nor any job's output.
        FileNotFoundError: In chained mode, if an upstream Delta table hasn't been written.
    """
    producers = inventory.producers()
    staged: dict[str, StagedInput] = {}
    for table in job.inputs:
        if table in inventory.sources:
            staged[table] = StagedInput(table, source_path(table), "parquet")
            continue
        producer = inventory.job(producers[table])
        sas_reads_tsql = job.language is Language.SAS and producer.language is Language.TSQL
        golden = golden_table(inventory, table)
        if mode == "chained":
            path = delta_path(table, lakehouse)
            if not (path / "_delta_log").is_dir():
                raise FileNotFoundError(f"{table} has no Delta table yet at {path}")
            if not sas_reads_tsql:
                staged[table] = StagedInput(table, path, "delta")
                continue
            if spark is None:
                raise ValueError("a Spark session is needed to re-order a chained input")
            data = spark.read.format("delta").load(str(path)).toArrow()
        else:
            if not sas_reads_tsql:
                staged[table] = StagedInput(table, golden.path, "parquet")
                continue
            data = pq.read_table(golden.path)
        volatile = [c for c in golden.output.volatile_columns if c in data.column_names]
        data = with_key_order_row_seq(data.drop_columns(volatile) if volatile else data)
        staging_dir.mkdir(parents=True, exist_ok=True)
        path = staging_dir / f"{table}.parquet"
        pq.write_table(data, path)
        staged[table] = StagedInput(table, path, "parquet")
    return staged


def schema_ddl(columns: list[ColumnSpec]) -> str:
    """
    Write a Spark DDL schema string for columns with logical types.

    Args:
        columns: The columns, whose ``data_type`` is a logical (Spark) type.

    Returns:
        Text such as ``\\`claim_id\\` int, \\`total_paid\\` decimal(14,2)``.
    """
    return ", ".join(f"`{c.name.replace('`', '``')}` {c.data_type}" for c in columns)


def empty_frame(spark: SparkSession, columns: list[ColumnSpec]) -> DataFrame:
    """
    Make an empty DataFrame with the given columns: a stateful job's state before batch 1.

    Args:
        spark: The Spark session.
        columns: The state table's columns.

    Returns:
        An empty frame with those columns and types.
    """
    return spark.createDataFrame([], schema_ddl(columns))


def conform(df: DataFrame, columns: list[ColumnSpec]) -> DataFrame:
    """
    Put an output in its table's column order and cast each column to its logical type.

    This is what inserting into the legacy engine's typed table does: a DECIMAL(38,6)
    value written to a DECIMAL(14,2) column is rounded, an integer written to a SAS numeric
    becomes a double. Columns the table lacks are dropped. Under ANSI mode a value that
    doesn't fit its type raises, as the legacy insert would have failed.

    Args:
        df: The job's output.
        columns: The output table's columns.

    Returns:
        The conformed frame.

    Raises:
        ValueError: If the output lacks a column the table has.
    """
    from pyspark.sql import functions as F

    have = {c.casefold(): c for c in df.columns}
    missing = [c.name for c in columns if c.name.casefold() not in have]
    if missing:
        raise ValueError(f"the job's output lacks columns {missing}")
    return df.select(
        *[F.col(f"`{have[c.name.casefold()]}`").cast(c.data_type).alias(c.name) for c in columns]
    )


def read_staged(spark: SparkSession, staged: StagedInput) -> DataFrame:
    """
    Read one staged input as a DataFrame.

    Args:
        spark: The Spark session.
        staged: The input, from :func:`stage_inputs`.

    Returns:
        The input's rows.
    """
    reader = spark.read.format(staged.format)
    return reader.load(str(staged.path))


def write_json(path: Path, data: object) -> Path:
    """
    Write JSON with sorted keys and a final newline, creating the folder if needed.

    Args:
        path: The file to write.
        data: Anything ``json.dumps`` can serialise.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
    return path


def input_schemas(
    inventory: EstateInventory, job: JobSpec, contracts: dict[str, Any] | None = None
) -> dict[str, list[ColumnSpec]]:
    """
    Give the columns of every table a job reads, as the job sees them.

    Source tables come from the data dictionary, with their ``pii`` and ``protected`` tags;
    an upstream output from its golden manifest, with the tags its contract gave it (passed
    in, or read from ``migrated/contracts/``), so a tagged column's flow survives from job to
    job. A SAS job sees a T-SQL output without its volatile columns and with ``_row_seq``
    added. A stateful job's own previous output is listed too.

    Args:
        inventory: The estate inventory.
        job: The job.
        contracts: Upstream outputs' data contracts by legacy table, for their tags.

    Returns:
        Columns by table name, in the job's input order, then its state tables.
    """
    from lansh.estate.generate import load_dictionary
    from lansh.reconcile.job import load_contract

    dictionary = {s.name: list(s.columns) for s in load_dictionary()}
    producers = inventory.producers()
    out: dict[str, list[ColumnSpec]] = {}
    for table in [*job.inputs, *job.state_tables]:
        if table in dictionary:
            out[table] = dictionary[table]
            continue
        golden = golden_table(inventory, table)
        columns = list(golden.output.columns)
        contract = (contracts or {}).get(table) or load_contract(table)
        if contract is not None:
            tags = {c.name.casefold(): c.tags for c in contract.columns}
            columns = [
                c.model_copy(update={"tags": tags.get(c.name.casefold(), c.tags)}) for c in columns
            ]
        producer = inventory.job(producers[table])
        if (
            job.language is Language.SAS
            and producer.language is Language.TSQL
            and table not in job.state_tables
        ):
            volatile = set(golden.output.volatile_columns)
            columns = [c for c in columns if c.name not in volatile]
            columns.append(ColumnSpec(name="_row_seq", data_type="int", legacy_type="num 8"))
        out[table] = columns
    return out
