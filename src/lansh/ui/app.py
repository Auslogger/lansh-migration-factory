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
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from lansh.config import REPO_ROOT, RUNS_DIR
from lansh.contracts import EvidenceReport, Gate
from lansh.governance.gatelog import GateLog

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
    return sorted(set(found), key=lambda r: (order.get(r, 3), -_mtime(RUNS_DIR / r)))


def _mtime(path: Path) -> float:
    """
    Give a folder's modification time, or 0 when it is missing.
    """
    return path.stat().st_mtime if path.exists() else 0.0


def _markdown(evidence: Path) -> str:
    """
    Give a job's evidence report as Markdown, rendered from the JSON when the file is missing.

    A clone has no Markdown files: the repository's ``.gitignore`` keeps ``*.md`` out of git.
    """
    path = evidence.parent / "evidence.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    from lansh.evidence import render

    return render(EvidenceReport.model_validate_json(evidence.read_text(encoding="utf-8")))


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
    """
    return str(job["metrics"].get("status") or "ERROR")


def badge(status: str) -> str:
    """
    Decorate a status for a table cell.
    """
    return {"MATCH": "✅ MATCH", "MISMATCH": "❌ MISMATCH", "ESCALATED": "⚠️ ESCALATED"}.get(
        status, f"⛔ {status}"
    )


### Pages


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
    cols[4].metric(
        "Claude, API-equivalent",
        f"${sum(u['cost_usd_equivalent'] for u in usage):.2f}",
        help="What the calls would cost at API prices. Nothing is billed: LANSH runs on a subscription.",
    )
    estate = data["estate"]
    if estate:
        st.subheader("Waves")
        for wave in estate["waves"]:
            cells = [f"{j} {badge(statuses.get(j, '—'))}" for j in wave["job_ids"]]
            cut = all(log.passed(j, Gate.H5) for j in wave["job_ids"] if j in jobs)
            st.write(
                f"**Wave {wave['number']}** {'(cut over)' if cut else ''}: " + " · ".join(cells)
            )
        dot = ["digraph { rankdir=LR; node [shape=box, style=rounded];"]
        for wave in estate["waves"]:
            for j in wave["job_ids"]:
                colour = {"MATCH": "palegreen", "MISMATCH": "lightpink"}.get(
                    statuses.get(j, ""), "lightgrey"
                )
                dot.append(f'"{j}" [style="rounded,filled", fillcolor={colour}];')
        for e in estate["edges"]:
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
        st.dataframe(gate_rows(ev.get("gates", [])), hide_index=True, width="stretch")
    with tabs[8]:
        st.markdown(v["markdown"], unsafe_allow_html=False)


def gate_rows(gates: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Tabulate gate decisions for display.
    """
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
            st.subheader("Projection onto the client's 1,600 jobs")
            st.dataframe(
                pd.DataFrame(card["business_case"]["rows"]),
                hide_index=True,
                width="stretch",
            )
            for note in card["business_case"].get("notes", []):
                st.caption(note)
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
    people = sum(d["reviewer"].startswith("person:") for d in decisions)
    st.write(
        f"{len(decisions)} gate decisions, {people} by people, {len(decisions) - people} by agents."
    )
    st.dataframe(gate_rows(decisions), hide_index=True, width="stretch")
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
    page = st.sidebar.radio("Page", ["Estate", "Job", "Scorecard", "Audit"])
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
