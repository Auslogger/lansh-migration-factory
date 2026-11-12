"""
The job template: the one shape every migrated job takes (plan §8.5).

A migrated job is a pure function::

    def run(spark, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]

``inputs`` holds every table the legacy job reads, by its legacy name in lower case
(``stg.claims``, ``dw.dim_customer``), and ``params`` the invocation's parameters as text
(``AsOfDate``: ``'2025-12-31'``). It returns every output table by its legacy name. A stateful
job (T02's type-2 history) also finds its own previous output among the inputs: empty before
the first batch, then each batch's result. The job never does its own I/O; the harness stages
the inputs and conforms and writes the outputs (``lansh.lakehouse``). Order-dependent logic
sorts on ``_row_seq``.

The module docstring records the legacy file and its hash, who wrote the code, the traps
handled and the bugs reproduced on purpose, each of which is marked ``# LANSH-DEFECT`` in the
code.
"""

from __future__ import annotations

from lansh.contracts import ColumnSpec, EstateInventory, JobSpec

SIGNATURE = (
    "def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) "
    "-> dict[str, DataFrame]:"
)
"""The entry point's signature, exactly."""

DEFECT_MARKER = "# LANSH-DEFECT"
"""Marks a line that reproduces a suspected legacy bug on purpose."""


def _columns_text(columns: list[ColumnSpec]) -> str:
    """
    List columns as ``name type`` lines for a docstring.
    """
    return "\n".join(f"            {c.name:<28} {c.data_type}" for c in columns)


def skeleton(job: JobSpec, inventory: EstateInventory, *, legacy_sha256: str) -> str:
    """
    Write an empty module in the job template, for a person or a translator to fill in.

    It lists the job's inputs, its parameters and each output's columns and types.

    Args:
        job: The legacy job.
        inventory: The estate inventory, for the output columns.
        legacy_sha256: The legacy file's hash.

    Returns:
        The module's source text. Its ``run`` raises ``NotImplementedError``.
    """
    from lansh.lakehouse import output_columns

    params = sorted({k for inv in job.invocations for k in inv.params})
    outputs = "\n".join(
        f"        {o.table}:\n{_columns_text(output_columns(inventory, o.table))}"
        for o in job.outputs
    )
    state = (
        f"\n    Stateful: inputs also hold {', '.join(job.state_tables)}, this job's previous "
        "output (empty before the first batch)."
        if job.state_tables
        else ""
    )
    inputs = ", ".join(job.inputs)
    returns = ", ".join(f'"{o.table}": ...' for o in job.outputs)
    return f'''"""
{job.job_id} {job.name}: migrated from {job.path}.

Legacy SHA-256: {legacy_sha256}
Written by: <who or what wrote this module>
Traps handled: <trap ids>
Bugs reproduced on purpose ({DEFECT_MARKER}): <defect ids, or none>
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


{SIGNATURE}
    """
    Reproduce {job.entrypoint or job.name} exactly, bugs included.

    Inputs: {inputs}.
    Params: {", ".join(params) or "none"} (text).{state}

    Returns:
{outputs}
    """
    raise NotImplementedError("fill in the migrated logic")
    return {{{returns}}}
'''
