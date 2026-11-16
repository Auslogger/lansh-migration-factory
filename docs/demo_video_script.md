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

If presenting without editing, allow the full replay time in addition to the narration.
The other screens use the published verified results. The human-review screen explicitly
shows the completed review of the published run, separately from this new replay.

## 0:00–0:25 · Put a financial consequence on screen

**Action**

Open [the guided demo](http://localhost:8501). On **The risk**, let the €1,288,029.36 overstatement and 289 affected claims register.
Turn on **Show one affected claim**. Point from **Payments in the ledger** to
**Legacy report says**. Keep this concrete example visible while speaking.

Reference files: [claims-report SQL](../estate/tsql/T04_usp_build_claims_summary.sql#L103) and [the measured defect report](../runs/showcase/T04/evidence.md#suspected-legacy-defects).

**What I say**

> "A migration can run successfully and still change an insurer’s financial numbers. This claims report contains a bug we deliberately planted. Joining payments to reserve rows counts some payments twice. Here is one affected claim. Across the report, the overstatement is almost 1.29 million euro. LANSH exposes that risk before anyone approves the migration."

## 0:25–0:50 · Show the system doing the work

**Action**

Click **Next: The translation**. Show the lineage, trap-finding and test counts, then the
SQL and generated PySpark side by side. Point to the marked join. Click **Replay the
migration now**. Record the real run through to its **MATCH** completion message and
shorten the idle wait as described above.

Source files shown side by side: [original SQL](../estate/tsql/T04_usp_build_claims_summary.sql#L103) and [generated PySpark](../runs/showcase/T04/jobs/t04.py#L75).

**What I say**

> "LANSH understands the job before translating it. It traces the columns, tests risky language behaviours and blocks unjustified constants that could fake a match. Here is the original SQL beside its PySpark translation. The inherited bug is marked explicitly. Now I’m replaying the migration through the actual factory using recorded model answers."

## 0:50–1:20 · Make the proof unmistakable

**Action**

After the replay completes, click **Next: The proof**. Show **823 / 823** matched rows,
**0** unexplained row differences and **12 / 12** passing tests. Show the isolated-execution and Delta checks together, then the green result confirming
both checks passed. Leave the optional fingerprint details closed.

Reference file: [T04 reconciliation report](../runs/showcase/T04/recon/rpt.claims_summary.md). The screen displays these results directly.

**What I say**

> "The job has finished, but successful execution is only the beginning. LANSH checks the schema, counts, totals and every column of every claim. All 823 rows match, with an identical output fingerprint. All twelve trap tests pass. Then it writes to the Delta lakehouse and reconciles again. The financial behaviour is preserved, including the bug we have made visible."

## 1:20–1:50 · Show who remains in control

**Action**

Click **Next: The human decision**. Show the recorded **Reproduce** decision and the named
team review. Turn on **Show the five review stages**, then **Show the bias check**.
Point to **14.3%** versus **5.3%**. Keep the privacy caption visible.

Reference files: [human review record](human_reviews.md) and [bias figures in the scorecard](../runs/showcase/scorecard.md#bias-s04s-legacy-risk-tiers).

**What I say**

> "An AI should not decide which financial rules to change. The reviewed decision here preserves the existing calculation for cut-over, with correction handled separately. People reviewed the evidence across all five stages. Oversight also includes bias: the inherited risk model rates younger customers HIGH more often. LANSH surfaces that pattern for review. Our data is synthetic, and the model agents have no tools."

## 1:50–2:20 · Prove why the extra machinery matters

**Action**

Click **Next: The repair**. Pause on the **719** differing rows from the separate one-shot
comparison. Turn on **Show the repair** to reveal **0** differences and **MATCH after
1 repair attempt**. Keep the before and after visible together. Do not open the patch details.

Source files: [original SAS risk-scoring job](../estate/sas/S04_risk_scoring.sas) and [the repaired PySpark job](../runs/showcase/benchmark/oneshot_claude+heal/S04/attempts/attempt-1/jobs/s04.py).

**What I say**

> "Here is why translation alone is not enough. In our comparison, one-shot Claude ran the risk-scoring job without an error but changed 719 rows. It missed SAS’s text-length and rounding behaviour. LANSH’s reconciliation caught the differences. Its repair loop diagnosed the causes, patched the translation and checked it again. One attempt later, the output matched. This is a recorded repair, not a staged failure."

## 2:20–2:55 · Close the technical and business case

**Action**

Click **Next: The outcome**. Show the ten matching jobs and the comparison chart, with
LANSH at ten, one-shot Claude at eight and sqlglot at zero. Scroll once to the manual-effort
projection. Keep its assumptions visible, then finish on the held-out result below it.

Reference files: [results and business-case scorecard](../runs/showcase/scorecard.md), [manual timesheet](../baseline/timesheet.csv) and [Azure architecture](architecture.md).

**What I say**

> "Across the estate, LANSH matched all ten SQL Server and SAS jobs first time, proving over 165,000 rows. One-shot Claude matched eight. Our manual baseline averaged 2.6 hours per job. The labelled projection roughly halves person-hours for 1,600 jobs. We also tested two sealed jobs: one matched immediately, while a failing test stopped the other from shipping. After the learning fixes, both matched. The same PySpark and Delta design maps onto Azure Databricks."

## 2:55–3:00 · Finish on the product promise

**Action**

Hold on **The proof travels with the migration**. Add the repository URL beneath it in the edit.
Do not navigate to another page.

Use [this repository URL](https://github.com/Auslogger/Agentic-Data-Platform-Modernisation) for the closing overlay.

**What I say**

> "LANSH makes migration a provable change, with people in control."

## Recording checks

- Every scene shows a consequence, transformation, verification or decision.
- Start and completion of the replay come from the same actual execution. Its idle wait is
  visibly shortened in the edited video.
- The planted bug, recorded repair, completed after-run reviews and business projection
  retain their labels. No new approval is implied by navigating the demo.
- Keep the numbers readable. Leave the repair details and full evidence tables closed.
- Export at 1080p and check the final video is no longer than three minutes.
