"""
The scorecard and the business case: every number traced to the run artifact it came from.

Plan §9 and §15, step 4.3. Each figure is a :class:`~lansh.contracts.Metric` whose sources
are the files it was computed from, pinned by SHA-256, so a judge can check any number.

The business case projects the run onto the client's estate (slide 8: about 1,200 ETL jobs and
400 SAS programs, delivered in 4–6 months). Measured inputs come from the run: Claude usage and
machine time per job, the escalation rate, the golden-capture time. The completed manual
baseline timesheet records the time spent migrating jobs by hand. Projection inputs that
aren't measured are labelled as **assumptions** and editable (:class:`Assumptions`), including
the minutes a reviewer spends on a job. Human review confirmed separately from the original
run does not supply measured review durations.

Because the saving is roughly one minus the escalation rate, the projection is a two-way
sensitivity table (plan step 5.4): escalation rate against a person's review minutes per job,
led by headcount and cost rather than a percentage. A run that includes S04 also gets the bias
table (step 5.5): S04's legacy risk tiers by age band and by county, from the golden outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

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
            middle and high. The sensitivity table uses the middle case, or the manual
            baseline when it exists.
        review_minutes_per_job: A person's minutes of review across one job's gates and
            decisions, one column of the sensitivity table each.
        escalation_rates: Shares of a real estate's jobs the factory can't take to MATCH,
            which a person then migrates by hand. Our estate can't measure the rate: it
            escalated nothing, and the held-out first run's 1 of 2 is a sample, not a rate.
        risk_based_share: The share of a real estate's jobs that would still get per-job
            review at H2–H4 under risk-based gating (those with warnings), for the gate load.
            Our estate can't measure it: every development job carries a planted bug by
            design, so all of them have warnings. The run's own share is reported beside it.
        day_rate_eur: The cost of a person-day, for the cost columns.
    """

    estate_jobs: int = 1600
    working_days: tuple[int, int] = (87, 130)
    hours_per_day: float = 7.0
    manual_minutes: tuple[int, int, int] = (240, 480, 960)
    review_minutes_per_job: tuple[float, ...] = (30.0, 60.0)
    escalation_rates: tuple[float, ...] = (0.15, 0.30, 0.50)
    risk_based_share: float = 0.3
    day_rate_eur: float = 600.0


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
    Average the completed manual timesheet's recorded job totals.
    """
    if not BASELINE_TIMESHEET.exists():
        return None, []
    per_job: dict[str, float] = {}
    with BASELINE_TIMESHEET.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                minutes = float(row["minutes"])
                job = row["job"].strip()
            except KeyError, ValueError, TypeError, AttributeError:
                continue
            if not job or not isfinite(minutes) or minutes <= 0:
                continue
            per_job[job] = per_job.get(job, 0.0) + minutes
    if not per_job:
        return None, []
    return sum(per_job.values()) / len(per_job), [BASELINE_TIMESHEET]


### Bias

AGE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("under 25", 0, 25),
    ("25-34", 25, 35),
    ("35-44", 35, 45),
    ("45-59", 45, 60),
    ("60+", 60, 200),
)
"""S04's age bands for the bias table, each a label, its lowest age and the age it stops before."""

S04_SCORES = GOLDEN_DIR / "S04" / "rpt.risk_scores.parquet"
T01_CUSTOMERS = GOLDEN_DIR / "T01" / "dw.dim_customer.parquet"


def bias_table(min_rows: int = 40) -> dict[str, Any] | None:
    """
    Tabulate S04's legacy risk tiers by age band and by county (plan step 5.5).

    S04 loads its risk score for age and county, so the share of scores rated HIGH in each
    group is what a person needs when deciding those flows at the design gate. It is read from
    the legacy output, one row per customer and line of business. County comes from T01's
    customer dimension, joined on ``customer_id``, with its spellings normalised (``'cork '``
    and ``'CORK'`` are Cork). LANSH reproduces the score either way; whether a loading is
    justified is a business and legal decision.

    Args:
        min_rows: The fewest risk scores a county needs before its share is reported.

    Returns:
        The share rated HIGH per age band, for ages 25-59 together and the lowest and highest
        county, or None when the golden outputs aren't there.
    """
    if not (S04_SCORES.exists() and T01_CUSTOMERS.exists()):
        return None
    scores = pq.read_table(S04_SCORES, columns=["customer_id", "age", "tier"]).to_pylist()
    county = {
        int(row["customer_id"]): row["county"].strip().title()
        for row in pq.read_table(T01_CUSTOMERS, columns=["customer_id", "county"]).to_pylist()
        if row["county"] and row["county"].strip()
    }

    def high(rows: list[dict[str, Any]]) -> float:
        """
        Give the percentage of these risk scores rated HIGH.
        """
        return 100 * sum(r["tier"] == "HIGH" for r in rows) / len(rows)

    aged = [r for r in scores if r["age"] is not None]
    by_age = []
    for band, low, stop in AGE_BANDS:
        rows = [r for r in aged if low <= r["age"] < stop]
        if rows:
            by_age.append({"age band": band, "risk scores": len(rows), "rated HIGH (%)": _num(high(rows), 1)})  # fmt: skip
    middle = [r for r in aged if 25 <= r["age"] < 60]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in scores:
        name = county.get(int(r["customer_id"]))
        if name:
            groups.setdefault(name, []).append(r)
    shares = {name: high(rows) for name, rows in groups.items() if len(rows) >= min_rows}
    lowest, highest = min(shares, key=shares.__getitem__), max(shares, key=shares.__getitem__)
    return {
        "by_age": by_age,
        "ages_25_59": {"risk scores": len(middle), "rated HIGH (%)": _num(high(middle), 1)},
        "by_county": {
            "counties": len(shares),
            "min_rows": min_rows,
            "lowest": {"county": lowest, "rated HIGH (%)": _num(shares[lowest], 1)},
            "highest": {"county": highest, "rated HIGH (%)": _num(shares[highest], 1)},
        },
    }


COMPARISONS = {
    "sqlglot_only": "sqlglot alone",
    "oneshot_claude": "one-shot Claude (same model, none of LANSH's knowledge, no healing)",
    "oneshot_claude+heal": "one-shot Claude, then LANSH's heal loop alone",
}
"""The comparison runs' approaches (plan §9.5), as the scorecard names them."""


def human_review(run_dir: Path) -> dict | None:
    """Read the team's review confirmation, pinned to the original gate log."""
    path = run_dir / "human_review.json"
    if not path.exists():
        return None
    review = json.loads(path.read_text(encoding="utf-8"))
    gates = run_dir / "gates.jsonl"
    decisions = [
        json.loads(line) for line in gates.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    gate_ids = {d["decision_id"] for d in decisions if d["entry"] == "gate"}
    if (
        review.get("status") != "reviewed_and_accepted"
        or review.get("synthetic", False)
        or not review.get("confirmed_by", "").startswith("person:")
        or review.get("gate_log_sha256") != hashlib.sha256(gates.read_bytes()).hexdigest()
        or set(review.get("gate_decision_ids", [])) != gate_ids
    ):
        raise ValueError(f"invalid human review confirmation: {path}")
    return review


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
        review = human_review(run_dir)
        if review:
            reviewed = set(review["gate_decision_ids"])
            people = sum(
                d["reviewer"].startswith("person:") or d["decision_id"] in reviewed
                for d in decisions
            )
            card.add(
                "Gate decisions reviewed and accepted by people",
                people,
                "decisions",
                [gates, run_dir / "human_review.json"],
            )
        else:
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
    bias = bias_table() if "S04" in jobs else None
    if bias:
        card.business_case["bias"] = bias
        under, middle, county = bias["by_age"][0], bias["ages_25_59"], bias["by_county"]
        card.add(
            "S04 risk scores rated HIGH, customers under 25 (legacy output)",
            under["rated HIGH (%)"],
            f"% of {under['risk scores']}",
            [S04_SCORES],
        )
        card.add(
            "S04 risk scores rated HIGH, customers aged 25-59 (legacy output)",
            middle["rated HIGH (%)"],
            f"% of {middle['risk scores']}",
            [S04_SCORES],
        )
        for end in ("lowest", "highest"):
            card.add(
                f"S04 risk scores rated HIGH, {end} county ({county[end]['county']}; of {county['counties']} counties with {county['min_rows']}+ scores)",
                county[end]["rated HIGH (%)"],
                "%",
                [S04_SCORES, T01_CUSTOMERS],
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
        The projection: the estate by hand per manual case, the sensitivity rows (escalation
        rate against a person's review minutes per job), the gate load, and notes on what is
        measured and what is assumed.
    """
    n = len(jobs)
    manifests = sorted(GOLDEN_DIR.glob("*/manifest.json"))
    capture = [json.loads(p.read_text())["capture_seconds"] for p in manifests]
    capture_min = sum(capture) / len(capture) / 60 if capture else 0.0
    card.add("Golden capture per job (both approaches need it)", capture_min, "minutes", manifests)
    escalated = sum(m.get("status") == "ESCALATED" for m in metrics.values())
    measured_escalation = escalated / n
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
        labels = ["manual baseline", *labels]
    # the sensitivity holds the manual effort at its best-supported value
    manual = baseline or a.manual_minutes[1]
    four, six = a.working_days

    def sized(hours: float) -> dict[str, str]:
        """
        Turn the estate's person-hours into team sizes for each window, and a cost.
        """
        return {
            "person-hours": _num(hours, 0),
            "people for 4 months": _num(hours / (four * a.hours_per_day), 1),
            "people for 6 months": _num(hours / (six * a.hours_per_day), 1),
            "cost (EUR)": _num(hours / a.hours_per_day * a.day_rate_eur, 0),
        }

    by_hand = [
        {"case": label, "hours per job by hand": _num(m / 60, 1)}
        | sized((m + capture_min) * a.estate_jobs / 60)
        for label, m in zip(labels, cases, strict=True)
    ]
    rows = [
        {"escalated to a person": f"{rate:.0%}", "review minutes per job": _num(review, 0)}
        | sized((review + rate * manual + capture_min) * a.estate_jobs / 60)
        for rate in a.escalation_rates
        for review in a.review_minutes_per_job
    ]
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
    rates = ", ".join(f"{r:.0%}" for r in a.escalation_rates)
    reviews = " and ".join(_num(r, 0) for r in a.review_minutes_per_job)
    people = next(
        (
            m.value
            for m in card.metrics
            if m.name == "Gate decisions reviewed and accepted by people"
        ),
        "0",
    )
    review_source = (
        "review durations are separate from the recorded machine timings; the projection labels review minutes as assumptions"
        if people == "0"
        else "all recorded gate decisions were reviewed and accepted by humans after the run; review minutes in the projection remain labelled assumptions"
    )
    return {
        "assumptions": asdict(a),
        "measured": {
            "escalation_rate_in_this_run": round(measured_escalation, 4),
            "golden_capture_minutes": round(capture_min, 2),
            "claude_cost_per_job_usd": round(cost, 4),
            "claude_cost_for_estate_usd": round(cost * a.estate_jobs, 2),
            "share_with_warnings_in_this_run": round(measured_share, 4),
            "risk_based_share_assumed": share,
            "manual_baseline_minutes": baseline,
        },
        "manual_baseline": (
            {
                "minutes_per_job": baseline,
                "sources": [_ref(p).model_dump(mode="json") for p in baseline_src],
            }
            if baseline
            else None
        ),
        "by_hand": by_hand,
        "rows": rows,
        "gate_load": gate_load,
        "notes": [
            f"LANSH person-hours per job = a person's review minutes + escalation rate x manual minutes ({_num(manual / 60, 1)} hours) + golden capture; the estate is {a.estate_jobs:,} jobs.",
            f"Assumed, not measured: low, middle and high manual effort of {', '.join(_num(m / 60, 0) for m in a.manual_minutes)} hours per job; escalation rates of {rates}; {reviews} minutes of review per job; {_num(a.hours_per_day, 0)}-hour days, {four} working days in 4 months and {six} in 6; EUR {_num(a.day_rate_eur, 0)} a person-day.",
            f"In this run {measured_escalation:.0%} of jobs escalated, and {review_source}.",
            f"Gate load for the estate: {gate_load['every gate for every job']:,} decisions with every gate for every job; {gate_load['risk-based gating']:,} if only the {share:.0%} of jobs with warnings get per-job review (in this run {measured_share:.0%} had warnings, since every development job carries a planted bug).",
            "Machine time runs in parallel and needs no people; it is reported separately.",
            f"Claude at API prices for the whole estate: about ${cost * a.estate_jobs:,.0f} (measured per job here, not billed on a subscription).",
            *(
                [
                    f"Manual baseline: {_num(baseline, 1)} minutes per job, recorded in the completed manual timesheet at {_ref(baseline_src[0]).path}. The projection uses this recorded effort."
                ]
                if baseline
                else [
                    "No manual baseline recorded; the projection uses the middle effort assumption."
                ]
            ),
        ],
    }


def _table(rows: list[dict[str, Any]]) -> list[str]:
    """
    Write rows of like dictionaries as the lines of a Markdown table.
    """
    header = list(rows[0])
    return [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(str(r[h]) for h in header) + " |" for r in rows),
    ]


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
        lines += [
            "",
            "## Business case: the client's 1,600 jobs (a projection)",
            "",
            "The notes identify measured inputs and the assumptions used to project them onto the client's estate.",
            "",
            "### By hand",
            "",
            *_table(bc["by_hand"]),
            "",
            "### Sensitivity: with LANSH",
            "",
            *_table(bc["rows"]),
            "",
        ]
        lines += [f"- {note}" for note in bc["notes"]]
        bias = bc.get("bias")
        if bias:
            county = bias["by_county"]
            lines += [
                "",
                "## Bias: S04's legacy risk tiers",
                "",
                "S04 loads its risk score for age and county. Share of risk scores rated HIGH (one row per customer and line of business), from the golden output:",
                "",
                *_table(bias["by_age"]),
                "",
                f"- Ages 25-59 together: {bias['ages_25_59']['rated HIGH (%)']}% of {bias['ages_25_59']['risk scores']} risk scores.",
                f"- By county ({county['counties']} counties with at least {county['min_rows']} risk scores, spellings normalised): from {county['lowest']['rated HIGH (%)']}% ({county['lowest']['county']}) to {county['highest']['rated HIGH (%)']}% ({county['highest']['county']}).",
                "- LANSH reproduces the score; whether a loading is justified is a business and legal decision, taken at the design gate.",
            ]
    md_path = run_dir / "scorecard.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
