"""
Score a factory run against the answer key: detection and bug reproduction (plan §15, step 3.7).

EVALUATION ONLY: this module reads ``estate/labels/``, which factory code never does.

**Detection.** A labelled trap occurrence is *detected* when a trap finding names the same
trap at an overlapping line range; a finding is a *true positive* when it overlaps a labelled
occurrence of its trap. A planted bug is detected when a suspected defect's evidence lines
overlap the bug's lines; a suspected defect that overlaps a labelled trap instead counts as
detecting that trap (``estate/README.md``), and one that overlaps nothing labelled is
*unconfirmed*: it may be a real issue the key doesn't list.

**Reproduction.** A planted bug is *reproduced* when its job reconciled MATCH and the bug's own
check query gives the same result on the migrated output as on the legacy output. For T-SQL
jobs the check runs in SQL Server, in a scratch database holding the source extracts and the
migrated output instead of the legacy job's; SAS checks need SAS, so for SAS jobs the record
says the result follows from the MATCH (every row, under the contract's policies).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lansh.config import LEGACY_DATABASE, RUNS_DIR
from lansh.estate.labels import JobLabel, load_label

log = logging.getLogger(__name__)

PROOF_DATABASE = "LanshProof"


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """
    Tell whether two inclusive line ranges share a line.
    """
    return a[0] <= b[1] and b[0] <= a[1]


@dataclass
class JobScore:
    """
    Detection on one job, against its answer key.

    Attributes:
        labelled_traps: Labelled trap occurrences.
        detected_traps: Those a finding (or a suspected defect) named.
        armed_semantic: Labelled semantic traps our data arms.
        armed_semantic_detected: Those detected.
        findings: Trap findings reported.
        true_findings: Findings that overlap a labelled occurrence of their trap.
        bugs: Planted bugs.
        bugs_detected: Those a suspected defect named.
        defects: Suspected defects reported.
        defects_confirmed: Those that overlap a planted bug or a labelled trap.
        missed: Labelled occurrences nothing named, as ``TRAP lines a-b``.
        unconfirmed: Findings and defects that overlap nothing labelled.
        bug_matches: For each planted bug, the suspected defect that named it.
    """

    job_id: str
    labelled_traps: int = 0
    detected_traps: int = 0
    armed_semantic: int = 0
    armed_semantic_detected: int = 0
    findings: int = 0
    true_findings: int = 0
    bugs: int = 0
    bugs_detected: int = 0
    defects: int = 0
    defects_confirmed: int = 0
    missed: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    bug_matches: dict[str, str | None] = field(default_factory=dict)


def score_job(
    label: JobLabel, findings: list[dict[str, Any]], defects: list[dict[str, Any]]
) -> JobScore:
    """
    Score one job's trap findings and suspected defects against its answer key.

    Args:
        label: The job's answer key.
        findings: Its trap findings, as the run wrote them (``traps.json``).
        defects: Its suspected defects, as the evidence report holds them.

    Returns:
        The job's detection score.
    """
    score = JobScore(label.job_id, findings=len(findings), defects=len(defects))
    spans = [(f["trap_id"], (f["line_start"], f["line_end"])) for f in findings]
    # a defect names the lines it cites, not everything between its first and last line
    defect_lines = [
        (d["defect_id"], set(d["evidence_lines"])) for d in defects if d.get("evidence_lines")
    ]

    def cites(lines: set[int], span: tuple[int, int]) -> bool:
        """
        Tell whether a defect cites a line inside a labelled range.
        """
        return any(span[0] <= n <= span[1] for n in lines)

    for trap in label.traps:
        lines = (trap.lines[0], trap.lines[1])
        named = any(t == trap.trap_id and _overlap(s, lines) for t, s in spans)
        named = named or any(cites(s, lines) for _, s in defect_lines)
        score.labelled_traps += 1
        score.detected_traps += named
        armed = trap.armed and trap.kind.value == "semantic"
        score.armed_semantic += armed
        score.armed_semantic_detected += armed and named
        if not named:
            score.missed.append(f"{trap.trap_id} lines {lines[0]}-{lines[1]}")
    for trap_id, s in spans:
        hit = any(
            t.trap_id == trap_id and _overlap(s, (t.lines[0], t.lines[1])) for t in label.traps
        )
        score.true_findings += hit
        if not hit:
            score.unconfirmed.append(f"finding {trap_id} lines {s[0]}-{s[1]}")
    for bug in label.bugs:
        lines = (bug.lines[0], bug.lines[1])
        match = next((d for d, s in defect_lines if cites(s, lines)), None)
        score.bugs += 1
        score.bugs_detected += match is not None
        score.bug_matches[bug.bug_id] = match
    for defect_id, s in defect_lines:
        on_bug = any(cites(s, (b.lines[0], b.lines[1])) for b in label.bugs)
        on_trap = any(cites(s, (t.lines[0], t.lines[1])) for t in label.traps)
        score.defects_confirmed += on_bug or on_trap
        if not (on_bug or on_trap):
            score.unconfirmed.append(f"defect {defect_id} lines {min(s)}-{max(s)}")
    return score


def adjudication(run_id: str) -> dict[str, dict[str, Any]]:
    """
    Read the evaluator's verdict on each bug matched by lines (``runs/<run>/adjudication.json``).

    A line match only says a suspected defect cites the bug's lines; a person reading both says
    whether it describes the planted bug. The file maps each bug id to ``{"defect_id",
    "genuine", "note"}``.

    Args:
        run_id: The run.

    Returns:
        The verdicts by bug id; empty when nobody has adjudicated the run.
    """
    path = RUNS_DIR / run_id / "adjudication.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def score_run(run_id: str, job_ids: list[str] | None = None) -> dict[str, JobScore]:
    """
    Score every job of a run that has evidence.

    Args:
        run_id: The run.
        job_ids: The jobs to score; every job with evidence when None.

    Returns:
        The score of each job.
    """
    run_dir = RUNS_DIR / run_id
    out = {}
    for evidence in sorted(run_dir.glob("*/evidence.json")):
        job_id = evidence.parent.name
        if job_ids and job_id not in job_ids:
            continue
        data = json.loads(evidence.read_text(encoding="utf-8"))
        out[job_id] = score_job(load_label(job_id), data.get("traps", []), data.get("defects", []))
    return out


def prove_reproduction(
    run_id: str, *, database: str = PROOF_DATABASE
) -> dict[str, list[dict[str, Any]]]:
    """
    Run each T-SQL job's answer-key checks on its migrated output, beside the legacy run's.

    The scratch database holds the source extracts; each job's output table is created from its
    deployment script and filled with the migrated output (in dependency order, so a check that
    reads an upstream table sees the migrated one). The legacy results come from running the
    same checks on the legacy database after the golden capture's jobs.

    Args:
        run_id: The run whose accepted outputs to check (its lakehouse Delta tables).
        database: The scratch database, dropped and recreated.

    Returns:
        For each job, one row per check: its id, the legacy and migrated affected counts, and
        whether they agree.
    """
    from lansh.config import REPO_ROOT
    from lansh.contracts import Language
    from lansh.engines import mssql
    from lansh.estate.golden import job_order
    from lansh.estate.inventory import load_inventory
    from lansh.estate.legacy import load_database
    from lansh.estate.runner import run_tsql_checks
    from lansh.generate.testgen import _identity_columns
    from lansh.lakehouse import delta_path

    inventory = load_inventory()
    lake = RUNS_DIR / run_id / "lakehouse"
    tsql = [j for j in job_order(inventory) if inventory.job(j).language is Language.TSQL]
    legacy = {
        job_id: {r.check_id: r.affected for r in run_tsql_checks(job_id, LEGACY_DATABASE)}
        for job_id in tsql
    }
    load_database(database, verify=False)
    out: dict[str, list[dict[str, Any]]] = {}
    with mssql.connect(database) as conn:
        for job_id in tsql:
            job = inventory.job(job_id)
            mssql.run_script(conn, (REPO_ROOT / job.path).read_text(encoding="utf-8"))
            for o in job.outputs:
                path = delta_path(o.table, lake)
                if not (path / "_delta_log").is_dir():
                    continue
                identity = _identity_columns(inventory, o.table)
                quoted = mssql.quote_table(o.table)
                if identity:
                    conn.cursor().execute(f"SET IDENTITY_INSERT {quoted} ON")
                mssql.load_table(conn, o.table, _latest_delta(path))
                if identity:
                    conn.cursor().execute(f"SET IDENTITY_INSERT {quoted} OFF")
    for job_id in tsql:
        outputs = [delta_path(o.table, lake) for o in inventory.job(job_id).outputs]
        if not all((path / "_delta_log").is_dir() for path in outputs):
            continue  # not migrated (yet) in this run: nothing to prove
        try:
            migrated = {r.check_id: r.affected for r in run_tsql_checks(job_id, database)}
        except Exception as exc:  # a check that can't run on the migrated output is a finding
            out[job_id] = [{"check_id": "-", "error": str(exc).splitlines()[0][:200]}]
            continue
        out[job_id] = [
            {
                "check_id": check_id,
                "legacy": legacy[job_id].get(check_id),
                "migrated": affected,
                "same": legacy[job_id].get(check_id) == affected,
            }
            for check_id, affected in sorted(migrated.items())
        ]
    return out


def _latest_delta(path: Path) -> Any:
    """
    Read a Delta table's current version as Arrow, through Spark.
    """
    from lansh.spark import get_spark

    return get_spark().read.format("delta").load(str(path)).toArrow()


def write_scores(run_id: str, *, prove: bool = False) -> Path:
    """
    Score a run and write ``runs/<run>/scores.json``, for the scorecard.

    Args:
        run_id: The run.
        prove: Also run the bug checks on the migrated outputs (needs SQL Server).

    Returns:
        The file written.
    """
    scores = score_run(run_id)
    data: dict[str, Any] = {"jobs": {j: asdict(s) for j, s in scores.items()}}
    totals = {k: sum(getattr(s, k) for s in scores.values()) for k in (
        "labelled_traps", "detected_traps", "armed_semantic", "armed_semantic_detected",
        "findings", "true_findings", "bugs", "bugs_detected", "defects", "defects_confirmed",
    )}  # fmt: skip
    verdicts = adjudication(run_id)
    if verdicts:
        totals["bugs_detected_adjudicated"] = sum(bool(v.get("genuine")) for v in verdicts.values())
        data["adjudication"] = verdicts
    data["totals"] = totals
    path = RUNS_DIR / run_id / "scores.json"
    if prove:
        data["reproduction"] = prove_reproduction(run_id)
    elif path.exists():
        # keep the reproduction proof of an earlier scoring; it needs SQL Server to redo
        earlier = json.loads(path.read_text(encoding="utf-8")).get("reproduction")
        if earlier:
            data["reproduction"] = earlier
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


### Held-out jobs (step 3.11)


def run_check_text(text: str, database: str) -> dict[str, int]:
    """
    Run a T-SQL check file's check batches in a database.

    Args:
        text: The check file: ``GO`` batches, each check opened by ``-- check: <id>``.
        database: The database whose tables the checks read.

    Returns:
        The ``affected`` count of each check.
    """
    from lansh.engines import mssql
    from lansh.estate.labels import is_check_batch

    out: dict[str, int] = {}
    with mssql.connect(database) as conn:
        cur = conn.cursor(as_dict=True)
        for batch in mssql.split_batches(text):
            cur.execute(batch)
            if not is_check_batch(batch):
                continue
            rows = cur.fetchall()
            while cur.nextset():
                pass
            for row in rows:
                out[str(row["check_id"])] = int(row["affected"] or 0)
    return out


def holdout_bug_impact(*, database: str = LEGACY_DATABASE) -> dict[str, int]:
    """
    Run the held-out author's bug checks, which size each planted bug on this data.

    Each check computes the job's result with and without the bug from the source tables alone,
    and counts the output rows that differ. It sizes the bug, but it can't show that a migrated
    output reproduces it: that proof is the job's MATCH, record for record, against the legacy
    output that holds the bug.

    Args:
        database: The legacy database (the checks read only its source tables).

    Returns:
        The rows each planted bug affects, by check id.
    """
    from lansh.config import HOLDOUT_DIR

    return run_check_text((HOLDOUT_DIR / "checks.sql").read_text(encoding="utf-8"), database)


def write_holdout(run_id: str) -> Path:
    """
    Score a held-out run and write ``runs/<run>/holdout_scores.json``, for the scorecard.

    The held-out answer key is its author's ``LABELS.md``, prose sealed with the jobs, so a
    person reads it against the run's evidence and records each verdict in the run's
    ``adjudication.json`` (bug id to ``{"defect_id", "genuine", "note"}``). The author's bug
    checks are run here to size each bug (needs SQL Server).

    Args:
        run_id: The held-out run.

    Returns:
        The file written.
    """
    data = {"bug_impact": holdout_bug_impact(), "adjudication": adjudication(run_id)}
    path = RUNS_DIR / run_id / "holdout_scores.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
