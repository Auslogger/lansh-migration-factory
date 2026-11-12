"""
The scorecard and the business case: every number traced to the run artifact it came from.

Plan §9 and §15, step 4.3. Each figure is a :class:`~lansh.contracts.Metric` whose sources
are the files it was computed from, pinned by SHA-256, so a judge can check any number.

The business case projects the run onto the client's estate (slide 8: about 1,200 ETL jobs and
400 SAS programs, delivered in 4–6 months). Measured inputs come from the run: Claude usage and
machine time per job, the escalation rate, the golden-capture time. What a run can't measure is
an **assumption**, labelled as one and editable (:class:`Assumptions`): the minutes a person
takes to migrate a job by hand (until the team's manual baseline, plan §9.1, replaces it) and
the minutes a reviewer spends at a gate (development runs are approved by the agent, in no
time at all, so their review time measures nothing).
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from lansh.config import GOLDEN_DIR, REPO_ROOT, RUNS_DIR
from lansh.contracts import ArtifactRef, Metric

BASELINE_TIMESHEET = REPO_ROOT / "baseline" / "timesheet.csv"


@dataclass
class Assumptions:
    """
    What the business case can't measure from a run, labelled and editable.

    Attributes:
        estate_jobs: Jobs in the client's estate (slide 8: 1,200 ETL jobs and 400 SAS programs).
        working_days: The delivery window in working days (4 to 6 months).
        hours_per_day: Productive hours in a person's working day.
        manual_minutes: Minutes to migrate one job by hand to a record-for-record MATCH: low,
            middle and high. Replaced by the manual baseline when it exists.
        review_minutes_per_gate: Minutes a person spends on one gate decision for one job.
        risk_based_share: The share of a real estate's jobs that would still get per-job
            review at H2–H4 under risk-based gating (those with warnings). Our estate can't
            measure it: every development job carries a planted bug by design, so all of them
            have warnings. The run's own share is reported beside it.
        escalation_rate: The share of a real estate's jobs the factory can't take to MATCH,
            which a person then migrates by hand. Conservative by design, since a synthetic
            estate written by the team escalates less than a client's would; the run's own
            rate is reported beside it.
    """

    estate_jobs: int = 1600
    working_days: tuple[int, int] = (87, 130)
    hours_per_day: float = 7.0
    manual_minutes: tuple[int, int, int] = (240, 480, 960)
    review_minutes_per_gate: float = 5.0
    risk_based_share: float = 0.3
    escalation_rate: float = 0.15


def _ref(path: Path) -> ArtifactRef:
    """
    Pin one source file by its hash.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
    return ArtifactRef(path=str(shown), sha256=digest)


def _num(value: float | int | Decimal, places: int = 2) -> str:
    """
    Write a number as decimal text, rounded half up.
    """
    number = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return format(number.normalize() if number == number.to_integral() else number, "f")


@dataclass
class Card:
    """
    A scorecard under construction: its metrics and the business case.
    """

    run_id: str
    metrics: list[Metric] = field(default_factory=list)
    business_case: dict[str, Any] = field(default_factory=dict)

    def add(
        self, name: str, value: float | int | str, unit: str | None, sources: list[Path]
    ) -> None:
        """
        Record one number with the files it came from.
        """
        text = value if isinstance(value, str) else _num(value)
        self.metrics.append(
            Metric(name=name, value=text, unit=unit, sources=[_ref(p) for p in sources])
        )


def _baseline_minutes() -> tuple[float | None, list[Path]]:
    """
    Read the manual baseline's minutes per job, when the team has recorded it (plan §9.1).
    """
    if not BASELINE_TIMESHEET.exists():
        return None, []
    per_job: dict[str, float] = {}
    with BASELINE_TIMESHEET.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                per_job[row["job"]] = per_job.get(row["job"], 0.0) + float(row["minutes"])
            except KeyError, ValueError:
                continue
    if not per_job:
        return None, []
    return sum(per_job.values()) / len(per_job), [BASELINE_TIMESHEET]


COMPARISONS = {
    "sqlglot_only": "sqlglot alone",
    "oneshot_claude": "one-shot Claude (same model, none of LANSH's knowledge, no healing)",
    "oneshot_claude+heal": "one-shot Claude, then LANSH's heal loop alone",
}
"""The comparison runs' approaches (plan §9.5), as the scorecard names them."""


def build(
    run_id: str,
    assumptions: Assumptions | None = None,
    *,
    holdout_run: str | None = None,
    learning_run: str | None = None,
) -> Card:
    """
    Compute a run's scorecard and business case.

    Args:
        run_id: The run.
        assumptions: The business case's assumptions; the defaults when not given.

    Returns:
        The scorecard.
    """
    a = assumptions or Assumptions()
    run_dir = RUNS_DIR / run_id
    card = Card(run_id)
    evidence = {p.parent.name: p for p in sorted(run_dir.glob("*/evidence.json"))}
    metrics_files = {p.parent.name: p for p in sorted(run_dir.glob("*/metrics.json"))}
    jobs = {j: json.loads(p.read_text()) for j, p in evidence.items()}
    metrics = {j: json.loads(p.read_text()) for j, p in metrics_files.items()}
    n = len(jobs)
    if not n:
        return card
    sources = list(evidence.values())
    match = [j for j, m in metrics.items() if m.get("status") == "MATCH"]
    card.add("Jobs migrated", n, "jobs", sources)
    card.add(
        "Jobs reconciled record for record (MATCH, zero unexplained differences)",
        len(match),
        "jobs",
        sources,
    )
    first_pass = [j for j in match if not jobs[j].get("heal")]
    card.add("First-pass MATCH (no healing needed)", len(first_pass), "jobs", sources)
    card.add(
        "Heal attempts", sum(len(e.get("heal", [])) for e in jobs.values()), "attempts", sources
    )
    escalated = [j for j, m in metrics.items() if m.get("status") == "ESCALATED"]
    card.add("Jobs escalated to a person", len(escalated), "jobs", sources)
    rows = sum(
        r["counts"]["legacy"]
        for e in jobs.values()
        for r in e.get("recon", [])
        if r.get("counts") and not (r.get("run_id") or "").endswith(":operate")
    )
    card.add("Legacy output rows proved record for record", rows, "rows", sources)
    identical = sum(
        1
        for e in jobs.values()
        for r in e.get("recon", [])
        if r.get("candidate_sha256")
        and r["candidate_sha256"] == r.get("golden_sha256")
        and not (r.get("run_id") or "").endswith(":operate")
    )
    card.add("Outputs whose content hash equals the legacy output's", identical, "outputs", sources)
    tests = [t for e in jobs.values() for t in e.get("tests", [])]
    card.add(
        "Trap-focused tests passing",
        sum(t["status"] == "pass" for t in tests),
        f"of {len(tests)}",
        sources,
    )
    defects = [d for e in jobs.values() for d in e.get("defects", [])]
    card.add("Suspected legacy defects flagged", len(defects), "defects", sources)
    usage_file = run_dir / "llm_usage.jsonl"
    usage = (
        [json.loads(line) for line in usage_file.read_text().splitlines() if line.strip()]
        if usage_file.exists()
        else []
    )
    # one record per answer: a replay of a recorded answer costs what the recording cost
    cost = sum(m.get("cost_usd_equivalent", 0.0) for m in metrics.values())
    calls = sum(m.get("llm_calls", 0) for m in metrics.values())
    card.add("Claude calls per job", calls / n, "calls", list(metrics_files.values()))
    card.add(
        "API-equivalent cost per job (not billed: subscription)",
        cost / n,
        "USD",
        list(metrics_files.values()),
    )
    # a replayed answer takes no time, so it counts the time its live call took when recorded
    machine = [
        (m.get("duration_seconds") or 0.0)
        + sum(u["duration_ms"] for u in jobs[j].get("llm_usage", []) if u.get("replayed")) / 1000
        for j, m in metrics.items()
    ]
    card.add(
        "Machine time per job, end to end, with every Claude call live",
        sum(machine) / n / 60,
        "minutes",
        list(metrics_files.values()) + sources,
    )
    model = [sum(u["duration_ms"] for u in e.get("llm_usage", [])) / 1000 for e in jobs.values()]
    card.add("Claude model time per job", sum(model) / n / 60, "minutes", sources)
    if usage:
        card.add(
            "Live Claude calls in this run",
            sum(not u["replayed"] for u in usage),
            "calls",
            [usage_file],
        )
    gates = run_dir / "gates.jsonl"
    if gates.exists():
        decisions = [
            json.loads(line)
            for line in gates.read_text().splitlines()
            if line.strip() and '"entry":"gate"' in line
        ]
        people = sum(d["reviewer"].startswith("person:") for d in decisions)
        card.add("Gate decisions recorded", len(decisions), "decisions", [gates])
        card.add("Gate decisions made by people", people, "decisions", [gates])
    scores = run_dir / "scores.json"
    if scores.exists():
        s = json.loads(scores.read_text())["totals"]
        if "bugs_detected_adjudicated" in s:
            card.add(
                "Planted bugs flagged with the planted diagnosis (read by the evaluator)",
                s["bugs_detected_adjudicated"],
                f"of {s['bugs']}",
                [scores],
            )
        else:
            card.add(
                "Planted bugs flagged (answer key)", s["bugs_detected"], f"of {s['bugs']}", [scores]
            )
        bug_jobs = [j for j, v in json.loads(scores.read_text())["jobs"].items() if v["bugs"]]
        reproduced = [j for j in bug_jobs if metrics.get(j, {}).get("status") == "MATCH"]
        card.add(
            "Planted bugs reproduced exactly (their jobs MATCH record for record)",
            len(reproduced),
            f"of {len(bug_jobs)}",
            [scores, *(metrics_files[j] for j in reproduced)],
        )
        card.add(
            "Labelled trap occurrences detected",
            s["detected_traps"],
            f"of {s['labelled_traps']}",
            [scores],
        )
        card.add(
            "Armed semantic traps detected",
            s["armed_semantic_detected"],
            f"of {s['armed_semantic']}",
            [scores],
        )
        card.add(
            "Trap findings that match the answer key (precision)",
            s["true_findings"],
            f"of {s['findings']}",
            [scores],
        )
        repro = json.loads(scores.read_text()).get("reproduction") or {}
        checks = [c for rows_ in repro.values() for c in rows_ if "same" in c]
        if checks:
            card.add(
                "Answer-key checks giving the legacy result on the migrated output",
                sum(c["same"] for c in checks),
                f"of {len(checks)}",
                [scores],
            )
    bench = run_dir / "benchmark.json"
    if bench.exists():
        rows_ = json.loads(bench.read_text())
        by_approach: dict[str, dict[str, str]] = {}
        for r in rows_:
            by_approach.setdefault(r["approach"], {})[r["job_id"]] = r["status"]
        # a healed job's result replaces its one-shot result; the others keep theirs
        oneshot = by_approach.get("oneshot_claude", {})
        if "oneshot_claude+heal" in by_approach:
            by_approach["oneshot_claude+heal"] = oneshot | by_approach["oneshot_claude+heal"]
        for approach, label in COMPARISONS.items():
            if approach in by_approach:
                statuses = by_approach[approach]
                card.add(
                    f"Comparison run, {label}: jobs reaching MATCH",
                    sum(s == "MATCH" for s in statuses.values()),
                    f"of {len(statuses)}",
                    [bench],
                )
        # wrong answers that ran cleanly: without reconciliation nobody would know
        silent = [
            r for r in rows_ if r["approach"] == "oneshot_claude" and r["status"] == "MISMATCH"
        ]
        if oneshot:
            card.add(
                "One-shot translations that ran cleanly but were wrong (only reconciliation shows it)",
                len(silent),
                f"of {len(oneshot)}",
                [bench],
            )
            card.add(
                "Rows those translations got wrong",
                sum(r.get("rows_differing") or 0 for r in silent),
                "rows",
                [bench],
            )
    if holdout_run:
        held = sorted((RUNS_DIR / holdout_run).glob("*/metrics.json"))
        statuses = [json.loads(p.read_text()).get("status") for p in held]
        if held:
            card.add(
                "Held-out jobs (sealed, written by an isolated agent) reaching MATCH on their first run",
                sum(s == "MATCH" for s in statuses),
                f"of {len(held)}",
                held,
            )
        # each held-out job has one planted bug; its MATCH proves the bug reproduced exactly
        card.add(
            "Held-out planted bugs reproduced exactly (their jobs MATCH record for record)",
            sum(s == "MATCH" for s in statuses),
            f"of {len(held)}",
            held,
        )
        scored = RUNS_DIR / holdout_run / "holdout_scores.json"
        verdicts = json.loads(scored.read_text()).get("adjudication") if scored.exists() else None
        if verdicts:
            card.add(
                "Held-out planted bugs flagged with the planted diagnosis (read by the evaluator)",
                sum(bool(v.get("genuine")) for v in verdicts.values()),
                f"of {len(verdicts)}",
                [scored],
            )
    if learning_run:
        # after a fix the held-out jobs prompted, they are no longer held out: reported apart
        again = sorted((RUNS_DIR / learning_run).glob("*/metrics.json"))
        if again:
            card.add(
                "Held-out jobs reaching MATCH after the post-freeze learning fixes (a second run, not a held-out result)",
                sum(json.loads(p.read_text()).get("status") == "MATCH" for p in again),
                f"of {len(again)}",
                again,
            )
    card.business_case = business_case(card, a, jobs, metrics, run_dir)
    if holdout_run:
        held = [json.loads(p.read_text()) for p in (RUNS_DIR / holdout_run).glob("*/metrics.json")]
        if held:
            stopped = sum(m.get("status") != "MATCH" for m in held)
            card.business_case["notes"].append(
                f"On their first run, {stopped} of the {len(held)} held-out jobs escalated to a person "
                "(stopped by a failing test, not shipped): a sample too small to replace the assumed rate."
            )
    return card


def business_case(
    card: Card, a: Assumptions, jobs: dict[str, Any], metrics: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    """
    Project the run onto the client's estate: human hours, team size, Claude cost, gate load.

    Args:
        card: The scorecard so far (the measured figures are added to it).
        a: The assumptions.
        jobs: Each job's evidence.
        metrics: Each job's run metrics.
        run_dir: The run's folder.

    Returns:
        The projection: rows per approach and case, the gate load, and notes on what is
        measured and what is assumed.
    """
    n = len(jobs)
    manifests = sorted(GOLDEN_DIR.glob("*/manifest.json"))
    capture = [json.loads(p.read_text())["capture_seconds"] for p in manifests]
    capture_min = sum(capture) / len(capture) / 60 if capture else 0.0
    card.add("Golden capture per job (both approaches need it)", capture_min, "minutes", manifests)
    escalated = sum(m.get("status") == "ESCALATED" for m in metrics.values())
    measured_escalation = escalated / n
    escalation_rate = a.escalation_rate
    warned = [
        j
        for j, e in jobs.items()
        if e.get("defects") or e.get("heal") or e.get("flows") or e.get("escalations")
    ]
    measured_share = len(warned) / n
    share = a.risk_based_share
    cost = sum(m.get("cost_usd_equivalent", 0.0) for m in metrics.values()) / n
    baseline, baseline_src = _baseline_minutes()
    cases = list(a.manual_minutes)
    labels = ["low", "middle", "high"]
    if baseline:
        cases = [baseline, *cases]
        labels = ["manual baseline (measured)", *labels]
    review_full = 5 * a.review_minutes_per_gate
    review_risk = (3 * a.review_minutes_per_gate) * share + 2 * a.review_minutes_per_gate / 20
    hours_per_fte = [d * a.hours_per_day for d in a.working_days]
    rows = []
    for label, manual in zip(labels, cases, strict=True):
        manual_h = (manual + capture_min) * a.estate_jobs / 60
        lansh_min = review_risk + escalation_rate * manual + capture_min
        lansh_h = lansh_min * a.estate_jobs / 60
        every_gate_h = (review_full + escalation_rate * manual + capture_min) * a.estate_jobs / 60
        rows.append(
            {
                "manual minutes per job": _num(manual, 0),
                "case": label,
                "manual: person-hours for the estate": _num(manual_h, 0),
                "LANSH, every gate reviewed: person-hours": _num(every_gate_h, 0),
                "LANSH, risk-based gating: person-hours": _num(lansh_h, 0),
                "hours saved": f"{_num(100 * (1 - lansh_h / manual_h), 0)}%",
                "manual: people for 6 / 4 months": f"{_num(manual_h / hours_per_fte[1], 1)} / {_num(manual_h / hours_per_fte[0], 1)}",
                "LANSH: people for 6 / 4 months": f"{_num(lansh_h / hours_per_fte[1], 1)} / {_num(lansh_h / hours_per_fte[0], 1)}",
            }
        )
    shares_from = sorted(run_dir.glob("*/evidence.json"))
    card.add(
        "Jobs with warnings in this run (each carries a planted bug by design)",
        measured_share * 100,
        "%",
        shares_from,
    )
    gate_load = {
        "every gate for every job": 5 * a.estate_jobs,
        "risk-based gating": round(a.estate_jobs * 3 * share + 2 * a.estate_jobs / 20),
    }
    return {
        "assumptions": asdict(a),
        "measured": {
            "escalation_rate_in_this_run": round(measured_escalation, 4),
            "escalation_rate_assumed": escalation_rate,
            "golden_capture_minutes": round(capture_min, 2),
            "claude_cost_per_job_usd": round(cost, 4),
            "claude_cost_for_estate_usd": round(cost * a.estate_jobs, 2),
            "share_with_warnings_in_this_run": round(measured_share, 4),
            "risk_based_share_assumed": share,
            "manual_baseline_minutes": baseline,
        },
        "rows": rows,
        "gate_load": gate_load,
        "notes": [
            "LANSH person-hours = reviewer minutes (5 a gate; H2-H4 for jobs with warnings, H1 and H5 per wave of about 20 jobs) + escalation rate x manual minutes + golden capture, per job.",
            "Manual minutes per job are assumptions (4, 8 and 16 hours) until the team's manual baseline (plan §9.1) is recorded in baseline/timesheet.csv; the baseline row then appears first.",
            f"Risk-based gating assumes {share:.0%} of a real estate's jobs carry warnings and get per-job review at H2-H4. That is an assumption: in this run {measured_share:.0%} did, because every development job has a planted bug.",
            f"The projection assumes {escalation_rate:.0%} of a real estate's jobs escalate and are migrated by hand (in this run {measured_escalation:.0%} did).",
            "For reference, EXL reports a 50% efficiency gain from its Code Harbor tooling on a SAS-to-PySpark migration (plan §9.3); LANSH's figure counts person-hours to a proven, record-for-record MATCH.",
            "Machine time runs in parallel and needs no people; it is reported separately.",
            f"Claude at API prices for the whole estate: about ${cost * a.estate_jobs:,.0f} (measured per job here, not billed on a subscription).",
            *([f"Manual baseline from {baseline_src[0].name}."] if baseline_src else []),
        ],
    }


def write(card: Card) -> tuple[Path, Path]:
    """
    Write the scorecard as JSON (for the Control Tower) and Markdown (for people).

    Args:
        card: The scorecard.

    Returns:
        The JSON file and the Markdown file.
    """
    run_dir = RUNS_DIR / card.run_id
    data = {
        "run_id": card.run_id,
        "metrics": [m.model_dump(mode="json") for m in card.metrics],
        "business_case": card.business_case,
    }
    json_path = run_dir / "scorecard.json"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Scorecard: run {card.run_id}",
        "",
        "| Metric | Value | Unit | From |",
        "|---|---|---|---|",
    ]
    for m in card.metrics:
        lines.append(
            f"| {m.name} | {m.value} | {m.unit or ''} | {', '.join(s.path for s in m.sources[:2])}{' …' if len(m.sources) > 2 else ''} |"
        )
    if card.business_case:
        bc = card.business_case
        lines += ["", "## Projection onto 1,600 jobs", ""]
        header = list(bc["rows"][0])
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(r[h]) for h in header) + " |" for r in bc["rows"]]
        lines += [
            "",
            f"Gate decisions: {bc['gate_load']['every gate for every job']:,} with every gate for every job, {bc['gate_load']['risk-based gating']:,} with risk-based gating.",
            "",
        ]
        lines += [f"- {note}" for note in bc["notes"]]
    md_path = run_dir / "scorecard.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
