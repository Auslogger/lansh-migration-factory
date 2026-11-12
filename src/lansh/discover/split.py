"""
Split legacy code into blocks: T-SQL statements, SAS DATA steps, PROCs and macros (plan §8.3).

The blocks feed the trap scan (with their line numbers), the sqlglot draft and the lineage
cross-check. Splitting works on a copy of the code with comments blanked out, character for
character, so line numbers and offsets stay those of the file and a change-log line that
mentions MERGE never looks like a MERGE.

T-SQL is split on semicolons and ``GO`` lines outside strings and brackets; control-flow
prefixes that carry no semicolon (``CREATE PROCEDURE ... AS BEGIN``, ``BEGIN TRY``, ``WHILE ...
BEGIN``, ``END``) are peeled off as their own blocks. Each statement records whether sqlglot
could parse it (rather than falling back to an opaque command). SAS is split into DATA steps
(to ``run;``), PROCs (to ``run;`` or ``quit;``), ``%macro`` definitions (to ``%mend``) and
single statements.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from lansh.contracts import CodeBlock, Language

BlockKind = Literal["statement", "data_step", "proc", "macro", "other"]


@dataclass(frozen=True)
class Block:
    """
    One block of a legacy job, with its text and where it sits in the file.

    Attributes:
        index: Position among the job's blocks, from 0.
        start: Offset of the block's first character in the file.
        end: Offset just past its last character.
        line_start: First line, from 1.
        line_end: Last line, inclusive.
        text: The block's original text, comments included.
        code: The same text with comments blanked out.
        sqlglot_parsed: For a T-SQL statement, whether sqlglot parsed it; None otherwise.
    """

    index: int
    kind: BlockKind
    start: int
    end: int
    line_start: int
    line_end: int
    text: str
    code: str
    sqlglot_parsed: bool | None = None

    def record(self, job_id: str) -> CodeBlock:
        """
        Give the contract's record of this block.
        """
        return CodeBlock(
            job_id=job_id,
            index=self.index,
            kind=self.kind,
            line_start=self.line_start,
            line_end=self.line_end,
            sqlglot_parsed=self.sqlglot_parsed,
        )


### Comments


def blank_comments(text: str, language: Language) -> str:
    """
    Replace every comment with spaces, keeping line breaks, so offsets and lines don't move.

    T-SQL comments are ``--`` to the end of the line and ``/* ... */`` (which nest in T-SQL);
    SAS comments are ``/* ... */`` and statements starting with ``*`` up to the next ``;``.
    Quoted strings are left alone, comment markers inside them included.

    Args:
        text: The legacy code.
        language: Its language.

    Returns:
        Text of the same length with comments blanked.
    """
    out = list(text)
    i, n = 0, len(text)
    depth = 0  # nested /* */ in T-SQL
    quote: str | None = None
    statement_start = True  # SAS: at the start of a statement, where * opens a comment
    while i < n:
        ch = text[i]
        if depth:
            if text.startswith("*/", i):
                out[i] = out[i + 1] = " "
                depth -= 1
                i += 2
                continue
            if language is Language.TSQL and text.startswith("/*", i):
                out[i] = out[i + 1] = " "
                depth += 1
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if text.startswith("/*", i):
            out[i] = out[i + 1] = " "
            depth = 1
            i += 2
            continue
        if language is Language.TSQL and text.startswith("--", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if language is Language.SAS and statement_start and ch == "*":
            while i < n and text[i] != ";":
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
            continue
        if ch in "'\"":
            quote = ch
            statement_start = False
        elif ch == ";":
            statement_start = True
        elif not ch.isspace():
            statement_start = False
        i += 1
    return "".join(out)


### T-SQL


_GO = re.compile(r"^[ \t]*GO[ \t]*$", re.IGNORECASE | re.MULTILINE)
_CONTROL = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"\ACREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\b.*?\bAS\b(?:\s+BEGIN\b)?",
        r"\ABEGIN\s+TRY\b",
        r"\AEND\s+TRY\b",
        r"\ABEGIN\s+CATCH\b",
        r"\AEND\s+CATCH\b",
        r"\AWHILE\b.*?\bBEGIN\b",
        r"\AIF\b[^;]*?\bBEGIN\b",
        r"\AELSE\s+BEGIN\b",
        r"\AELSE\b(?!\s+IF\b)",
        r"\ABEGIN\b(?!\s+(?:TRAN|TRANSACTION|DISTRIBUTED)\b)",
        r"\AEND\b",
    )
]


def _raw_chunks(code: str) -> list[tuple[int, int]]:
    """
    Cut comment-blanked T-SQL into spans at semicolons and GO lines, outside strings.
    """
    spans: list[tuple[int, int]] = []
    go_lines = {m.start() for m in _GO.finditer(code)}
    start = 0
    i, n = 0, len(code)
    quote: str | None = None
    while i < n:
        ch = code[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'[":
            quote = "'" if ch == "'" else "]"
            i += 1
            continue
        line_start = code.rfind("\n", 0, i) + 1
        if i == line_start and i in go_lines:
            spans.append((start, i))
            end = code.find("\n", i)
            i = n if end < 0 else end + 1
            start = i
            continue
        if ch == ";":
            spans.append((start, i + 1))
            start = i + 1
        i += 1
    spans.append((start, n))
    return spans


def _peel(code: str, start: int, end: int) -> list[tuple[int, int, BlockKind]]:
    """
    Split one span into control-flow prefixes and the statement after them.
    """
    out: list[tuple[int, int, BlockKind]] = []
    while start < end:
        while start < end and code[start].isspace():
            start += 1
        if start >= end:
            break
        piece = code[start:end]
        for pattern in _CONTROL:
            m = pattern.match(piece)
            if m:
                out.append((start, start + m.end(), "other"))
                start += m.end()
                break
        else:
            out.append((start, end, "statement"))
            break
    return out


def _parses(sql: str) -> bool:
    """
    Tell whether sqlglot parses a T-SQL statement into a real expression, not a fallback command.
    """
    import sqlglot
    from sqlglot import exp

    quiet = logging.getLogger("sqlglot")
    level = quiet.level
    quiet.setLevel(logging.ERROR)  # its fallback to a command is our answer, not a warning
    try:
        parsed = sqlglot.parse(sql, read="tsql")
    except Exception:  # sqlglot raises several error types; any means no parse
        return False
    finally:
        quiet.setLevel(level)
    return bool(parsed) and all(p is not None and not isinstance(p, exp.Command) for p in parsed)


def split_tsql(text: str) -> list[Block]:
    """
    Split a T-SQL deployment script into statements and control-flow blocks.

    Args:
        text: The script.

    Returns:
        The blocks in file order, each with its line range.
    """
    code = blank_comments(text, Language.TSQL)
    pieces = [p for s, e in _raw_chunks(code) for p in _peel(code, s, e)]
    blocks = []
    for start, end, kind in pieces:
        body = code[start:end].strip()
        if not body or body == ";":
            continue
        # trim to the statement's own characters, so its lines are exact
        lead = len(code[start:end]) - len(code[start:end].lstrip())
        start += lead
        end = start + len(code[start:end].rstrip())
        statement = kind == "statement"
        blocks.append(
            Block(
                index=len(blocks),
                kind=kind,
                start=start,
                end=end,
                line_start=text.count("\n", 0, start) + 1,
                line_end=text.count("\n", 0, max(start, end - 1)) + 1,
                text=text[start:end],
                code=code[start:end],
                sqlglot_parsed=_parses(code[start:end]) if statement else None,
            )
        )
    return blocks


### SAS


def _sas_statements(code: str) -> list[tuple[int, int]]:
    """
    Cut comment-blanked SAS into statements ending at a semicolon outside quotes.
    """
    spans = []
    start, quote = 0, None
    for i, ch in enumerate(code):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == ";":
            spans.append((start, i + 1))
            start = i + 1
    if code[start:].strip():
        spans.append((start, len(code)))
    return spans


def split_sas(text: str) -> list[Block]:
    """
    Split a SAS program into DATA steps, PROCs, macro definitions and other statements.

    Args:
        text: The program.

    Returns:
        The blocks in file order, each with its line range.
    """
    code = blank_comments(text, Language.SAS)
    statements = []
    for s, e in _sas_statements(code):
        lead = len(code[s:e]) - len(code[s:e].lstrip())
        if code[s:e].strip():
            statements.append((s + lead, e))
    blocks: list[Block] = []
    i = 0
    while i < len(statements):
        start, end = statements[i]
        head = code[start:end].strip().lower()
        kind: BlockKind
        if head.startswith("%macro"):
            kind, closers = "macro", ("%mend",)
        elif re.match(r"data\b(?!\s*=)", head):
            kind, closers = "data_step", ("run",)
        elif re.match(r"proc\b", head):
            kind, closers = "proc", ("run", "quit")
        else:
            kind, closers = "other", ()
        j = i
        if closers:
            while j < len(statements):
                word = code[statements[j][0] : statements[j][1]].strip().lower().rstrip(";")
                first = word.split()[0] if word.split() else ""
                if first in closers or (kind == "macro" and first.startswith("%mend")):
                    break
                # a step that runs into the next step has ended without its run;
                if j > i and kind != "macro" and re.match(r"(data\b(?!\s*=)|proc\b)", word):
                    j -= 1
                    break
                j += 1
            j = min(j, len(statements) - 1)
        end = statements[j][1]
        blocks.append(
            Block(
                index=len(blocks),
                kind=kind,
                start=start,
                end=end,
                line_start=text.count("\n", 0, start) + 1,
                line_end=text.count("\n", 0, max(start, end - 1)) + 1,
                text=text[start:end],
                code=code[start:end],
            )
        )
        i = j + 1
    return blocks


def split_code(text: str, language: Language) -> list[Block]:
    """
    Split legacy code in either language.

    Args:
        text: The code.
        language: T-SQL or SAS.

    Returns:
        The blocks in file order.
    """
    return split_tsql(text) if language is Language.TSQL else split_sas(text)


def numbered(text: str) -> str:
    """
    Prefix every line with its number, as prompts show legacy code to the agents.

    Args:
        text: The code.

    Returns:
        The code with ``  12 | `` before line 12.
    """
    lines = text.splitlines()
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))
