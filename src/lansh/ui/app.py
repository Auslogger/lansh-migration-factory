"""
The LANSH Control Tower: the estate, each job's evidence, the scorecard and the audit trail.

Plan §8.11. Run it with ``lansh ui`` (or ``make ui``). It reads one run's folder in ``runs/``
and changes nothing, except that a person may decide a gate a run is waiting at: the evidence
and its warnings are shown first, a reason is required with warnings or a rejection, and the
decision goes into the run's hash-chained gate log as that person's. A banner says when the
run's Claude answers were replayed rather than asked live.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from lansh.config import REPO_ROOT, RUNS_DIR
from lansh.contracts import EvidenceReport, Gate
from lansh.governance.gatelog import GateLog
from lansh.scorecard import human_review

GATES = ["H1", "H2", "H3", "H4", "H5"]
GATE_NAMES = {
    "H1": "Scope and lineage",
    "H2": "Contract and bug decisions",
    "H3": "Code review",
    "H4": "Evidence acceptance",
    "H5": "Cut-over",
}


### Reading a run


def _json(path: Path, default: Any = None) -> Any:
    """
    Read a JSON file, or give ``default`` when it doesn't exist.
    """
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def runs() -> list[str]:
    """
    List the runs with evidence: the showcase, its held-out runs, then the rest newest first.
    """
    found = [p.parent.parent.name for p in RUNS_DIR.glob("*/*/evidence.json")]
    # the showcase's held-out runs are published inside it, the only committed run folder
    found += [
        f"showcase/{p.parent.parent.name}" for p in RUNS_DIR.glob("showcase/*/*/evidence.json")
    ]
    order = {"showcase": 0, "showcase/held-out": 1, "showcase/learning": 2}
    if os.environ.get("LANSH_DEMO_RUNS") == "1":
        found = [r for r in found if r in {*order, "video"}]
    return sorted(set(found), key=lambda r: (order.get(r, 3), -_mtime(RUNS_DIR / r)))


def _mtime(path: Path) -> float:
    """
    Give a folder's modification time, or 0 when it is missing.
    """
    return path.stat().st_mtime if path.exists() else 0.0


def _markdown(evidence: Path) -> str:
    """
    Give a job's evidence report as Markdown, rendered from the JSON when the file is missing.
    """
    path = evidence.parent / "evidence.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    from lansh.evidence import render

    return render(
        EvidenceReport.model_validate_json(evidence.read_text(encoding="utf-8")),
        human_review=human_review(evidence.parent.parent),
    )


@st.cache_data(show_spinner=False)
def load(run_id: str, stamp: float) -> dict[str, Any]:
    """
    Read everything the pages show about one run; ``stamp`` refreshes the cache on change.
    """
    del stamp
    run_dir = RUNS_DIR / run_id
    jobs = {}
    for evidence in sorted(run_dir.glob("*/evidence.json")):
        job_id = evidence.parent.name
        jobs[job_id] = {
            "evidence": _json(evidence, {}),
            "metrics": _json(evidence.parent / "metrics.json", {}),
            "operate": _json(evidence.parent / "operate.json"),
            "tests": _json(evidence.parent / "tests.json", {}),
            "markdown": _markdown(evidence),
        }
    usage = [
        json.loads(line)
        for line in (run_dir / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if (run_dir / "llm_usage.jsonl").exists() else []  # fmt: skip
    return {
        "jobs": jobs,
        "estate": _json(run_dir / "estate.json"),
        "usage": usage,
        "register": _json(run_dir / "defect_register.json", []),
        "flows": _json(run_dir / "tagged_flows.json", []),
        "benchmark": _json(run_dir / "benchmark.json", []),
        "heals": {
            path.parent.name: _json(path, {})
            for path in sorted((run_dir / "benchmark" / "oneshot_claude+heal").glob("*/heal.json"))
        },
        "scores": _json(run_dir / "scores.json"),
        "scorecard": _json(run_dir / "scorecard.json"),
    }


def status_of(job: dict[str, Any]) -> str:
    """
    Give a job's headline status: MATCH, MISMATCH, ERROR or ESCALATED.

    A job stopped at a gate with an open escalation is ESCALATED, as its evidence report says,
    even where its metrics recorded the stop as an ERROR (held-out X1's, at code review).
    """
    status = job["metrics"].get("status")
    escalations = job["evidence"].get("escalations") or []
    if status in (None, "ERROR") and any(e.get("resolved_at") is None for e in escalations):
        return "ESCALATED"
    return str(status or "ERROR")


def badge(status: str) -> str:
    """
    Decorate a status for a table cell.
    """
    return {"MATCH": "✅ MATCH", "MISMATCH": "❌ MISMATCH", "ESCALATED": "⚠️ ESCALATED"}.get(
        status, f"⛔ {status}"
    )


### Pages


def demo_page() -> None:
    """Walk through verified results without navigating the underlying reports."""
    folder = RUNS_DIR / "showcase"
    if not (folder / "T04" / "evidence.json").exists():
        st.info("The guided demo uses the published showcase included with the project.")
        return
    data = load("showcase", _mtime(folder / "gates.jsonl"))
    evidence = data["jobs"]["T04"]["evidence"]
    steps = [
        "The risk",
        "The translation",
        "The proof",
        "The human decision",
        "The repair",
        "The outcome",
    ]
    step = st.session_state.get("demo_step", 0)
    st.caption("Recorded results · synthetic insurer · no live model calls in this walkthrough")
    st.progress((step + 1) / len(steps), text=f"{step + 1} of {len(steps)} · {steps[step]}")
    if step == 0:
        defect = next(d for d in evidence["defects"] if d["defect_id"] == "T04-D1")
        impact = defect["impact"]
        st.header("Move the system. Keep control of the numbers.")
        st.write(
            "This claims report contains a planted legacy bug: joining payments to multiple "
            "reserve rows counts some payments twice. A migration must expose that problem "
            "without silently changing the numbers finance already uses."
        )
        a, b = st.columns(2)
        a.metric("Paid-to-date overstatement", f"€{float(impact['amount_affected']):,.2f}")
        b.metric("Claims affected", impact["rows_affected"])
        if st.toggle("Show one affected claim", key="demo_claim"):
            golden = pd.read_parquet(REPO_ROOT / "estate/golden/T04/rpt.claims_summary.parquet")
            payments = pd.read_parquet(REPO_ROOT / "estate/data/claim_payments.parquet")
            payments = payments[pd.to_datetime(payments["payment_date"]) <= "2025-12-31"]
            paid = payments.groupby("claim_id")["amount"].sum()
            comparison = golden.set_index("claim_id")[["total_paid"]].copy()
            comparison["ledger"] = paid.reindex(comparison.index).fillna(0)
            affected = comparison[comparison["total_paid"] != comparison["ledger"]].iloc[0]
            st.subheader(f"Claim {affected.name}")
            a, b, c = st.columns(3)
            a.metric("Payments in the ledger", f"€{affected['ledger']:,.2f}")
            b.metric("Legacy report says", f"€{affected['total_paid']:,.2f}")
            c.metric("Overstatement", f"€{affected['total_paid'] - affected['ledger']:,.2f}")
            st.caption("Calculated from the committed payment ledger and SQL Server golden output.")
    elif step == 1:
        st.header("Translate the behaviour. Make the bug explicit.")
        st.write(
            "LANSH produces PySpark from the legacy SQL and marks the behaviour it must "
            "preserve. The joins below retain the payment fan-out deliberately. "
            "Fixing it belongs in a separate business decision."
        )
        a, b, c = st.columns(3)
        a.metric("Column lineage edges", len(evidence["lineage"]))
        b.metric("Trap findings for review", len(evidence["traps"]))
        c.metric("Generated trap tests", len(evidence["tests"]))
        left, right = st.columns(2)
        legacy = (REPO_ROOT / evidence["legacy_path"]).read_text().splitlines()
        generated = (REPO_ROOT / evidence["code"]["module_path"]).read_text().splitlines()
        left.subheader("Before · SQL Server")
        left.code("\n".join(legacy[102:115]), language="sql")
        right.subheader("After · generated PySpark")
        right.code("\n".join(generated[74:88]), language="python")
        st.info(
            "T04-D1 is marked at the join and sum. A separate literal guard rejects data "
            "constants that the legacy code, contract or trap cards cannot justify."
        )
        if st.button("Replay the migration now", key="demo_run"):
            with st.spinner(
                "Running T04 through the factory using recorded answers. Usually about 75 seconds…"
            ):
                try:
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "from lansh.cli import app; app()",
                            "run-job",
                            "T04",
                            "--run",
                            "demo",
                            "--mode",
                            "replay",
                        ],
                        cwd=REPO_ROOT,
                        env=dict(os.environ, LANSH_LLM_MODE="replay"),
                        capture_output=True,
                        text=True,
                        timeout=240,
                        check=False,
                    )
                    fresh = _json(RUNS_DIR / "demo" / "T04" / "evidence.json")
                    if (
                        result.returncode == 0
                        and fresh
                        and all(r["status"] == "MATCH" for r in fresh["recon"])
                    ):
                        st.session_state.demo_live_evidence = fresh
                        st.success("T04 has just finished: MATCH. Continue to inspect the proof.")
                    else:
                        st.error("The replay did not complete successfully.")
                        with st.expander("Run details"):
                            st.text((result.stdout + result.stderr)[-3000:])
                except subprocess.TimeoutExpired:
                    st.error(
                        "The replay exceeded four minutes. The published results remain available."
                    )
    elif step == 2:
        st.header("Every claim matches. Then we check it again on Delta.")
        evidence = st.session_state.get("demo_live_evidence", evidence)
        st.caption(
            "Fresh replay result"
            if "demo_live_evidence" in st.session_state
            else "Verified result from the published run; replay T04 on the previous screen to regenerate it."
        )
        sandbox = next(r for r in evidence["recon"] if not r["run_id"].endswith(":operate"))
        delta = next(r for r in evidence["recon"] if r["run_id"].endswith(":operate"))
        a, b, c = st.columns(3)
        a.metric("Rows matched", f"{sandbox['rows']['matched']} / {sandbox['counts']['legacy']}")
        b.metric(
            "Unexplained row differences",
            sum(sandbox["rows"][k] for k in ("value_diff", "missing", "extra")),
        )
        c.metric(
            "Trap tests passed",
            f"{sum(t['status'] == 'pass' for t in evidence['tests'])} / {len(evidence['tests'])}",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Verification": "Isolated execution",
                        "Claims matched": sandbox["rows"]["matched"],
                        "Result": sandbox["status"],
                    },
                    {
                        "Verification": "Delta lakehouse",
                        "Claims matched": delta["rows"]["matched"],
                        "Result": delta["status"],
                    },
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        with st.expander("Verify the output fingerprint"):
            st.code(
                f"SQL Server  {sandbox['golden_sha256']}\nPySpark     {sandbox['candidate_sha256']}",
                language="text",
            )
        if sandbox["status"] == "MATCH" and delta["status"] == "MATCH":
            st.success(
                "MATCH in the isolated run. MATCH again after writing to the Delta lakehouse."
            )
        else:
            st.error("The recorded outputs do not both match. Inspect the reconciliation evidence.")
        st.write(
            "Schema, counts, totals and every column are checked. The inherited bug stays visible."
        )
    elif step == 3:
        st.header("The migration preserves the bug. People own the decision.")
        st.caption("Completed review of the published run")
        decision = next(d for d in evidence["defect_decisions"] if d["defect_id"] == "T04-D1")
        review = human_review(folder)
        st.subheader("Payment/reserve join fan-out · T04-D1")
        st.metric("Recorded decision", decision["decision"].replace("_", " ").capitalize())
        st.write(
            "Preserve the existing calculation for migration parity. Any correction can then "
            "be approved separately, with its financial impact understood."
        )
        if review:
            st.success("Human review completed after the run")
            st.write(
                "Reviewed collectively by " + ", ".join(review.get("reviewer_names", [])) + "."
            )
            st.caption(
                "Gregory and Vansh led most reviews. Original automated recordings are retained."
            )
        if st.toggle("Show the five review stages", key="demo_reviews"):
            decisions = {g["gate"]: g for g in evidence["gates"]}
            for gate in GATES:
                if gate in decisions:
                    st.write(f"✓ {GATE_NAMES[gate]} · {decisions[gate]['outcome']}")
        if st.toggle("Show the bias check", key="demo_bias"):
            bias = data["scorecard"]["business_case"]["bias"]
            young = next(r for r in bias["by_age"] if r["age band"] == "under 25")
            a, b = st.columns(2)
            a.metric("Under 25 · rated HIGH", f"{young['rated HIGH (%)']}%")
            b.metric("Ages 25–59 · rated HIGH", f"{bias['ages_25_59']['rated HIGH (%)']}%")
            st.write(
                "The inherited age loading is visible for human review. Migration parity does not establish fairness."
            )
        st.caption(
            "Synthetic data. Agents have no tools. Personal fields are masked in model samples."
        )
        st.caption(
            "This shows the completed review; clicking through does not create a new approval."
        )
    elif step == 4:
        st.header("A translation can run successfully and still change the result.")
        heal = data["heals"]["S04"]
        attempt = heal["attempts"][0]
        st.write(
            "In the separate one-shot comparison, Claude changed the risk-scoring job's output. "
            "SAS stores a tier as MEDI; the translation wrote MEDIUM. "
            "Reconciliation exposed the differences."
        )
        left, right = st.columns(2)
        left.metric("Before repair · differing rows", attempt["score_before"][-1])
        if st.toggle("Show the repair", key="demo_repair"):
            right.metric("After repair · differing rows", attempt["score_after"][-1])
            st.success(f"{heal['status']} after {len(heal['attempts'])} repair attempt")
            st.write(
                "The repair restored SAS's fixed character length and corrected its rounding "
                "behaviour. The output was reconciled again before being accepted."
            )
            with st.expander("Inspect the recorded patch"):
                st.write(attempt["patch_summary"])
        st.caption("These are saved before-and-after results from the one-shot healing benchmark.")
    else:
        st.header("Ten migrated jobs. Evidence behind every result.")
        jobs = data["jobs"]
        a, b, c, cost = st.columns(4)
        a.metric(
            "Development jobs matching",
            f"{sum(status_of(j) == 'MATCH' for j in jobs.values())} / {len(jobs)}",
        )
        b.metric(
            "Legacy rows proved",
            f"{sum(j['evidence']['recon'][0]['counts']['legacy'] for j in jobs.values()):,}",
        )
        baseline = data["scorecard"]["business_case"]["manual_baseline"]["minutes_per_job"]
        c.metric("Measured manual baseline", f"{baseline / 60:.1f} hours / job")
        cost.metric(
            "Model cost / job",
            f"${sum(j['metrics'].get('cost_usd_equivalent', 0) for j in jobs.values()) / len(jobs):.2f}",
            help="API-equivalent model cost, not billed on the subscription.",
        )
        st.subheader("Same jobs. Same ground truth. Different results.")
        comparison = pd.DataFrame(data["benchmark"])
        matched = comparison.groupby("approach")["status"].apply(
            lambda rows: int((rows == "MATCH").sum())
        )
        st.bar_chart(
            pd.Series(
                {
                    "sqlglot alone": matched.get("sqlglot_only", 0),
                    "One-shot Claude": matched.get("oneshot_claude", 0),
                    "LANSH first pass": sum(status_of(j) == "MATCH" for j in jobs.values()),
                },
                name="Jobs reaching MATCH",
            ),
            horizontal=True,
        )
        st.subheader("What this could mean for 1,600 jobs")
        bc = data["scorecard"]["business_case"]
        manual = next(r for r in bc["by_hand"] if r["case"] == "manual baseline")
        projected = next(
            r
            for r in bc["rows"]
            if r["escalated to a person"] == "30%" and r["review minutes per job"] == "30"
        )
        st.bar_chart(
            pd.Series(
                {
                    "By hand": float(manual["person-hours"]),
                    "LANSH projection": float(projected["person-hours"]),
                },
                name="Person-hours",
            ),
            horizontal=True,
        )
        st.caption(
            "Projection: 30% escalation, 30 review minutes per job; manual time measured on two jobs."
        )
        st.write(
            "The separate held-out test matched one of two jobs first time and stopped the "
            "other at a failing test. After the reported learning fixes, both matched."
        )
        st.subheader("The proof travels with the migration.")
        st.caption(
            "Azure target: the same PySpark and Delta design maps to Azure Databricks. The demonstrated execution is local."
        )
    st.divider()
    back, forward = st.columns(2)
    if back.button("← Previous", disabled=step == 0, key="demo_back"):
        st.session_state.demo_step = step - 1
        st.rerun()
    label = f"Next: {steps[step + 1]} →" if step < len(steps) - 1 else "Start again"
    if forward.button(label, type="primary", key="demo_next"):
        st.session_state.demo_step = (step + 1) % len(steps)
        st.rerun()


def estate_page(run_id: str, data: dict[str, Any], log: GateLog) -> None:
    """
    Show the estate: headline numbers, waves, the DAG and every job's status.
    """
    jobs = data["jobs"]
    statuses = {j: status_of(v) for j, v in jobs.items()}
    usage = data["usage"]
    cols = st.columns(5)
    cols[0].metric("Jobs", len(jobs))
    cols[1].metric("Record-for-record MATCH", sum(s == "MATCH" for s in statuses.values()))
    cols[2].metric(
        "Suspected defects", sum(len(v["evidence"].get("defects", [])) for v in jobs.values())
    )
    cols[3].metric("Heal attempts", sum(len(v["evidence"].get("heal", [])) for v in jobs.values()))
    # per job, as the scorecard counts it: the folder's usage log also holds the comparison runs
    per_job = [v["metrics"].get("cost_usd_equivalent", 0.0) for v in jobs.values()]
    cols[4].metric(
        "Claude per job, API-equivalent",
        f"${sum(per_job) / len(per_job):.2f}" if per_job else "—",
        help=(
            "What each job's Claude calls would cost at API prices; every call logged in this "
            f"run's folder, comparison runs included, comes to ${sum(u['cost_usd_equivalent'] for u in usage):.2f}. "
            "Nothing is billed: LANSH runs on a subscription."
        ),
    )
    estate = data["estate"]
    if estate:
        st.subheader("Waves")
        # the estate's plan also places the held-out jobs, which run apart, in their own runs
        for wave in estate["waves"]:
            in_run = [j for j in wave["job_ids"] if j in jobs]
            if not in_run:
                continue
            cells = [f"{j} {badge(statuses[j])}" for j in in_run]
            cut = all(log.passed(j, Gate.H5) for j in in_run)
            st.write(
                f"**Wave {wave['number']}** {'(cut over)' if cut else ''}: " + " · ".join(cells)
            )
        dot = ["digraph { rankdir=LR; node [shape=box, style=rounded];"]
        for wave in estate["waves"]:
            for j in wave["job_ids"]:
                if j not in jobs:
                    continue
                colour = {"MATCH": "palegreen", "MISMATCH": "lightpink"}.get(
                    statuses.get(j, ""), "lightgrey"
                )
                dot.append(f'"{j}" [style="rounded,filled", fillcolor={colour}];')
        for e in estate["edges"]:
            if e["upstream"] not in jobs or e["downstream"] not in jobs:
                continue
            dot.append(
                f'"{e["upstream"]}" -> "{e["downstream"]}" [label="{", ".join(e["tables"])}", fontsize=8];'
            )
        dot.append("}")
        st.graphviz_chart("\n".join(dot))
    st.subheader("Jobs")
    rows = []
    for job_id, v in jobs.items():
        ev, m = v["evidence"], v["metrics"]
        reached = log.stage_reached(job_id)
        rows.append(
            {
                "job": job_id,
                "legacy": ev.get("legacy_path", ""),
                "status": badge(statuses[job_id]),
                "gate passed": reached.value if reached else "—",
                "traps": len(ev.get("traps", [])),
                "suspected defects": len(ev.get("defects", [])),
                "tests": f"{sum(t['status'] == 'pass' for t in ev.get('tests', []))}/{len(ev.get('tests', []))}",
                "heal attempts": len(ev.get("heal", [])),
                "Claude calls": m.get("llm_calls", 0),
                "API-equivalent $": round(m.get("cost_usd_equivalent", 0.0), 2),
                "seconds": round(m.get("duration_seconds") or 0),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if data["flows"]:
        st.subheader("Flows of personal and protected columns")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "tag": f["tag"],
                        "from": f"{f['source']['table']}.{f['source']['column']}",
                        "into": f"{f['output']['table']}.{f['output']['column']}",
                        "through": " → ".join(f["job_ids"]),
                    }
                    for f in data["flows"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def _pending(run_id: str, job_id: str) -> list[Path]:
    """
    List the gates a job is waiting at in a run.
    """
    return sorted((RUNS_DIR / run_id / "pending").glob(f"{job_id}-H*.json"))


def decide_form(run_id: str, pending: Path) -> None:
    """
    Show a pending gate's evidence and warnings, then take a person's decision on it.
    """
    from lansh.pipeline import approve_pending

    data = json.loads(pending.read_text(encoding="utf-8"))
    st.warning(f"**{data['gate']} {GATE_NAMES[data['gate']]}** is waiting for a decision.")
    st.write(data.get("summary", ""))
    for e in data["evidence"]:
        st.write(f"- evidence `{e['ref']}` (`{(e.get('sha256') or '')[:12]}`)")
    for w in data["warnings"]:
        st.write(f"- ⚠️ {w}")
    with st.form(f"decide-{pending.name}"):
        reviewer = st.text_input("Your name (recorded as person:<name>)")
        reason = st.text_area("Reason (required with warnings or a rejection)")
        approve, reject = st.columns(2)
        ok = approve.form_submit_button("Approve")
        no = reject.form_submit_button("Reject")
    if ok or no:
        if not reviewer.strip():
            st.error("A decision needs your name.")
            return
        try:
            decision = approve_pending(
                run_id, pending, f"person:{reviewer.strip()}", reason or None, approve=ok
            )
        except Exception as exc:  # the gate log refuses, for example, a missing reason
            st.error(str(exc))
            return
        flag = " (flagged: faster than the review threshold)" if decision.flagged_fast else ""
        st.success(
            f"Recorded {decision.outcome.value} by {decision.reviewer}{flag}. Resume the run to continue."
        )


def defect_form(log: GateLog, job_id: str, defect: dict[str, Any]) -> None:
    """
    Take a person's decision on one undecided suspected defect: reproduce, fix later, or not one.
    """
    from lansh.contracts import DefectDecisionKind

    with st.form(f"defect-{defect['defect_id']}"):
        st.write(
            f"Decide **{defect['defect_id']}**: the default is to reproduce the legacy behaviour."
        )
        choice = st.radio(
            "Decision",
            ["reproduce", "fix_after_cutover", "not_a_defect"],
            horizontal=True,
            key=f"choice-{defect['defect_id']}",
        )
        reviewer = st.text_input("Your name", key=f"who-{defect['defect_id']}")
        reason = st.text_input("Reason", key=f"why-{defect['defect_id']}")
        submitted = st.form_submit_button("Record decision")
    if submitted:
        if not (reviewer.strip() and reason.strip()):
            st.error("A decision needs your name and a reason.")
            return
        gate = Gate.H4 if log.passed(job_id, Gate.H2) else Gate.H2
        log.decide_defect(
            defect["defect_id"],
            job_id,
            DefectDecisionKind(choice),
            reason,
            f"person:{reviewer.strip()}",
            gate=gate,
        )
        st.success(f"Recorded {choice} for {defect['defect_id']} at {gate.value}.")


def flow_form(log: GateLog, flow: dict[str, Any]) -> None:
    """
    Take a person's bias decision on one flow of a protected or personal column (H2).
    """
    with st.form(f"flow-{flow['flow_id']}"):
        st.write(
            f"**{flow['tag']}** column `{flow['source']['table']}.{flow['source']['column']}` flows into "
            f"`{flow['output']['table']}.{flow['output']['column']}` through {', '.join(flow['job_ids'])}."
        )
        flagged = st.checkbox(
            "Flag it for a bias review after cut-over", value=True, key=f"flag-{flow['flow_id']}"
        )
        reviewer = st.text_input("Your name", key=f"fwho-{flow['flow_id']}")
        reason = st.text_input("Reason", key=f"fwhy-{flow['flow_id']}")
        submitted = st.form_submit_button("Record decision")
    if submitted:
        if not (reviewer.strip() and reason.strip()):
            st.error("A decision needs your name and a reason.")
            return
        decision = "reproduce_flagged" if flagged else "reproduce_accepted"
        log.decide_flow(flow["flow_id"], decision, reason, f"person:{reviewer.strip()}")
        st.success(f"Recorded {decision} for {flow['flow_id']}.")


def job_page(run_id: str, data: dict[str, Any], log: GateLog) -> None:
    """
    Show one job's evidence: code side by side, lineage, traps, contract, reconciliation, defects.
    """
    jobs = data["jobs"]
    if not jobs:
        st.info("This run has no jobs yet.")
        return
    job_id = st.selectbox("Job", list(jobs), index=list(jobs).index("T04") if "T04" in jobs else 0)
    v = jobs[job_id]
    ev = v["evidence"]
    st.write(f"**{job_id}** · {badge(status_of(v))} · legacy `{ev['legacy_path']}`")
    cols = st.columns(5)
    for col, gate in zip(cols, GATES, strict=True):
        col.metric(
            f"{gate} {GATE_NAMES[gate]}", "passed" if log.passed(job_id, Gate(gate)) else "—"
        )
    for pending in _pending(run_id, job_id):
        decide_form(run_id, pending)
    tabs = st.tabs(
        [
            "Code",
            "Reconciliation",
            "Defects",
            "Lineage",
            "Traps",
            "Contract",
            "Tests",
            "Gates",
            "Report",
        ]
    )
    with tabs[0]:
        left, right = st.columns(2)
        legacy = (REPO_ROOT / ev["legacy_path"]).read_text(encoding="utf-8")
        left.caption(f"Legacy: {ev['legacy_path']}")
        left.code(
            legacy,
            language="sql" if ev["legacy_path"].endswith(".sql") else "sas",
            line_numbers=True,
        )
        code = ev.get("code") or {}
        module = REPO_ROOT / code.get("module_path", "") if code else None
        right.caption(f"PySpark: {code.get('module_path', '—')} ({code.get('translator', '')})")
        if module and module.is_file():
            right.code(module.read_text(encoding="utf-8"), language="python", line_numbers=True)
    with tabs[1]:
        for r in ev.get("recon", []):
            where = "Delta lakehouse" if (r.get("run_id") or "").endswith(":operate") else "sandbox"
            st.markdown(f"#### {r['table']} ({where}): {badge(r['status'])}")
            st.write(r["explanation"])
            if r.get("counts"):
                c = r["counts"]
                st.write(
                    f"Rows {c['legacy']:,} vs {c['candidate']:,} · matched {r['rows']['matched']:,} · "
                    f"content hash {'identical' if r.get('candidate_sha256') == r.get('golden_sha256') else 'differs'}"
                )
            if r.get("totals"):
                st.dataframe(pd.DataFrame(r["totals"]), hide_index=True)
        if ev.get("heal"):
            st.markdown("#### Heal timeline")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"attempt": h["attempt"], "kept": h["kept"], "before": str(h["score_before"]),
                         "after": str(h["score_after"]), "diagnosis": h["diagnosis"]}
                        for h in ev["heal"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )  # fmt: skip
    with tabs[2]:
        logged = {d.defect_id: d.model_dump(mode="json") for d in log.defect_decisions(job_id)}
        decisions = {d["defect_id"]: d for d in ev.get("defect_decisions", [])} | logged
        for d in ev.get("defects", []):
            impact = d.get("impact") or {}
            dec = decisions.get(d["defect_id"])
            if dec is None:
                defect_form(log, job_id, d)
            st.markdown(
                f"**{d['defect_id']} {d['title']}** (lines {d.get('evidence_lines', [])[:1]}…)"
            )
            st.write(d["description"])
            st.write(
                f"Impact on the legacy output: {impact.get('rows_affected', 'not measured')} rows"
                + (
                    f", {impact['amount_affected']} in {impact.get('amount_column')}"
                    if impact.get("amount_affected")
                    else ""
                )
                + f" · decision: {dec['decision'] + ' by ' + dec['decided_by'] if dec else 'undecided'}"
            )
    with tabs[3]:
        st.dataframe(
            pd.DataFrame(
                [
                    {"output": e.get("output_column") or "(rows)", "kind": e["kind"],
                     "input": f"{e.get('input_table') or e['input_kind']}.{e.get('input_column') or ''}",
                     "transform": e.get("transform"), "sqlglot agrees": e.get("agrees_with_sqlglot")}
                    for e in ev.get("lineage", [])
                ]
            ),
            hide_index=True,
            width="stretch",
        )  # fmt: skip
    with tabs[4]:
        st.dataframe(
            pd.DataFrame(
                [{"trap": t["trap_id"], "lines": f"{t['line_start']}-{t['line_end']}", "found by": t["detector"],
                  "note": t.get("note"), "code": t["snippet"]} for t in ev.get("traps", [])]
            ),
            hide_index=True,
            width="stretch",
        )  # fmt: skip
    with tabs[5]:
        decided_flows = {f.flow_id for f in log.flow_decisions()}
        for flow in ev.get("flows", []):
            if flow["flow_id"] not in decided_flows:
                flow_form(log, flow)
        for c in ev.get("contracts", []):
            st.markdown(f"**{c['table']}** ({c['layer']}): {c['grain']}")
            st.write(f"Key {c['keys'] or 'none'} · partitions {c['partition_columns'] or 'none'}")
            st.dataframe(
                pd.DataFrame(
                    [{"column": col["name"], "type": col["data_type"], "legacy": col.get("legacy_type"),
                      "policy": col["policy"]["kind"], "reason": col["policy"].get("reason"),
                      "tags": ", ".join(col.get("tags", []))} for col in c["columns"]]
                ),
                hide_index=True,
                width="stretch",
            )  # fmt: skip
    with tabs[6]:
        tests = v["tests"]
        st.write(f"{tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed")
        st.dataframe(
            pd.DataFrame(
                [{"test": t["test_id"], "trap": t.get("trap_id"), "expected from": t["expected_source"],
                  "status": t["status"], "sets up": t["description"]} for t in ev.get("tests", [])]
            ),
            hide_index=True,
            width="stretch",
        )  # fmt: skip
    with tabs[7]:
        st.dataframe(
            gate_rows(ev.get("gates", []), human_review(RUNS_DIR / run_id)),
            hide_index=True,
            width="stretch",
        )
    with tabs[8]:
        st.markdown(v["markdown"], unsafe_allow_html=False)


def gate_rows(gates: list[dict[str, Any]], review: dict | None = None) -> pd.DataFrame:
    """
    Tabulate gate decisions for display.
    """
    if review:
        return pd.DataFrame(
            [
                {
                    "gate": r["gate"],
                    "jobs": ", ".join(r["job_ids"]),
                    "human acceptance": r["outcome"],
                    "review timing": "reviewed after the run",
                    "reviewer": ", ".join(r.get("reviewer_names", [])) or "Team confirmation",
                    "scope checked": r["review_scope"],
                    "human reason": r.get("reason"),
                    "original decision": r["decision_id"],
                }
                for r in review.get("reviews", [])
                if r["decision_id"] in {g["decision_id"] for g in gates}
            ]
        )
    return pd.DataFrame(
        [
            {
                "gate": g["gate"],
                "jobs": ", ".join(g["job_ids"]),
                "outcome": g["outcome"],
                "reviewer": g["reviewer"],
                "fast": g["flagged_fast"],
                "spot-check": g["spot_check"],
                "reason": g.get("reason"),
                "decided": g["decided_at"],
            }
            for g in gates
        ]
    )


def scorecard_page(run_id: str, data: dict[str, Any]) -> None:
    """
    Show the scorecard: proof, detection, the comparison runs and the business case.
    """
    card = data["scorecard"]
    if not card:
        st.info(f"No scorecard yet for this run: `lansh scorecard --run {run_id}` writes one.")
    else:
        st.subheader("Every number traces to a run artifact")
        st.dataframe(
            pd.DataFrame(
                [{"metric": m["name"], "value": m["value"], "unit": m.get("unit") or "",
                  "from": ", ".join(s["path"] for s in m["sources"][:3])} for m in card["metrics"]]
            ),
            hide_index=True,
            width="stretch",
        )  # fmt: skip
        if card.get("business_case"):
            bc = card["business_case"]
            st.subheader("Business case: the client's 1,600 jobs (a projection)")
            if bc.get("by_hand"):
                st.caption("By hand: manual effort per job")
                st.dataframe(pd.DataFrame(bc["by_hand"]), hide_index=True, width="stretch")
                st.caption(
                    "With LANSH: the escalation rate against a person's review minutes per job"
                )
            st.dataframe(pd.DataFrame(bc["rows"]), hide_index=True, width="stretch")
            for note in bc.get("notes", []):
                st.caption(note)
            bias = bc.get("bias")
            if bias:
                st.subheader("Bias: S04's legacy risk tiers by age band")
                st.dataframe(pd.DataFrame(bias["by_age"]), hide_index=True, width="stretch")
                county = bias["by_county"]
                st.caption(
                    f"Ages 25-59 together: {bias['ages_25_59']['rated HIGH (%)']}% rated HIGH. "
                    f"By county ({county['counties']} counties with at least {county['min_rows']} risk scores): "
                    f"from {county['lowest']['rated HIGH (%)']}% ({county['lowest']['county']}) "
                    f"to {county['highest']['rated HIGH (%)']}% ({county['highest']['county']}). "
                    "LANSH reproduces the score; whether a loading is justified is a business and legal decision."
                )
    if data["benchmark"]:
        st.subheader("Comparison runs: what the proof loop adds")
        st.caption(
            "Every approach is reconciled against the same golden outputs, under the same contracts. "
            "One-shot Claude is the same model and effort as LANSH's translator, with the same module "
            "interface but none of LANSH's knowledge (trap cards, language rules, draft, notes) and no healing."
        )
        frame = pd.DataFrame(data["benchmark"])
        pivot = frame.pivot_table(
            index="job_id", columns="approach", values="status", aggfunc="first"
        )
        healed = "oneshot_claude+heal"
        if healed in pivot and "oneshot_claude" in pivot:
            # a one-shot translation that matched needed no healing
            pivot[healed] = pivot[healed].fillna(pivot["oneshot_claude"])
        pivot["LANSH"] = pd.Series({j: status_of(job) for j, job in data["jobs"].items()})
        st.dataframe(pivot, width="stretch")
        st.bar_chart((pivot == "MATCH").sum())
    if data["heals"]:
        st.subheader("The heal loop on the one-shot translations that failed")
        for job_id, heal in data["heals"].items():
            attempts = heal.get("attempts", [])
            with st.expander(f"{job_id}: {heal.get('status')} after {len(attempts)} attempt(s)"):
                st.dataframe(
                    pd.DataFrame(
                        [{"attempt": a["attempt"], "diagnosis": a["diagnosis"], "patch": a["patch_summary"],
                          "score before": a["score_before"], "score after": a["score_after"],
                          "status after": a.get("recon_status_after"), "kept": a["kept"]} for a in attempts]
                    ),
                    hide_index=True,
                    width="stretch",
                )  # fmt: skip
                if heal.get("escalation"):
                    st.warning(f"Escalated to a person: {heal['escalation']['diagnosis']}")


def audit_page(run_id: str, log: GateLog) -> None:
    """
    Show the gate log and check its hash chain.
    """
    problems = log.verify()
    if problems:
        st.error("The gate log's hash chain is broken:\n" + "\n".join(problems))
    else:
        st.success(
            f"The gate log is intact: {len(log.entries())} entries, each chained to the one before."
        )
    decisions = [d.model_dump(mode="json") for d in log.decisions()]
    review = human_review(RUNS_DIR / run_id)
    if review:
        reviewed = set(review["gate_decision_ids"])
        people = sum(
            d["reviewer"].startswith("person:") or d["decision_id"] in reviewed for d in decisions
        )
        st.write(
            f"{len(decisions)} gate decisions, {people} reviewed and accepted by humans after the run."
        )
        st.caption(
            f"Human review confirmed by the team on {review['confirmation_recorded_on']}. "
            "The table preserves the original recording identities and timings."
        )
    else:
        people = sum(d["reviewer"].startswith("person:") for d in decisions)
        st.write(
            f"{len(decisions)} gate decisions, {people} by people, {len(decisions) - people} by agents."
        )
    st.dataframe(gate_rows(decisions, review), hide_index=True, width="stretch")
    spot = [d for d in decisions if d["spot_check"]]
    if spot:
        st.write(
            f"Picked for random re-review: {', '.join(d['gate'] + ' ' + ','.join(d['job_ids']) for d in spot)}"
        )


def main() -> None:
    """
    Lay out the Control Tower: pick a run, show the replay banner, then the chosen page.
    """
    st.set_page_config(page_title="LANSH Control Tower", layout="wide")
    st.title("LANSH Control Tower")
    available = runs()
    if not available:
        st.info("No runs yet: `lansh run --all` (or `make demo`) creates one.")
        return
    run_id = st.sidebar.selectbox("Run", available)
    page = st.sidebar.radio(
        "Page",
        ["Estate", "Demo", "Job", "Scorecard", "Audit"],
        index=1 if os.environ.get("LANSH_DEMO_RUNS") == "1" else 0,
    )
    if page == "Demo":
        demo_page()
        return
    data = load(run_id, _mtime(RUNS_DIR / run_id / "gates.jsonl"))
    if data["usage"] and all(u["replayed"] for u in data["usage"]):
        st.info(
            "**Replay.** Every Claude answer in this run was played back from `runs/cassettes/`: "
            "nothing was sent to Claude. A live run can give different answers."
        )
    log = GateLog(RUNS_DIR / run_id / "gates.jsonl")
    if page == "Estate":
        estate_page(run_id, data, log)
    elif page == "Job":
        job_page(run_id, data, log)
    elif page == "Scorecard":
        scorecard_page(run_id, data)
    else:
        audit_page(run_id, log)


main()
