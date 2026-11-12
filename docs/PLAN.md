# LANSH: implementation plan

**Team LANSH · EXL × Trinity Data & AI Hackathon 2026 · Challenge 03: Agentic data platform modernisation**

| | |
|---|---|
| Version | 5 (12 Nov 2026): Phase 5 revised after a critical review (Appendix G) and an independent review of it (G.4) |
| Status | **Phases 0–4 built; G1–G4 accepted by the agent (overnight run); G5 waits on the team.** A critical review of the whole repo against the brief and rubric (Appendix G) found the factory and its evidence ahead of the brief, but not the submission: the pack doesn't exist yet, a clone can't be set up, the business case's headline is an assumption, and no person has signed a gate. Phase 5 (§4) is rewritten around those gaps, in priority order. The defaults in §2.2 stand. |

This is the implementation plan. It covers **what** we build and in **what order**, with a review gate between phases. It doesn't schedule time or assign people. Everyone working on the repo follows it, AI coding agents included. When reality differs from the plan, update the plan and the progress log (Appendix E).

---

## 1. What we're building

**LANSH** is a reconciliation-first agentic migration factory. It takes a realistic legacy estate of insurance jobs (T-SQL on SQL Server 2022, SAS on SAS OnDemand) and migrates them to PySpark on a Delta lakehouse.

For every job, LANSH **proves the new output matches the legacy output record for record**: counts, totals and every row, **bugs included**. The legacy code contains mistakes we planted on purpose. LANSH reproduces each one exactly and flags it for a human decision. A human signs off at each of the five stages the brief describes.

**How it differs from what already exists** (details in §9.5):
- EXL's Code Harbor already translates SAS to PySpark with validation.
- Databricks' Lakebridge already reconciles migrated outputs.
- LANSH is the **proof-and-governance layer** that can sit around any translator, including those. It adds bug-for-bug reproduction with a defect register, a library of SAS and T-SQL traps tied to the shape of reconciliation failures, and evidence-backed human gates.
- We measure how much the proof loop adds by running two simpler approaches through the same reconciliation:
  - the sqlglot translation on its own
  - a one-shot Claude translation with no trap knowledge and no repair loop

**How it maps to the rubric:**
- **Technical (25%):** objective, checkable proof, with a reconciliation report per job.
- **Business Impact (30%):** the defect register, plus a measured comparison with a manual migration and a projection onto the client's 1,600 jobs (§9).
- **Innovation (20%):** the proof loop, with measured uplift over simpler approaches.
- **Responsible AI (15%):** gates, bias and privacy controls, sandboxing (§10).

---

## 2. Decisions

### 2.1 Locked

| # | Decision |
|---|---|
| L1 | We build the legacy estate ourselves: T-SQL and SAS jobs on synthetic data (§3). EXL's sample jobs are added if they arrive. |
| L2 | The target is PySpark 4.2 with Delta Lake in bronze, silver and gold layers (§6.4). It runs locally, and the code sticks to APIs that run on Azure Databricks. The Azure target state is described in §6.2. |
| L3 | **Claude runs on our existing subscription** through Claude Code's non-interactive mode (`claude -p`). There's no API key and no API bill (§8.2). Development also uses Claude Code. We declare both. |
| L4 | **Java 21 everywhere**: Spark, Delta, saspy and CI. |
| L5 | The repo stays private until submission, then goes public. |
| L6 | The demo video goes on unlisted YouTube, OneDrive and Google Drive, with all three links in the submission. |
| L7 | The format of the deck, diagram and Responsible AI note is planned separately. This plan produces their source material. |
| L8 | "Humans review at each gate" applies twice: in the product (five stage gates, §6.3) and in our build (gates G0–G6, §4). |
| L9 | The team and the product are both called **LANSH**. The Python package and the command are `lansh`. |
| L10 | **The legacy code contains deliberate mistakes.** The migration reproduces each one exactly, and LANSH flags each one for a human decision (§6.5 principle 6, Appendix B). |
| L11 | **A manual baseline is part of the evidence.** Two jobs are migrated by hand, without AI, and timed (§9.1). |

### 2.2 Defaults adopted (change any at any time)

| # | Decision | Default |
|---|---|---|
| D2 | What git tracks in `docs/` | Track `docs/` but ignore `docs/*.pptx`. The EXL deck is never committed. |
| D3 | Licence | None until the terms and conditions say who owns the work. A public repo without a licence can be viewed but not reused. |
| D4 | Model for the agents | Opus 5.5 (`--model opus`), with effort set per agent. Sonnet 5.5 can take bulk steps if usage limits bite. |
| D5 | Live-call cap | At most 150 live Claude calls per full run. Every answer is cached, so the same call never runs twice. |
| D6 | SAS route | **saspy, which is verified to connect.** The paste route (§7.3) is the fallback. |
| D8 | Estate size | Tier 1: 10 development jobs (7 T-SQL, 3 SAS) plus 2 sealed held-out T-SQL jobs. Tier 2 brings it to 15. |
| D9 | Merging | Work merges only when `make check` passes. Each gate reviews the combined result and a demo. |

---

## 3. Data and legacy code: generate or reuse?

**We generate the data and write the legacy jobs ourselves. Public sources are used only to make the data realistic.** The brief allows this explicitly. Slide 8 offers "self-built T-SQL jobs on synthetic data" as a starter option, and slides 13 and 16 say "public or synthetic data only; never personal data".

**Why we generate rather than download:**
- No public dataset has a whole insurer's linked tables for ETL jobs to run on.
- Reconciliation needs edge cases and bugs planted in places we know.
- Synthetic data raises no licence or personal-data questions.
- A seeded generator produces identical data on every machine.

| Source | What it is | Our use |
|---|---|---|
| [Central Bank of Ireland NCID private motor reports](https://www.centralbank.ie/statistics/data-and-analysis/national-claims-information-database/ncid-private-motor-insurance) | Aggregate Irish motor statistics, with an XLSX annex | **Tier 2.** Calibrate the generator's distributions from aggregates only, and cite the source. Figures come from the official annex. |
| [freMTPL2](https://dutangc.github.io/CASdatasets/reference/freMTPL.html) | Anonymised real French motor policies, GPL-2.0 per the [OpenML mirror](https://api.openml.org/d/43593) | **Not used.** It's real policyholder data with no dates, payments or reserves, and it's GPL. |
| [CAS Loss Reserve Database](https://www.casact.org/article/more-data-now-available-cas-sponsored-research-including-updated-schedule-p-data) | US loss triangles; terms not confirmed | **Not used.** |
| [Microsoft WideWorldImporters](https://learn.microsoft.com/en-us/sql/samples/wide-world-importers-what-is) | MIT-licensed sample for a fictional wholesaler, with an SSIS-based ETL | **Tier 3.** A possible held-out job written by a third party. |
| EXL sample jobs | Offered on slide 8; not received | **Use if they arrive.** Ask again at the next EXL session. |

**Generator rules:**
- Names and addresses are fictional, from Faker's Irish locale (`en_IE`).
- Emails use the reserved `.example` domain, and there are no phone numbers.
- No real records are copied.
- The README says the data is 100% synthetic and records the seed.

---

## 4. Implementation sequence

Phases run in order, and each ends at a **⛔ gate**: a review against the packet in Appendix C. Within a phase, steps marked *independent* can run in parallel.

| Gate | What's reviewed |
|---|---|
| G0 Plan | This plan and the defaults (§2.2) |
| G1 Foundations | Contracts, `make check`, spike results |
| G2 Ground truth | Realism of the legacy jobs, planted bugs, data, golden manifests and their re-run, held-out seal |
| G3 Vertical slice | T04 through all five stages, its evidence report, Claude usage per job; confirm D4 and D5 |
| G4 Estate reconciled | Scorecard, defect register and decisions, escalations, comparison runs, manual baseline, held-out results |
| G5 Release candidate | Setup from the README on a clean checkout; the demo path |
| G6 Publish | Pre-publication checklist (§17) |

Scope comes in priority order. Tier 1 (§13) is finished before Tier 2 work starts.

### Phase 0: Foundations

**0.1 Environment.** Every development machine follows the setup guide, which is the Setup section of `README.md`:
- Java 21
- uv and the Python packages
- the Claude Code CLI
- OrbStack with SQL Server, on the machine that captures golden outputs
- the SAS checks and saspy
- the smoke test

*Status:* done on the first machine. All five smoke-test checks pass, SQL Server 2022 runs under emulation, and saspy reaches SAS OnDemand.

⛔ **G0: Plan.**

**0.2 Scaffold the repository.**
- Rename the package to `lansh` and add the `lansh` command.
- Keep `pandas>=2.3,<3` (already pinned).
- Set `JAVA_HOME` to Java 21 in the Makefile.
- Add ruff, pytest and `make check`.
- Add `AGENTS.md`, a condensed §12, plus a `CLAUDE.md` that loads it.
- Add `AI_USAGE.md`, `THIRD_PARTY.md`, `.env.example`, the setup guide in `README.md` and `scripts/smoke_test.py`.
- Apply D2, create the private GitHub repo `lansh`, make the first commit and push.

*Done when:* `make check` passes.

**0.3 Contracts.** These are the shared Pydantic models every part of LANSH uses (§8.1), plus the `estate/jobs.yaml` format.

*Done when:* the models round-trip through JSON in tests. They're frozen after G1.

**0.4 Spikes** (*independent*), each with a decided fallback:
- **SQL Server.** Write `compose.yaml`, which reads `MSSQL_SA_PASSWORD` from `.env` so the password can't drift again, and `make legacy-up`.
- **SAS.** A saspy round trip of a small dataset, exported with explicit formats (§7.3).
- **Claude backend.** One structured `claude -p` call with the full flag set (§8.2), recorded and then replayed offline.
- **Spark reconciliation.** Find planted case, space and NULL differences between two small tables, using collations in the comparison and storing plain strings.

⛔ **G1: Foundations.**

### Phase 1: Legacy estate and ground truth

**1.1 Generate the synthetic insurer** (§7.1).
- 9 seeded tables, each with a `_row_seq` column that records the original row order.
- Tags for personal and protected-attribute columns.
- The planted edge cases, plus the conditions each planted bug needs to show up, with a test for each.
- Output in Parquet and CSV, with a data dictionary.

*Done when:* two runs produce identical hashes.

**1.2 Write the T-SQL legacy jobs** (§7.2), starting with **T04**, the vertical-slice job.
- Plant the traps (Appendix A) and the bugs (Appendix B).
- Write one check query for each *semantic* trap and each bug, proving it changes the result.

*Done when:* every job runs cleanly and every check passes.

**1.3 Freeze T01–T03.** The SAS jobs read their outputs, so these must be final before any SAS output is captured.

**1.4 Write the SAS legacy jobs**: S01, S03 and S04, with their traps, bugs and check queries.

**1.5 Write the sealed held-out jobs** (§7.4), *independent*. An isolated agent writes X1 and X2, which are T-SQL. X3, in SAS, is Tier 2. The folder is then sealed with a hash.

**1.6 Capture the golden outputs** (§7.3).
- Run every job on its real engine, in dependency order.
- Store each output raw and as typed Parquet, with a manifest.
- `make legacy-verify` must reproduce the T-SQL hashes exactly.

**1.7 Write the answer key.** Record each job's planted traps and bugs in `estate/labels/`. Only the evaluation code reads it.

⛔ **G2: Ground truth.**

### Phase 2: Vertical slice, T04 through all five stages

In this phase, every stage is built in a minimal but real form, and T04 is taken all the way through. Phase 3 deepens each stage. Steps 2.1–2.3 only need the contracts, so they can start as soon as G1 passes.

**2.1 Reconciliation engine** (§8.6). `lansh reconcile --job ID --candidate FILE` also checks hand-written jobs.

*Done when:* unit tests catch every kind of difference, and datacompy agrees.

**2.2 Claude gateway** (§8.2).

*Done when:* tests pass offline from recordings, and one live call works.

**2.3 Gate log** (§8.9).

*Done when:* illegal transitions are refused and decisions are recorded.

**2.4 Discover** (§8.3).
- Claude extracts the lineage, and every column it names is checked against the schemas.
- sqlglot cross-checks the simple SELECT statements.
- The trap scan runs.

*Done when:* T04's lineage matches a hand check.

**2.5 Design, minimal** (§8.4). Build T04's contract from the DDL and from profiling the golden output: keys, types, comparison policies and tags.

**2.6 Generate, with tests and guardrails** (§8.5, §8.7). The translator reproduces legacy behaviour exactly, and the guardrails (§8.5) run before any code executes.

*Done when:* T04's module runs and its tests pass.

**2.7 Heal loop** (§8.6).

*Done when:* a deliberately broken T04 heals to MATCH.

**2.8 Defect list, minimal.** Build it from `# LANSH-DEFECT` markers plus the Defect reviewer agent.

*Done when:* BUG-03 is listed.

**2.9 Operate, minimal.** Write T04 to Delta and reconcile it against its golden output.

**2.10 Wire T04 end to end** through H1–H5, producing its evidence report.

*Done when:* `lansh run-job T04` ends in MATCH, with BUG-03 reproduced and flagged.

⛔ **G3: Vertical slice.**

### Phase 3: Whole estate

**3.1 Manual baseline** (§9.1), for T05 and S01.
- It needs the golden outputs, the candidate mode from 2.1 and the job template from 2.6.
- It must be finished before whoever does it sees LANSH's version of those jobs.

**3.2 Trap cards**, *independent*. Write a card for every trap in Appendix A that a Tier 1 job contains.

**3.3 All T-SQL jobs through the factory.** Fixes must be generic and logged in `docs/learning-log.md`; job-specific code is never allowed.

*Done when:* every job reaches MATCH, or is escalated with a diagnosis.

**3.4 SAS support**, *independent*. SAS lineage, SAS trap rules and the translator's SAS mode. Then run S01, S03 and S04.

**3.5 Design for every job.** The contract agent proposes, validators check against the golden outputs, and H2 approves.

**3.6 Estate-wide Discover.** The DAG, the waves, and how tagged columns flow through to outputs.

*Done when:* the waves match §7.2.

**3.7 Defect review and register.**
- The Defect reviewer agent lists suspected bugs for each job.
- An impact query on the golden data measures the rows and amounts affected.
- Each suspected bug gets a decision at H2/H4.

*Done when:* every planted bug is reproduced, and detection is scored against the answer key.

**3.8 Tests for every job** (§8.7).

**3.9 Operate, full** (§8.8).
- Run the waves on Delta, with chained reconciliation.
- Write a schedule file per wave.
- Check SLAs.
- Export OpenLineage events.

*Done when:* `lansh operate run --all` is green.

**3.10 Comparison runs** (§9.5). Run the sqlglot draft on its own, and a one-shot Claude translation (no trap cards, no healing), through the same reconciliation for every development job.

**3.11 Freeze the factory, then run the held-out jobs once.** Report them separately.

**3.12 EXL sample jobs**, if they arrive. Write an import adapter and run them, reporting the results separately.

⛔ **G4: Estate reconciled.**

### Phase 4: Control Tower, replay and documentation

**4.1 Control Tower UI** (§8.11). Start it as soon as T04's artifacts exist.

**4.2 Showcase run.** Do one final live run of the estate from an **empty cache**, so the timings are honest. Run it on an account with enough usage headroom, and record it. `make demo` then replays it offline.

**4.3 Scorecard and business case** (§9). Every number traces back to a run artifact.

**4.4 Documentation.**
- The README.
- `docs/architecture.md`, including the Azure target state (§6.2).
- `docs/responsible-ai.md`, written from §10.
- `AI_USAGE.md` and `THIRD_PARTY.md`.

**4.5 Fresh-clone test.** Clone into an empty folder on a clean machine or user account, and follow the README exactly.

⛔ **G5: Release candidate.**

### Phase 5: Evidence, story and submission (revised after the critical review, Appendix G)

Pre-screening scores the submission pack (deck, video, the two one-page documents and the repo's README), not the factory. Phase 5 therefore spends its effort on evidence only a person can produce, on the story, and on publishing, and adds almost nothing to the factory.

- **P0:** without it the submission fails or loses heavily.
- **P1:** high value at low risk. A P1 step that changes what the video shows (5.6, 5.7) comes before the video, or is skipped.
- **P2:** finale work, on a later tag than the submitted `v1.0.0` (5.17), never mixed into the submitted version.
- *The team's* marks a step an agent mustn't do: it needs a person, or no AI at all.
- **Order:** steps are in dependency order. 5.1, 5.2 and 5.5 depend on nothing. The one-page documents and the deck (5.8, 5.9) are drafted from the start with placeholders; only their final figures wait for 5.3–5.5.
- Old step numbers: 3.1 → 5.2, 5.1 → 5.12, 5.2 → 5.10, 5.3 → 5.13, 5.4 → 5.14, 5.5 → 5.15.

**5.1 A repository that sets up from a clone (P0).** Fixes G-T1 to G-T3, G-P5 and G-R5 (Appendix G).
- **`.gitignore`:**
  - apply G5 decision 1, which publishes the Markdown deliverables;
  - also track `runs/freeze.json` (`!runs/freeze.json`): `lansh freeze` reads only that file, so a clone today gives no verdict;
  - delete the comment that says "the rest of docs/ is tracked", because the next line ignores all of it.
- **The freeze.** `lansh freeze` prints "CHANGED … config.py", because an error message's path changed after freeze 2 (the `.env` template move). Record freeze 3 with that reason, before any re-publish of the showcase, since publishing copies the freeze record:

  ```bash
  uv run lansh freeze --write --note "config.py: the .env template's path in one error message; no job's outcome depends on it"
  ```

- **`README.md`:**
  - replace it with G5's proposed README, corrected as G.4 lists (two generic fixes, not one);
  - put the video links at the top, and embed the one-page architecture diagram and one Control Tower screenshot;
  - take its business-case line from 5.4.
- **The private plan.** About 100 tracked files cite "plan §…", including the scorecard's notes, `AI_USAGE.md` and `estate/README.md`, and the proposed README says `docs/` holds the plan and the gate packets. Choose one:
  - publish `docs/PLAN.md` and `docs/gates.md` with the organiser's address removed;
  - or reword the citations a reader will follow, in those three files and the README.
- **`AGENTS.md`** is published under decision 1. Retire its "Overnight run" section first: Appendix E keeps the history.
- **Declarations:**
  - **The licence (D3) and the author email** in `pyproject.toml` (G5 decision 5).
  - **The gate wording in `AI_USAGE.md`.** The team reviewed the G1 and G2 packets on 11 Nov, and the agent recorded their acceptance overnight: say both.
  - **The manual baseline.** Describe it in the past tense, as done or not done, there and in the Responsible AI note.
  - **The commit convention.** State that commits carry no AI trailers by the team's convention, because AI use is declared in `AI_USAGE.md` instead.

*Done when:* a fresh clone of the pushed branch runs `make setup`, `make check` and `make demo` with no other step, and its `lansh freeze` reports unchanged.

**5.2 Manual baseline (P0, the team's).** This is §9.1, unchanged, for T05 and S01. It's the only measured "manual" number the business case can have (G-B2).
- **Stay unexposed.** Whoever does it finishes before seeing T05 or S01 anywhere in LANSH: the 5.3 run, the Control Tower (its Scorecard page shows one-shot S01's heal), the video or the cassettes. Anyone doing both steps does 5.2 first.
- **Report it as a lower bound,** as §9.1's fairness notes say: the people who built the estate do it, with the reconciliation harness in hand. Include its story: the minutes per phase, and any differences left at the cap.
- **What the brief requires, and what we chose.** The brief asks for neither a baseline nor a recording of one. Challenge 03 asks for record-for-record proof (slide 8); "show the time … gained versus hand-built" is Challenge 01's requirement (slide 6); and the only video is the 3-minute demo of the prototype (slide 13). The baseline is our own decision (L11), and so is its screen recording: §9.1's evidence rule, which `AI_USAGE.md` already declares. Keep the recording, unedited, as the evidence behind the numbers in the Q&A. If the team drops it, change §9.1 and `AI_USAGE.md` to match.
- **How it's presented.** A statement of minutes is enough for the deck and the README, provided it compares like with like:
  - per job, a person's minutes by hand to MATCH, or "over 3 hours, N differences left";
  - beside that, LANSH's minutes of a person's time (5.3), with its machine minutes shown apart: machine time needs no people (§9.2);
  - the protocol in one line: AI off, a 3-hour cap, and the same definition of done, a record-for-record MATCH;
  - the caveats;
  - each figure from `baseline/timesheet.csv` and the scorecard.

*Done when:* `baseline/timesheet.csv` has both jobs, each at MATCH or "over 3 hours, N differences left", with the recordings linked, and `lansh scorecard` shows the measured row first.

**5.3 The showcase run with a person's sign-offs (P0, the team's; after 5.1's freeze, and after 5.2 if the same person does both).** It fixes G-R1, G-R4 and G-T9, and feeds 5.4.
1. **Run the estate with a person deciding,** as in Appendix E ("For the team", item 4). Read each decision and give a reason in your own words.

   ```bash
   uv run lansh run --all --run showcase-live --reviewer person:<name> --interactive --mode replay
   ```

   - **Triage the 47 suspected defects** as *reproduce*, *fix after cut-over* or *not a defect*. That measures the defect reviewer's precision, which nothing measures today.
   - **Confirm or overturn the agent's "planted diagnosis" verdicts** (6 of 8 development, 2 of 2 held-out), in a copy of `runs/showcase/adjudication.json`.
2. **Before publishing, rebuild the evidence an estate run doesn't write.**
   - Why: `lansh showcase` deletes `runs/showcase/` and copies only the source run, and `lansh run --all` writes no comparison runs, scores or adjudication. Publishing straight away would lose sqlglot's 0 of 10, one-shot's 8 of 10, the 805 rows, the heal timelines, 81 of 82 and 41 of 41.
   - Scoring reads the adjudication, so copy it first:

     ```bash
     cp runs/showcase/adjudication.json runs/showcase-live/      # then record the person's verdicts in it
     uv run lansh benchmark --run showcase-live --approach sqlglot_only --approach oneshot_claude --approach oneshot_claude+heal --mode replay
     uv run lansh estate score --run showcase-live --prove      # --prove needs SQL Server
     ```

   - If the benchmark won't replay, carry `benchmark.json` and `benchmark/` over from `runs/showcase/` instead.
   - Have `lansh showcase` rewrite the run paths inside `benchmark.json`, as it already does for evidence reports. Today 16 of them point at the ignored `runs/dev-estate/`. The CLI is outside the freeze.
3. **Publish and score:**

   ```bash
   uv run lansh showcase --from showcase-live --holdout dev-holdout --learning dev-holdout-learn
   uv run lansh scorecard --run showcase --holdout showcase/held-out --learning showcase/learning
   ```

   Check that the scorecard still has every row it has today.

The held-out runs keep the agent's development approvals: they ran once, and stay as they ran. The pack says so.

**Fallback,** if the full run can't be finished: a person signs T04's five gates and its defects in a separate run. The pack then says plainly that the rest of the estate's gates are the agent's development approvals.

*Done when:*
- `lansh audit verify --run showcase` reports every gate decision as a person's;
- the scorecard keeps every comparison and scoring row;
- the person's minutes per job are measured, as the job's wall time in this run less its wall time in an agent replay (such as `runs/replay-check`). Per-gate review times won't do: defect and flow decisions carry no review time of their own, so they would miss the triage.

**5.4 Scorecard v2: measured where possible, every assumption labelled (P0; final numbers after 5.2 and 5.3).** Change `lansh scorecard` only; it's outside the freeze. It fixes G-B1 to G-B4.
- **Person minutes per job** come from 5.3's wall times, and replace the fixed 5 minutes a gate. The reviewers built the estate, so these are a lower bound for a reviewer who didn't.
- **Manual minutes** come from 5.2, shown beside the assumed cases. A job stopped at the 3-hour cap counts as at least its minutes, shown with its differences left, never as a finished migration. Today `_baseline_minutes` in `scorecard.py` sums each job's minutes and ignores `differences_left`.
- **A two-way sensitivity table:** the escalation rate (15%, 30%, 50%) against the person minutes of review per job (the measured value, 30 and 60).
  - Leave out a 0% row: it prints 98–99%, which no judge believes.
  - Mark the 50% column illustrative: the held-out first run's 1 of 2 is a sample of 2, not a rate.
- **Lead with headcount and cost:** the people needed for a 4- and a 6-month window, and the cost at a labelled, editable day rate. At the scorecard's middle case, a 4-month window needs about 21 people by hand, against about 7.6 with LANSH at 30% escalation and 30 minutes of review per job. Recompute both in v2.
- **Defect precision** from 5.3: confirmed defects out of suspected ones.
- **Tags:** every metric is tagged *measured* or *assumed*, and the deck repeats the tags.
- **Code Harbor:** don't set our projection beside EXL's measured 50%. If it's cited at all, say what each number is.

*Done when:* every business-case number in the deck, video and README is one of the scorecard's, with its tag and sources.

**5.5 Bias table (P0; depends on nothing).** Slide 13 names bias, and the gate log flags 11 protected flows "for a bias review" without anyone having looked (G-R2). A short evaluation script tabulates S04's risk tier, on its legacy output, by age band and by county. County comes from T01's customer dimension, joined on `customer_id`, and is normalised first: 108 spellings become the 26 counties. Measured for this review:
- **By age:** under-25s are HIGH-tier 14.3% of the time (n = 168), against 5.3–5.4% at ages 25–59, and MEDI 41.7%, against about 20.6%.
- **By county:** HIGH runs from about 1% to 10% across the counties with at least 40 customers. The samples are small.

The table goes into the Responsible AI note and slide 9, as context for the people who decide. LANSH reproduces the score and puts the pattern in front of them; whether an age loading is justified is a business and legal decision. It doesn't change the job.

*Done when:* the table reproduces from the committed golden outputs.

**5.6 Lineage you can see (P1, before 5.10).** Column-level lineage is one of the three agent tasks the brief names, but today it shows only as tables and JSON (G-T5).
- Each job's Lineage tab draws its column lineage as a graph (graphviz, as the Estate page already does), and the tagged-flow paths across jobs get a graph too.
- Reconciliation totals of id columns are labelled as hash totals, the audit control they are (G-T6).

*Done when:* T04's and S04's lineage graphs are readable at video resolution.

**5.7 Control Tower: a landing view (P1, before 5.10).** Change `lansh/ui/` only. The Estate page has five tiles and the DAG, but the comparison, the money and the sign-offs are pages away (G-P3). Keep it small:
- **An Overview page,** first in the menu: the headline numbers, and, per approach, the jobs that MATCH, silently differ or fail.
- **Measured impacts with units:** shown as money only when the column is money (EUR); otherwise as rows, with the column named (G-B5).

*Done when:* AppTest renders every page for every run, and a person has read the Overview page on screen.

**5.8 The one-page architecture diagram and Responsible AI note (P0; draft now, final figures after 5.3–5.5).**
- **The architecture diagram:**
  - export `docs/architecture.md`'s diagram to one page, as PDF or PNG (email readers don't render Mermaid);
  - add the agent and model at each stage, because the brief asks for "AI models";
  - add the Azure target state.
- **The Responsible AI note:**
  - **Add the prompt-injection stance (G-R3).** Agents run with `--tools ""`, so they have no files, network or shell, and legacy code is treated as untrusted input. A steered answer that makes code wrong fails reconciliation. One that leaves something out, such as a lineage edge or a defect, isn't caught deterministically; state that as a limitation (the sqlglot cross-check covers part of the lineage).
  - **Add the figures** from 5.3 (decisions by people, person minutes per job, approvals flagged as fast) and 5.5's table.
  - **Export it to one page.**

*Done when:* each is one page, and each figure matches the scorecard.

**5.9 Deck, at most 10 slides (P0; draft now, final figures after 5.4 and 5.8).** This is the deck's source material; its format is planned separately (L7). Lead every slide with its outcome in plain words. Gate ids, card ids and run names go in the speaker notes and the Q&A, not on the slides (G-P2).

| # | Slide | Content and source |
|---|---|---|
| 1 | Title | LANSH, team and Challenge 03, plus one line: "We migrate legacy T-SQL and SAS to PySpark, and prove every row." |
| 2 | The problem | 1,200 ETL jobs and 400+ SAS programs, undocumented, lineage unknown, and every output must reconcile exactly (slide 8). The hook (G-B6): one-shot Claude ran all 10 jobs without an error, yet 2 outputs had silently changed the legacy numbers, on 805 rows. It had "fixed" two legacy bugs nobody had decided to fix, and got SAS rounding wrong. |
| 3 | The approach | The proof loop: five stages, five human gates. Agents propose, deterministic checks verify, people approve. |
| 4 | Architecture | The one-page diagram (5.8): components, data flows, the agent and model at each stage, the Azure target state. |
| 5 | One job, end to end | T04: lineage, contract, then a bug we planted, labelled as planted: payments counted once per reserve type, overstating paid-to-date by €1.29M on 289 claims, measured and decided. Then the translation: MATCH on 823 of 823 rows, content hash identical. Then cut-over on Delta. |
| 6 | Results | 10 of 10 MATCH on the first translation; 165,412 rows proved; the comparison runs (0, 8, 10 and 10 of 10); held-out 1 of 2 on the first run, reported as it came out, then 2 of 2 after two generic fixes; traps found 81 of 82; planted bugs reproduced 8 of 8. |
| 7 | Business impact | Manual against LANSH, measured (5.2, 5.3). The 1,600-job projection as headcount and cost, with its sensitivity (5.4). About $1 and 5 minutes of machine time per job. 20 suspected defects with a measured impact. The documentation every job leaves behind (lineage, contract, evidence report), which slide 8 says the estate lacks (G-B8). The pilot: a first wave of about 20 jobs, with §9.4's KPIs and targets. |
| 8 | Why it's new | The five mechanisms, in plain words (G-I2). The positioning (G-I3): LANSH wraps a translator. Here it wraps a plain one-shot translator and takes it from 8 to 10 of 10; EXL's Code Harbor could be wrapped the same way. The proof loop, not the prompt, is the product (G-I1). |
| 9 | Responsible AI | Synthetic data; minimal disclosure, with `pii` masked; agents with no tools; the sandbox and the anti-hard-coding check; human gates, with 5.3's measured figures; S04's tiers by age band (5.5); limitations. |
| 10 | Next steps and declaration | A pilot on Azure (Foundry and Databricks); what we'd build next; the AI tools, as in `AI_USAGE.md`. |

*Done when:*
- there are at most 10 slides;
- every number on them comes from the scorecard, with its tag;
- the AI tools are declared;
- a person who hasn't seen LANSH can say what it does after slides 1–3.

**5.10 Demo video, at most 3 minutes (P0, the team's to record and publish; after 5.3, 5.4, 5.6 and 5.7).** Record it in replay mode along §14's video cut, saying on screen that the agents' answers were recorded live in the estate run and are replayed here. Upload it to YouTube (unlisted), OneDrive and Google Drive.

*Done when:* the video runs 3:00 or less, and each link plays in a logged-out browser.

**5.11 CI (P1, after 5.1; was Tier 2).** A GitHub Actions workflow that sets up Java 21 and uv and runs `make check` (G-T7). The Makefile's Java 21 candidates don't include the runner's JDK path, so the workflow sets `LANSH_JAVA_HOME` to the JDK that `setup-java` installs. The badge goes in the README only once the workflow is green on the public repo.

*Done when:* the workflow is green on the pushed branch.

**5.12 Bug bash (P0).** Run the demo path, fixing bugs only.

**5.13 Pre-publication checks (P0, after 5.1).** The §17 checklist, including the scan in Appendix E ("For the team", item 8).

⛔ **G6: Publish.**

**5.14 Go public (P0, the team's).** Tag the submitted version `v1.0.0` and make the repo public. Check that an anonymous clone runs `make setup` and `make demo`.

**5.15 Submit (P0, the team's).**
- **The email:** to Monika.Rawal@exlservice.com, from a Trinity address, with the subject "EXL Hackathon | LANSH | Challenge 03".
- **The links:** the repo at `v1.0.0`, the three video links, the deck, and the two one-page PDFs.
- **The AI declaration:** in the deck and in the email body.
- **A last check:** open every link logged out.

**5.16 Finale kit (for the finale, after 5.15).**
- **The talk:** a rehearsed 10-minute pitch and 5-minute live demo, in replay mode, offline, on the presenting laptop, with the Control Tower already open on `showcase`.
- **A backup:** a recording of the demo.
- **The Q&A bank:** Appendix G.3, with each answer's evidence.

**5.17 Finale extras (P2, on a later tag than `v1.0.0`, each reported as it comes out).**
- **A second reporting date** (needs SQL Server and SAS, no Claude). Every job was proved on 2025-12-31, the date its tests and any fixer saw (G-T4).
  1. Capture every job's legacy outputs at 2025-06-30 (the half-year close, and T02's first snapshot) into a folder of their own. `estate/golden/` stays immutable.
  2. Run the modules in `migrated/jobs/` unchanged with that date, and reconcile them.

  This needs evaluation code only, outside the freeze.
- **More held-out jobs.** X3 in SAS, plus up to two T-SQL jobs, written by the §7.4 protocol, sealed, and run once on the current freeze. There's no SAS held-out job today.
- **The bias probe as a factory feature.** At H2, every output fed by a `protected` column gets 5.5's table for its decision columns.
- **Databricks Free Edition** (a new external service, but free). Run one or two migrated modules unchanged on the same inputs, and compare their content hashes.
- **Failing trap tests to the fixer** (G-T8). This changes the factory, so it needs a new freeze and a learning run reported apart.

---

## 5. Requirements traceability

| Requirement (brief slide) | How we meet it |
|---|---|
| Migrate 10–15 legacy T-SQL and SAS jobs to PySpark (8) | 10 development jobs plus 2 held-out jobs in Tier 1, and up to 15 in Tier 2 |
| AI agents map column-level lineage (8) | The Claude lineage agent, checked against schemas and cross-checked with sqlglot (§8.3) |
| AI agents translate logic (8) | A deterministic draft, then the Claude translator with trap cards (§8.5) |
| AI agents generate tests (8) | The test agent, with expected values from the legacy engine (§8.7) |
| Prove outputs match legacy record for record (8) | Reconciliation of counts, totals and every record, with an evidence report per job (§8.6) |
| Every pipeline must "reconcile exactly" (8) | Exact comparison by default, with declared and approved policies only. Bugs are reproduced, never silently fixed. |
| Discover: parse code, build lineage and waves (8) | §8.3 |
| Design: bronze, silver and gold, with data contracts (8) | §6.4, §8.4 |
| Generate: PySpark and Spark SQL with tests (8) | §8.5, §8.7 |
| Reconcile: parallel-run diffs on counts, totals and records (8) | §8.6 |
| Operate: schedule, monitor SLAs, publish lineage (8) | Schedule per wave, SLA checks, OpenLineage export (§8.8) |
| Humans review at each gate (8) | H1–H5, recorded, with automation-bias controls (§8.9, §10) |
| "Azure lakehouse" (8); Azure preferred where named (16) | Code that runs on Databricks, plus the Azure target-state mapping (§6.2) |
| README and setup steps; diagram; Responsible AI note (13) | Step 4.4 |
| Public or synthetic data only (13, 16) | §3 |
| Declare AI tools and existing code (13, 16) | `AI_USAGE.md`, `THIRD_PARTY.md`, the deck and the submission email |

---

## 6. Solution overview

### 6.1 Architecture

```text
LEGACY ESTATE (built by us; the factory's input)
  synthetic insurer data ──┬─► SQL Server 2022 ── 10 T-SQL jobs ──┐
  (seeded, 9 tables)       └─► SAS OnDemand ───── 5 SAS jobs ─────┴─► golden outputs
                                                                      (frozen + hashed)
LANSH FACTORY
  Discover ─H1─► Design ─H2─► Generate ─H3─► Reconcile ─H4─► Operate ─H5─► cut-over
                                 ▲               │
                                 └── self-heal ──┘
  shared:   trap cards · defect register · Claude gateway · gate log · evidence reports
  surfaces: CLI `lansh …` · Streamlit Control Tower · replay mode (no Claude access needed)
```

The job counts show the full 15-job estate. Tier 1 is 7 T-SQL and 3 SAS development jobs, plus 2 held-out T-SQL jobs.

### 6.2 Azure target state

The prototype runs locally. The same code and design map onto Azure like this:

| Concern | Prototype | Azure target state |
|---|---|---|
| Storage and tables | Delta Lake on local disk (bronze, silver and gold) | ADLS Gen2 with Delta; Unity Catalog schemas for bronze, silver and gold |
| Compute | Local PySpark 4.2 | Azure Databricks. Jobs use only APIs that work there (§8.5) |
| Scheduling | A schedule file per wave, plus the local orchestrator | Databricks Workflows, one job per wave |
| Lineage | OpenLineage JSON export | Unity Catalog lineage, or Microsoft Purview via OpenLineage |
| Agents | Claude Code CLI on a consumer subscription, with synthetic data only | Claude in [Microsoft Foundry](https://claude.com/resources/articles/claude-in-microsoft-foundry), inside the client's Azure tenancy and under enterprise terms |
| Gate sign-off | Local gate log | Entra ID identities, with approvals recorded in the client's workflow tool |
| Secrets | `.env` and `~/.authinfo` | Azure Key Vault |
| Legacy side | SQL Server container and SAS OnDemand | The client's SQL Server and SAS. Parallel runs read from them. |

### 6.3 The five product stages and gates

| Stage | What happens | Gate | Enforced before approval |
|---|---|---|---|
| **1 Discover** | Lineage, traps, suspected bugs, dependencies and waves | **H1** Scope and lineage | Every job is parsed or flagged, and every lineage column exists |
| **2 Design** | Layer, contract (keys, types, comparison policies), tags and suspected bugs | **H2** Contract and bug decisions | Keys are unique in the golden output; every non-exact policy has a reason; every suspected bug has a decision; tagged columns that flow into decisions have been reviewed |
| **3 Generate** | sqlglot draft, Claude translation, guardrails and tests | **H3** Code review | Guardrails, literal check and tests all pass |
| **4 Reconcile** | Counts, totals and records compared; diagnose, patch and re-run up to 3 times, then escalate | **H4** Evidence acceptance | Status is MATCH with zero unexplained differences |
| **5 Operate** | The estate runs in DAG order on Delta, with every output re-checked, SLAs checked and lineage published | **H5** Cut-over, per wave | Every job in the wave is accepted |

Agents may loop between Generate and Reconcile in the sandbox. A job is accepted only after H3 and H4.

### 6.4 Bronze, silver and gold (the medallion layers)

The brief's Design step asks us to "map to bronze, silver and gold layers". Each table sits in one layer, according to how refined its data is.

| Layer | What it holds | Our examples |
|---|---|---|
| **Bronze** | Raw data exactly as it arrived. It's never edited, so everything else can be rebuilt from it. | The 9 synthetic source tables |
| **Silver** | Cleaned and standardised data, with one consistent row per customer, policy or claim | `silver.dim_customer` (T01), `silver.dim_policy` (T02), `silver.fact_premium_earned` (T03), `silver.claims_enriched` (S01) |
| **Gold** | Business-ready tables, each built for one report or decision | `gold.claims_summary` (T04), `gold.loss_triangle_paid` (T06), `gold.risk_scores` (S04) |

The legacy warehouse has the same layers under other names: staging tables, warehouse tables and reporting tables. Each table gets a **data contract**: a written promise about its columns, types, keys and tags, which reconciliation then checks.

### 6.5 Design principles

1. **Ground truth comes from real legacy engines.** Golden outputs are frozen and hashed. An LLM never decides what "correct" means.
2. **Deterministic first, LLM second, verify everything.** Nothing an LLM produces is trusted until the guardrails, tests and reconciliation have passed.
3. **No silent tolerances.** Comparison is exact by default. Any other comparison policy has to be declared, given a reason and approved.
4. **Agents propose, humans approve.** Every gate decision is recorded.
5. **Fix the factory, never the job.** Fixes are generic and logged, and factory code never contains `if job_id == …`.
6. **Reproduce everything, change nothing silently.** Legacy behaviour is reproduced exactly, bugs included. Suspected bugs go to a human decision, and any fix is a separate, approved change.
7. **The translator can be swapped out.** The proof loop wraps any translator, and the comparison runs measure what that loop adds.
8. **Everything replays.** Anyone can re-run the demo offline from the recorded agent calls and the frozen ground truth.

### 6.6 Agents

All agents run on Opus 5.5 through Claude Code and return schema-checked JSON.

| Agent | What it does | How it's verified |
|---|---|---|
| Lineage | Column lineage for T-SQL and SAS, plus the subtle traps | Every column it names must exist; it must agree with sqlglot on simple SELECTs |
| Contract | Proposes keys, types, layer, comparison policies and tags | Keys are unique in the golden output; H2 |
| Translator | Writes the PySpark job, **reproducing legacy behaviour exactly** | Guardrails, literal check, reconciliation |
| Test author | Writes edge-case inputs for each detected semantic trap | Expected values come from running the legacy engine |
| Diagnoser/Fixer | Explains a failed reconciliation and patches the job | The next run must strictly reduce the differences; the literal check still applies |
| Defect reviewer | Lists suspected legacy bugs, with evidence and an impact query | The impact query runs on golden data; the answer key scores it |

### 6.7 Verified on 10 Nov

**Environment**
- Java 21.0.13 runs PySpark 4.2.0 and delta-spark 4.4.1 on Python 3.14, Delta MERGE included. pandas 2.3.3 is pinned, so PySpark's pandas-3 warning is gone.
- SQL Server 2022 (16.0.4305.5) runs on Apple Silicon under OrbStack, with collation `SQL_Latin1_General_CP1_CI_AS`.
- saspy reaches SAS OnDemand: `INTCK('year', 31DEC2025, 01JAN2026)` returns 1.

**Claude Code CLI**
- Versions 2.1.311 and 2.1.319 both run `-p` on our subscription with no API key, returning schema-checked JSON in `structured_output`.
- `--setting-sources ""` loads no user settings or plugins. With our own `--system-prompt` and a `--json-schema`, the minimal call measured 1,098 input tokens (spike 0.4).
- `--bare` only accepts an API key, so it's never used.

**sqlglot**
- It falls back to an opaque "Command" for whole stored procedures, and can't parse them.
- It leaves `DATEDIFF` and `LIKE '[0-9]%'` unchanged, though they mean different things in Spark.

**Collations** (the review checked these)
- `UTF8_LCASE_RTRIM` matches SQL Server's equality, which ignores case and trailing spaces. Its **ordering** of accented names differs, though, and `UNICODE_CI_RTRIM` comes closer.
- **Delta refuses to store collated string types.** Comparisons use collations, and storage uses plain strings.

**Sandbox escapes** (the review checked these)
- Generated code can get round an import allowlist through `spark.sql`: `TRANSFORM … USING` runs shell commands, `reflect()` calls Java, and `` text.`/path` `` reads files. That's why the guardrails in §8.5 scan SQL strings too.

**Rounding**
- Spark's `round` on literal doubles behaves like T-SQL: 2.675 → 2.68 and −2.5 → −3. The rounding traps only show up on computed values.
- SAS's `round(x, unit)` takes a rounding *unit*, not a number of decimal places: `round(2.85, 1)` is 3.

**Spikes (step 0.4; details in `spikes/README.md`)**
- *SQL Server.* Managed by `compose.yaml` (image pinned by digest; SA password from `.env`). Typed reads and writes round-trip exactly: fadas, trailing spaces, `''` against NULL, CHAR padding, decimals, `DATETIME2(6)`, and bigints beyond 2^53.
- *Spark.* `UTF8_LCASE_RTRIM` works with null-safe `<=>`. Spark rewrites collated join keys to `collationkey(...)`, and a test guards that. Collations travel with the type and clash with plain columns (`INDETERMINATE_COLLATION_IN_EXPRESSION`). **Parquet keeps collated types as well as Delta refusing them**, so cast to plain `string` before writing any file. The fallback normalisation is `lower(rtrim())`. Float comparisons need a finiteness guard, because Spark treats NaN as equal to NaN. datacompy agrees with the `exact` comparison.
- *Claude Code.*
  - `--json-schema` accepts Pydantic's `$defs`, `$ref` and enums as they are.
  - A structured answer takes 2 turns. The minimal call used 1,098 input tokens in 2.6 s.
  - An unsatisfiable schema returns `success` with no `structured_output`.
  - `--effort` accepts low, medium, high, xhigh and max; it ignores an unknown value with only a warning, and `CLAUDE_CODE_EFFORT_LEVEL` overrides it.
  - Prompts go on stdin.
- *SAS.*
  - **`BEST32.` writes at most 15 significant digits, so it can't round-trip a double**: only 8 of the 20 planted doubles survived as text. Exports therefore carry an exact `HEX16.` sidecar.
  - SAS reads decimal text exactly.
  - OnDemand sessions start with `NONOTES`; LANSH turns notes on.
  - `E8601DT26.6` treats an empty field as invalid data, so datetimes are staged through text.
  - `ENCODING='UTF-8'` writes a BOM unless `nobom` is set.
  - SAS has no empty string and drops trailing blanks.
  - SAS's calendar has no 29 February in years divisible by 4000, so `'31DEC9999'd` is 2 days short of Python's count.

---

## 7. The legacy estate

### 7.1 Synthetic data

- **The insurer.** SynthInsure, a fictional Irish insurer selling motor, home and travel cover, from 2019 to 2025. Every job reports as of **2025-12-31**.
- **The 9 source tables:** `customers`, `brokers`, `products`, `policy_snapshots` (two snapshot dates), `premium_transactions`, `claims`, `claim_payments`, `claim_reserves` and `fx_rates`. About 230k rows in all: 20,000 customers, with claims at a realistic frequency (paid claims about 64% of earned premium).
- **Committed and hashed.** Inputs are committed as Parquet with SHA-256 hashes.
- **`_row_seq` on every input table.** It records the original row order, because Spark has no physical order. SAS logic that depends on order (NODUPKEY, RETAIN, LAG, FIRST./LAST.) and T-SQL cursors are reproduced by sorting on it.
- **Tags in the data dictionary.**
  - `pii`: names, email, address, date of birth.
  - `protected`: date of birth (age) and county, which can act as a proxy.
- **Planted edge cases:**
  - case variants and trailing spaces
  - NULLs and duplicates whose emails differ only in case
  - boundary dates: 31 Dec and 1 Jan, 29 Feb 2024, month-ends
  - negative payments and zero premiums
  - over-long strings and Irish names with fadas
  - ties in rankings and gaps in exchange rates
- **The conditions each planted bug needs** in order to show up (Appendix B).

### 7.2 Job catalogue

The jobs cover the finance, actuarial and claims reporting named on slide 8. Trap IDs refer to Appendix A, and bug IDs to Appendix B.

| ID | Legacy job | Reads | Writes | Traps | Bug | Needs | Tier |
|---|---|---|---|---|---|---|---|
| T01 | `usp_load_dim_customer` | customers | silver.dim_customer | TSQL-01, 02, 04, 15 | BUG-01 | none | 1 |
| T02 | `usp_load_dim_policy` (history, 2 batches, IDENTITY keys, load-timestamp column; its own output is its state between batches) | policy_snapshots, brokers, products, T01 | silver.dim_policy | TSQL-11, 06, 01, 02 | none | T01 | 1 |
| T03 | `usp_build_fact_premium_earned` (carries T02's `policy_sk`, a foreign key to a surrogate) | premium_transactions, fx_rates, T02 | silver.fact_premium_earned | TSQL-03, 07, 09, 18 | BUG-02 | T02 | 1 |
| T04 | `usp_build_claims_summary` (**vertical slice**) | claims, claim_payments, claim_reserves, policy_snapshots | gold.claims_summary | TSQL-01, 05, 16 | BUG-03 | none | 1 |
| T05 | `usp_claim_aging` (cursor) | claims, claim_payments | gold.claim_aging | TSQL-12, 13, 04 | BUG-04 | none | 1 |
| T06 | `usp_loss_triangle` | claims, claim_payments | gold.loss_triangle_paid | TSQL-17, 04 | BUG-05 | none | 1 |
| T08 | `usp_fraud_flags` | claims, policy_snapshots, T01 | gold.claim_fraud_flags | TSQL-14, 15, 16 | BUG-07 | T01 | 1 |
| S01 | `claims_enrich.sas` | claims, claim_payments | silver.claims_enriched | SAS-05, 06, 01, 02 | BUG-08 | none | 1 |
| S03 | `premium_bands.sas` | T03 output | gold.premium_band_summary | SAS-12, 09, 14 | none | T03 | 1 |
| S04 | `risk_scoring.sas` (macros; uses `protected` columns: age and county from T01) | S01, S03, T01 | gold.risk_scores | SAS-13, 10, 11, 15 | BUG-10 | S01, S03, T01 | 1 |
| X1, X2 | Sealed held-out T-SQL jobs (§7.4) | Author's choice | Author's choice | Labelled by the author | 1 each | Any | 1 |
| T07 | `usp_broker_commission` | T03, T02, brokers | gold.broker_commission | TSQL-10, 08, 07, 02 | BUG-06 | T02, T03 | 2 |
| S02 | `policy_lapse.sas` | T02 output | gold.policy_lapse | SAS-07, 08, 04, 03 | BUG-09 | T02 | 2 |
| X3 | Sealed held-out SAS job | Author's choice | Author's choice | Labelled | 1 | Any | 2 |

**Expected waves for the Tier 1 development jobs.** Discover must find these on its own:

| Wave | Jobs |
|---|---|
| 1 | T01, T04, T05, T06, S01 |
| 2 | T02, T08 |
| 3 | T03 |
| 4 | S03 |
| 5 | S04 |

**Rules for writing the legacy code:**
- **Genuine legacy style:** upper-case keywords, change-log headers, `SET NOCOUNT ON`, `NOLOCK`, TRY/CATCH writing to `etl_log`, magic numbers, and `options mprint;` in SAS. Each job is 40–200 lines.
- **Deterministic output.**
  - Every sort and ranking ends with a unique tiebreaker, such as an ID or `_row_seq`.
  - Results never depend on how text sorts, except through a labelled trap (TSQL-19).
  - Use the `@AsOfDate` parameter, never `GETDATE()`, except in a labelled audit column such as T02's load timestamp, which gets an `exclude` policy.
- **Check queries for semantic traps only.** Each *semantic* trap and each bug gets a check query proving it changes the result on our data. *Construct* traps (Appendix A) change the shape of the code, not its results, so the job running cleanly is their check.
- **Rounding traps go on computed values.** TSQL-07 and SAS-15 are planted on computed values, such as `ROUND(rate * 10, 1)`, not on literals.
- **Honest mistakes.** The bugs should look like the kind a real developer makes.

### 7.3 Ground truth (golden outputs)

- **T-SQL.** SQL Server 2022 Developer Edition runs in a container with collation `SQL_Latin1_General_CP1_CI_AS`.
  - The compose file reads the SA password from `.env`.
  - The SA password is only set when the volume is first created. Change it later with `ALTER LOGIN`.
  - Parameters are fixed, and T02 runs both of its batches.
- **SAS, through saspy (verified).**
  - Inputs are uploaded and read with explicit informats, including `_row_seq`.
  - Outputs are exported with explicit formats: `BEST32.` for numbers, `YYMMDD10.` for dates and `E8601DT26.6` for datetimes. A `HEX16.` sidecar holds every numeric variable's exact bits, because `BEST32.` keeps at most 15 significant digits. Numbers are taken from the sidecar after a cross-check against the text.
  - The `PROC CONTENTS` metadata and the log are kept with each output (`GoldenOutput.sidecars`).
  - **Input order.** Source tables carry their extract `_row_seq`. A table written by a T-SQL job is given `_row_seq` in **key order** (sorted by its first column, then the others), which is how a SAS `libname` read of the warehouse table sees it. A migrated job must use the same order. A table written by a SAS job is read as its native data set, and no job may depend on its physical order.
- **Paste route (fallback; two pastes that reuse the engine's code, so the bytes and the parsing are identical).**
  1. Upload the inputs to `~/lansh/inputs` once.
  2. Paste program A (`estate/sas/run_all.sas`): it reads the inputs, runs the SAS jobs and exports each output's PROC CONTENTS metadata.
  3. Download the metadata; Python generates program B from it.
  4. Paste program B: it exports every output with its `HEX16.` sidecar and zips them, with the metadata and the log, into `~/lansh/golden.zip`.
  5. Download the zip into `estate/golden/_sas_drop/`. The full procedure is in `spikes/README.md` ("SAS round trip").
- **Golden pack per job:**
  - the raw export
  - a typed Parquet copy
  - a manifest: engine version, parameters, row counts, SHA-256 hashes and a log excerpt
- **`make legacy-verify`** re-runs the T-SQL jobs and must reproduce identical hashes.
- **Golden outputs are immutable.** Any change means a fresh capture, approved at a gate.

### 7.4 Held-out jobs and the answer key

- **Who writes X1–X3.** An isolated agent, working in an empty folder outside the repo. It sees only one-paragraph business briefs, the source schema and the legacy style guide. It never sees factory code, prompts, trap cards or the bug list. It plants one bug per job of its own choosing and labels it.
- **How they're protected.** The folder is sealed with a SHA-256 hash. It isn't opened until the factory freeze (Step 3.11). The jobs then run once, and those first-run results are reported as they come out.
- **The answer key.** `estate/labels/` lists every job's planted traps and bugs. Only the evaluation code reads it.

---

## 8. Factory components

### 8.1 Contracts (`lansh/contracts.py`)

These Pydantic v2 models are frozen at G1:

- `JobSpec`, `TableSchema`, `ColumnSpec` (including `tags`: `pii`, `protected`)
- `LineageEdge`
- `TrapCard`, `TrapFinding`
- `SuspectedDefect`, `DefectDecision`
- `DataContract`, which holds a `ComparisonPolicy` per column
- `MigrationArtifact`, `ReconReport`, `HealAttempt`, `TestCase`
- `GateDecision`, `RunMetrics`

### 8.2 Claude gateway (`lansh/llm/`)

Every Claude call goes through this module. It runs `claude -p` as a subprocess with these flags:

| Flag | Value |
|---|---|
| `--output-format` | `json` |
| `--json-schema` | The schema from the agent's Pydantic model. The answer arrives in `structured_output`. |
| `--system-prompt` | The agent's prompt |
| `--model` | `opus` |
| `--effort` | Set per agent |
| `--tools` | `""` (no tools) |
| `--setting-sources` | `""`, so no user settings or plugins are loaded |
| also | `--no-session-persistence`, `--strict-mcp-config` |

- **Environment.** Each call runs in an empty temporary folder. The child environment drops every `ANTHROPIC_*` and `CLAUDE_CODE_*` variable (except the OAuth token that signs in to the subscription), the parent session's variables and `MSSQL_SA_PASSWORD`. The prompt goes on stdin, never in argv. `--bare` is never used. The binary is `LANSH_CLAUDE_BIN` if it's set, otherwise `claude` from PATH.
- **Answers, not records.** Each agent answers in its own small model (`lansh.llm.answers`). Factory code turns answers into the §8.1 records and fills in ids, hashes and `verified` itself. The gateway refuses a contract record as a response schema.
- **Repeatable.** Prompt inputs are normalised before sending: sample rows are sorted, and there are no absolute paths or timestamps. That keeps recorded answers matching their requests. Every call records the CLI version and the models that actually answered (from `modelUsage`).
- **Cached.** Every answer is recorded, keyed by a hash of the model, effort, prompts and schema, and replays offline. The modes are `live`, `replay` and `auto`, and the demo uses `replay`.
- **Usage limits.** Runs are capped at D5 live calls (the gateway's default; `LANSH_LLM_MAX_LIVE_CALLS` overrides it). A run stops cleanly when the subscription's usage limit is reached, and resumes from the cache.
- **Validated.** Claude Code checks the schema, then Pydantic re-checks it. On failure there's one retry, then the call is escalated.
- **Usage log.** Each call records the agent, job, tokens, duration and the API-equivalent cost (not billed).
- **Optional backend.** An Anthropic API backend is Tier 3.

### 8.3 Discover (`lansh/discover/`)

- **Lineage, T-SQL and SAS.** The Claude Lineage agent reads each job and lists, for every output column, the input columns it's derived from or filtered by.
  - Every column it names must exist in the DDL or the known SAS schemas. Anything else is rejected.
  - For simple SELECT statements, sqlglot's `lineage()` cross-checks the result, and any disagreement is flagged.
  - There's no hand-built tracing through temp tables, MERGE or cursors.
- **Splitting.** T-SQL procedures are split into statements, and SAS programs into DATA, PROC and %macro blocks. These pieces feed the trap scan and the translator.
- **Trap scan.** Deterministic rules from each trap card (regexes, sqlglot checks, type checks such as INT/INT), plus Claude for the subtle cases. Findings include line numbers.
- **Estate.** A networkx DAG of all the jobs. Waves are its topological generations. Lineage paths from tagged columns into outputs are shown at H1 and H2.

### 8.4 Design and defects (`lansh/design/`)

- **Layer.** Bronze, silver or gold (§6.4).
- **Types.**
  - INT → int
  - DECIMAL(p,s) → decimal(p,s)
  - VARCHAR → string
  - DATE → date
  - DATETIME2 → timestamp_ntz
  - SAS numeric → double, or date if it carries a date format
  - SAS character → string

  The session time zone is UTC.
- **Collations.** They're applied in **computations and comparisons only**, never stored, because Delta rejects collated types.
  - Equality, GROUP BY and joins use `UTF8_LCASE_RTRIM`.
  - Where text order matters, use `UNICODE_CI_RTRIM`, and treat any remaining difference as trap TSQL-19.
  - Values are cast back to plain `string` before writing any file: Delta refuses collated types, and Parquet would keep them.
  - If collations misbehave, normalise with `lower(rtrim())` instead.
- **Comparison policy per column.**

  | Policy | Use |
  |---|---|
  | `exact` | The default |
  | `ci_rtrim` | SQL Server columns with case-insensitive collation |
  | `rtrim`, `blank_is_null` | SAS character values |
  | `float_rel(≤1e-9)` | SAS doubles only |
  | `surrogate` | IDENTITY or generated keys: rows are matched on the business key and generated values aren't compared |
  | `exclude(reason)` | Audit columns such as load timestamps |

  Every policy other than `exact` needs a reason and H2 approval.
- **Tags.** `pii` and `protected` tags from the data dictionary are carried into the contract. H2 shows every path from a `protected` column into an output, such as S04's risk score, for a bias decision.
- **Defect decisions.** Each suspected bug is shown at H2 with its measured impact. The decision is *reproduce* (the default) or *fix after cut-over*.

### 8.5 Generate (`lansh/generate/`)

- **Job template.** Each job is a pure function: `run(spark, inputs: dict[str, DataFrame], params) -> dict[str, DataFrame]`. Its docstring records the legacy file and hash, the model, the traps handled and the bugs reproduced on purpose. Stateful jobs, such as T02, take the previous state plus a batch. Order-dependent logic sorts on `_row_seq`.
- **Draft.** sqlglot transpiles each statement to Spark SQL, carrying the trap-scan warnings with it.
- **Translator.** Writes PySpark using the DataFrame API or Spark SQL, and **reproduces legacy behaviour exactly**.
  - Anything that looks like a bug is kept and marked `# LANSH-DEFECT`.
  - If it "fixes" a bug anyway, reconciliation catches the difference and the heal loop restores the legacy behaviour.
- **Guardrails, checked before anything runs:**
  1. **Python syntax tree.**
     - Only allowlisted imports: `pyspark`, `datetime`, `decimal`, `math`, `re`, `functools`, `typing`.
     - No `open`, `eval`, `exec`, `__import__`, `os`, `subprocess` or `socket`.
     - None of `.read`, `.write`, `_jvm`, `_jsc`, `sparkContext`, `.rdd`, `.cache()`, `.persist()` or `spark.conf.set`. Jobs never do their own I/O, and these APIs don't run on Databricks serverless compute.
  2. **SQL strings.** Every string passed to `spark.sql` is parsed with sqlglot (Spark dialect). The following are rejected:
     - `TRANSFORM … USING` scripts
     - `reflect`, `java_method` and `try_reflect`
     - file-path tables such as `` csv.`/path` ``
     - `ADD JAR` and `ADD FILE`
     - `CREATE FUNCTION`
     - `LOAD DATA`
     - `SET`
  3. **Literal check.** Every literal in the job (numbers, strings, dates) must appear in the legacy code, the contract or the job's parameters. Any other literal blocks H3 until a reviewer accepts it with a reason. This stops a fixer from hard-coding its way to a MATCH. Jobs also never receive golden outputs as inputs.
  4. **Lint and isolation.** ruff runs, and the job executes in a worker process with a timeout.

### 8.6 Reconcile and heal (`lansh/reconcile/`)

- **Checks, in this order:**
  1. schema
  2. **counts**, in total and per partition
  3. **totals** of each numeric column
  4. key integrity
  5. a full outer join on the keys with null-safe equality
  6. a comparison of each column under its policy
  7. a status for every row: match, value difference, missing or extra

  Outputs without keys are compared as multisets.
- **Modes.**
  - *Isolated:* the job's inputs are the upstream golden outputs.
  - *Chained:* its inputs are the upstream migrated outputs.
  - *Candidate:* a hand-written job is checked, which the manual baseline uses.
- **Cross-check.** datacompy's `PandasCompare` has to agree with our engine in tests.
- **Report.** JSON and Markdown, with sample differences and a plain-English explanation of what went wrong.
- **Diff signatures.** These recognise the patterns a known trap leaves behind:
  - case split
  - trailing-space split
  - integer truncation
  - off by one period
  - NULL against a value
  - rounding
  - row multiplicity
  - truncated string
  - order dependence
- **Heal loop.** Diagnose, then patch. The guardrails and the literal check run again, then the job re-runs. The patch is kept only if the differences shrink. The loop stops at MATCH, or escalates after 3 attempts, and every attempt is stored.
- **Data minimisation.** Claude sees code, schemas, summary statistics of the differences, and at most 5 sample rows, with any `pii` columns masked (hashed or redacted). The limit can be set to 0.

### 8.7 Tests (`lansh/generate/testgen.py`)

- **What's tested.** Every detected *semantic* trap gets a small set of inputs from Claude, 5–20 rows per table.
- **Expected values come from the legacy engine.**
  - T-SQL runs in a scratch SQL Server database.
  - SAS runs through saspy.
  - If saspy is unavailable, SAS tests check the contract instead: schema, keys and row counts.
- **Construct traps** are covered by the job running and reconciling.
- **Output.** pytest files in `migrated/tests/`.

### 8.8 Operate (`lansh/operate/`)

- **Run.** Migrated jobs run wave by wave on a local Delta lakehouse (`lakehouse/bronze|silver|gold`, gitignored), with chained reconciliation of every output.
- **Schedule.** One YAML schedule file per wave, which maps to Databricks Workflows.
- **SLA check.** Each job's contract sets a maximum runtime and an expected row count with a tolerance. The run log flags any breach.
- **Lineage export.** One OpenLineage JSON event per job run, including column lineage, in `runs/<run>/openlineage/`.

### 8.9 Gate log (`lansh/governance/`)

- **Records.** An append-only log of every decision: who decided, which job, which stage, when, why, and the evidence shown. Illegal transitions are refused.
- **Automation-bias controls:**
  - The evidence (differences, warnings, flows from tagged columns, suspected bugs) is shown before the approve button.
  - Approving anything that has warnings requires a written reason.
  - Approvals faster than a set threshold are flagged.
  - A random sample of approved jobs is re-reviewed.
- **Tier 2.** Each entry carries a hash of the previous one, and `lansh audit verify` checks the chain.

### 8.10 Evidence report

One Markdown report and one JSON file per job, covering:

- the legacy and migrated code, with their hashes
- lineage
- traps found
- suspected bugs, with impacts and decisions
- the contract and its tags
- the reconciliation result and heal history
- test results
- Claude usage
- gate decisions

### 8.11 Control Tower (`lansh/ui/`, Streamlit)

The UI is read-only apart from gate approvals. It shows a banner while replaying.

**Tier 1 pages:**
- **Estate:** jobs, waves and status.
- **Job:** the legacy code beside the PySpark, lineage, traps, contract and tags, reconciliation, the heal timeline, suspected bugs, and approval with a reason.
- **Scorecard:** §9 and §15, including the comparison runs and the manual baseline.

**Tier 2 page:** audit-trail verification.

### 8.12 CLI and replay

**Commands:**
- `lansh estate generate|load|golden|verify`
- `lansh discover|design|generate|reconcile --job ID|--all`
- `lansh reconcile --job ID --candidate FILE`
- `lansh approve`
- `lansh operate run --all`
- `lansh benchmark` (the comparison runs)
- `lansh ui`
- `lansh demo`

**Make targets:** `setup`, `legacy-up`, `golden`, `legacy-verify`, `check`, `ui`, `demo`. `make demo` needs no Docker, SAS or Claude access.

---

## 9. Business impact

### 9.1 Manual baseline, step by step

**What it measures.** How long migrating a legacy job by hand takes, without AI, to LANSH's standard: the output reconciles record for record.

**Jobs.**
- **T05:** T-SQL with a cursor.
- **S01:** SAS with MERGE and RETAIN.
- **T06,** optionally.

**Rules**
- The person doing the baseline **must not have written or reviewed that legacy job**, and must not see LANSH's version until they've finished.
- **No AI help.** Claude Code, Copilot and chat assistants are all turned off. Documentation and web search are allowed.
- **Same definition of done as LANSH:** the job uses the job template, and reconciliation reports MATCH.
- **The protocol is fixed in advance.** This section, and the timesheet template, are committed before any baseline starts.
- **The session is screen-recorded.** The recording is the evidence, and it can also be used as video footage.
- **Each job is capped at 3 hours.** A job that isn't finished by then is still a result: "over 3 hours, N differences left".

**Steps**
1. **Prepare, before starting the clock.**
   - Create the branch `baseline/t05`.
   - Copy the job template to `baseline/t05_manual.py`.
   - Open `baseline/timesheet.csv`, with columns `job, phase, start, end, minutes, differences_left, notes`.
   - Check that `lansh reconcile --job T05 --candidate baseline/t05_manual.py` runs.
   - Turn off every AI assistant and start the screen recording.
2. **Understand.** Read the legacy code. In `baseline/t05_lineage.md`, write down the inputs, the output's key, and where each output column comes from. Note anything that looks like a mistake, and log the time.
3. **Translate.** Write the PySpark. Log the time when it first runs without errors.
4. **Reconcile and debug.** Run the reconcile command. After every attempt, add a timesheet row with the number of differences left. Fix until MATCH. Reproduce any legacy bug rather than fixing it, and make a note of it.
5. **Test.** Optional, but still timed: write one pytest test for the trickiest behaviour.
6. **Stop** at MATCH or at the cap. Record the minutes per phase, the differences left and the bugs you noticed.
7. **Commit** the code, the notes, the timesheet and a link to the recording.

**Fairness notes, to state alongside the results:**
- The person has the reconciliation engine and the golden outputs. A real manual migration starts without them, so these times are an underestimate.
- The people doing the baseline also built LANSH and know this plan, including the bug list. That's another underestimate of manual effort.
- It covers two jobs, so the result is indicative.

### 9.2 What we compare

| | Manual (§9.1) | LANSH |
|---|---|---|
| Time per job | Timesheet minutes, by phase | Measured from the showcase run, which starts with an empty cache: machine minutes, reviewer minutes (gate timers), and human minutes spent fixing escalated jobs |
| Result | MATCH, or the differences left at the cap | MATCH, heal attempts, escalations |
| Lineage | A hand-written note | Schema-checked column lineage |
| Bugs found | From the person's notes | The defect register, scored against the answer key |
| Tests | One, optional | One per semantic trap |

### 9.3 Projection onto the client's estate

The brief describes about 1,200 ETL jobs and 400 SAS programs, with a delivery window of 4–6 months (slide 8). That's about 1,600 jobs, assuming the SAS programs aren't counted among the ETL jobs. Over 87–130 working days, that means **about 12–18 jobs per working day**.

**Human effort per job.**

| Approach | Human effort per job |
|---|---|
| Manual | manual minutes (§9.1) + golden-capture minutes |
| LANSH | reviewer minutes + (escalation rate × manual minutes) + golden-capture minutes |

- Golden-capture minutes are the time to run and export a legacy job's output. Both approaches need them, so they're measured, not assumed.
- Machine time is reported separately. It runs in parallel and doesn't need people.

**Gate load.** Five gates for each of 1,600 jobs is about **8,000 human decisions**. At scale, LANSH uses risk-based gating:
- H1 and H5 run once per wave.
- H2–H4 run per job only for jobs with warnings: non-exact policies, suspected bugs, escalations, flows from tagged columns, or low-confidence lineage.
- Clean MATCH jobs are approved per wave, with a random sample re-reviewed.

The scorecard shows the reviewer load under both approaches.

**Projection.** Human hours for the estate, and the size of team needed to meet the 12–18 jobs per day, for manual and for LANSH. Running cost at API prices is Claude usage per job × 1,600.

**Sensitivity table.** Low, middle and high cases for manual minutes per job, based on:
- our baseline
- EXL's own published result for Code Harbor, [a 50% efficiency gain](https://www.exlservice.com/insights/case-study/how-exl-helped-leading-insurance-provider-migrate-sas-pyspark-with-50-percent-efficiency-gains) on a SAS-to-PySpark migration, as a reference point for what tooling achieves
- an estimate of manual person-days per job, from EXL at an info session, if we get one

Every other assumption is editable and labelled.

**What the sensitivity must vary (found by the review, Appendix G, G-B1).** The saving is ((1 − e) × m − R) ÷ (m + c), for escalation rate e, manual minutes m, person minutes of review per job R and golden-capture minutes c. With R small beside m, it is about 1 − e, so varying the manual minutes barely moves it: all three cases print 83–84% at the assumed 15%. The variables that matter are **e** and **R**.
- R is measured in the person-signed run, as each job's wall time (step 5.3).
- The table crosses e (15%, 30%, 50%) with R (measured, 30 and 60 minutes), and leads with headcount and cost (step 5.4).
- There's no 0% row, which would print 98–99%. The 50% column is illustrative: the held-out first run's 1 of 2 is a sample of 2.
- The manual cases stay, because they set the absolute hours and the cost.

### 9.4 Pilot KPIs (how a client would measure success)

For a first wave of about 20 jobs:
- the share of jobs that reconcile first time
- reviewer minutes per job
- escalation rate
- suspected bugs found per 100 jobs
- **zero unexplained differences at cut-over**
- API-equivalent cost per job
- elapsed time per wave

The scorecard reports our measured values for each.

### 9.5 Positioning

- **[EXL Code Harbor](https://www.exlservice.com/insights/case-study/how-exl-helped-leading-insurance-provider-migrate-sas-pyspark-with-50-percent-efficiency-gains)** is a multi-agent SAS-to-PySpark migration tool, and EXL launched a [code migration accelerator with Databricks](https://seekingalpha.com/pr/20121454-exl-partners-with-databricks-to-launch-gen-ai-powered-code-migration-accelerator).
- **[Databricks Lakebridge](https://databrickslabs.github.io/lakebridge/docs/reconcile/configuration/)** reconciles migrated outputs at row and column level.
- **LANSH doesn't compete with either.** It is the proof-and-governance layer around whatever translator is used, and adds:
  1. bug-for-bug reproduction, plus a defect register with measured impact
  2. a trap library linking SAS and T-SQL semantics to the shapes reconciliation failures take, which drives automatic repair
  3. human gates backed by evidence, with automation-bias controls
  4. measured uplift: the comparison runs (Step 3.10) show how many jobs reach MATCH with sqlglot alone, with one-shot Claude, and with LANSH

---

## 10. Responsible AI

This section is the source for `docs/responsible-ai.md` and for the one-page note. That note has to cover data, privacy, bias, limitations and safeguards (slide 13).

- **Data.**
  - All data is synthetic, from a seeded generator.
  - Public sources are used only as aggregates.
  - There's no personal data anywhere.
  - The data dictionary tags columns `pii` and `protected`.
- **Privacy.**
  - What reaches the model is code, schemas, summary statistics of differences, and at most 5 sample rows with `pii` columns masked. Sample rows can be switched off entirely.
  - The prototype runs on a consumer Claude subscription because the data is synthetic.
  - **In production, no client data goes to consumer services.** Claude runs in Microsoft Foundry inside the client's Azure tenancy, under enterprise terms (§6.2).
- **Security.**
  - Generated code runs only after the guardrails pass: the syntax-tree checks, the SQL-string scan, the banned APIs and the literal check (§8.5).
  - It runs in a separate worker process with a timeout.
  - Secrets live only in `.env` and `~/.authinfo`, never in the repo, logs or recorded answers.
  - *Limitation:* the local worker doesn't block network access.
- **Bias.**
  - LANSH reproduces legacy logic faithfully, including any bias, because changing behaviour silently would be worse.
  - Lineage shows every path from a `protected` column into a decision output. S04's risk score uses age and county, for example.
  - H2 requires a human decision on each of these paths.
- **Human oversight and automation bias.**
  - A human gate sits at every stage.
  - The evidence is shown before the approve button.
  - Approving anything with warnings requires a written reason.
  - Approvals that are too fast are flagged, and approved jobs are spot-checked.
  - At scale, risk-based gating keeps human attention on the jobs that need it (§9.3).
- **Transparency.** Every job has an evidence report. AI usage is declared. Each agent's role and how it's verified are documented (§6.6).
- **Limitations, stated openly.**
  - The legacy estate is synthetic, and the team wrote it. Held-out jobs and EXL's samples, if they arrive, reduce this.
  - The manual baseline is small.
  - SAS macro coverage is partial.
  - Text ordering can differ between SQL Server and Spark.
  - LLM output varies between runs. Replay makes the demo reproducible, but a live re-run can differ.

---

## 11. Repository layout

```text
.
├── AGENTS.md  CLAUDE.md  README.md  AI_USAGE.md  THIRD_PARTY.md  Makefile  pyproject.toml   (.env template: tests/fixtures/.env.example)
├── compose.yaml                 # SQL Server 2022 (password from .env)
├── docs/                        # PLAN.md, gates.md, tutorial.md; later architecture.md, responsible-ai.md, learning-log.md
├── scripts/                     # smoke_test.py, third_party.py
├── spikes/                      # Phase 0 spikes; README.md has their findings
├── estate/
│   ├── jobs.yaml                # inventory: id, language, path, params, inputs, outputs
│   ├── data/                    # synthetic inputs (Parquet), data dictionary with tags, manifest
│   ├── tsql/  sas/              # legacy code (+ sas/run_all.sas for the paste route)
│   ├── golden/<job>/            # golden outputs and manifests
│   ├── holdout/                 # sealed
│   └── labels/                  # answer key (evaluation only)
├── src/lansh/                   # contracts, llm, estate, engines, discover, design, generate, reconcile, operate, governance, ui, cli
├── baseline/                    # manual baseline: hand-written jobs, lineage notes, timesheet.csv
├── migrated/                    # factory output: jobs/, tests/, contracts/
├── runs/                        # run artifacts; runs/showcase/ and cassettes are committed
└── tests/
```

---

## 12. Working standards (condensed into AGENTS.md)

- **Overnight run (from 12 Nov).** `AGENTS.md`'s "Overnight run" section overrides the standards below where they conflict:
  - one agent works alone;
  - it accepts gates itself;
  - it may change this plan;
  - it makes no commits unless the team asks (the overnight work was committed and pushed at their request, as `b1568b2`).
- **Gates.** Every phase ends at a gate (§4), reviewed with the packet in Appendix C.
- **Changes that need a team decision:**
  - scope
  - contract changes after G1
  - new external services
  - anything made public
  - licence and declarations
  - bug decisions
- **Stack.**
  - Python 3.14 managed with uv, on Java 21.
  - Pinned `pyspark==4.2.0`, `delta-spark==4.4.1`, `pandas>=2.3,<3`.
  - ruff and pytest.
  - Type hints throughout, and Pydantic v2 between modules.
  - `logging`, not `print`.
- **Spark.** One session builder: Delta, UTC, ANSI mode on, and a small number of partitions.
- **Tests.** Unit tests run offline, with no Claude access. Integration tests are marked `mssql`, `sas` or `live_llm`. `make check` must pass before merging.
- **Git.** One branch per step and small Conventional Commits. No AI signatures (`Co-Authored-By:` trailers, "generated with" lines) in commits, pull requests or code; AI use is declared in `AI_USAGE.md`.
- **Code style.** Docstrings on every module, class and function: the opening quotes on their own line, a one-line summary, what isn't obvious, then `Args:`, `Returns:` and `Raises:`. Short lower-case comments that say why. Legacy code keeps its own style.
- **Secrets.** Only in `.env` (gitignored) and `~/.authinfo`.
- **"Done" means:**
  - the step's "done when" holds
  - tests are added
  - `make check` passes
  - docs are updated
  - the step is ticked in Appendix D
- **Never:**
  - push to `main` without checks
  - change the repo's visibility
  - read `estate/holdout/` or `estate/labels/` from factory code
  - edit golden outputs
  - write job-specific factory code
  - fix a legacy bug inside a migrated job
  - stage a failure for the demo

---

## 13. Scope tiers

**Tier 1: must ship**
1. 10 development jobs (7 T-SQL, 3 SAS) and 2 sealed held-out T-SQL jobs, each with golden outputs from the real engine, planted traps and planted bugs.
2. The per-job pipeline:
   - lineage and trap scan
   - a contract with tags
   - translation with guardrails and tests
   - reconciliation (counts, totals, records) with the heal loop
3. One human approval per stage, with the automation-bias controls.
4. Bugs reproduced, with a defect register and a decision per bug.
5. The whole estate run in DAG order, with chained reconciliation, SLA checks and OpenLineage export.
6. The comparison runs: sqlglot alone and one-shot Claude.
7. The manual baseline on T05 and S01.
8. The UI (estate, job and scorecard pages), replay mode and the README.

**Tier 2** (re-prioritised by the review, Appendix G: CI is now step 5.11, X3 is part of step 5.17, and T07 and S02 are deferred, because the brief's 10–15 jobs are met and more of the same adds no new kind of evidence)
1. T07, S02 and X3, bringing the estate to 15 jobs.
2. CI on GitHub Actions: lint, tests and replay.
3. The hash-chained gate log.
4. A corrected version of one or two bugs, with "explained differences" showing exactly what changes.
5. Calibration from the Central Bank's NCID figures.
6. Measured impact for every suspected bug, beyond the planted ones.

**Tier 3**
- An investigator agent with tools.
- Lineage checked by perturbing inputs.
- A Codespaces devcontainer.
- A Databricks export or run.
- A second-day incremental run.
- An Anthropic API backend.
- A WideWorldImporters held-out job.

---

## 14. Demo path

It must work in replay mode in 5 minutes or less. The 3-minute video is a cut of it.

1. **Estate.** Jobs across SQL Server and SAS, in waves. Approve H1.
2. **T04.** The legacy code and the PySpark side by side, with lineage and the traps at their lines. The contract keeps `status` exact: T04 passes the stored value through, so a proposed `ci_rtrim` would be a tolerance with no reason, and H2 refuses it (no silent tolerances).
3. **The bug.** T04 counts some payments twice (BUG-03).
   - LANSH reproduced the bug exactly, so the job still reaches MATCH.
   - LANSH also flagged the bug, with its measured impact. Decide: reproduce now, fix after cut-over. Approve H2.
4. **Bias check.** S04's risk score uses age and county. Lineage shows it, and H2 asks for a decision.
5. **A job that genuinely needed healing.** MISMATCH, with its explanation, then the patch, then MATCH: counts ✓, totals ✓, N records ✓.
6. **Operate.** The waves run on Delta, with chained reconciliation all green, the SLA check and the lineage export.
7. **Scorecard.**
   - Comparison runs: how many jobs reach MATCH with sqlglot alone, with one-shot Claude, and with LANSH.
   - Held-out results.
   - Manual against LANSH minutes.
   - The projection onto 1,600 jobs, including the gate load under risk-based gating.

**The video cut (3 minutes; step 5.10).** Record it in replay mode, on the person-signed showcase run (step 5.3), after steps 5.6 and 5.7. Say on screen that the agents' answers were recorded live in the estate run and are replayed here. Narrate outcomes in plain words: no gate ids, card ids or run names on screen.

| Time | Shows | Says |
|---|---|---|
| 0:00–0:15 | The comparison chart | "AI can translate legacy code. One-shot Claude ran all 10 of our jobs without an error, and 2 of them silently changed the legacy numbers, on 805 rows: it 'fixed' two bugs nobody had decided to fix, and got SAS rounding wrong. Nothing but a record-by-record check would have told you." |
| 0:15–0:35 | Overview, then Estate: SQL Server and SAS jobs in five waves | The estate, the five stages and a person's gate at each stage |
| 0:35–1:10 | T04: legacy beside PySpark, the lineage graph, a trap at its line, the defect | "We planted a bug here to test LANSH: it counts some payments twice, overstating paid-to-date by €1.29M on 289 claims. LANSH finds it and reproduces it, so the numbers still match, and asks a person: reproduce now, or fix after cut-over." The person's decision and reason |
| 1:10–1:40 | Reconciliation: 823 of 823 rows, content hash identical; then the heal on one-shot S04, `MEDIUM` against `MEDI`, diagnosed and patched to MATCH | Proof, then repair |
| 1:40–2:00 | Operate: the waves on Delta, re-reconciled; the SLA check; the lineage export | Cut-over |
| 2:00–2:35 | Scorecard: the held-out result as it came out (1 of 2, then 2 of 2); manual against LANSH; the 1,600-job projection with its sensitivity | The business case, measured first |
| 2:35–2:55 | Audit: the person's sign-offs, flagged-fast checks, the intact hash chain; S04's protected flows and its tiers by age band (step 5.5) | Responsible AI |
| 2:55–3:00 | The repo link | "The translation is the easy part. The proof is the product." |

---

**How to run it (built in Phases 2–4).** All of it works offline, from the committed golden outputs and recorded answers:
- `make demo` replays T04 through all five stages in about a minute (no Docker, SAS or Claude), then opens the Control Tower. The Control Tower also shows the whole-estate run committed as `runs/showcase/`.
- Step 1: the **Estate** page shows the waves, the DAG and every job's status. Then the H1 decisions on the **Audit** page.
- Steps 2–3: the **Job** page for T04 shows:
  - the legacy code beside the PySpark;
  - the lineage and the traps, at their lines;
  - the contract;
  - BUG-03 on the Defects tab: 289 rows, €1,288,029.36, decided *reproduce*.

  To show H2 refusing a tolerance: `uv run pytest tests/test_design.py -k tolerance -v`, or set `status` to `ci_rtrim` in the contract and run `lansh run-job T04`. H2 blocks it with "a tolerance with no reason".
- Step 4: S04's Contract tab, and the Estate page's table of tagged flows, show `stg.customers.date_of_birth` reaching the risk score through T01.
- Step 5: LANSH's own estate run needed no healing, so the genuine heals are on the **Scorecard** page, under "The heal loop on the one-shot translations that failed". One-shot Claude's S04 was MISMATCH on 719 rows (`MEDIUM` where SAS stores `MEDI`); the fixer diagnosed SAS-11 and patched it, and it reconciled MATCH in one attempt. S01 healed the same way, diagnosing SAS-02. `uv run pytest tests/test_heal.py` also replays a deliberately broken T04, labelled as such, healing from 60 missing and 740 differing rows.
- Step 6: each job's Reconciliation tab shows the Delta re-run. Each wave's schedule is in `runs/showcase/schedules/`, and the OpenLineage events are in `runs/showcase/<job>/openlineage/`.
- Step 7: the **Scorecard** page has:
  - the proof, and detection against the answer key;
  - the comparison runs: sqlglot alone 0/10, one-shot Claude 8/10 (2 silently wrong), LANSH 10/10;
  - the held-out results: 1 of 2 on the first run. X1 escalated with a precise diagnosis; pick the run `showcase/held-out` to see it, and `showcase/learning` for the second run after the generic fix;
  - the projection onto 1,600 jobs.

## 15. Metrics

| Metric | How it's measured |
|---|---|
| Jobs reconciled record for record | Status MATCH, with zero unexplained differences |
| Held-out jobs reconciled | Their first run after the factory freeze |
| Planted bugs reproduced | The job is MATCH, and the bug's check query shows the same result on the migrated output |
| Planted bugs and traps detected | Findings compared with the answer key |
| First-pass match rate, heal attempts, escalations | Heal history |
| Comparison with alternatives | MATCH rate for sqlglot alone, one-shot Claude and LANSH |
| Factory fixes per wave (the learning curve) | Entries in Appendix F (the learning log) |
| Manual against LANSH time | §9.1 and §9.2 |
| Reviewer load | Gate decisions and reviewer minutes per job, under both gating approaches |
| Claude usage per job | Tokens, plus the API-equivalent cost |
| Reproducibility | `make demo` on a fresh clone, with no Claude access |

---

## 16. Risks

| Risk | Mitigation or fallback |
|---|---|
| SQL Server under emulation | It's verified working. Fallbacks: Docker Desktop, or GitHub Codespaces on native Intel |
| saspy stops connecting | The paste route (§7.3) |
| Subscription usage limits | Every answer is cached; runs stop and resume; the D5 cap; Sonnet for bulk steps; the showcase run uses an account with headroom |
| LLM translations miss subtle semantics | Deterministic draft, trap cards, heal loop, escalation |
| The translator "fixes" a planted bug | Reconciliation catches it, the heal loop restores the bug, and the episode becomes evidence |
| A fixer hard-codes its way to a MATCH | The literal check; jobs never see golden outputs |
| Generated code escapes the sandbox | The syntax-tree checks, the SQL-string scan and the banned APIs (§8.5) |
| Collation and text-ordering differences | Collations used in comparisons only; tiebreakers; TSQL-19 |
| "You marked your own homework" | Held-out jobs in Tier 1; a hidden answer key; the comparison runs; golden outputs re-verified |
| "How is this different from Code Harbor or Lakebridge?" | §9.5 positioning, backed by the comparison runs |
| The live demo fails | Offline replay mode and a backup video |
| Something sensitive goes public | Pre-publication checklist and secret scan; the EXL deck is never tracked |
| Ownership terms are unknown | No licence until they're clear (D3) |
| The business case's headline is an assumption restated (Appendix G, G-B1) | Measured manual and reviewer minutes (steps 5.2, 5.3); the escalation-rate sensitivity; every number tagged measured or assumed (5.4) |
| A judge clones the repo and setup fails (G-T1) | Step 5.1's fresh-clone test; CI (5.11) |
| The freeze record is unpublished, and reports the factory changed (G-T2) | Track `runs/freeze.json`, and record freeze 3 with its reason (5.1) |
| No person has signed a gate (G-R1) | The person-signed showcase run (5.3) |
| Re-publishing the showcase deletes the comparison and scoring evidence (G-T9) | Step 5.3 rebuilds it in the new run before publishing, and checks the scorecard keeps every row |

---

## 17. Submission checklist (repo side)

- [ ] The public repo works while logged out, and `make demo` works from a fresh clone.
- [ ] The README covers the results table, the quickstart (replay mode), the full setup, the architecture (including Azure), limitations, the AI tools used and the video links.
- [ ] `AI_USAGE.md` covers Claude Code for development and Claude Opus 5.5 through Claude Code in the product. It states that the manual baseline was done without AI. The same declaration appears in the deck and the email.
- [ ] `THIRD_PARTY.md` lists the dependencies and their licences.
- [ ] Data statement: 100% synthetic, the seed, no personal data.
- [ ] `docs/architecture.md` and `docs/responsible-ai.md` are ready to become the one-page documents.
- [ ] The showcase run is committed: evidence reports, the defect register, the scorecard and the recorded answers.
- [ ] No secrets in the git history (gitleaks), no EXL material, no `.env`.
- [ ] The licence decision (D3) is applied, and `v1.0.0` is tagged.
- [ ] `lansh freeze` reports unchanged, and `lansh audit verify --run showcase` reports the person's decisions.
- [ ] Every number in the deck, video and README matches the scorecard and carries its *measured* or *assumed* tag.
- [ ] Every link in the email (repo, three videos, deck, two one-page PDFs) opens in a logged-out browser.
- [ ] Work after submission goes on a later tag; `v1.0.0` stays what was submitted.

---

## Appendix A. Trap cards

Traps are **differences between engines**: the legacy engine behaves one way and Spark another.

- **Semantic** traps change results. Each one planted gets a check query and a test.
- **Construct** traps change the shape of the code but not its results. Running and reconciling the job covers them.

Tier 1 needs a card for every trap planted in a Tier 1 job.

| ID | T-SQL → Spark trap | Kind | Jobs |
|---|---|---|---|
| TSQL-01 | Case-insensitive collation in `=`, GROUP BY, DISTINCT and joins (compare with `UTF8_LCASE_RTRIM`; store plain strings) | semantic | T01, T02, T04 |
| TSQL-02 | Comparisons that ignore trailing spaces; CHAR padding | semantic | T01, T02, T07 |
| TSQL-03 | Integer division truncates | semantic | T03 |
| TSQL-04 | DATEDIFF counts boundaries crossed | semantic | T01, T05, T06 |
| TSQL-05 | `+` concatenation with NULL | semantic | T04 |
| TSQL-06 | ISNULL typing; NULL treated as equal to empty in change detection | semantic | T02 |
| TSQL-07 | DECIMAL scale and ROUND on computed values; `ROUND(x,n,1)` truncates | semantic | T03, T07 |
| TSQL-08 | TOP / TOP WITH TIES | semantic | T07 |
| TSQL-09 | CROSS APPLY with TOP 1 | construct | T03 |
| TSQL-10 | UPDATE…FROM | construct | T07 |
| TSQL-11 | MERGE and type-2 history | construct | T02 |
| TSQL-12 | Cursors and WHILE loops | construct | T05 |
| TSQL-13 | Temp tables | construct | T05 |
| TSQL-14 | LIKE character classes `[0-9]` | semantic | T08 |
| TSQL-15 | LEN ignores trailing spaces; SUBSTRING from 0 | semantic | T01, T08 |
| TSQL-16 | CONVERT style codes | semantic | T04, T08 |
| TSQL-17 | PIVOT | construct | T06 |
| TSQL-18 | EOMONTH and DATEADD at month-end | semantic | T03 |
| TSQL-19 | Text ordering under collations (accents): ORDER BY, MIN/MAX on text | semantic | Not planted; card for when it's detected |

| ID | SAS → PySpark trap | Kind | Jobs |
|---|---|---|---|
| SAS-01 | A missing value is smaller than any number | semantic | S01 |
| SAS-02 | SUM() ignores missing values; `+` propagates them | semantic | S01 |
| SAS-03 | Dates as days since 1960 | semantic | S02 |
| SAS-04 | INTCK and INTNX boundaries | semantic | S02 |
| SAS-05 | MERGE BY with IN= | semantic | S01 |
| SAS-06 | RETAIN and the sum statement (in `_row_seq` order) | semantic | S01 |
| SAS-07 | FIRST./LAST. | construct | S02 |
| SAS-08 | LAG inside IF | semantic | S02 |
| SAS-09 | NODUPKEY keeps the first row in input order (`_row_seq`) | semantic | S03 |
| SAS-10 | PROC SQL remerging summary statistics | semantic | S04 |
| SAS-11 | Length fixed at first assignment (silent truncation) | semantic | S04 |
| SAS-12 | PROC FORMAT range boundaries | semantic | S03 |
| SAS-13 | Macro loops | construct | S04 |
| SAS-14 | PROC MEANS with CLASS and NWAY | construct | S03 |
| SAS-15 | ROUND fuzz on computed values; 8-byte floats | semantic | S04 |

---

## Appendix B. Planted legacy bugs

Bugs are **mistakes in the legacy logic itself**. LANSH must reproduce each one (its job reaches MATCH) and flag each one in the defect register.

| ID | Job | What the legacy code does | What was intended | Tier |
|---|---|---|---|---|
| BUG-01 | T01 | De-duplication keeps the **oldest** record (`ORDER BY updated_at ASC`) | The latest | 1 |
| BUG-02 | T03 | Divides by a hard-coded 365, even in 2024 | Days in the term | 1 |
| BUG-03 | T04 | Joins payments and reserves together, so payments are counted once per reserve row | Aggregate each separately | 1 |
| BUG-04 | T05 | Ageing bands `< 30`, `31–60`, `> 60` leave exactly 30 days in no band ('UNKNOWN') | Bands with no gaps | 1 |
| BUG-05 | T06 | Excludes payments made on the loss date (`>` instead of `>=`) | Include day 0 | 1 |
| BUG-07 | T08 | The "reported soon after inception" rule compares with the policy **end** date | The start date | 1 |
| BUG-08 | S01 | `if amount < 0` also flags **missing** amounts as recoveries (via SAS-01) | Negative amounts only | 1 |
| BUG-10 | S04 | Tier is set to 'HIGH' first, so 'MEDIUM' is stored as 'MEDI' (via SAS-11) | 'MEDIUM' | 1 |
| X1, X2 | Held-out | One bug each, chosen by the isolated author | Not known to the factory | 1 |
| BUG-06 | T07 | Commission is also paid on cancelled policies | Exclude cancelled policies | 2 |
| BUG-09 | S02 | `lag()` inside an IF takes the previous end date from the wrong row (via SAS-08) | The previous row | 2 |

---

## Appendix C. Gate review packet (template)

```markdown
## Gate <N>: <name>
**Asking for:** Approve / Approve with changes / Reject
**What was built:** <bullets, with links>
**Check it yourself:** <exact commands and what you should see>
**Evidence:** <test results, metrics, hashes>
**Changes from the plan:** <what changed and why>
**Risks and open issues:** <with proposed handling>
**Decisions needed:** <numbered, each with a recommended default>
**Starts on approval:** <next steps>
```

---

## Appendix D. Step tracker

Tick each step when it's done. Mark the step in progress with "(doing)".

- [x] 0.1 Environment (first machine: smoke test 5/5)
- [x] **G0** Plan (approved 10 Nov by the instruction to implement Phases 0 and 1)
- [x] 0.2 Scaffold (committed locally; creating the GitHub repo and pushing awaits the team)
- [x] 0.3 Contracts (53 models, revised after an independent review)
- [x] 0.4 Spikes (SQL Server, SAS, Claude backend, Spark reconciliation; each independently verified)
- [x] **G1** Foundations (accepted by the agent, overnight run, 12 Nov; evidence: `make check` 488 passed plus the known failure, `make smoke` 5/5, Claude spike replays identically, seal verifies)
- [x] 1.1 Synthetic insurer (232,267 rows, seed 20251231, 46 condition tests; recalibrated at the G2 review)
- [x] 1.2 T-SQL legacy jobs (7 jobs, independently reviewed)
- [x] 1.3 Freeze T01–T03 (captured before any SAS output)
- [x] 1.4 SAS legacy jobs (S01, S03, S04)
- [x] 1.5 Held-out jobs (sealed; SHA-256 51591fd9…)
- [x] 1.6 Golden outputs (all 10; `make legacy-verify-all` reproduces every hash)
- [x] 1.7 Answer key (82 traps, 8 bugs, 52 checks; evaluation only)
- [x] **G2** Ground truth (accepted by the agent, overnight run, 12 Nov; evidence: `make legacy-verify-all` reproduced all 10 golden hashes from a fresh rebuild, T04 checks 5/5 PASS)
- [x] 2.1 Reconciliation engine (`lansh.reconcile`: engine, diff signatures, harness and `lansh reconcile --candidate`; 17 new tests plus the spike's 26; datacompy agrees on T04)
- [x] 2.2 Claude gateway (both G1 open items fixed; agent answer models in `lansh.llm.answers`; `ask()` stamps run and stage and appends `llm_usage.jsonl`; 60 offline tests; `make test-live` 1 live call passed)
- [x] 2.3 Gate log (`lansh.governance.gatelog`: in-order transitions, blockers, reasons, fast flags, seeded spot-checks, defect and flow decisions, the Tier 2 hash chain and `lansh audit verify`; 8 tests)
- [x] 2.4 Discover (`lansh.discover`: splitter, 35 trap cards, rule pass plus trap-scan agent, Lineage agent verified against the schemas and cross-checked by sqlglot through temp tables; T04's lineage matches the hand check, 20/20 columns agree with sqlglot; 11 tests)
- [x] 2.5 Design (minimal) (`lansh.design.contract`: keys from the DDL and the golden profile, default policies with reasons, tags carried by lineage from job to job, the Contract agent for grain and partitions, H2's checks; T04 all exact; 6 tests)
- [x] 2.6 Generate, tests, guardrails (draft, Translator agent, guardrails with the literal check, Test author agent with expected values from SQL Server; T04 translated first time to MATCH with an identical content hash; its 12 trap tests pass; 31 tests)
- [x] 2.7 Heal loop (`lansh.reconcile.heal`: Diagnoser/Fixer agent, guardrails and literal check on every patch, kept only on a strictly better score, escalation after 3; the deliberately broken T04 healed to MATCH in one attempt)
- [x] 2.8 Defect list (minimal) (`lansh.design.defects`: `# LANSH-DEFECT` markers plus the Defect reviewer agent, whose impact queries run read-only on golden data after the SQL guardrails; BUG-03 listed, measured at 289 rows and EUR 1,288,029.36, the answer key's own figures)
- [x] 2.9 Operate (minimal) (`lansh.operate.run`: the worker writes Delta, every output is reconciled again, SLA checks, OpenLineage run events with column lineage, wave schedule files mapping to Databricks Workflows; T04 on Delta: MATCH, SLA met)
- [x] 2.10 T04 end to end (`lansh.pipeline`, `lansh run-job`, `lansh approve`, the evidence report; T04: MATCH through H1–H5 in 170 s, BUG-03 reproduced, marked and measured; replays offline with every decision reused)
- [x] **G3** Vertical slice (accepted by the agent, overnight run, 12 Nov; evidence: `make check` 587 passed plus the known failure, `make test-e2e` T04 MATCH offline, `lansh audit verify` intact; D4 and D5 confirmed)
- [ ] 3.1 Manual baseline (the team's: kit ready, with `baseline/timesheet.csv`, `lansh template --job T05 --out baseline/t05_manual.py` and `lansh reconcile --job T05 --candidate baseline/t05_manual.py`; see Appendix E)
- [x] 3.2 Trap cards (done early with 2.4: all 35 cards, TSQL-01..19 and SAS-01..16, as generic engine knowledge in `src/lansh/discover/trap_cards.yaml`)
- [x] 3.3 All T-SQL jobs (7/7 MATCH on the first translation, no healing; 4 generic factory fixes, in Appendix F)
- [x] 3.4 SAS support and jobs (S01, S03, S04 MATCH on the first translation; SAS lineage, trap rules, the translator's SAS rules, contract-level SAS tests)
- [x] 3.5 Design for all jobs (10 contracts in `migrated/contracts/`; keys unique in the goldens; non-exact policies only on SAS doubles and text, and T02's volatile `load_ts`)
- [x] 3.6 Estate-wide Discover (`lansh.discover.estate`: the DAG, its waves and tagged flows across jobs; the waves match §7.2 exactly, by test)
- [x] 3.7 Defect review and register (47 suspected defects in `defect_register.md`; planted bugs flagged 8/8, labelled traps detected 81/82; all 41 answer-key checks give the legacy result on the migrated outputs)
- [x] 3.8 Tests for all jobs (55 trap tests passing: T-SQL expected values from SQL Server, SAS contract checks)
- [x] 3.9 Operate (full) (`lansh run --all`: 5 waves cut over on Delta with chained inputs, every output reconciled again; schedule files, SLA checks, OpenLineage events)
- [x] 3.10 Comparison runs (sqlglot alone 0/10, one-shot Claude 8/10 with its 2 misses silently wrong on 805 rows, one-shot then LANSH's heal loop 10/10, LANSH 10/10 first time; `runs/dev-estate/benchmark.json`)
- [x] 3.11 Factory freeze and held-out run (frozen 03:29 UTC, `a15acd7a…`; first run: X2 MATCH, X1 escalated at H3 by a failing trap test; both planted bugs flagged with the planted diagnosis; after two generic post-freeze fixes, a second run, reported apart: 2 of 2 MATCH)
- [x] 3.12 EXL samples (not received: nothing to import)
- [x] **G4** Estate reconciled (accepted by the agent, overnight run, 12 Nov; evidence: `make check` 666 passed plus the known failure, `lansh audit verify` intact, `lansh freeze` unchanged since freeze 2 with freeze 1 reproduced, all 9 T-SQL golden hashes reproduced; packet in `docs/gates.md`)
- [x] 4.1 Control Tower UI (every page, and every job's 9 tabs, render without an exception for all 7 runs under Streamlit AppTest; `lansh ui` serves)
- [x] 4.2 Showcase run and replay (the agent's: `runs/showcase/` published from `dev-estate`, with both held-out runs; `make demo` replays T04 to MATCH in 64 s with SQL Server stopped; the whole estate replays in 8.5 min with no live call. The person-signed showcase run is the team's: Appendix E)
- [x] 4.3 Scorecard and business case (`runs/showcase/scorecard.md`: every number with its files and their SHA-256; projection onto 1,600 jobs with labelled assumptions)
- [x] 4.4 Documentation (`docs/architecture.md` and `docs/responsible-ai.md` with final numbers, `AI_USAGE.md`, `THIRD_PARTY.md` current; the README is the team's, its proposed text is in the G5 packet)
- [x] 4.5 Fresh-clone test (on a copy of exactly what git would publish: two blockers found, see G5; with the Markdown deliverables added, `make setup` and `make demo` work and `make check` gives the same result as here)
- [ ] **G5** Release candidate (packet ready in `docs/gates.md`; not accepted, because the README and the `.gitignore` decision are the team's; `.env.example` restored and the work pushed as `b1568b2`)
- [ ] Tier 2 items (re-prioritised by the review, Appendix G: CI is 5.11 and X3 is part of 5.17; T07 and S02 are deferred)

Phase 5, as revised by the review (§4, Appendix G); 3.1 above is now 5.2:
- [ ] 5.1 A repository that sets up from a clone (P0): `.gitignore`, the freeze record and freeze 3, README, declarations
- [ ] 5.2 Manual baseline (P0, the team's)
- [ ] 5.3 Showcase run with a person's sign-offs, keeping the comparison and scoring evidence (P0, the team's)
- [ ] 5.4 Scorecard v2: measured where possible, every assumption labelled (P0)
- [ ] 5.5 Bias table (P0)
- [ ] 5.6 Lineage you can see (P1)
- [ ] 5.7 Control Tower landing view (P1)
- [ ] 5.8 One-page architecture diagram and Responsible AI note (P0)
- [ ] 5.9 Deck (P0)
- [ ] 5.10 Demo video (P0, the team's)
- [ ] 5.11 CI (P1)
- [ ] 5.12 Bug bash (P0)
- [ ] 5.13 Pre-publication checks (P0)
- [ ] **G6** Publish
- [ ] 5.14 Go public (P0, the team's)
- [ ] 5.15 Submit (P0, the team's)
- [ ] 5.16 Finale kit
- [ ] 5.17 Finale extras (P2)

---

## Appendix E. Progress log

| Date | Event |
|---|---|
| 10 Nov | Spikes: sqlglot on a T-SQL procedure, Spark collations, saspy on Python 3.14. Plan v1. |
| 10 Nov | Plan v2: named LANSH; data sources; bronze/silver/gold; Claude via our subscription; deliberate legacy bugs. |
| 10 Nov | Plan v3: Java 21 installed and verified; pandas below 3; manual baseline added. |
| 10 Nov | Environment verified: SQL Server password fixed; smoke test 5/5. |
| 10 Nov | Plan v4, after an independent review. Timing and people removed. Technical fixes: collations, sandbox escapes, literal check, `_row_seq`, `surrogate`/`exclude` policies, SAS export formats, `--setting-sources ""`, semantic vs construct traps. Business case: cost model, gate load, sensitivity, pilot KPIs, positioning. Responsible AI section (§10). Azure target state. Comparison runs and held-out jobs in Tier 1. |
| 10 Nov | G0 approved (instruction to implement Phases 0–1). 0.2 scaffold: `lansh` package and CLI, Makefile on Java 21, `make check`, AGENTS.md/CLAUDE.md, AI_USAGE.md, THIRD_PARTY.md, setup guide, smoke test 5/5. Creating the GitHub repo and pushing were held back: a permission check stopped the upload, so the team decides. |
| 10 Nov | 0.3 contracts (53 models) revised after an independent review: 1 blocker (stateful T02 batches) and 13 major issues fixed before the freeze. 0.4 spikes, all independently verified: SQL Server under compose (image pinned by digest); SAS exact round trip (`BEST32.` is lossy, so a `HEX16.` sidecar is added; §7.3 corrected); Claude backend recorded and replayed; Spark reconciliation with collations (datacompy agrees). G1 packet written. |
| 10 Nov | 1.1 synthetic insurer: 9 tables, 177,189 rows, two runs byte-identical, SQL Server load verified by content hash. 1.5 held-out X1 and X2 written by an isolated `claude -p` session in a dontAsk sandbox, verified without reading the code, sealed. |
| 10–11 Nov | 1.2 and 1.4: agents wrote T01, T02, T04, T05, T06, T08 and S01; independent reviews passed T01, T04, T05 and T06, and translatability probes reproduced T05 and T06 exactly in PySpark. The subscription's 5-hour usage limit then stopped the remaining agents mid-run. T03, S03 and S04 were written directly. Independent reviews of T02, T08, T03, S03 and S04 found real issues, all fixed: T03's `earned_pct` became DECIMAL so its integer-division trap is truly armed; S04's rounding check now matches Spark, the rounding-unit trap got its own check, and S04 now produces all three tiers. Agent scratch re-implementations of T05 and S01 were deleted to keep the manual baseline AI-free. |
| 11 Nov | 1.3 and 1.6: T01–T03 frozen, then all 10 golden outputs captured (SQL Server 16.0.4305.5, SAS 9.04.01M9); `make legacy-verify-all` reproduces every hash from a fresh rebuild. 1.7: the answer key passes its tests (82 traps, 8 bugs, 52 checks, all passing). G2 packet written. |
| 11 Nov | Tidy at the G1/G2 review. Docs consolidated: the setup guide is in `README.md`, the gate packets are in `docs/gates.md`, the style guide and answer-key notes are in `estate/README.md`, the spike reports are in `spikes/README.md`, and `compose.yaml` is at the root. Every Python module, test and spike was redocumented in the house style (AGENTS.md "Code style"), and an AST comparison proves no code changed. T06's `cum_0..cum_6` renamed `cumulative_0..cumulative_6`, with T06's golden output recaptured (same values). No AI signatures in commits or code from now on (CLAUDE.md), and the trailers were removed from the unpushed history. The generator's claim frequency was found to be 4–6× realistic (loss ratios about 350%); the fix is decision 4 in the G2 packet. |
| 11 Nov | G1/G2 review fixes. Estate recalibrated: realistic claim frequency (paid claims about 64% of earned premium, was about 350%), 20,000 customers, 232,267 rows; planted policy dates no longer collide with renewals or predate their customer; six claims mis-keyed for T08; S04's tiers retuned. All 10 goldens recaptured, every label count re-measured, the held-out jobs re-verified blind; all 53 checks pass and `make legacy-verify-all` reproduces all 10 jobs. 33 code review findings fixed, each with a test; the factory-isolation test is now an AST check. Pushed as a single private commit to `Auslogger/Agentic-Data-Platform-Modernisation`; the `.gitignore` keeps Markdown out. |
| 12 Nov | Handoff for the overnight run. `c870e52` (the re-measured answer key) pushed; it is the last commit. `AGENTS.md` now opens with the overnight-run rules (one agent working alone, which accepts gates itself, may edit this plan and doesn't commit), the state of play, the environment and the challenge's standards. Next: accept G1 and G2, then Phase 2. |
| 12 Nov | Overnight run starts. G1 and G2 accepted by the agent: `make check` 488 passed plus the known failure, `make smoke` 5/5, `make legacy-verify-all` reproduced all 10 golden hashes, T04 checks 5/5. Decisions: contract freeze approved; SAS-16 a card planted nowhere; `.gitignore` and `.env.example` left as the team left them. Next: 2.1. |
| 12 Nov | 2.1 done. `lansh.reconcile.engine` is the spike's engine plus case-insensitive names, masked `pii` samples, missing/extra samples, explanations and double totals within summation-error bounds; `signatures` names 9 diff patterns, including filters that ignored case or trailing spaces. The harness: `lansh.lakehouse` stages inputs as each legacy engine saw them (SAS sees T-SQL outputs in key order) and conforms outputs to their typed tables; `lansh.generate.worker` runs a module in its own process with a timeout and stripped environment; `lansh reconcile --job ID --candidate FILE` and `lansh template` exist. A deliberately naive T04 is caught with every mistake named: TSQL-01 (49 rows), TSQL-02 (11), TSQL-05 (99), BUG-03 fixed (268, exactly 2x). `make check`: 505 passed plus the known failure. |
| 12 Nov | 2.2 done. The usage-limit detector no longer matches "Context limit reached" and now catches a limit worded inside a result the CLI calls a success. `lansh.llm.answers` holds the seven agent answer models (lineage, trap scan, translation, fix, test author, defect review, contract). `ClaudeGateway.ask()` stamps each usage record with the run and stage and appends it to the run's `llm_usage.jsonl`. 60 offline gateway tests pass; `make test-live` made its one live call. |
| 12 Nov | 2.3 done, with the Tier 2 hash chain brought forward because it is small. The gate log refuses a gate before the one ahead of it, an approval with blockers, warnings without a reason and a decision made before the evidence was shown; re-deciding an earlier gate retires later approvals; approvals under 20 s are flagged and a seeded 10% are picked for re-review. Reviewers are `person:` or `agent:`, so an agent's development approvals can never pass for a person's sign-off (`human_signoff`). |
| 12 Nov | 2.4 done, and 3.2 with it, because the trap scan needs the cards. The 35 cards are written as generic engine knowledge, with no example copied from a development job, so the held-out jobs test generalisation. Discover on T04 took 2 live calls (77 s, about $0.34 API-equivalent): 47 verified lineage edges, with sqlglot composing its own lineage through the three temp tables and agreeing on all 20 columns; 15 trap findings. The Lineage agent flagged BUG-03's payment fan-out unprompted. The cross-check traces only explicit projections: T01's `SELECT v.*` temp tables are not expanded. |
| 12 Nov | 2.5 done. Every output's candidate keys come from its DDL primary key and a search of the golden output: an IDENTITY key gives way to the business key (T02 `policy_id, valid_from`); SAS ids stored as doubles still count; amounts never do. Policies default to exact; volatile columns `exclude`, SAS doubles `float_rel` 1e-9 and SAS text `blank_is_null`, each with its reason. H2 refuses a text tolerance on a T-SQL output unless the job sorts text under a collation (TSQL-19): the demo's `ci_rtrim` on T04's `status` is blocked as a tolerance with no reason. Tags flow from the dictionary through each job's lineage and the upstream contracts, so S04's age loading inherits `protected` from T01. Design change: IDENTITY keys stay `exact`, not `surrogate`, because SQL Server assigns them in the INSERT's ORDER BY and a faithful migration can reproduce them. |
| 12 Nov | 2.6 done. Guardrails: syntax-tree allowlist, banned I/O and engine APIs, SQL strings parsed with sqlglot and every string scanned, the literal check (a data literal needs provenance in the legacy code, contract, params or a trap card; short strings must be a whole legacy literal or word; the module's own aliases are names), and ruff. The Translator agent's first T04 module reconciled MATCH on all 823 rows with the golden content hash reproduced exactly (`88c866643793`), BUG-03 reproduced and marked `# LANSH-DEFECT`. The Test author wrote 12 cases; running the legacy job on each in a scratch `LanshTest` database gave the expected values; all 12 pass (25 s). Cost of T04 so far: 5 live calls, about $1.0 API-equivalent. |
| 12 Nov | 2.7 done. `tests/fixtures/t04_broken.py` is the factory's T04 with two traps undone (case-sensitive status filter, mm/dd/yyyy). It reconciled MISMATCH (60 rows missing, 740 differing); the Fixer diagnosed both faults in one attempt (32 s), and the patch passed the guardrails and reconciled MATCH with the golden content hash. A patch that fails the guardrails or brings an unexplained literal is not run, and the reason goes to the next attempt. Generated code (`migrated/`, `tests/fixtures/`) is now excluded from ruff, because reformatting it changes what recorded answers were asked about. `make check`: 571 passed plus the known failure. |
| 12 Nov | 2.8 done. The Defect reviewer listed 4 suspected defects in T04: the payment/reserve fan-out (BUG-03), whose impact query measured 289 rows and EUR 1,288,029.36 on the golden output, exactly the answer key's figures, merged with the translator's marker for the same lines; the NULL claim reference (109 rows, trap TSQL-05); and two latent issues with no impact on our data. 1 live call, 40 s. |
| 12 Nov | 2.9 done, built to cover 3.9 as well. T04's accepted module wrote `lakehouse/gold/claims_summary` as Delta, which reconciled MATCH against the golden output. Its SLA check passed (7.1 s against 600 s; 823 rows, expected 823 ± 10%), and its OpenLineage `RunEvent` records 4 input datasets and the column lineage of all 20 output columns. |
| 12 Nov | 2.10 done, and G3 accepted. `lansh run-job T04` takes T04 through all five gates in 170 s: MATCH, BUG-03 reproduced and flagged (289 rows, EUR 1,288,029.36), 12 trap tests passing, the Delta output reconciled again, and the evidence report written. Gate evidence is pinned by a hash of what it says (timings dropped), so replaying the run reuses every decision; a person can decide in the terminal, or later with `lansh approve` once the run pauses at a gate. The legacy answers to test inputs are recorded, so `make test-e2e` runs T04 end to end with SQL Server deliberately unreachable. Next: Phase 3, the whole estate. |
| 12 Nov | Estate run `dev-estate` started (live recording, agent reviewer). Wave 1 so far: S01 (the first SAS job) and T01 both MATCH on the first translation, with no healing (S01: 2,911 rows; T01: 20,000 rows); T04 replays. 3.6 done: Discover's waves equal §7.2. Written while the run goes: the scoring module (`lansh estate score`, evaluation only; S01 detects 7/7 labelled traps and its planted bug), the comparison runs (`lansh benchmark`: sqlglot alone drafts 4 of 10 jobs; T02, T05 and T06 have MERGE, a cursor or UPDATE, and SAS has no dialect), the scorecard and business case (`lansh scorecard`, every number pinned to its source files by SHA-256), the Control Tower (`lansh ui`), `make ui` and `make demo`, drafts of `docs/architecture.md` and `docs/responsible-ai.md`, the `AI_USAGE.md` update, and `baseline/timesheet.csv` for the team's manual baseline. |
| 12 Nov | The estate run's wave 1: S01, T01, T04 and T05 MATCH on the first translation and were cut over on Delta (H5, wave 1). T06 and then T02 were blocked at H3 by literal-check false positives: a name built from parts, `"d" + str(n)` and `"s." + name`, and an error message that reproduces SQL Server's MERGE error. Both are fixed generically (Appendix F). The run was restarted in the same run id, where it replays every recorded answer and reuses every decision whose evidence is unchanged. The bug-reproduction proof (`prove_reproduction`) runs the answer key's own checks on the migrated outputs in a scratch `LanshProof` database: T01 9/9, T04 5/5 and T05 5/5 give the legacy results. The scorecard's projection now states its assumptions (30% of a real estate's jobs with warnings, 15% escalated), because every development job carries a planted bug and our escalation rate is 0, which would overstate the saving. |
| 12 Nov | Estate run `dev-estate` complete: **all 10 development jobs MATCH record for record on the first translation, with no healing**, every wave cut over on Delta with chained inputs and reconciled again (H5 for waves 1–5). 165,412 legacy rows proved; 8 of 10 outputs have content hashes identical to the legacy outputs, and S03 and S04 match within their declared SAS-double tolerance. 55 trap tests pass. The gate log is intact (123 entries, 47 decisions, all the agent's). Scored against the answer key: planted bugs flagged 8/8, labelled trap occurrences detected 81/82, trap findings 82% precise; all 41 answer-key checks give the legacy result on the migrated outputs. The literal check needed 4 generic fixes (Appendix F), and a missing upstream Delta table is now an H5 blocker, not a crash. A person can now accept an unexplained literal (`lansh accept-literal`, pinned to the module's hash) and decide defects and flows in the terminal, with `lansh decide` or in the Control Tower. |
| 12 Nov | 3.10 done: the comparison runs, each reconciled against the same golden outputs under the same contracts (`lansh benchmark`, `runs/dev-estate/benchmark.json`). **sqlglot alone: 0 of 10.** Six jobs can't be drafted (SAS, MERGE, UPDATE, a cursor). T01, T03 and T08 fail in Spark on T-SQL that sqlglot doesn't transpile, even with its optimizer typing the queries from the input schemas: `RTRIM(x) + ' '`, `CONVERT(..., 103)` and ROUND's truncate mode. T04 runs and differs on all 823 rows. **One-shot Claude: 8 of 10.** It uses the same model and effort, and the same module interface, but none of LANSH's knowledge (trap cards, language rules, draft, notes) and no healing. Its two misses ran cleanly and were silently wrong on 805 rows. Both are legacy behaviour it "fixed": S01's missing-amount buckets (86 rows, BUG-08's) and S04's `MEDI` truncation (654 rows, BUG-10, SAS-11), plus SAS ROUND at the halfway point. **LANSH's heal loop alone repaired both, in one attempt each** (S01 297 s, diagnosing SAS-02; S04 58 s, diagnosing SAS-11). These are the first genuine heals, and the Control Tower's Scorecard page shows their timelines. **LANSH: 10 of 10, first time.** The first one-shot attempt's prompt lacked the factory's example of the input keys, and two SAS jobs failed on `inputs["fact_premium_earned"]`. That attempt was discarded, and the baseline re-run with the factory's interface text, shared in code. The factory's own prompts stay byte-identical, so every recording still replays. 12 live calls kept, 4 discarded; dev-estate now totals 70 live calls, $12.67 API-equivalent. The scorecard counts replayed answers at their recorded time: 5.3 minutes per job end to end with every call live. |
| 12 Nov | 3.11 under way. The factory was frozen at 03:29:16 UTC (`lansh freeze --write`: SHA-256 `a15acd7a…`, 53 files). The freeze covers every module, prompt and trap card that decides a job's outcome; the CLI, Control Tower, reports, comparison runs and scoring stay outside it, and `lansh freeze` checks it. The seal verified, and X1 and X2 were unsealed and added to the inventory. Their goldens were captured on a fresh SynthInsureDW: X1 126 rows (`8db4e15f…`), X2 79 rows (`0978475d…`), the counts of the blind re-verification. The held-out run `dev-holdout` started. Held-out jobs now run only when named (`lansh run --all` means the development estate), and four Phase 1 tests that assumed an inventory without them now describe the development estate. |
| 12 Nov | Held-out run `dev-holdout`: X1 and X2 ran once on the frozen factory (`lansh freeze` reported it unchanged before and after), and the results are reported as they came out. **X2: MATCH on the first translation**, with a content hash identical to the legacy output's, cut over on Delta. Its planted bug (the reserve `ROW_NUMBER` partition leaves out `reserve_type`) was flagged with the planted diagnosis, measured at 43 rows, the author's own count. **X1: escalated to a person at Generate**, because 1 of its 13 trap tests failed: a broker ratio exactly on the 0.75 threshold. Its planted bug (claims paid limited to claims notified in the same year) was flagged with the planted diagnosis (X1-D1, 87 rows, EUR 1,388,119.21). Diagnosed afterwards, outside the run: on the full data the module differs on 3 of 126 rows, by one rounding step in `paid_to_written`. SQL Server truncates a DECIMAL quotient to its result scale (15000.99/20000 gives 0.750049, where Spark rounds to 0.750050), and card TSQL-07 wrongly said intermediate results are rounded. The trap test caught the error before reconciliation did. The author's bug checks turned out to compute each bug from the source tables alone, so they size the bug (X1 120 rows, X2 43) but can't prove reproduction; the scorecard now counts a held-out bug as reproduced only when its job MATCHes (1 of 2). 12 live calls, $2.95. |
| 12 Nov | 3.11 done, with the learning loop the held-out run prompted, reported apart from the held-out result. **Two generic fixes (Appendix F).** First, card TSQL-07's fix guidance now states that SQL Server truncates a DECIMAL quotient toward zero at its result scale, measured on SQL Server 2022, with a Spark recipe; its `legacy_behaviour` sentence stays as it was, since every trap-scan prompt quotes it. Second, the literal check no longer reads a type's precision and scale as data: inside SQL text (`CAST(x AS DECIMAL(38,10))`), or as an integer from 0 to 38 that the module declares in a decimal type and passes to a scale-taking call. Re-translated under the corrected card, T03 first stopped at H3 on its derived scale 13 and X1 on the 38 inside its SQL `CAST`; with the second fix both reconcile MATCH, content hashes identical. X2 re-translated MATCH. T03 stays MATCH in `dev-estate`, so the estate is still 10 of 10. The learning run `dev-holdout-learn` gives **2 of 2 held-out jobs MATCH**, X1 passing all 13 trap tests, the 0.75-threshold case included. **The freeze record keeps both freezes.** `lansh freeze` now keeps per-file hashes and a history. Freeze 1 (the held-out run's) was reconstructed by putting the frozen `trap_cards.yaml` and `guardrails.py` back, which reproduces its hash `a15acd7a…` exactly. Freeze 2, `5832b65d…`, differs from it in those two files only. 4 live calls. |
| 12 Nov | G4 accepted by the agent: the packet is in `docs/gates.md`, every Phase 3 "done when" holds, and the evidence commands pass (`make check` 666 passed plus the known failure). Next: Phase 4, starting with the showcase (`lansh showcase --from dev-estate --holdout dev-holdout --learning dev-holdout-learn`) and an offline check of `make demo`. |
| 12 Nov | Phase 4 built and checked. **4.1:** under Streamlit AppTest the Control Tower renders every page, and every job's 9 tabs, for all 7 runs without an exception. It renders a missing evidence report from its JSON, lists the showcase's held-out runs, puts LANSH beside the comparison approaches, and shows the heal timelines. **4.2:** `lansh showcase --from dev-estate --holdout dev-holdout --learning dev-holdout-learn` publishes `runs/showcase/` (6.6 MB, 336 files). Absolute paths become repo-relative; the gate logs stay byte-identical, and all three chains verify. Publishing refuses any file that still names the home folder. `make demo` replays T04 to MATCH in 64 s with SQL Server stopped and no Claude call, and `lansh run --all --mode replay` replays the whole estate in 8.5 minutes, every module byte-identical. **4.3:** `runs/showcase/scorecard.md`. **4.4:** both one-page notes tightened, with final numbers. **4.5:** fresh-clone test on a copy of exactly the files git would publish. It found that `make setup` stopped on the missing `.env.example`; the Makefile now skips that copy when there's no example. It also found that `pyproject.toml` needs `README.md`, which the `.gitignore` excludes with every `*.md`: the team's decision, flagged in G5. With the Markdown deliverables added, `make setup` and `make demo` work and `make check` gives the same result as here. |
| 12 Nov | G5 packet written; it is not accepted overnight, because it needs the team's README and `.gitignore` decision. The overnight run stops here; what the team needs to do is listed under the table. |
| 12 Nov | At the team's request: the `.env` template restored as `tests/fixtures/.env.example` (the Makefile, `lansh.config` and the scaffold test point there; `make setup` copies it again), so `make check` passes in full, 667 tests. The overnight work was then committed in ten commits by area, the two earlier commit messages were reworded (same trees and dates), and `main` was force-pushed to the private repo: `b1568b2`. A secrets scan of every pushed file and of both earlier commits found no `.env` value, `~/.authinfo` credential, home path, key or organiser address (only the dummy `sk-ant-` strings in the gateway tests). README.md is untouched; Markdown is still ignored, so docs and README stay local. |
| 12 Nov | Critical review of the whole repo against the brief and rubric, at the team's request (Appendix G). Re-ran `make check` (667 passed, 3 min 20 s), a fresh clone (`uv sync` fails: no README.md), `lansh freeze` (CHANGED: `config.py`, after the `.env` template move) and `lansh audit verify` (intact; 0 decisions by people). Finding: the factory is ahead of the brief; the submission isn't (no pack, an unclonable repo, an assumption-driven headline, no person's sign-off). Plan v5: Phase 5 rewritten in priority order (P0, P1, P2), §9.3's sensitivity corrected, the 3-minute video cut added to §14, risks and checklist extended, Tier 2 re-prioritised. One independent agent, at the team's request, then reviewed the review (G.4). No code changed. |
| 12 Nov | The critical review reviewed by one independent agent, at the team's request (G.4); each of its claims re-checked before use. **Corrected:** the defect counts (46 measured, 20 non-zero); the hook (the one-shot "fixed" planted bugs, so "silently changed", not "wrong"); the freeze record (unpublished, so a clone gives no verdict); the injection claim (omissions aren't caught); the G1/G2 wording; two generic fixes, not one. **Added:** G5 decision 3's and item 4's re-publish would delete the comparison and scoring evidence, so 5.3 now rebuilds it first; the planned sensitivity would print 98–99% and 49%, so 5.4 is a two-way table led by headcount; the baseline's independence; per-job documentation as a benefit; the private plan's citations. **Re-prioritised:** the bias table to P0 (measured: under-25s HIGH-tier 14.3%, against 5.3–5.4% at 25–59); lineage graphs before the landing view; the second reporting date to the finale extras. Phase 5 renumbered 5.1–5.17. No code changed. |

### For the team (from the overnight run)

The overnight work is committed and pushed (`b1568b2`, private repo). Markdown is still ignored, so this plan, `docs/gates.md`, `AGENTS.md` and the README exist only in the working tree. These steps are the team's.

**The revised Phase 5 (§4) now sets the order.** This list keeps its commands, and maps onto it:

| Item | Phase 5 step |
|---|---|
| 2 | 5.1 |
| 3 | 5.2 |
| 4 | 5.3 |
| 5 | 5.7 and 5.12 |
| 6 | 5.10 |
| 7 | 5.9 |
| 8 | 5.13 |
| 9 | 5.14 and 5.15 |
| 10 | After submission (Appendix G.2) |

1. ~~Review and commit the work.~~ Done at the team's request: ten commits on `origin/main`, ending at `b1568b2`. Review them on GitHub.
   - The `runs/dev-*` folders are the overnight runs' full local evidence and stay ignored.
2. **The G5 decisions** (`docs/gates.md`, Gate 5):
   - un-ignore the Markdown deliverables;
   - ~~restore `.env.example`~~ done, at `tests/fixtures/.env.example`;
   - adopt the proposed README, with the video links;
   - choose a licence (D3), and settle the author email in `pyproject.toml`.
3. **The manual baseline (3.1, §9.1).** A person migrates T05 and S01 by hand with every AI tool off, timing each task in `baseline/timesheet.csv`.
   - Before finishing, don't open `migrated/jobs/t05.py` or `s01.py`, the T05 or S01 folders of any run (`runs/showcase/` included), or the cassettes.
   - The kit:

     ```bash
     uv run lansh template --job T05 --out baseline/t05_manual.py
     uv run lansh reconcile --job T05 --candidate baseline/t05_manual.py
     ```

   - `lansh scorecard` then puts the measured minutes first in the business case.
4. **The showcase run with a person's sign-offs.** This replaces the agent's approvals in `runs/showcase/`:

   ```bash
   uv run lansh run --all --run showcase-live --reviewer person:<name> --interactive --mode replay
   uv run lansh showcase --from showcase-live --holdout dev-holdout --learning dev-holdout-learn
   uv run lansh scorecard --run showcase --holdout showcase/held-out --learning showcase/learning
   ```

   Expect about 120 decisions, and read each one: approvals under 20 s are flagged. `--mode live` re-records the answers, on an account with headroom.

   **Correction (Appendix G, G-T9):** between the first two commands, run step 2 of PLAN step 5.3. `lansh showcase` replaces `runs/showcase/` with only what `showcase-live` holds, and an estate run writes no comparison runs, scores or adjudication.
5. **Look at the Control Tower by eye** (`make demo`) before recording. It was checked headlessly only.
6. **The demo video (5.10).** At most 3 minutes, recorded in replay mode along §14's path, then uploaded to YouTube (unlisted), OneDrive and Google Drive.
   - Step 5 now has real heals: the Scorecard page's heal timelines for one-shot S01 and S04.
   - Step 7 has the comparison runs and the held-out results.
7. **The deck** (at most 10 slides). Its numbers are in `runs/showcase/scorecard.md`; declare the AI tools as in `AI_USAGE.md`.
8. **Pre-publication checks (5.13),** after the `.gitignore` change. Check every file git would publish:
   - for the home path, `.env` values, `sk-ant-`, `AKIA`, `BEGIN ... PRIVATE KEY`, any `*.pptx` or `*.pdf`, and the organiser's address;
   - for example `git ls-files -co --exclude-standard | xargs grep -lF "$HOME"`.
9. **Go public (5.14) and submit (5.15).** Making the repo public, tagging `v1.0.0`, checking that an anonymous clone runs `make demo`, and the submission email are the team's.
10. **Card TSQL-07.** When the recordings are next refreshed, amend its `legacy_behaviour` sentence too (Appendix F).

---

## Appendix F. Learning log

Every factory fix found while migrating the estate (plan step 3.3). Each fix is generic: none names a job, and each comes with a test. The count per wave is the learning curve (§15).

| Wave | Found on | What went wrong | Generic fix | Test |
|---|---|---|---|---|
| 1 | T06 | The literal check read the string part of a column name built in code, `F.col("d" + str(n))`, as a data literal, and blocked H3 | String parts of a name built with `+` or an f-string in a naming position count as names. Data built from parts is still checked | `test_names_built_from_parts_are_names` |
| 2 | T02 | The literal check again read alias-qualified name parts, `F.col("s." + name)`: the same cause as T06, already fixed after the running estate process started | (the wave 1 fix) | `test_names_built_from_parts_are_names` |
| 2 | T02 | The translator reproduces SQL Server's own MERGE error for duplicate source rows, `raise RuntimeError("The MERGE statement attempted to UPDATE ...")`, and the literal check read the message as data | The message of a `raise` or an `assert` is not data: it never reaches an output | `test_exception_messages_are_not_data` |
| 2 | T08 | The translator rendered `LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'` as the regex `(?is)^[0-9][0-9].*-[A-Z].*-[0-9]`, as card TSQL-14 prescribes, and the literal check found the whole regex nowhere in the legacy code | A literal that is legacy text joined only by a card's syntax tokens (`^`, `.*`, regex flags) derives from the legacy code; a hard-coded value (`^300035$`) still leaves a foreign piece. TSQL-14 also allows the `(?s)` and `(?is)` flags | `test_like_patterns_translated_by_the_card_derive_from_legacy` |
| 4 | S03 | The module parses its own `&as_of` parameter defensively with `re.fullmatch(r"-?\d+", text)`, and the literal check read the Python pattern as a data literal | A pattern given to Python's `re` module parses the job's own text, never data, so it is a name-like string. Spark's `rlike` and `regexp_*` patterns, which touch data, stay checked | `test_python_re_patterns_are_not_data` |
| after the freeze | X1 (held-out) | Card TSQL-07 said DECIMAL intermediate results are rounded at each step, but SQL Server truncates a quotient toward zero at its result scale (15000.99/20000 gives 0.750049; Spark's quotient rounds to 0.750050). The translator followed the card, a trap test at X1's 0.75 threshold failed, and X1 escalated; on the full data 3 of 126 rows differ by one rounding step | The card's fix guidance states the division rule, measured on SQL Server 2022, with a Spark recipe (divide at a higher scale, truncate toward zero at the T-SQL scale, then cast), and its constants are allowed literals. Its `legacy_behaviour` sentence is left as it was, because every trap-scan prompt quotes it and changing it would invalidate every T-SQL recording; amend it when the recordings are next refreshed | `test_tsql07_division_recipe_reproduces_sql_server` |
| after the freeze | T03, X1 (re-translated under the corrected TSQL-07) | The literal check read a type's precision and scale as data. T03's translator passed T-SQL's quotient scale, 13, to its own truncation helper (`int / int` on `DECIMAL(25,2)` has scale 13, which the legacy code never writes); X1's SQL text held `CAST(num AS DECIMAL(38,10))`. Both blocked H3 | A number inside a SQL type is never a literal; an integer from 0 to 38 that the module declares in a decimal type (a type string, `DecimalType`, or a SQL `CAST`) and passes straight to a scale-taking call (`F.round`, `F.floor`, ..., or the module's own function) is a type constant. The same number in a comparison, or a scale the module never declares, still needs provenance | `test_a_types_precision_and_scale_are_not_data` |

---

## Appendix G. Critical review (12 Nov)

**What was reviewed:**
- the brief (the EXL deck, slides 3–16) and its rubric;
- this plan, the gate packets, the README, the two one-page notes, `AI_USAGE.md`, `THIRD_PARTY.md` and `AGENTS.md`;
- the factory's code, the migrated jobs, the showcase run and its scorecard;
- what git actually publishes.

**Re-run for the review:**
- `make check`: 667 passed in 3 min 20 s;
- a fresh clone of `main`, then `uv sync`;
- `lansh freeze`;
- `lansh audit verify` on the three showcase runs.

An independent agent then reviewed this review. Its corrections were each re-checked, are folded into the findings below, and are listed in G.4.

**Verdict.** The factory and its evidence are ahead of what the brief asks: real-engine ground truth, record-for-record proof, honest held-out and comparison runs, and 667 passing tests. The submission is not:
- the pack that pre-screening scores doesn't exist yet;
- a clone can't be set up;
- the business case's headline is an assumption;
- no person has signed a gate.

Phase 5 is rewritten around these four gaps (§4), and adds almost nothing to the factory.

### G.1 Findings

Each finding names the Phase 5 step that answers it.

**Business Impact (30%, and the tie-break)**
- **G-B1 The headline saving is an assumption restated.** `lansh/scorecard.py` fixes the reviewer time at 5 minutes a gate, per-job review for 30% of jobs, and the escalation rate e at 15%.
  - **The formula.** The saving is ((1 − e) × m − R) ÷ (m + c), for manual minutes m, review minutes per job R (5.0 under risk-based gating) and golden-capture minutes c. With R small beside m, that is about 1 − e: the low, middle and high cases all print 83–84%. A judge who does the arithmetic sees an input, not a result.
  - **Varying e alone doesn't help.** At 0% the saving prints 98–99%, which nobody believes. At 50% it prints 48–49%, just under the 50% that EXL measured for Code Harbor.
  - **Measured review time would be biased low.** Defect and flow decisions are taken before H2's evidence is shown, and carry no review time of their own (`pipeline.py`, where `_decide_defects` runs before `pass_gate`).

  → 5.3, 5.4, §9.3.
- **G-B2 The manual side is assumed,** at 4, 8 and 16 hours per job. The baseline (§9.1) hasn't started: `baseline/timesheet.csv` holds only its header. When it's done, it is a lower bound, made by the estate's builders with the harness in hand, and it's only independent if its person hasn't seen LANSH's T05 or S01. → 5.2.
- **G-B3 No money, and no named users.** The case is in person-hours, but EXL's leaders buy in cost, team size and months. The brief also asks for "clear user benefits", so say who gains and what each gets: migration engineers, data owners, the finance and actuarial users of the reports, and audit. → 5.4, 5.9 (slide 7).
- **G-B4 The defect register is the best business story, and it's buried.** It holds 47 suspected defects: 46 measured on the legacy output, 20 with a non-zero impact, 26 measuring 0 rows; T02-M5 wasn't measured. For example:
  - T04 overstates paid-to-date by €1,288,029.36 on 289 claims;
  - T06's paid triangle leaves out €390,467.67 of payments made on the loss date, across 19 cells;
  - T03 misstates earned premium by €307,279.59 in absolute terms, across 21,145 transactions.

  T04's overstatement is 30% of the €4.27M it reports as paid, which is credible only when labelled as planted. The planted bugs are ours, and nobody has yet measured how many of the rest are real. → 5.3 (triage), 5.4 (precision), 5.9 (label what was planted).
- **G-B5 The register's "Amount" column mixes units.** It prints 8,436.00 for `age_at_join`, 12,045.22 for `earned_pct` and "0.00 (None)". These read as money, and aren't. → 5.7; the deck quotes money only.
- **G-B6 The strongest risk number isn't the hook, and needs careful words.** One-shot Claude ran all 10 jobs without an error, and 2 outputs silently differed from the legacy outputs, on 805 rows. Only record-level reconciliation showed it.
  - **Most of it was "fixes".** The one-shot "fixed" the planted bugs BUG-08 and BUG-10 (86 and 654 rows), and got SAS rounding wrong on about 65 more.
  - **So don't call it "silently wrong".** A judge will reply that the baseline was more correct. The point is that it changed finance numbers nobody had decided to change.
  - **It's a sample of 10.** Quote what happened, never a rate across 1,600 jobs.

  → 5.9 (slide 2), the video's opening (§14).
- **G-B7 "A credible way to measure success" exists, but isn't offered.** §9.4's pilot KPIs appear nowhere a judge looks: not in the scorecard, and not in the README as a pilot proposal with targets. → 5.9 (slide 7).
- **G-B8 The documentation is an unclaimed benefit.** Slide 8 says the estate's logic is undocumented and its lineage unknown. LANSH leaves verified lineage, a data contract and an evidence report for every job. Say so, and say what that means for the accuracy of financial and regulatory reporting. → 5.9 (slide 7).

**Technical (25%)**
- **G-T1 A clone can't be set up.** Reproduced for this review: a clone of `main` has no Markdown at all, and `uv sync` fails, because `pyproject.toml` names the missing `README.md`. The GitHub repo is private and shows no README. → 5.1.
- **G-T2 The freeze record doesn't verify, and isn't published.**
  - Locally, `lansh freeze` prints "CHANGED since the freeze at 2026-11-12T04:13:59+00:00", naming `config.py`: the `.env` template move edited an error message after freeze 2. The G4 packet and `AGENTS.md` still say "unchanged".
  - `runs/freeze.json` is git-ignored (`runs/*`), and `lansh freeze` reads only that file. A clone therefore gives a hash and no verdict, so a judge can't check the "frozen factory" claim, nor `AI_USAGE.md`'s "`lansh freeze` checks it".

  → 5.1.
- **G-T3 The working-tree README is stale.** It says Phases 0 and 1 are built and that G1 and G2 await review. → 5.1.
- **G-T4 Generalisation rests on thin evidence.**
  - Only two held-out jobs, both T-SQL and both written by Claude; there's no SAS held-out job.
  - Every job is proved on one reporting date, the date its tests and the fixer saw.

  → 5.17 (a second date, and more held-out jobs).
- **G-T5 Lineage is invisible.** Column-level lineage is one of the three agent tasks the brief names. The Control Tower shows it as a table, and the OpenLineage events stay files. → 5.6.
- **G-T6 Totals of id columns look naive.** "Total of `claim_id`: 248594498" is a legitimate hash total, but unlabelled it reads like a mistake. → 5.6.
- **G-T7 No CI.** There's no `.github/`, so nothing shows a visitor that the tests pass. The Makefile's Java 21 candidates also miss a runner's JDK path. → 5.11.
- **G-T8 Gaps to own in the Q&A, not to fix before submission.**
  - A failing trap test escalates rather than heals, because the fixer sees only reconciliations. X1 might otherwise have healed.
  - SAS trap tests check the contract only.
  - The defect reviewer is weakest on SAS: BUG-08 and BUG-10 were reproduced but not diagnosed.

  → G.3, 5.17.
- **G-T9 Re-publishing the showcase as planned would delete evidence.**
  - `lansh showcase` deletes `runs/showcase/` (`_publish` in `cli.py`) and copies only the source run.
  - `lansh run --all` writes no `benchmark.json`, `scores.json` or `adjudication.json`, as `runs/replay-check/` shows.
  - So G5 decision 3's commands, and Appendix E item 4's, would drop the comparison runs, the heal timelines and the answer-key scores that slides 2 and 6 rest on.
  - The published `benchmark.json` also points 16 times at the ignored `runs/dev-estate/`.

  → 5.3.

**Innovation (20%)**
- **G-I1 The comparison runs can be misread.** One-shot plus LANSH's heal loop also reaches 10 of 10, so a judge may conclude LANSH's knowledge adds little. The point is twofold:
  - one-shot's failures were silent, and only the proof loop found and repaired them;
  - LANSH's knowledge got every job right first time, with no heal cycles, and found the traps for the reviewer (81 of 82), explaining each at its gate.

  → 5.9 (slide 8).
- **G-I2 The new ideas go by internal names.** For the deck:
  1. bug-for-bug parity, with a defect register that measures each bug's impact;
  2. a trap library that turns the shape of a difference into a diagnosis;
  3. an anti-cheating guard: no constant may appear that the legacy code doesn't justify;
  4. a sealed exam: held-out jobs, opened only after the factory was frozen;
  5. human gates that show pinned evidence first and flag rubber-stamping.

  → 5.9.
- **G-I3 The positioning beside Code Harbor is a strength with EXL's jury, but "Code Harbor included" is untested.** The evidence we have is the one-shot row: wrapped in LANSH's proof loop, a plain one-shot translator goes from 8 to 10 of 10. Claim that, and say Code Harbor could be wrapped the same way. → 5.9.

**Responsible AI (15%)**
- **G-R1 No person has signed a gate.** `lansh audit verify --run showcase` reports "126 entries, 50 gate decisions (0 by people)", and the scorecard prints "Gate decisions made by people: 0". The brief's "humans review at each gate" has no evidence yet. Even after 5.3, the held-out runs stay agent-signed, as they ran. → 5.3.
- **G-R2 Bias is flagged, never looked at.** The agent decided all 11 flows of `protected` columns as "reproduce, flagged for a bias review". S04's legacy output shows what the flag is about: under-25s are HIGH-tier 14.3% of the time, against 5.3–5.4% at 25–59. → 5.5.
- **G-R3 Prompt injection isn't addressed.**
  - **LANSH has a partial answer.** The agents run with no tools, so legacy code, which is untrusted input, can at worst steer an answer, and a steered answer that makes code wrong fails reconciliation.
  - **Omissions aren't caught.** An answer that leaves something out, such as a lineage edge or a defect, isn't caught deterministically. State that as a limitation.

  → 5.8.
- **G-R4 The agent graded its own diagnoses.** The "planted diagnosis" verdicts (6 of 8, and 2 of 2) are the overnight agent's reading. → 5.3.
- **G-R5 Who built what must be said plainly.** Declaring the overnight build is right: the agent built Phases 2–4, and recorded the G1–G4 acceptances under the team's written rules.
  - The team reviewed the G1 and G2 packets on 11 Nov, with fixes, and the agent then recorded their acceptance. Both statements are true, but `AI_USAGE.md` makes only the first.
  - `AI_USAGE.md` and the Responsible AI note speak of the manual baseline in the present tense, as if it were done.
  - The deck and the Q&A need one clear sentence on the team's part: the design, the ground truth, the rules and gates, the decisions, the manual baseline and the sign-offs.

  → 5.1, G.3.

**Presentation and Q&A (10%), and the pack that pre-screening scores**
- **G-P1 The pack doesn't exist.** There's no deck, video, one-page PDF or email draft, and the repo isn't public. → 5.8–5.10, 5.13–5.15.
- **G-P2 The writing is precise but dense, and internal.** The scorecard runs to over 30 rows, and the documents speak of gates, cards, freezes and runs by id. Judges skim, so every deliverable leads with the outcome in plain words. → 5.9, 5.10.
- **G-P3 The Control Tower is a developer console.** The Estate page has five tiles and the DAG, but the comparison, the money and the sign-offs are pages away, and lineage is a table. → 5.6, 5.7.
- **G-P4 The finale is a different test:** a 10-minute pitch, a 5-minute live demo, then questions on approach, evidence and Responsible AI. → 5.16, G.3.
- **G-P5 The published repo would point readers at a private plan, and has no pictures.**
  - About 100 tracked files cite "plan §…".
  - The proposed README says `docs/` holds the plan and the gate packets, which decision 1 keeps private.
  - The README has no diagram and no screenshot.

  → 5.1.

**What's strong, and must stay visible.** The review found that these hold:
- ground truth from the real engines, frozen and hashed;
- record-for-record proof: 10 of 10 jobs and 165,412 rows, 8 content hashes identical, then proved again on Delta with chained inputs;
- an honest held-out result. X1's miss was stopped by its own test, not shipped, and the learning run is reported apart;
- the comparison runs, on the same goldens and contracts;
- the guardrails and the anti-hard-coding check;
- replay of every agent answer;
- intact hash-chained gate logs;
- migrated code that reads well: T04's module cites its traps, the legacy lines and the defects it reproduces, inline.

### G.2 What not to do before submission

- Don't grow the estate (T07, S02) or add trap cards: 12 jobs already meet the brief's 10–15.
- Don't change the frozen factory (53 files in `runs/freeze.json`) except through a recorded freeze with its reason. Report any run on a changed factory apart.
- Don't re-record the cassettes to correct TSQL-07's sentence. It would invalidate every T-SQL recording, for no visible gain.
- Don't re-publish the showcase without 5.3's step 2, which rebuilds the comparison and scoring evidence.
- Don't let an agent touch the manual baseline, or stand in for a person's sign-off.
- Don't present an assumption as a result, or a sample as a rate. That rules out:
  - a 0% escalation case;
  - the held-out 1 of 2 as an escalation rate;
  - the one-shot 2 of 10 as an error rate.
- Don't headline "47 defects": 20 have a non-zero measured impact, and their precision is unmeasured until 5.3.
- Don't claim LANSH has wrapped Code Harbor, or set our projection beside EXL's measured 50%.
- Don't round the held-out result up: 1 of 2 on the first run, then 2 of 2 on a second run, reported apart.
- Don't start the second reporting date or more held-out jobs before submission. Each needs the legacy engines and new code, and a failure found late would have to be disclosed late (5.17).
- Don't change `v1.0.0` after submission. Finale work goes on a later tag.

### G.3 Questions the jury will ask

| Question | Answer, and its evidence |
|---|---|
| You wrote the legacy jobs and the factory. Haven't you marked your own homework? | Partly, and we measured how much. Held-out jobs were written by an isolated agent, sealed, and run once on a frozen factory: 1 of 2 on the first run, then 2 of 2 after two generic fixes, reported apart. The golden outputs come from SQL Server and SAS, not from us, and the comparison runs use the same goldens |
| What did the team build, and what did the AI build? | One sentence, as in G-R5, matching `AI_USAGE.md` |
| How is this different from Code Harbor or Lakebridge? | They translate, or reconcile. LANSH wraps a translator, and adds bug-for-bug parity with measured defects, a trap library tied to the shapes of differences, an anti-hard-coding guard and human gates that show pinned evidence first (§9.5). Wrapped around a plain one-shot translator, it took 8 of 10 jobs to 10 of 10 |
| Your one-shot baseline "fixed" real bugs. Wasn't it more correct than the legacy code? | On those rows, yes, and that's the point. It changed finance outputs nobody had decided to change, and it got SAS rounding wrong on about 65 rows. LANSH reproduces the legacy result, flags the bug with its impact, and leaves the fix to its owner |
| Why trust an LLM with finance and actuarial logic? | We don't. Nothing it writes is accepted until the deterministic checks and a record-for-record reconciliation pass and a person approves. The one-shot run shows why: 2 of 10 jobs ran cleanly and silently changed the numbers |
| Why reproduce bugs instead of fixing them? | A cut-over must change nothing silently. Each bug is measured, and its owner decides; a fix is a separate, approved change after cut-over |
| Your defect reviewer missed the S04 truncation the heal shows. Why? | The trap library caught it: LANSH's translator reproduced it first time (card SAS-11), and the fixer diagnosed it in the one-shot run. The defect reviewer is weakest on SAS, and we report that: 6 of 8 planted bugs diagnosed |
| Can the fixer cheat, say by hard-coding the expected numbers? | No. Every constant must trace to the legacy code, the contract or a trap card, and jobs never see the golden outputs |
| What if there's no golden output, or a job isn't deterministic? | In production, a parallel run supplies the legacy output. Volatile columns get a declared `exclude` (T02's `load_ts`), and ordering ties are broken by `_row_seq` |
| Will it scale to 1,600 jobs, and to SAS programs thousands of lines long? | Waves come from the DAG and programs are split into blocks. Each job takes about $1 and 5 minutes of machine time, and risk-based gating keeps people on the jobs that need them. Macro-heavy SAS and dynamic SQL are the known hard cases |
| What did it cost? | Measured per job: Claude calls, tokens and the API-equivalent cost. The scorecard projects them onto 1,600 jobs |
| What failed? | X1 escalated, because a trap card had SQL Server's DECIMAL division wrong. The literal check needed 5 generic fixes for false positives: 4 during the estate run, 1 after the freeze. The defect reviewer missed two SAS diagnoses |
| Privacy, security, prompt injection? | Synthetic data only, with `pii` masked in anything Claude sees. Agents have no tools, and code passes the guardrails and then runs in a separate worker. A steered answer that makes code wrong fails reconciliation; one that leaves something out isn't caught, and we say so. In production, Claude runs in Microsoft Foundry inside the client's tenancy |
| Bias? | S04's risk score uses age and county. Lineage traces both into the score, a person decides each flow at H2, and 5.5's table shows the effect: under-25s are HIGH-tier 14% of the time, against about 5% at 25–59 |
| Why not Databricks or Azure? | The jobs use only APIs that Databricks supports, and the guardrails enforce that. §6.2 maps each part to Azure. A Databricks Free Edition run can back this up at the finale (5.17) |

### G.4 Review of this review

An independent agent checked every finding against the files and artifacts. It ran at the team's request, the one exception to the rule against subagents. Each of its claims was re-checked before it changed this plan.

**Confirmed:** most findings, and every number in the deck outline and the video cut, including:
- G-B1's arithmetic;
- 823 of 823 rows, and the content hash `88c866643793`;
- 165,412 rows;
- the comparison runs' 0, 8, 10 and 10 of 10;
- 81 of 82 traps, and 8 of 8 bugs reproduced;
- $1.01 and 5.35 minutes per job.

**Corrected:**
- **G-B4:** 46 of 47 defects measured, 20 non-zero (not "20 measured").
- **G-B6:** most of the 805 rows were the one-shot "fixing" planted bugs, so the hook now says "silently changed".
- **G-T2:** the freeze record isn't published, so a clone gives no verdict.
- **G-I2 and G-I3:** "measures" each bug, not "prices"; the Code Harbor claim now rests on the one-shot evidence.
- **G-R3:** verification catches wrong code, not omissions.
- **G-R5:** both statements about G1 and G2 are true.
- **G-P3:** the Estate page already has tiles and the DAG.
- **G.3 and the proposed README:** two generic fixes, not one; five literal-check fixes, not four false positives.

**Missed, now added:**
- **G-T9:** the planned re-publish would delete the comparison and scoring evidence.
- **G-B1:** the sensitivity as first planned would print 98–99% and 49%, and per-gate review times miss defect triage.
- **G-B2:** the baseline's independence from 5.3, and its lower bound.
- **G-B8:** each job's documentation, as a benefit.
- **G-P5:** citations of the private plan; no pictures in the README.
- **Stale step numbers** in Appendix E and `docs/gates.md`.
- **Smaller points:** the held-out runs staying agent-signed, the benchmark's dangling paths, and the commit-convention declaration.

**Re-prioritised:**
- the bias table up to P0, with its figures measured for this review;
- the lineage graphs ahead of the landing view, and the landing view cut down;
- the second reporting date down to the finale extras;
- CI's badge only once the workflow is green;
- the one-page documents and the deck drafted from the start with placeholders.

**Rules:**
- **Changed:** the CI step's test duration was dropped, and the deck outline is labelled as source material under L7.
- **Kept, though judged borderline:** the reviewer judged the findings and the Q&A bank borderline for an implementation plan. They stay here, because steps 5.1–5.16 cite them and the team asked for the review to live in these files.
