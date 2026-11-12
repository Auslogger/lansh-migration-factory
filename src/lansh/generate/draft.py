"""
The deterministic draft: sqlglot's translation of each legacy statement (plan §8.5).

For T-SQL, every statement that moves data (``SELECT ... INTO``, ``INSERT ... SELECT``,
``UPDATE``, ``MERGE``, a ``SELECT`` into variables) is transpiled to Spark SQL, headed by its
line numbers and the traps the scan found on those lines. Logging, transactions, ``TRY``/
``CATCH`` and temp-table housekeeping are the harness's business and are left out. A statement
sqlglot can't parse is named, so the translator knows to work from the code itself. SAS has no
sqlglot dialect, so only the SQL inside ``PROC SQL`` is drafted, read as generic SQL.

The draft is a starting point, never trusted: sqlglot keeps ``DATEDIFF`` and ``LIKE '[0-9]%'``
as they are, although they mean different things in Spark (plan §6.7), which is why the trap
warnings travel with each statement.
"""

from __future__ import annotations

import logging
import re

from lansh.contracts import Language, TrapFinding
from lansh.discover.split import Block

_HOUSEKEEPING = re.compile(
    r"^\s*(EXEC(UTE)?\s+etl\.|SET\s+NOCOUNT|SET\s+@\w+\s*=\s*@@ROWCOUNT|BEGIN\s+TRAN|COMMIT|"
    r"ROLLBACK|THROW|RAISERROR|PRINT|IF\s+@@TRANCOUNT|IF\s+OBJECT_ID\s*\(\s*'tempdb|"
    r"CREATE\s+(UNIQUE\s+)?(CLUSTERED|NONCLUSTERED)?\s*INDEX|SELECT\s+@err_)",
    re.IGNORECASE,
)
_DATA = re.compile(r"^\s*(WITH\b|SELECT\b|INSERT\b|UPDATE\b|MERGE\b|DELETE\b|TRUNCATE\b)", re.I)


def _transpile(sql: str, read: str) -> str | None:
    """
    Transpile one statement to Spark SQL, or None when sqlglot can't.
    """
    import sqlglot

    quiet = logging.getLogger("sqlglot")
    level = quiet.level
    quiet.setLevel(logging.ERROR)
    try:
        out = sqlglot.transpile(sql, read=read or None, write="spark", pretty=True)
    except Exception:  # any sqlglot error: no draft for this statement
        return None
    finally:
        quiet.setLevel(level)
    return "\n".join(out) if out else None


def _traps_on(block: Block, traps: list[TrapFinding]) -> str:
    """
    Name the traps found on a block's lines, for its header.
    """
    hits = sorted(
        {
            f"{t.trap_id} (line {t.line_start})"
            for t in traps
            if t.line_start <= block.line_end and block.line_start <= t.line_end
        }
    )
    return f"; traps: {', '.join(hits)}" if hits else ""


def tsql_draft(blocks: list[Block], traps: list[TrapFinding]) -> str:
    """
    Draft a T-SQL job statement by statement.

    Args:
        blocks: The job's blocks.
        traps: Its trap findings.

    Returns:
        The draft: Spark SQL per data statement, each headed by its lines and traps.
    """
    parts = []
    for block in blocks:
        code = " ".join(block.code.split())
        if block.kind != "statement" or _HOUSEKEEPING.match(code):
            continue
        header = f"-- lines {block.line_start}-{block.line_end}{_traps_on(block, traps)}"
        if not block.sqlglot_parsed:
            parts.append(f"{header}\n-- no draft: sqlglot can't parse this ({code[:80]}...)")
            continue
        if not _DATA.match(code) and not code.upper().startswith(("SET @", "DECLARE @")):
            continue
        spark = _transpile(block.code, "tsql")
        parts.append(f"{header}\n{spark or '-- no draft: sqlglot could not transpile it'}")
    return "\n\n".join(parts)


def sas_draft(blocks: list[Block], traps: list[TrapFinding]) -> str:
    """
    Draft the SQL inside a SAS job's PROC SQL steps.

    Args:
        blocks: The job's blocks.
        traps: Its trap findings.

    Returns:
        The draft, one entry per PROC SQL query; DATA steps and macros are only named.
    """
    parts = []
    for block in blocks:
        header = (
            f"-- lines {block.line_start}-{block.line_end} ({block.kind}){_traps_on(block, traps)}"
        )
        if block.kind == "proc" and re.match(r"\s*proc\s+sql\b", block.code, re.I):
            statements = [s.strip() for s in block.code.split(";")[1:] if s.strip()]
            queries = [s for s in statements if re.match(r"(create\s+table|select)\b", s, re.I)]
            drafts = [_transpile(q, "") or f"-- no draft for: {q[:60]}..." for q in queries]
            parts.append(header + "\n" + "\n".join(drafts))
        else:
            parts.append(f"{header}\n-- no draft: translate this {block.kind} from the code")
    return "\n\n".join(parts)


def make_draft(language: Language, blocks: list[Block], traps: list[TrapFinding]) -> str:
    """
    Draft a job in either language.

    Args:
        language: T-SQL or SAS.
        blocks: The job's blocks.
        traps: Its trap findings.

    Returns:
        The draft text.
    """
    if language is Language.TSQL:
        return tsql_draft(blocks, traps)
    return sas_draft(blocks, traps)
