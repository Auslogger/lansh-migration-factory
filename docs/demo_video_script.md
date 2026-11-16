# LANSH demo video: recording script (3:00 max)

One screen recording of the LANSH Control Tower plus one terminal clip, with a voice-over.
The voice-over is about 410 words, which is a calm 140 words a minute. **Hard stop at 3:00.**

---

## A. Before recording (once, about 15 minutes)

Do this on the Mac that has Java 21 (the setup in `README.md`).

### A1. Make a real sign-off to film (this is clip D)

1. Turn on Do Not Disturb. Close Slack, mail and everything else.
2. Open Terminal and set the font to 18 pt (Terminal → Settings → Profiles → Text).
3. `cd` into the repo.
4. **Start a screen recording now:** Cmd+Shift+5 → *Record Selected Portion* → draw a box
   around the Terminal window → *Record*.
5. Run this, putting your real name in place of `Your Name`:

   ```bash
   uv run lansh run-job T04 --run video --mode replay --reviewer "person:Your Name" --interactive
   ```

6. Answer each prompt as follows. **Read each prompt for at least 20 seconds before you
   answer.** A faster approval is flagged in the log as "fast", and the reading is real review.
   You'll cut the waiting out in editing.

   | Prompt | Type | Then at `Reason:` / `reason:` type |
   |---|---|---|
   | `=== H1 for T04 ===` … `Approve? [y/N]` | `y` | `Lineage checked against the legacy code and sqlglot.` |
   | `--- suspected defect T04-D1: Payment/reserve join fan-out…` `decision: [r]eproduce…` | `r` | `Finance reports paid-to-date this way today. Reproduce for cut-over, fix later by change request.` |
   | `--- suspected defect T04-D2` / `D3` / `D4` | `r` | `Reproduce the legacy behaviour at cut-over.` |
   | `=== H2 for T04 ===` `Approve? [y/N]` | `y` | `Contract exact on every column; defects decided.` |
   | Each later `Approve? [y/N]` (H3, H4, H5) | `y` | One sentence on what you checked |

7. Wait for the last line, `T04: MATCH (run video)`. Stop the recording (the stop button in the
   menu bar). Rename the file `clip-D-terminal.mov`.

If the run stops with a missing recorded answer, run the same command again with
`--mode auto` instead of `--mode replay`. That calls Claude live for the missing answers (it
uses subscription quota).

If the team has already done plan step 5.3 (the person-signed showcase run), you can skip A1.
Film clip D during that run instead and use that run for the Audit shot (H2).

### A2. Set up the Control Tower

1. In a second Terminal tab, run `uv run lansh ui`. It opens <http://localhost:8501>.
2. Use Chrome in full screen (Ctrl+Cmd+F) at 1920×1080. Set the browser zoom to **80%**
   (Cmd+−) so all nine tabs and the tables fit.
3. Click Streamlit's **⋮** menu (top right) → *Settings* → *Theme: Light*.
4. Check that the sidebar's **Run** list shows `showcase`, `showcase/held-out`,
   `showcase/learning` and `video`.
5. Rehearse every click in section B once, with a stopwatch.

### A3. How to record

- Record the screen **silently**, one clip per segment (B1 to B9). Use Cmd+Shift+5 →
  *Record Entire Screen*.
- Then record the **voice-over in one take** with a headset mic, reading section B's "Say"
  lines against a stopwatch. One person reads, or split it: speaker 1 takes B1–B4, speaker 2
  takes B5–B9.
- Edit in iMovie, CapCut or DaVinci Resolve: lay the voice on the timeline, then trim each
  clip to its slot. **Export at 1080p, and check the length is 3:00 or less.**
- Move the mouse slowly. Hover the pointer over the thing being talked about.

---

## B. The script

Each segment gives its time slot, the exact clicks, what's on screen, and the words to say.
Unless a step says otherwise, the run is **`showcase`**.

### B1 · 0:00–0:15 · The hook

**Clicks:**
1. Sidebar → **Run** `showcase` → **Page** `Scorecard`.
2. Scroll down to **"Comparison runs: what the proof loop adds"**.
3. Keep the bar chart in view: `LANSH` 10, `oneshot_claude` 8, `oneshot_claude+heal` 10,
   `sqlglot_only` 0.

**Say:**
> "AI can translate legacy code. We gave Claude our ten legacy jobs, one shot each. All ten ran. Eight matched. Two ran without a single error and were still wrong, on 805 rows. Only a record-by-record check catches that."

### B2 · 0:15–0:35 · The factory and the estate

**Clicks:**
1. Sidebar → **Page** `Estate`.
2. Hover the five tiles at the top: `Jobs 10`, `Record-for-record MATCH 10`.
3. Scroll to **Waves** (Wave 1 to Wave 5), then the green dependency graph.
4. Scroll to the **Jobs** table and hover the `legacy` column (`.sql` and `.sas` files).

**On-screen text (add in the editor, bottom of the frame, B2 only):** *Synthetic data only.
Agents' answers were recorded live in the estate run and are replayed here.*

**Say:**
> "This is LANSH, a reconciliation-first migration factory. Ten SQL Server and SAS jobs from a synthetic Irish insurer, migrated to PySpark on Delta, in five waves by dependency. All ten match the legacy output record for record. Every job passes five stages, Discover, Design, Generate, Reconcile, Operate, and a gate after each."

### B3 · 0:35–1:15 · One job: the claims summary

**Clicks:**
1. Sidebar → **Page** `Job`. **Job** is already `T04`.
2. Tab **Code** (0:35–0:45): legacy T-SQL on the left, PySpark on the right. In the right pane,
   scroll to the `#money` block and hover a line ending in `# LANSH-DEFECT: T04-D1`.
3. Tab **Traps** (0:45–0:53): hover rows `TSQL-01`, `TSQL-02` (line 73) and `TSQL-05`
   (line 136).
4. Tab **Lineage** (0:53–1:00): hover the `sqlglot agrees` column.
5. Tab **Defects** (1:00–1:15): hover **T04-D1 Payment/reserve join fan-out inflates
   total_paid and incurred** and its line `Impact on the legacy output: 289 rows,
   1288029.36 in total_paid`.

**Say:**
> "One job: the open-claims summary. Legacy T-SQL on the left, the PySpark LANSH wrote on the right."
>
> "Discover found fifteen traps, places where SQL Server and Spark disagree, like case-insensitive comparison and NULL concatenation, each pinned to its line."
>
> "It mapped column-level lineage and cross-checked it with sqlglot."
>
> "And it found the bug we planted: payments counted twice, overstating paid-to-date by one point two nine million euro on 289 claims. LANSH doesn't silently fix it. It reproduces it, marks it in the code, and asks a person."

### B4 · 1:15–1:35 · A person decides (terminal clip D)

**Clip:** `clip-D-terminal.mov`, cut to three moments:
1. The `--- suspected defect T04-D1 …` prompt, with its impact line (about 8 s).
2. Typing `r` and the reason (about 6 s, speed it up 2× if needed).
3. `=== H2 for T04 ===`, then `y` and the reason (about 6 s).

**Say:**
> "Every stage stops at a gate. Here a person decides: reproduce it now, so finance's numbers don't move at cut-over, and fix it later by change request. The decision, with a name and a reason, goes into a hash-chained log."

### B5 · 1:35–1:55 · The proof

**Clicks:**
1. Back in the browser, still on **Job** `T04`, open the **Reconciliation** tab.
2. Hover the first block, `rpt.claims_summary (sandbox): ✅ MATCH`, then the line
   `Rows 823 vs 823 · matched 823 · content hash identical`.
3. Hover the totals table (`legacy` and `candidate` columns side by side).
4. Scroll to the second block, `rpt.claims_summary (Delta lakehouse): ✅ MATCH`.

**Say:**
> "The proof: schema, counts, totals, then a full outer join on the key and every column compared. 823 of 823 rows match, content hash identical. Then it runs again on the Delta lakehouse, fed by its upstream migrated jobs, and matches again."

### B6 · 1:55–2:15 · Healing a wrong translation

**Clicks:**
1. Sidebar → **Page** `Scorecard`.
2. Scroll to **"The heal loop on the one-shot translations that failed"**.
3. Click the expander **`S04: MATCH after 1 attempt(s)`**.
4. Hover `score before` `[0, 0, 0, 719]`, then `status after` `MATCH`. Then hover the
   `diagnosis` cell (its text begins "tier (654 rows, all 'MEDIUM' vs 'MEDI')").

**Say:**
> "When a translation is wrong, LANSH heals it. One-shot Claude's risk-scoring job was wrong on 719 rows, mostly MEDIUM where SAS stores MEDI. The fixer diagnosed SAS's fixed text length, patched it, and it matched in one attempt."

### B7 · 2:15–2:40 · Held-out jobs and the business case

**Clicks:**
1. Sidebar → **Run** `showcase/held-out` → **Page** `Estate`. In the **Jobs** table, hover
   `X1 ⚠️ ESCALATED`, then `X2 ✅ MATCH` (2:15–2:22).
2. Sidebar → **Run** `showcase` → **Page** `Scorecard`.
3. Scroll to **"Business case: the client's 1,600 jobs (a projection)"**.
4. In the first table, hover the `manual baseline` row: `4229` person-hours.
5. In the second table, hover the row `30%` / `30`: `2070` person-hours.

**Say:**
> "We also tested on two sealed jobs that an isolated agent wrote. On the first run one matched, and the other was stopped by a failing test and escalated, never shipped. By hand, a job took us 2.6 hours. For the client's 1,600 jobs that's 4,200 person-hours. With LANSH it's about 2,100 at a 30% escalation rate. That rate is an assumption, so we show it as a range."

### B8 · 2:40–2:55 · Responsible AI

**Clicks:**
1. Still on **Scorecard**, scroll to **"Bias: S04's legacy risk tiers by age band"**. Hover
   `under 25` → `14.3` (2:40–2:47).
2. Sidebar → **Run** `video` → **Page** `Audit`. Hover the green box **"The gate log is
   intact: … each chained to the one before."** and the line **"… gate decisions, … by
   people, 0 by agents."**

**Say:**
> "Responsible AI: the legacy risk score rates under-25s HIGH almost three times as often as other ages. LANSH reproduces it and flags it for a person. Every sign-off sits in a verified hash chain."

### B9 · 2:55–3:00 · Close

**Screen:** a title card, white text on black: **LANSH: the proof is the product**, and under
it the GitHub repo URL (once the repo is public, plan step 5.14).

**Say:**
> "Translation is the easy part. The proof is the product."

---

## C. Final checks before you upload

- [ ] Length is **3:00 or less**. If it's long, cut words from B3 and B7 first, never from
      B1, B5 or B9.
- [ ] Every number you said is on screen at the moment you said it: 805, 10, 823,
      1.29 million, 289, 719, 2.6 hours, 4,200, 2,100, under-25s.
- [ ] No agent approval is presented as a person's. The Audit shot uses run `video` (or the
      5.3 run), never `showcase`, which reads "0 by people".
- [ ] The B2 caption about synthetic data and replayed answers is visible.
- [ ] No passwords, `.env`, email or notifications appear in any frame.
- [ ] Upload to YouTube (unlisted), OneDrive and Google Drive (plan step 5.10).
