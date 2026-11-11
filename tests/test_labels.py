"""
The answer key (step 1.7) is complete and consistent with the plan.

This is an evaluation test: tests may read estate/labels/, but factory code may not (see
test_holdout_seal.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lansh.config import LABELS_DIR, REPO_ROOT
from lansh.contracts import TrapKind
from lansh.estate.inventory import load_inventory
from lansh.estate.labels import (
    CHECK_ID,
    is_check_batch,
    load_label,
    sas_check_ids,
    tsql_check_ids,
)

# each job's planned traps and bugs, from the PLAN §7.2 job catalogue (Tier 1) and Appendix B
PLANNED = {
    "T01": ({"TSQL-01", "TSQL-02", "TSQL-04", "TSQL-15"}, {"BUG-01"}),
    "T02": ({"TSQL-11", "TSQL-06", "TSQL-01", "TSQL-02"}, set()),
    "T03": ({"TSQL-03", "TSQL-07", "TSQL-09", "TSQL-18"}, {"BUG-02"}),
    "T04": ({"TSQL-01", "TSQL-05", "TSQL-16"}, {"BUG-03"}),
    "T05": ({"TSQL-12", "TSQL-13", "TSQL-04"}, {"BUG-04"}),
    "T06": ({"TSQL-17", "TSQL-04"}, {"BUG-05"}),
    "T08": ({"TSQL-14", "TSQL-15", "TSQL-16"}, {"BUG-07"}),
    "S01": ({"SAS-05", "SAS-06", "SAS-01", "SAS-02"}, {"BUG-08"}),
    "S03": ({"SAS-12", "SAS-09", "SAS-14"}, set()),
    "S04": ({"SAS-13", "SAS-10", "SAS-11", "SAS-15"}, {"BUG-10"}),
}
# the construct traps in PLAN Appendix A; all others are semantic
CONSTRUCT = {
    "TSQL-09",
    "TSQL-10",
    "TSQL-11",
    "TSQL-12",
    "TSQL-13",
    "TSQL-17",
    "SAS-07",
    "SAS-13",
    "SAS-14",
}
# every trap ID in PLAN Appendix A
KNOWN = {f"TSQL-{n:02d}" for n in range(1, 20)} | {f"SAS-{n:02d}" for n in range(1, 16)}

JOBS = sorted(PLANNED)


@pytest.mark.parametrize("job_id", JOBS)
def test_label_matches_the_plan(job_id: str) -> None:
    """
    Each label lists its job's planned traps and bugs, with the right trap kinds.

    Every planned semantic trap must also be armed: our data makes it change the result.
    """
    label = load_label(job_id)
    job = load_inventory().job(job_id)
    assert label.legacy_path == job.path
    traps, bugs = PLANNED[job_id]
    labelled = {t.trap_id for t in label.traps}
    assert traps <= labelled, f"missing planned traps {sorted(traps - labelled)}"
    assert labelled <= KNOWN
    assert {b.bug_id for b in label.bugs} == bugs
    for trap in label.traps:
        expected = TrapKind.CONSTRUCT if trap.trap_id in CONSTRUCT else TrapKind.SEMANTIC
        assert trap.kind is expected, trap.trap_id
    for trap_id in traps:
        if trap_id not in CONSTRUCT:
            assert any(t.armed for t in label.traps if t.trap_id == trap_id), trap_id


@pytest.mark.parametrize("job_id", JOBS)
def test_lines_and_checks_exist(job_id: str) -> None:
    """
    Labelled lines lie within the legacy file, and the job's check file declares every check.
    """
    label = load_label(job_id)
    n_lines = len((REPO_ROOT / label.legacy_path).read_text(encoding="utf-8").splitlines())
    for item in [*label.traps, *label.bugs]:
        assert 1 <= item.lines[0] <= item.lines[1] <= n_lines, item
    checks = LABELS_DIR / "checks"
    if job_id.startswith("T"):
        declared = tsql_check_ids((checks / f"{job_id}.sql").read_text(encoding="utf-8"))
    else:
        declared = sas_check_ids((checks / f"{job_id}.sas").read_text(encoding="utf-8"))
    assert [c for c in declared if not re.fullmatch(CHECK_ID, c)] == []
    missing = set(label.check_ids()) - set(declared)
    assert not missing, sorted(missing)


@pytest.mark.parametrize("job_id", [j for j in JOBS if j.startswith("S")])
def test_sas_check_files_declare_exactly_the_labelled_checks(job_id: str) -> None:
    """
    The ``check_id = '...'`` assignments in a SAS check file are the label's checks, each once.
    """
    text = (LABELS_DIR / "checks" / f"{job_id}.sas").read_text(encoding="utf-8")
    assert sorted(sas_check_ids(text)) == load_label(job_id).check_ids()


def test_sas_check_ids_reads_assignment_statements_only() -> None:
    """
    An assignment declares a check in either quote style and any case; a comparison or a
    comment does not.
    """
    text = (
        "  CHECK_ID = 'S01_A';\n"
        '  check_id="S01_B" ;\n'
        "  if check_id = 'S01_C' then output;\n"
        "/* check: S01_D */\n"
    )
    assert sas_check_ids(text) == ["S01_A", "S01_B"]


def test_check_batches_are_found_by_their_header_line() -> None:
    """
    A T-SQL batch is a check when it has the ``-- check: <id>`` line that tsql_check_ids
    reads, with or without a blank after ``--``.
    """
    check = "-- check: T01_A\nSELECT 'T01_A' AS check_id, 1 AS affected"
    assert is_check_batch(check)
    assert tsql_check_ids(check) == ["T01_A"]
    assert is_check_batch("--check: T01_B\nSELECT 'T01_B' AS check_id, 0 AS affected")
    assert not is_check_batch("SELECT 1 AS n -- check: not a header line\nINTO #k")
    assert not is_check_batch("CREATE TABLE #k (claim_id INT)")


def test_labels_load_with_plain_yaml_types(tmp_path: Path) -> None:
    """
    Labels load with the inventory's YAML rules: NO and off stay words and an unquoted date
    stays text, where YAML 1.1 would make them booleans and a date.
    """
    (tmp_path / "T99.yaml").write_text(
        "job_id: T99\n"
        "legacy_path: estate/tsql/T99.sql\n"
        "summary: 2025-12-31\n"
        "traps:\n"
        "  - trap_id: TSQL-02\n"
        "    kind: semantic\n"
        "    armed: false\n"
        "    lines: [1, 2]\n"
        "    where: NO\n"
        "    effect: off\n",
        encoding="utf-8",
    )
    label = load_label("T99", tmp_path)
    assert label.summary == "2025-12-31"
    assert (label.traps[0].where, label.traps[0].effect) == ("NO", "off")


def test_each_planted_bug_belongs_to_exactly_one_job() -> None:
    seen: dict[str, str] = {}
    for job_id in JOBS:
        for bug in load_label(job_id).bugs:
            assert bug.bug_id not in seen, f"{bug.bug_id} in {seen.get(bug.bug_id)} and {job_id}"
            seen[bug.bug_id] = job_id
    assert set(seen) == {
        "BUG-01",
        "BUG-02",
        "BUG-03",
        "BUG-04",
        "BUG-05",
        "BUG-07",
        "BUG-08",
        "BUG-10",
    }
