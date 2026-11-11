"""
The answer key: planted traps and bugs per legacy job (plan §7.4, step 1.7).

EVALUATION ONLY. Factory code must never import this module or read ``estate/labels/``
(AGENTS.md). The evaluation code uses it to score detection and to prove that every planted
bug is reproduced.

Each job has ``estate/labels/<JOB>.yaml`` (a :class:`JobLabel`) and a check file,
``estate/labels/checks/<JOB>.sql`` for T-SQL jobs or ``<JOB>.sas`` for SAS jobs. A check
proves that a semantic trap or a bug changes the result **on our data**: it returns a
positive ``affected`` count. Construct traps need no check; the job running is their check.

The check file formats, and what ``armed`` means for each kind of trap, are in the
"The answer key" section of ``estate/README.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from lansh.config import LABELS_DIR
from lansh.contracts import JobId, Model, TrapId, TrapKind
from lansh.estate.inventory import parse_yaml

CHECK_ID = r"^[A-Z]{1,3}[0-9]{1,3}_[A-Za-z0-9_]+$"
"""A check id: the job id, an underscore and a name, such as ``T04_BUG03_payments_fan_out``."""


class LabelledTrap(Model):
    """
    One planted trap in a legacy job: where it is and what it would break.

    Attributes:
        trap_id: The trap card in plan Appendix A, such as ``TSQL-01``.
        kind: Semantic traps change results; construct traps change only the code's shape.
        check: Id of the check that proves the trap changes the result. An armed semantic
            trap must have one.
    """

    trap_id: TrapId
    kind: TrapKind
    armed: bool = Field(description="True when our data makes the trap change the result.")
    lines: tuple[int, int] = Field(description="First and last line in the legacy file.")
    where: str = Field(min_length=1, description="The code that contains the trap.")
    effect: str = Field(min_length=1, description="What a naive translation would get wrong.")
    check: str | None = Field(default=None, pattern=CHECK_ID)

    @model_validator(mode="after")
    def _check(self) -> LabelledTrap:
        """
        Reject a reversed line range, and an armed semantic trap without a check.
        """
        if self.lines[1] < self.lines[0]:
            raise ValueError("lines must be (first, last)")
        needs_check = self.kind is TrapKind.SEMANTIC and self.armed
        if needs_check and not self.check:
            raise ValueError(f"armed semantic trap {self.trap_id} needs a check")
        return self


class LabelledBug(Model):
    """
    One planted legacy bug, which the migrated job must reproduce and flag.

    Attributes:
        bug_id: ``BUG-nn`` from plan Appendix B, or ``X<n>-BUG`` for a held-out job.
        lines: First and last line in the legacy file.
        where: The code that contains the bug.
        check: Id of the check that proves the bug changes the result on our data.
    """

    bug_id: str = Field(pattern=r"^(BUG-[0-9]{2}|X[0-9]+-BUG)$")
    lines: tuple[int, int]
    where: str = Field(min_length=1)
    does: str = Field(min_length=1, description="What the legacy code actually does.")
    intended: str = Field(min_length=1, description="What the author meant it to do.")
    via_trap: TrapId | None = Field(
        default=None, description="The trap the bug works through (BUG-08 via SAS-01)."
    )
    check: str = Field(pattern=CHECK_ID)


class JobLabel(Model):
    """
    The answer key for one legacy job, as stored in ``estate/labels/<JOB>.yaml``.

    Attributes:
        author: Who wrote the job: the team, the isolated agent (held-out jobs) or EXL.
        legacy_path: Repository-relative path to the legacy code.
        summary: What the job does.
    """

    job_id: JobId
    author: Literal["team", "isolated_agent", "exl"] = "team"
    legacy_path: str
    summary: str = Field(min_length=1)
    traps: list[LabelledTrap] = Field(default_factory=list)
    bugs: list[LabelledBug] = Field(default_factory=list)

    def check_ids(self) -> list[str]:
        """
        List the checks this label names, from its traps and its bugs.

        Returns:
            The distinct check ids, sorted.
        """
        ids = [t.check for t in self.traps if t.check] + [b.check for b in self.bugs]
        return sorted(set(ids))


class CheckResult(Model):
    """
    The outcome of one answer-key check, run after the legacy job.

    Attributes:
        affected: How many rows (or other units) the trap or bug changes on our data.
        detail: Optional free text from the check.
        engine: Where the check ran: SQL Server or SAS.
    """

    job_id: JobId
    check_id: str
    affected: int
    detail: str | None = None
    engine: Literal["mssql", "sas"]

    @property
    def passed(self) -> bool:
        """
        Tell whether the check proved that its trap or bug changes the result on our data.

        Returns:
            True when ``affected`` is positive.
        """
        return self.affected > 0


def load_label(job_id: str, labels_dir: Path = LABELS_DIR) -> JobLabel:
    """
    Load and validate one job's answer key.

    The YAML is parsed as the inventory is (see :func:`~lansh.estate.inventory.parse_yaml`),
    so a word such as ``NO`` or an unquoted date stays text.

    Args:
        job_id: The job, such as ``T04``.
        labels_dir: Folder holding the ``<JOB>.yaml`` label files.

    Returns:
        The job's label.
    """
    data = parse_yaml((labels_dir / f"{job_id}.yaml").read_text(encoding="utf-8"))
    return JobLabel.model_validate(data)


_CHECK_HEADER = re.compile(r"^--\s*check:\s*(\S+)\s*$", re.MULTILINE)
"""Matches the ``-- check: <id>`` line that opens each T-SQL check batch."""


def tsql_check_ids(text: str) -> list[str]:
    """
    List the check ids declared in a T-SQL check file (``-- check: <id>`` lines).

    Args:
        text: The check file.

    Returns:
        The ids in file order.
    """
    return _CHECK_HEADER.findall(text)


def is_check_batch(batch: str) -> bool:
    """
    Tell whether a batch of a T-SQL check file is a check rather than setup.

    A check batch has the ``-- check: <id>`` line that :func:`tsql_check_ids` reads.

    Args:
        batch: One batch of a T-SQL check file.

    Returns:
        True for a check batch.
    """
    return _CHECK_HEADER.search(batch) is not None


_SAS_CHECK_ID = re.compile(
    r"""^[ \t]*check_id[ \t]*=[ \t]*(['"])([^'"\n]+)\1[ \t]*;""", re.MULTILINE | re.IGNORECASE
)
"""Matches a ``check_id = '<id>';`` statement that starts a line, in either quote style."""


def sas_check_ids(text: str) -> list[str]:
    """
    List the check ids declared in a SAS check program (``check_id = '<id>';`` statements).

    Each check sets ``check_id`` in the DATA step that writes ``work._lansh_checks``. Only an
    assignment at the start of a line counts, so a comparison such as
    ``if check_id = '...'`` doesn't. The name may be in any case, as SAS ignores case.

    Args:
        text: The check program.

    Returns:
        The ids in program order.
    """
    return [match.group(2) for match in _SAS_CHECK_ID.finditer(text)]
