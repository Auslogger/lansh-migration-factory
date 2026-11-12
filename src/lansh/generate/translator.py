"""
The Translator agent: writes the migrated PySpark module, reproducing legacy behaviour exactly.

The request carries everything the translation needs and nothing it shouldn't: the legacy
code with line numbers, the input schemas, the output contract's columns and types, the
parameters, the trap findings with their full cards, the sqlglot draft, the Lineage agent's
notes and the job template. Never the golden data: jobs never see golden outputs.

The one-shot request used by the comparison runs (plan §9.5) is the same task with none of the
help: no trap cards, no draft, no notes, and no healing afterwards.
"""

from __future__ import annotations

from lansh.contracts import (
    ColumnSpec,
    DataContract,
    Effort,
    JobSpec,
    Language,
    SuspectedDefect,
    TrapFinding,
)
from lansh.discover.split import numbered
from lansh.discover.traps import load_cards
from lansh.generate.template import DEFECT_MARKER, SIGNATURE
from lansh.llm.answers import TranslationAnswer
from lansh.llm.request import ClaudeRequest

_INTERFACE = """\
- Imports only from pyspark (pyspark.sql, pyspark.sql.functions as F, pyspark.sql.types as T, \
pyspark.sql.Window), datetime, decimal, math, re, functools and typing.
- Exactly this entry point: {signature}
- inputs holds every input table by its legacy name in lower case (e.g. "stg.claims"); params \
holds the parameters as text (e.g. params["AsOfDate"] == "2025-12-31").
- Return a dict from each output's legacy name to a DataFrame with the output's columns. The \
harness then casts each column to the contract type shown, as the legacy table's insert would \
(so a decimal(38,6) value stored into decimal(14,2) is rounded half up).
- Never do I/O or reach engine internals: no spark.read, .write, saveAsTable, spark.conf, RDDs, \
UDFs, .cache(), getattr, eval, open, os or sys. spark.sql, F.expr and selectExpr only with \
plain string literals (no f-strings).
- Use only constants that appear in the legacy code, the parameters, or a trap card's fix \
guidance (format patterns, collation names). Never hard-code data values.
- Reproduce every legacy behaviour exactly, including anything that looks like a bug: never fix \
it. Mark each line that reproduces a suspected bug with a "{marker}: <what>" comment and list \
the bug in defects.
"""
"""The module's interface and rules, shared by the factory's and the one-shot translator."""

_ORDER = """\
- Row order: Spark has none. Wherever the result depends on order (first or last row, a running \
value, a cursor, NODUPKEY, RETAIN, LAG), sort on the legacy ORDER BY and then _row_seq, which \
every source table has in its original row order.
- Spark runs with ANSI mode on: overflow and invalid casts raise errors, and a division by zero \
raises; use try_divide or a guard only where the legacy engine returns NULL.
"""
"""Row order and ANSI mode: facts of the harness, shared by both translators."""

TRANSLATOR_SYSTEM = (
    """\
You are the translator agent of LANSH. You migrate one legacy {language} job to PySpark 4.2, \
and your output must reproduce the legacy output EXACTLY, record for record and value for \
value, bugs included: reconciliation compares every row and column with the legacy engine's \
own output.

Write one Python module in the LANSH job template:
- A module docstring: "<job id> <name>: migrated from <legacy path>.", then the lines \
"Legacy SHA-256: <hash>", "Written by: LANSH translator (Claude)", "Traps handled: <ids>" and \
"Bugs reproduced on purpose ({marker}): <short names, or none>".
"""
    + _INTERFACE
    + """\
- Handle every trap finding you are given, following its card's fix guidance, and list the \
trap ids in traps_handled.
"""
    + _ORDER
    + "{language_rules}"
)

_TSQL_RULES = """\
- T-SQL specifics: text comparisons, IN lists, GROUP BY, DISTINCT, PARTITION BY and joins ignore \
case and trailing spaces under the database collation; CHAR(n) output columns hold values padded \
to n; INT / INT truncates; + on strings is NULL if any part is NULL; ISNULL takes its first \
argument's type; DATEDIFF counts boundaries. The cards give exact fixes.
- Temp tables become DataFrames; logging (etl.usp_log_step), transactions, TRY/CATCH and \
@@ROWCOUNT are harness concerns: leave them out.
"""

_SAS_RULES = """\
- SAS specifics: every SAS number is an 8-byte double: cast numeric inputs to double before any \
arithmetic and output numbers as doubles; a missing number is smaller than every number in \
comparisons; sum() skips missing values while + propagates them; character values are \
blank-padded, so trailing blanks never count and a blank value is missing (output NULL for it); \
a character variable's length is fixed by its first assignment; DATA steps read rows in their \
data set order (_row_seq for source tables).
- Work data sets become DataFrames; macros are expanded by hand.
"""

_STATE_RULES = """\
- This job keeps history between batches: inputs also hold its own previous output, {tables} \
(empty, with the output's columns, before the first batch). Return the whole new table after \
this batch.
"""


def _columns(columns: list[ColumnSpec] | list) -> str:
    """
    List columns with their logical and legacy types.
    """
    return ", ".join(f"{c.name} {c.data_type} ({c.legacy_type or '-'})" for c in columns)


def _schemas(schemas: dict[str, list[ColumnSpec]]) -> str:
    """
    List tables and their columns, one table per line.
    """
    return "\n".join(f"- {t}: {_columns(cols)}" for t, cols in schemas.items())


def _cards_for(traps: list[TrapFinding]) -> str:
    """
    Give the full card of every trap found, once each.
    """
    cards = load_cards()
    seen = sorted({t.trap_id for t in traps})
    out = []
    for trap_id in seen:
        c = cards[trap_id]
        out.append(
            f"### {c.trap_id} ({c.kind.value}): {c.title}\n"
            f"Legacy: {' '.join(c.legacy_behaviour.split())}\n"
            f"Spark: {' '.join(c.spark_behaviour.split())}\n"
            f"Fix: {' '.join(c.fix_guidance.split())}\n"
            + (f"Example: {c.example_legacy} -> {c.example_spark}\n" if c.example_spark else "")
        )
    return "\n".join(out)


def _system(job: JobSpec) -> str:
    """
    Build the translator's system prompt for a job's language and statefulness.
    """
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    rules = _TSQL_RULES if job.language is Language.TSQL else _SAS_RULES
    if job.state_tables:
        rules += _STATE_RULES.format(tables=", ".join(job.state_tables))
    return TRANSLATOR_SYSTEM.format(
        language=language, marker=DEFECT_MARKER, signature=SIGNATURE, language_rules=rules
    )


def _job_text(job: JobSpec, legacy_sha256: str) -> str:
    """
    Describe the job, its invocations and its file.
    """
    calls = "; ".join(
        f"{inv.label or 'run'}: {', '.join(f'{k}={v}' for k, v in inv.params.items())}"
        for inv in job.invocations
    )
    return (
        f"Job {job.job_id}: {job.name} ({job.language.value}), legacy file {job.path} "
        f"(SHA-256 {legacy_sha256}).\n{job.description or ''}\nInvocations, in order: {calls}.\n"
    )


def translation_request(
    job: JobSpec,
    text: str,
    legacy_sha256: str,
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
    traps: list[TrapFinding],
    draft: str,
    notes: str,
    defects: list[SuspectedDefect] | None = None,
) -> ClaudeRequest[TranslationAnswer]:
    """
    Build the Translator agent's request for one job.

    Args:
        job: The job.
        text: Its legacy code.
        legacy_sha256: The legacy file's hash, for the module docstring.
        inputs: Its input tables' columns.
        contracts: The approved contracts of its outputs.
        traps: Its trap findings.
        draft: The sqlglot draft.
        notes: The Lineage agent's notes, which often say what to watch for.
        defects: The suspected legacy bugs Design found, to reproduce and mark.

    Returns:
        The request.
    """
    findings = "\n".join(
        f"- {t.trap_id} lines {t.line_start}-{t.line_end}: {t.note or ''}" for t in traps
    )
    outputs = "\n".join(
        f"- {c.legacy_table} (key {c.keys or 'none'}): {_columns(c.columns)}" for c in contracts
    )
    prompt = (
        _job_text(job, legacy_sha256) + f"\nLegacy code:\n{numbered(text)}\n\n"
        f"Input tables:\n{_schemas(inputs)}\n\n"
        f"Output tables (contract types, legacy types):\n{outputs}\n\n"
        f"Trap findings in this job:\n{findings or '(none)'}\n\n"
        f"Trap cards:\n{_cards_for(traps)}\n"
        f"sqlglot draft (a starting point, not trusted):\n{draft or '(none)'}\n\n"
        f"Lineage agent's notes:\n{notes or '(none)'}\n"
    )
    if defects:
        listed = "\n".join(
            f"- {d.defect_id} {d.title} (lines {d.evidence_lines}): {d.description}"
            for d in defects
        )
        prompt += (
            "\nSuspected legacy bugs found at Design (reproduce each exactly, and mark the "
            f"lines that reproduce it with the marker and its id):\n{listed}\n"
        )
    return ClaudeRequest(
        agent="translator",
        job_id=job.job_id,
        system_prompt=_system(job),
        prompt=prompt,
        response_model=TranslationAnswer,
        effort=Effort.HIGH.value,
    )


ONESHOT_SYSTEM = (
    """\
Translate one legacy {language} job to PySpark 4.2. Your output must reproduce the legacy \
output EXACTLY, record for record and value for value, bugs included: reconciliation compares \
every row and column with the legacy engine's own output.

Write one Python module:
"""
    + _INTERFACE
    + _ORDER
    + "{state_rules}"
)
"""
The comparison runs' one-shot prompt: the factory's interface, without LANSH's knowledge.

It leaves out the trap cards, the language rules, the sqlglot draft, Discover's notes and the
defect list, so the comparison measures what those add (plan §9.5).
"""


def oneshot_request(
    job: JobSpec,
    text: str,
    legacy_sha256: str,
    inputs: dict[str, list[ColumnSpec]],
    contracts: list[DataContract],
) -> ClaudeRequest[TranslationAnswer]:
    """
    Build the one-shot translation request of the comparison runs.

    It gives the same model, effort and module interface as the factory's translator, and
    nothing of LANSH's knowledge (see ``ONESHOT_SYSTEM``).

    Args:
        job: The job.
        text: Its legacy code.
        legacy_sha256: The legacy file's hash.
        inputs: Its input tables' columns.
        contracts: Its outputs' contracts (for the column names and types).

    Returns:
        The request, answered in the same model as the factory's translation.
    """
    language = "T-SQL (SQL Server 2022)" if job.language is Language.TSQL else "SAS 9.4"
    state = _STATE_RULES.format(tables=", ".join(job.state_tables)) if job.state_tables else ""
    outputs = "\n".join(f"- {c.legacy_table}: {_columns(c.columns)}" for c in contracts)
    prompt = (
        _job_text(job, legacy_sha256)
        + f"\nLegacy code:\n{text}\n\nInput tables:\n{_schemas(inputs)}\n\n"
        f"Output tables:\n{outputs}\n"
    )
    return ClaudeRequest(
        agent="oneshot_translator",
        job_id=job.job_id,
        system_prompt=ONESHOT_SYSTEM.format(
            language=language, signature=SIGNATURE, marker=DEFECT_MARKER, state_rules=state
        ),
        prompt=prompt,
        response_model=TranslationAnswer,
        effort=Effort.HIGH.value,
    )
