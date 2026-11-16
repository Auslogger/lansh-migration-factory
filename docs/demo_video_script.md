# LANSH demo: the proof travels with the migration

## Before recording

Run `LANSH_DEMO_RUNS=1 uv run lansh ui` and open [http://localhost:8501](http://localhost:8501).
The **Demo** page opens automatically. Use full screen at a readable zoom and start on
**The risk**. The **Next** button moves through six scenes without sidebar navigation.

Record the screen and voice separately. In scene 2, actually press **Replay the migration
now** and let it finish. It usually takes about 75 seconds. Keep the click, a short portion
of the wait, and the completion message in the edit. Use an **Offline replay · wait
shortened** caption over the cut. Recorded model answers drive a fresh pipeline execution;
this does not make a new live model call. Do not manufacture progress or a completion result.

* [ ] If presenting without editing, allow the full replay time in addition to the narration.
  The other screens use the published verified results. The human-review screen explicitly
  shows the completed review of the published run, separately from this new replay.

## How to read this script

Each scene is a table: do the **🎬 ACTION** in the left column, then say the **🎤 SCRIPT**
in the right column. Rows marked *(silent)* have no narration.

---

## ⏱ 0:00–0:25 · The risk

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Open [the guided demo](http://localhost:8501) on **The risk** | "Dear EXL Judges, we are team LANSH, presenting our solution for Challenge 3: agentic data platform modernisation. A migration can run successfully and still change an insurer's financial numbers. This claims report contains a bug we deliberately planted. Joining payments to reserve rows counts some payments twice." |
| **2** | Turn on **Show one affected claim** | "Here is one affected claim. Across the report, the overstatement is almost 1.29 million euro. LANSH exposes that risk before anyone approves the migration." |

Refs: [claims-report SQL](../estate/tsql/T04_usp_build_claims_summary.sql#L103) · [defect report](../runs/showcase/T04/evidence.md#suspected-legacy-defects)

---

## ⏱ 0:25–0:50 · The translation

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Click **Next: The translation** | "LANSH understands the job before translating it. It traces the columns, tests risky language behaviours and blocks unjustified constants that could fake a match. Here is the original SQL beside its PySpark translation. The inherited bug is marked explicitly." |
| **2** | Click **Replay the migration now**, wait for **MATCH** | "Now I'm replaying the migration through the actual factory using recorded model answers." *(cut the idle wait, caption **Offline replay · wait shortened**)* |

Refs: [original SQL](../estate/tsql/T04_usp_build_claims_summary.sql#L103) · [generated PySpark](../runs/showcase/T04/jobs/t04.py#L75)

---

## ⏱ 0:50–1:20 · The proof

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Click **Next: The proof** | "The job has finished, but successful execution is only the beginning. LANSH checks the schema, counts, totals and every column of every claim. All 823 rows match, with an identical output fingerprint. All twelve trap tests pass. Then it writes to the Delta lakehouse and reconciles again. The financial behaviour is preserved, including the bug we have made visible." |

Refs: [T04 reconciliation report](../runs/showcase/T04/recon/rpt.claims_summary.md)

---

## ⏱ 1:20–1:50 · The human decision — CHARLES

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Click **Next: The human decision** | "An AI should not decide which financial rules to change. The reviewed decision here preserves the existing calculation for cut-over, with correction handled separately." |
| **2** | Turn on **Show the five review stages** | "People reviewed the evidence across all five stages." |
| **3** | Turn on **Show the bias check** | "Oversight also includes bias: the inherited risk model rates younger customers HIGH more often. LANSH surfaces that pattern for review. Our data is synthetic, and the model agents have no tools." |

Refs: [human review record](human_reviews.md) · [bias figures](../runs/showcase/scorecard.md#bias-s04s-legacy-risk-tiers)

---

## ⏱ 1:50–2:20 · The repair — CHARLES

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Click **Next: The repair** | "Here is why translation alone is not enough. In our comparison, one-shot Claude ran the risk-scoring job without an error but changed 719 rows. It missed SAS's text-length and rounding behaviour. LANSH's reconciliation caught the differences." |
| **2** | Turn on **Show the repair** | "Its repair loop diagnosed the causes, patched the translation and checked it again. One attempt later, the output matched. This is a recorded repair, not a staged failure." |

Refs: [original SAS job](../estate/sas/S04_risk_scoring.sas) · [repaired PySpark](../runs/showcase/benchmark/oneshot_claude+heal/S04/attempts/attempt-1/jobs/s04.py)

---

## ⏱ 2:20–2:55 · The outcome — VANSH

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Click **Next: The outcome** | "Across the estate, LANSH matched all ten SQL Server and SAS jobs first time, proving over 165,000 rows. One-shot Claude matched eight." |
| **2** | Scroll once to the manual-effort projection | "Our manual baseline averaged 2.6 hours per job. The labelled projection roughly halves person-hours for 1,600 jobs. We also tested two sealed jobs: one matched immediately, while a failing test stopped the other from shipping. After the learning fixes, both matched. The same PySpark and Delta design maps onto Azure Databricks." |

Refs: [scorecard](../runs/showcase/scorecard.md) · [manual timesheet](../baseline/timesheet.csv) · [Azure architecture](architecture.md)

---

## ⏱ 2:55–3:00 · Close — VANSH

| # | 🎬 ACTION (do this) | 🎤 SCRIPT (say this) |
|:-:|---|---|
| **1** | Hold on **The proof travels with the migration** *(add [repo URL](https://github.com/Auslogger/Agentic-Data-Platform-Modernisation) overlay in edit)* | "LANSH makes migration a provable change, with people in control. Thank you for the opportunity, and thank you for listening." |

## Recording checks

- Every scene shows a consequence, transformation, verification or decision.
- Start and completion of the replay come from the same actual execution. Its idle wait is
  visibly shortened in the edited video.
- The planted bug, recorded repair, completed after-run reviews and business projection
  retain their labels. No new approval is implied by navigating the demo.
- Keep the numbers readable. Leave the repair details and full evidence tables closed.
- Export at 1080p and check the final video is no longer than three minutes.
