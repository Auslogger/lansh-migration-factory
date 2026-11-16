# Gate review packets

One section per gate (PLAN §4), newest last, each in the PLAN Appendix C format. A gate is
closed when its decisions are recorded in PLAN Appendix D.

**13 Nov: completed manual baseline.** The baseline was completed personally and recorded in
`baseline/timesheet.csv`: T05 took 148 minutes and S01 took 169 minutes, with zero differences
left at final reconciliation for each job. The 12 entries record the phase timings and notes.
The scorecard uses the measured average of **158.5 minutes per job**. Steps 3.1 and 5.2 are
complete.

## Gate 1: Foundations

**Asking for:** Approve. Work continued into Phase 1 without a pause, on the instruction to
implement Phases 0 and 1 in one go, so this packet is for retrospective review: anything you
reject here is fixed before G2 closes.

**What was built**
- **0.2 Scaffold.**
  - The package is renamed to `lansh`, with a `lansh` command (typer).
  - The `Makefile` pins `JAVA_HOME` to Java 21, and `make check` runs ruff plus the offline pytest suite.
  - [AGENTS.md](../AGENTS.md) is the condensed §12, and [CLAUDE.md](../CLAUDE.md) loads it.
  - Also added: [AI_USAGE.md](../AI_USAGE.md), [THIRD_PARTY.md](../THIRD_PARTY.md) (generated from package metadata by `make third-party`), [.env.example](../.env.example), the setup guide in [README.md](../README.md#setup) and [scripts/smoke_test.py](../scripts/smoke_test.py).
  - D2 is applied: `docs/` is tracked, and the EXL deck never is.
- **0.3 Contracts.** [src/lansh/contracts.py](../src/lansh/contracts.py) has 53 Pydantic v2 models, and `estate/jobs.yaml` follows `EstateInventory`.
  - An independent review found 1 blocker, 13 major and 14 minor issues, and the models were revised before the freeze (see "Changes from the plan").
- **0.4 Spikes.** Each spike was built by one agent and independently verified by another. All four pass.
  - **SQL Server:** [compose.yaml](../compose.yaml) (image pinned by digest, password from `.env`), `make legacy-up`, and the adapter [src/lansh/engines/mssql.py](../src/lansh/engines/mssql.py).
  - **SAS:** [src/lansh/engines/sas.py](../src/lansh/engines/sas.py), which round-trips tables exactly ([results](../spikes/README.md#sas-round-trip)).
  - **Claude backend:** the gateway seed in [src/lansh/llm/](../src/lansh/llm/): one structured `claude -p` call with the full §8.2 flag set, recorded and then replayed offline ([results](../spikes/README.md#claude-backend)).
  - **Spark reconciliation:** the prototype [spikes/spark_recon.py](../spikes/spark_recon.py). It finds the planted case, space and NULL differences using collations, stores plain strings, and datacompy agrees with it ([results](../spikes/README.md#spark-reconciliation)).

**Check it yourself** (about 10 minutes)
```bash
make check                      # ruff + 339 offline tests, about 35 s
make smoke                      # 5/5: Spark+Delta on Java 21, sqlglot, SQL Server, Claude, SAS
make legacy-up                  # SQL Server healthy in about 7 s
make test-mssql                 # exact round trip through SQL Server
make test-sas                   # exact round trip through SAS OnDemand, about 25 s
uv run python spikes/claude_backend.py   # replays the recorded answer, no Claude call
uv run python spikes/spark_recon.py      # about 17 s; "datacompy agrees with the exact policy"
```

**Evidence**
- `make check`: 339 passed, plus 4 integration tests (`mssql`, `sas`, `live_llm`), all passing when run. `make smoke`: 5/5.
- Contracts: 148 tests. Every model round-trips through JSON and exports a JSON Schema with `additionalProperties: false` and ASCII-only patterns.
- SQL Server round trip is exact for: fadas, trailing spaces, `''` against NULL, CHAR padding, `DECIMAL`, `DATETIME2(6)`, and integers beyond 2^53. `code = 'MOT'` matches `'MOT '`, `'mot'` and `'Mot'` (case- and space-insensitive collation confirmed).
- SAS:
  - 20/20 planted values come back exact through the `HEX16.` sidecar, but only 8/20 doubles survive `BEST32.` text alone.
  - A bulk probe read 4,011 of 4,016 numbers exactly; the other 5 are subnormal doubles, which SAS can't read. All 4,016 random datetimes came back exact.
- Claude:
  - The trap scan of a 10-line T-SQL snippet found exactly the 6 planted traps.
  - The minimal call took 2.6 s and 1,098 input tokens.
  - Replay is identical with no subprocess started.
  - 6 live calls in total (cap 6), about $0.10 API-equivalent, not billed.
- Spark: exact policy found 9 value differences, 2 missing and 3 extra rows; contract policies 2, 1 and 2. datacompy agrees on every count.

**Changes from the plan**
1. **§7.3 was wrong about SAS numbers.** `BEST32.` keeps at most 15 significant digits, so it can't round-trip a double. SAS exports now carry an exact `HEX16.` sidecar, and §7.3 is corrected.
2. **Contracts revised after the independent review** (all additive or tightening):
   - `JobSpec.state_tables` and an acyclic inventory: the blocker, for T02's two batches.
   - `audit_tables` (`etl.etl_log`).
   - `GateDecision.job_ids` (wave approvals list their jobs), hashed `EvidenceRef`s and `re_review_of`.
   - A heal-loop `score` that ranks a crash below a mismatch.
   - `approach` and `run_id` for the comparison runs.
   - `TaggedFlow` and `FlowDecision` for H2's bias decisions.
   - `LiteralFinding` with acceptances, and `TrapCard.allowed_literals`.
   - `surrogate_ref` for T03's foreign key to T02's IDENTITY.
   - An absolute floor for `float_rel`, and policy/type compatibility checks.
   - Case-insensitive identifiers with canonical lower-case table names, and ASCII-only patterns.
   - Typed `TableRows` for tests, and timezone-aware timestamps.
   - Escalations, waves, schedules, SLA checks, metrics and an `EvidenceReport`.
   - `ComparisonPolicy.approved_by` is removed: approval is a gate decision pinned to the contract's hash.
3. **Records are never Claude's answers.** Each agent will answer in its own small model (step 2.2), and the gateway already refuses a contract record as a response schema.
4. **SQL Server moved to compose management.** The old `docker run` container was replaced; it uses the same volume, so no data was lost.
5. The private GitHub repo was created by the team; the code was pushed there on 11 Nov as a single initial commit.

**Risks and open issues**
- **Usage limits on the subscription.** Everything recorded so far replays offline. The gateway now defaults to D5's 150 live calls per run.
- SAS OnDemand: only one session should be open at a time; capture already runs sequentially.
- **Review findings: 33 found while redocumenting the code (11 Nov), all fixed, each with a test.**
  - *Claude gateway:*
    - usage records carry `outcome`, `attempt` and `num_turns`;
    - the cassette scrubber finds a secret however JSON escapes it;
    - `max_live_calls=None` always means the D5 cap;
    - a contract model's subclass can't be a response model;
    - the smoke test uses the gateway's environment and reports failures.
  - *Contracts:*
    - `TaggedFlow` compares column names case-insensitively;
    - a refused assignment leaves the record unchanged;
    - `total_score([])` raises.
  - *Reconciliation spike:*
    - infinite double totals are guarded;
    - per-row keys and partition labels are reported as given.
  - *Engines:*
    - name checks refuse a trailing newline;
    - SQL Server names escape `]`;
    - `text` and `ntext` are unbounded;
    - the SAS `ensure_dir` refuses `..`.
  - *Estate tooling:*
    - SAS check ids are compared with those declared;
    - the SAS date literal doesn't depend on the locale;
    - the estate commands live in the estate package.
  - *Factory-isolation test:* now an AST check covering 24 forms of reaching the answer key or the sealed jobs, including the evaluation-only functions.
- **Still open, for step 2.2:**
  - the usage-limit detector also matches "Context limit reached";
  - a usage-limit message inside a non-error result isn't detected.
- **Still open, for step 2.1:** the reconciliation spike matches key and partition column names case-sensitively, unlike the contracts.

**Decisions needed**
1. Approve the contract freeze, including the review fixes to `TaggedFlow`, assignment and `total_score` above. *Default: approve.*
2. ~~Create the private repo and push.~~ Done on 11 Nov: one initial commit pushed to the private repo `Auslogger/Agentic-Data-Platform-Modernisation`.
3. Proposed trap card **SAS-16**: SAS's calendar has no 29 February in years divisible by 4000, so day counts to the `9999-12-31` sentinel are 2 days short. *Default: add the card, plant nothing (Tier 2).*

**Starts on approval:** Phase 1 (already under way on your instruction), then step 2.1.

**Accepted** by the agent, overnight run, 12 Nov 2026. Evidence re-run that night:
- `make check`: 488 passed; the one failure is the known `test_env_example_lists_required_settings` (the team removed `.env.example`).
- `make smoke`: 5/5, with one live Claude call.
- `spikes/claude_backend.py` replays its 6 findings identically, with no call made.
- `verify_seal()` is True.

Decisions taken:
1. The contract freeze is approved, review fixes included.
3. SAS-16 is added as a trap card and planted nowhere (step 3.2).

---

## Gate 2: Ground truth

**Asking for:** Approve. With approval, the golden outputs are frozen: any change means a
fresh capture, approved at a gate.

**What was built**
- **1.1 The synthetic insurer.** 9 source tables, 232,267 rows for 20,000 customers, seed 20251231.
  - Claims arrive at a realistic frequency: 0.078 a policy-year for motor, 0.052 for home and 0.05 for travel.
  - Paid claims come to about 64% of earned premium (motor 67%, home 61%, travel 56%).
  - Two runs produce identical files, and SQL Server is verified to hold exactly the committed Parquet ([estate/README.md](../estate/README.md)).
  - 46 tests guard the planted edge cases, the bug preconditions, the consistency of the policies and the loss ratios.
- **1.2 and 1.4: ten legacy jobs** in SynthInsure legacy style ([estate/README.md](../estate/README.md#legacy-coding-style)), 1,519 lines in all.

  | Job | Lines | Output (rows) | Planted bug | Measured impact on our data |
  |---|---|---|---|---|
  | T01 | 175 | dw.dim_customer (20,000) | BUG-01 keeps the oldest CRM version | 2,963 customers show superseded details |
  | T02 | 182 | dw.dim_policy (69,255), 2 batches | none | type-2 history; 37,801 versions store `'DIRECT-SAL'` (TSQL-06) |
  | T03 | 154 | dw.fact_premium_earned (67,879) | BUG-02 divides by 365 | 21,145 facts misstated; 10,572 of them 366-day covers |
  | T04 | 179 | rpt.claims_summary (823) | BUG-03 payments x reserve rows | total paid overstated by €1.29m on 289 claims |
  | T05 | 190 | rpt.claim_aging (823), cursors | BUG-04 30 days falls between bands | 31 claims left `UNKNOWN` |
  | T06 | 169 | rpt.loss_triangle_paid (21), PIVOT | BUG-05 drops day-0 payments | 196 payments (€390k) missing; 19 of 21 rows short |
  | T08 | 182 | rpt.claim_fraud_flags (1,042) | BUG-07 compares with the end date | 146 flags wrong: SIU gets 1 HIGH referral, not 14 |
  | S01 | 109 | dw.claims_enriched (2,911) | BUG-08 missing amount < 0 | 86 unkeyed payments counted as recoveries |
  | S03 | 75 | rpt.premium_band_summary (13) | none | |
  | S04 | 104 | rpt.risk_scores (2,645) | BUG-10 `'MEDIUM'` stored as `'MEDI'` | 654 of 2,645 tiers (HIGH 160, LOW 1,831) |

- **1.3 and 1.6: golden outputs** for all 10 jobs in [estate/golden/](../estate/golden/).
  - Engines: SQL Server 2022 16.0.4305.5 (image pinned by digest) and SAS 9.04.01M9.
  - Each job's pack holds the raw export, a typed Parquet copy and a manifest (engine version, legacy-code hash, input fingerprints, row counts, content hashes, log excerpt).
  - SAS packs also keep the exact `HEX16.` numbers, PROC CONTENTS and the redacted log.
  - T01–T03 are captured before any SAS job runs, and the SAS jobs read the T-SQL goldens.
- **1.5 Held-out jobs.** X1 and X2 are sealed in [estate/holdout/](../estate/holdout/) (SHA-256 `51591fd9…`).
  - They were written by an isolated `claude -p` session in a sandbox that refused everything except two SQL helpers, and verified without reading the code.
  - Re-verified the same way on the recalibrated data: both run deterministically (X1 126 rows, X2 79), and both bug checks stay positive (X1 120 rows affected, X2 43).
- **1.7 The answer key** in [estate/labels/](../estate/labels/) (evaluation only; a test keeps factory code out):
  - 82 labelled trap occurrences, 47 of them armed semantic traps;
  - 8 bugs, each in exactly one job;
  - 53 check queries (T-SQL or SAS), each proving its trap or bug changes the result on our data.

**Check it yourself** (about 15 minutes)
```bash
make check                                   # ruff + the offline tests, under a minute
make legacy-up && make load                  # SQL Server, then the 9 extracts (about 1 min)
make legacy-verify                           # 7 T-SQL jobs reproduce their golden hashes
make legacy-verify-all                       # plus the 3 SAS jobs (needs SAS OnDemand), about 3 min
uv run lansh estate checks --job T04         # the vertical slice: 5 checks PASS
uv run python -c "from lansh.estate.holdout import verify_seal; print(verify_seal())"  # True
```
Then read [estate/tsql/T04_usp_build_claims_summary.sql](../estate/tsql/T04_usp_build_claims_summary.sql) and
[estate/labels/T04.yaml](../estate/labels/T04.yaml) side by side.

**Evidence**
- `make legacy-verify-all` after the recalibration: **all 10 jobs reproduced their golden hashes** from a freshly rebuilt database (2 min 45 s). That includes T02's IDENTITY surrogate keys, and the SAS raw exports byte for byte.
- `make data` regenerates the extracts byte for byte. The integration tests pass: SQL Server 2, and SAS 1, the live round trip, which now includes a value with leading blanks.
- All 53 checks pass on the recaptured goldens. The answer-key tests pass for all 10 jobs: every planned trap labelled, every bug in exactly one job, every line range and check present, and the SAS check programs declare exactly their labels' checks.
- Every count in the labels was re-measured on the new data, by query or from the golden Parquet, never scaled. Each definition was first confirmed by reproducing the old label's number on the old data.
- **Independent review:** every job except S01 was reviewed by a separate agent and passed after fixes. S01's review was cut off by the usage limit; I reviewed it myself.
  - The reviews found real problems, all fixed: T03's integer-division trap wasn't truly armed (fixed with a DECIMAL column); S04's rounding check overcounted and the rounding-unit trap had no check; S04 never produced a LOW tier.
- **Translatability:** independent PySpark translations reproduced T02, T03, T05, T06 and T08 with 0 differing rows, S03's sums were reproduced bit for bit, a Python emulation of S01 was bit-exact, and for S04 DECIMAL arithmetic with half-up rounding reproduces the score. These ran on the first data; the jobs' code is unchanged since, except S04's two tier thresholds. The translations were deleted.

**Changes from the plan** (all applied in docs/PLAN.md)
1. S04 also reads T01 for age and county (the protected attributes). T02 also reads `stg.products`. The waves are unchanged.
2. T03 carries T02's IDENTITY `policy_sk`, a foreign key to a surrogate, which the `surrogate_ref` policy covers.
3. Demo step 2 (§14): T04 passes `status` through unchanged, so `ci_rtrim` isn't needed there. The demo shows H2 refusing it as a tolerance with no reason.
4. SAS reads a table written by a T-SQL job in key order (`_row_seq` by its first column). This is documented in §7.3, because a migrated job must use the same order.
5. Data volume is about 232k rows for 20,000 customers (the plan said about 250k): enough to arm every trap at a realistic claim frequency, and SAS uploads stay quick.
6. The answer key defines `armed` for construct traps as "present and runs on our data", and scores a suspected defect at a labelled trap as detecting that trap.
7. **At review (11 Nov), T06:** its cumulative columns were renamed from `cum_0`…`cum_6` to `cumulative_0`…`cumulative_6`, in the job, its label and its check.
8. **At review (11 Nov), the estate was recalibrated.**
   - Claims came at four to six times a real book's frequency, so paid claims were about 350% of earned premium. The frequency is now realistic, and the book has 20,000 customers so the claim-side edge cases stay plentiful.
   - The planted start dates (29 February 2024, 31 December, 1 January) and the early-2019 sterling lines no longer overlap their renewals or predate their customer.
   - Six claims are keyed against another line of business, so T08's `lob_mismatch_flag` now fires on a genuine keying error.
   - S04's referral thresholds were retuned to the new scores: HIGH from 35, MEDIUM from 22 (were 60 and 35).
   - All 10 goldens were recaptured, every count in the labels re-measured, and the held-out jobs re-verified without reading them.
   - The new data arms one more occurrence: TSQL-02 in T08's motor test, through claim 302250 keyed `'Mot '`. It is now labelled armed, with a check.

**Risks and open issues**
- **What the repo holds.** It's pushed as a single private commit to `Auslogger/Agentic-Data-Platform-Modernisation`. The current `.gitignore` keeps every Markdown file out of it (`README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/`), and `.env.example` has been deleted. The submission needs a README with setup, and `make setup` copies `.env.example` to create `.env`.
- **T08's `lob_mismatch_flag` is 1 on one row.** Only one of the six mis-keyed claims falls inside T08's 12-month window. Its traps still show on 1,041 rows under a naive translation.
- **The subscription's 5-hour usage limit stopped about nine parallel agents once.** All work was recovered. Since then at most two agents run at a time.

**Decisions needed**
1. Approve G2 and freeze the golden outputs. *Default: approve.*
2. Approve G1 retrospectively (the contract freeze). *Default: approve.*
3. Which Markdown files belong in the repo, and whether `.env.example` comes back. *Recommended: track `README.md` (the submission needs it) and restore `.env.example`; the rest can stay local until submission.*
4. Proposed trap card SAS-16 (SAS has no 29 February in years divisible by 4000). *Default: add it as a card, plant it nowhere.*

**Starts on approval:** Phase 2, the vertical slice. Steps 2.1 (reconciliation engine, starting from `spikes/spark_recon.py`), 2.2 (Claude gateway, starting from `src/lansh/llm/`) and 2.3 (gate log) can start in parallel.

**Accepted** by the agent, overnight run, 12 Nov 2026. Evidence re-run that night:
- `make legacy-verify-all` rebuilt `SynthInsureDW` from scratch, and **all 10 jobs reproduced their golden hashes** (3 min 30 s).
- `lansh estate checks --job T04`: 5/5 PASS, among them BUG-03 on 289 claims (€1,288,029.36).
- The seal verifies.

Decisions taken:
1. The goldens are frozen.
2. G1 is approved retrospectively.
3. `.gitignore` and `.env.example` stay as the team left them, as `AGENTS.md` instructs. Deciding what Markdown to track before submission is listed for the team.
4. SAS-16 becomes a card, planted nowhere.

---

## Gate 3: Vertical slice

**Asking for:** Approve: T04 has been through all five stages, and D4 and D5 are confirmed.

**What was built** (Phase 2, steps 2.1–2.10; every module's docstring has the detail)
- **2.1 Reconciliation:** [src/lansh/reconcile/](../src/lansh/reconcile/).
  - `engine` is the spike's engine plus:
    - column names matched case-insensitively;
    - masked `pii` samples, and samples of missing and extra rows;
    - a plain-English explanation;
    - double totals checked within the summation-error bound.
  - `signatures` names 9 diff patterns and links each to the trap cards.
  - `job` runs a module in the isolated worker and reconciles every output; `lansh reconcile --job ID --candidate FILE` checks a hand-written job.
- **2.2 Claude gateway:** both open items from G1 are fixed. The seven agent answer models are in `lansh.llm.answers`, and usage is logged per run and stage.
- **2.3 Gate log:** [src/lansh/governance/gatelog.py](../src/lansh/governance/gatelog.py).
  - Gates pass in order only, and re-deciding an earlier gate retires later approvals.
  - Blockers refuse approval; warnings need a written reason.
  - Approvals under 20 s are flagged, and a seeded 10% are spot-checked.
  - Defect and flow decisions are recorded alongside.
  - The Tier 2 hash chain, with `lansh audit verify`.
- **2.4 Discover:** [src/lansh/discover/](../src/lansh/discover/).
  - The splitter, and 35 trap cards (step 3.2, brought forward).
  - The two-pass trap scan: rules, then the trap-scan agent.
  - The Lineage agent, checked against the schemas and cross-checked by sqlglot, whose per-statement lineage is composed through the temp tables.
- **2.5 Design:** [src/lansh/design/contract.py](../src/lansh/design/contract.py).
  - Keys come from the DDL and a profile of the golden output.
  - Every default policy carries its reason.
  - Tags are carried from job to job.
  - H2's checks refuse a tolerance with no reason.
- **2.6 Generate:** [src/lansh/generate/](../src/lansh/generate/).
  - The sqlglot draft and the Translator agent.
  - The guardrails: syntax tree, SQL strings, the literal check, ruff.
  - The worker.
  - The Test author agent, with expected values from the legacy job run in a scratch SQL Server database, recorded so the tests replay offline.
- **2.7 Heal loop:** [src/lansh/reconcile/heal.py](../src/lansh/reconcile/heal.py).
- **2.8 Defects:** [src/lansh/design/defects.py](../src/lansh/design/defects.py): markers plus the Defect reviewer agent, with impact queries run on golden data.
- **2.9 Operate:** [src/lansh/operate/run.py](../src/lansh/operate/run.py): Delta, reconciled again, SLA checks, OpenLineage events, wave schedules.
- **2.10 The pipeline:** [src/lansh/pipeline.py](../src/lansh/pipeline.py) and `lansh run-job`.
  - Each stage writes its evidence into `runs/<run>/<job>/`.
  - Each gate pins the evidence by hash; a decision is reused only on the same evidence.
  - A person can decide in the terminal, or later with `lansh approve` once the run pauses.
  - The evidence report is in [src/lansh/evidence.py](../src/lansh/evidence.py).

**Check it yourself** (about 5 minutes, all offline)
```bash
make check                                    # ruff + 587 offline tests (the migrated T04's 12 trap tests among them)
make test-e2e                                 # T04 through H1-H5 in replay mode, SQL Server patched unreachable (about 1 min)
uv run lansh run-job T04 --mode replay        # the same from the command line: "T04: MATCH"
uv run lansh audit verify --run dev-t04       # the development run's gate log: intact
uv run lansh reconcile --job T04 --candidate tests/fixtures/t04_naive.py --keys claim_id   # MISMATCH, every mistake named
```
Then read `runs/dev-t04/T04/evidence.md`.

**Evidence**
- **The T04 slice.** The first translation reconciled MATCH on all 823 rows, with the golden content hash reproduced exactly (`88c866643793`).
  - BUG-03 was reproduced on purpose and marked `# LANSH-DEFECT`.
  - The Defect reviewer flagged it, and its impact query measured **289 rows and €1,288,029.36** on the golden output: the answer key's own figures, found independently.
  - 15 trap findings and 47 verified lineage edges; sqlglot agrees on all 20 output columns.
  - 12 trap tests with expected values from SQL Server, all passing.
  - The Delta output reconciled again, and the SLA held.
  - The run took 170 s.
- **Healing.** `tests/fixtures/t04_broken.py`, the factory's own T04 with two traps undone, started at 60 missing and 740 differing rows. It healed to MATCH in one Fixer attempt (32 s), and its patch passed the guardrails.
- **The naive candidate.** `tests/fixtures/t04_naive.py` is caught with each mistake named:

  | Mistake | Rows |
  |---|---|
  | TSQL-01 filter variants | 49 |
  | TSQL-02 trailing spaces | 11 |
  | TSQL-05 NULL concatenation | 99 |
  | BUG-03 "fixed" (`row_multiplicity`, exactly 2×) | 268 |

  datacompy agrees with the engine on T04's real output.
- **The guardrails** refuse imports, I/O, engine internals, dunder access, `reflect`, file-path tables, `SET` and f-string SQL. The literal check blocks a hard-coded data value (`300035`) but accepts a trap card's `dd/MM/yyyy`.
- **Claude usage for T04: 6 agent calls, about $1.10 API-equivalent, not billed.**

  | Agent | Effort | Output tokens | Model time | API-equivalent |
  |---|---|---|---|---|
  | trap scan | medium | 3,181 | 29 s | $0.16 |
  | lineage | medium | 6,403 | 47 s | $0.19 |
  | contract | low | 995 | 16 s | $0.06 |
  | defect reviewer | high | 4,875 | 41 s | $0.14 |
  | translator | high | 7,241 | 58 s | $0.24 |
  | test author | medium | 12,501 | 90 s | $0.31 |

  The fixer, when needed: high effort, 32 s, $0.20.
- **Determinism.** A replay of the run reuses all five decisions and makes no live calls.

**Changes from the plan**
1. Trap cards (step 3.2) were written in 2.4, because the trap scan needs them. They are generic: no example is copied from a development job, so that the held-out jobs test generalisation.
2. IDENTITY keys default to `exact`, not `surrogate`. SQL Server assigns them in the INSERT's ORDER BY, so a faithful migration can reproduce them. `surrogate` stays available, behind an H2 reason.
3. The Defect reviewer runs at Design, before translation, and the translator is given its findings to reproduce and mark. Markers the translator adds that Design didn't list are decided at H4.
4. The legacy engine's answers to test inputs are recorded (`runs/cassettes/legacy/`), so the tests and `make demo` replay without SQL Server.
5. Generated code (`migrated/`, `tests/fixtures/`) is excluded from ruff: reformatting it changes what recorded answers were asked about.
6. The Tier 2 hash-chained gate log was brought forward into 2.3. `migrated/tests` joins the default test paths.
7. Gate evidence is pinned by a hash of what it says, with timings dropped, so a resumed run reuses a person's decision.

**Risks and open issues**
- In development runs every approval is the agent's, flagged as fast (0 s), and `human_signoff` is False. The showcase run's sign-offs are the team's (AGENTS.md).
- The sqlglot cross-check covers explicit projections only: `SELECT *` into temp tables isn't expanded (T01).
- SAS trap tests check the contract only (schema and keys), since SAS isn't run per case. Each SAS job's MATCH is still proved against its SAS golden output.
- Usage. About 6 calls a job, plus heals. The 12-job estate plus the 10 one-shot comparison translations needs about 90–110 live calls, within D5's 150.

**Decisions needed**
1. D4: Opus 5.5 for every agent. Effort is medium for lineage, trap scan and test author, low for the contract, and high for the translator, fixer and defect reviewer. *Default: confirm.*
2. D5: at most 150 live calls per full run. *Default: confirm.*

**Starts on approval:** Phase 3. All T-SQL and SAS jobs go through the factory wave by wave. Then the estate-wide Discover, the defect register scored against the answer key, the comparison runs, and the held-out run after the factory freeze.

**Accepted** by the agent, overnight run, 12 Nov 2026. Every "done when" in Phase 2 holds:
- 2.1: the unit tests catch every kind of difference, and datacompy agrees;
- 2.2: offline from recordings, plus one live call;
- 2.3: illegal transitions refused;
- 2.4: T04's lineage matches the hand check;
- 2.6: the module runs and its tests pass;
- 2.7: the broken T04 heals to MATCH;
- 2.8: BUG-03 listed;
- 2.10: `lansh run-job T04` ends in MATCH with BUG-03 reproduced and flagged.

The evidence commands above were run. D4 and D5 are confirmed.

---

## Gate 4: Estate reconciled

**Asking for:** Approve: all 10 development jobs reconcile record for record, every planted bug in them reproduced; the comparison runs and the held-out run are measured and reported as they came out. Phase 4 can start.

**What was built** (Phase 3, steps 3.2–3.11; every module's docstring has the detail)
- **The whole estate through the factory.** `lansh run --all` takes the development estate wave by wave ([src/lansh/pipeline.py](../src/lansh/pipeline.py)).
  - Each job goes through H1–H4 on isolated inputs.
  - Each wave then runs on Delta with chained inputs, is reconciled again, and is cut over at H5.
  - A job blocked or escalated before H4 doesn't stop the others.
  - Held-out jobs run only when named, so their one run is reported apart.
- **3.3 and 3.4, T-SQL and SAS:** SAS steps in the splitter, SAS lineage and trap rules, the translator's SAS rules, and contract-level SAS tests.
- **3.5, design for every job:** 10 contracts in `migrated/contracts/`, every key unique in its golden output. The only non-exact policies, each with its reason:
  - SAS doubles: `float_rel` 1e-9;
  - SAS text: `blank_is_null`;
  - T02's volatile `load_ts`: `exclude`.
- **3.6, estate-wide Discover:** [src/lansh/discover/estate.py](../src/lansh/discover/estate.py) builds the DAG, the waves (§7.2 exactly, by test) and the tagged flows across jobs.
- **3.7, the defect register:** `runs/<run>/defect_register.md`, each suspected defect with its impact measured on the golden output and its decision. Scoring against the answer key is in [src/lansh/estate/scoring.py](../src/lansh/estate/scoring.py), evaluation code that the factory never imports.
- **3.8, tests:** trap tests for every job in `migrated/tests/`. T-SQL expected values come from SQL Server; SAS tests check the contract.
- **3.9, Operate:** wave schedules in Databricks Workflows shape, SLA checks and OpenLineage events for every job.
- **3.10, comparison runs:** [src/lansh/benchmark.py](../src/lansh/benchmark.py) and `lansh benchmark`.
- **3.11, freeze and held-out run:**
  - `lansh freeze`, which checks the factory against `runs/freeze.json` and keeps every freeze, with per-file hashes;
  - `lansh estate unseal`;
  - `lansh estate score --holdout`.

**Check it yourself** (offline unless marked)
```bash
make check                                          # ruff + 666 offline tests, the 73 migrated trap tests among them
uv run lansh audit verify --run dev-estate          # the estate run's gate log: intact
uv run lansh freeze                                 # "unchanged since the freeze at 2026-11-12T04:13:59+00:00"; its history holds freeze 1
uv run lansh scorecard --run dev-estate --holdout dev-holdout --learning dev-holdout-learn
uv run lansh ui                                     # the Control Tower: every run, job and comparison
make legacy-verify-all                              # needs SQL Server and SAS: every golden hash reproduced
```
Then read `runs/dev-estate/scorecard.md` (every number with the files it came from and their SHA-256), `runs/dev-estate/defect_register.md`, and any job's `runs/<run>/<job>/evidence.md`.

**Evidence**

*The development estate* (`runs/dev-estate`; agent reviewer; 71 live Claude calls, $13.06 API-equivalent, not billed)

| Job | Legacy rows | Sandbox | Delta | Hash identical | Traps found | Suspected defects | Trap tests | Heal attempts | Calls | API-equiv. |
|---|---|---|---|---|---|---|---|---|---|---|
| S01 | 2,911 | MATCH | MATCH | yes | 17 | 7 | 5/5 | 0 | 6 | $0.89 |
| S03 | 13 | MATCH | MATCH | within 1e-9 (SAS doubles) | 7 | 3 | 5/5 | 0 | 6 | $0.75 |
| S04 | 2,645 | MATCH | MATCH | within 1e-9 (SAS doubles) | 7 | 5 | 6/6 | 0 | 6 | $1.07 |
| T01 | 20,000 | MATCH | MATCH | yes | 24 | 4 | 5/5 | 0 | 6 | $0.87 |
| T02 | 69,255 | MATCH | MATCH | yes | 19 | 5 | 3/3 | 0 | 6 | $1.15 |
| T03 | 67,879 | MATCH | MATCH | yes | 20 | 6 | 6/6 | 0 | 6 | $1.40 |
| T04 | 823 | MATCH | MATCH | yes | 15 | 4 | 12/12 | 0 | 6 | $1.10 |
| T05 | 823 | MATCH | MATCH | yes | 10 | 4 | 3/3 | 0 | 6 | $0.73 |
| T06 | 21 | MATCH | MATCH | yes | 5 | 4 | 1/1 | 0 | 6 | $0.81 |
| T08 | 1,042 | MATCH | MATCH | yes | 11 | 5 | 9/9 | 0 | 6 | $1.28 |

- **10 of 10 MATCH, all on the first translation, with no healing.** 165,412 legacy rows were proved record for record, first in the sandbox and again on Delta with chained inputs, and all 5 waves were cut over.
- **8 of 10 outputs have the legacy output's exact content hash.** S03 and S04 match within their declared SAS-double tolerance.
- **55 trap tests pass.** With machine time counting each replayed answer at its recorded live time, a job takes 5.3 minutes end to end and about $1.01 API-equivalent.
- **The defect register:** 47 suspected defects, 20 of them with a measured impact on the golden output, and 29 flows of `pii` or `protected` columns into outputs. Each has a decision, all the agent's defaults:
  - every defect *reproduce*;
  - flows of `pii` columns *reproduce, accepted* (18 decisions);
  - flows of `protected` columns *reproduce, flagged for a bias review* (11 decisions).
- **The gate log:** 126 entries, 50 decisions, all the agent's, labelled so; the hash chain is intact.

*Against the answer key* (`runs/dev-estate/scores.json`; evaluation only)
- Labelled trap occurrences detected: **81 of 82**, armed semantic traps 47 of 47; trap findings 111 of 135 true (82% precise).
- Planted bugs **reproduced exactly: 8 of 8**. Their jobs MATCH, and all 41 answer-key checks give the legacy result on the migrated outputs (every check reads the job outputs).
- Planted bugs **flagged: 8 of 8 by cited lines, 6 of 8 with the planted diagnosis**, as read by the evaluator (`runs/dev-estate/adjudication.json`). BUG-08 (S01) and BUG-10 (S04) were reproduced, but the defects at their lines describe something else.

*The comparison runs* (`runs/dev-estate/benchmark.json`): every approach was reconciled against the same goldens under the same contracts.

| Approach | Jobs reaching MATCH | What happened |
|---|---|---|
| sqlglot alone (its optimizer given the input schemas) | **0 of 10** | 6 can't be drafted (SAS, MERGE, UPDATE, a cursor). T01, T03 and T08 fail in Spark on T-SQL that sqlglot doesn't transpile (`RTRIM(x) + ' '`, `CONVERT(..., 103)`, ROUND's truncate mode). T04 runs and differs on all 823 rows |
| One-shot Claude: same model, effort and module interface; no trap cards, language rules, draft or healing | **8 of 10** | The 2 misses ran cleanly and were **silently wrong on 805 rows**. Each "fixed" a legacy behaviour nobody had decided to change: S01's missing-amount buckets (86 rows, BUG-08's) and S04's `MEDI` truncation (654 rows, BUG-10) |
| One-shot, then LANSH's heal loop alone | **10 of 10** | Both healed in one attempt: S01 in 297 s, diagnosing SAS-02 (missing values through `+`); S04 in 58 s, diagnosing SAS-11 (a character length fixed by its first assignment) and SAS ROUND at the half-way point. These are the first genuine heals; the Control Tower's Scorecard page shows their timelines |
| **LANSH** | **10 of 10, first time** | The proof alongside: lineage, traps, contracts, measured defects, tests, gates |

*The held-out run* (`runs/dev-holdout`): run once on the frozen factory, and reported as it came out
- **The freeze:** freeze 1 at 03:29:16 UTC, `a15acd7a…`, 53 files. `lansh freeze` reported it unchanged before and after the run. The seal verified before unsealing, and the goldens were captured on a fresh SynthInsureDW: X1 126 rows, X2 79 rows, the counts of the blind re-verification.
- **X2 (large-loss watchlist): MATCH on the first translation.** Its content hash is identical to the legacy output's, and it was cut over on Delta, with 5/5 trap tests. The planted bug was flagged with the planted diagnosis (X2-D1, "latest reserve picked across all reserve types", line 76) and measured at 43 rows, the author's own count.
- **X1 (broker production): escalated to a person at Generate.** 1 of its 13 trap tests failed: a broker ratio exactly on the 0.75 review threshold. The planted bug was flagged with the planted diagnosis (X1-D1, "claims paid limited to claims notified in the same year", lines 93–112, 87 rows, EUR 1,388,119.21).
  - **Root cause:** SQL Server truncates a DECIMAL quotient toward zero at its result scale (15000.99/20000 gives 0.750049), where Spark's quotient rounds (0.750050). Card TSQL-07 wrongly said intermediate results are rounded, and the translator followed it.
  - A full-data reconciliation afterwards, outside the run: 3 of 126 rows differ by one rounding step. The trap test caught it before reconciliation did.
- **Scored:** 1 of 2 MATCH on the first run. Planted bugs flagged with the planted diagnosis: 2 of 2. Planted bugs reproduced exactly: 1 of 2 (the job must MATCH).
- **The author's bug checks** compute each bug from the source tables alone (X1 120 rows, X2 43), so they size the bugs but can't prove reproduction; they're reported as sizes only.
- **Usage:** 12 live calls, $2.95 API-equivalent.

*The learning loop the held-out run prompted* (`runs/dev-holdout-learn`): a second run, not a held-out result
- **Two generic fixes,** each with a test (PLAN Appendix F):
  1. Card TSQL-07 now states the division rule, measured on SQL Server 2022, with a Spark recipe.
  2. The literal check no longer reads a decimal type's precision and scale as data.
- **Re-translated under the corrected card, X1 and X2 both MATCH,** with identical content hashes; X1 passes all 13 trap tests. T03, the one development job with a TSQL-07 finding, was re-translated too and stays MATCH with an identical hash. The estate is still 10 of 10.
- **Freeze 2,** `5832b65d…`, differs from freeze 1 in `discover/trap_cards.yaml` and `generate/guardrails.py` only. Putting their frozen versions back reproduces `a15acd7a…` exactly, and `runs/freeze.json` keeps both freezes.

**Changes from the plan**
1. **A third comparison, "one-shot then heal".** LANSH's own run never needed healing, so this measures the heal loop on real, unstaged failures.
2. **The one-shot baseline shares the factory translator's interface text,** in code. A first attempt with vaguer wording failed two SAS jobs on input keys; it was discarded as unfair to the baseline. The factory's own prompts stayed byte-identical.
3. **sqlglot alone gets the input schemas,** so its optimizer can type each query: the strongest fair version of that baseline.
4. **The freeze covers only what decides a job's outcome.** The CLI, the Control Tower, reports, comparison runs and scoring stay outside it, so Phase 4 can change them.
5. **The learning log is PLAN Appendix F,** not `docs/learning-log.md` (AGENTS.md: no new notes files).
6. **The held-out answer key is the author's prose,** so its bug verdicts are the evaluator's (`runs/dev-holdout/adjudication.json`). The author's checks size the bugs but can't prove reproduction.
7. **Post-freeze fixes are allowed, but reported apart** from the first run, with both freezes on record.

**Risks and open issues**
- **Healing in LANSH's own run:** none was needed. The loop is evidenced by the broken-T04 fixture and the two one-shot heals.
- **BUG-08 and BUG-10** were reproduced but not diagnosed as planted. The defect reviewer is weakest on SAS semantics. The one-shot comparison shows what "fixing" them silently would have changed: 86 and 654 rows.
- **A failing trap test escalates; it doesn't heal.** The fixer only ever sees reconciliations. Feeding failing test cases to the fixer is the natural next step (Tier 2).
- **TSQL-07's `legacy_behaviour` sentence still says intermediate results are rounded.** Correcting it would change every T-SQL trap-scan prompt and so every recording. Its fix guidance now states the exception for division. Amend the sentence when the recordings are next refreshed, for example before a live showcase run.
- **Development approvals are the agent's,** flagged as fast. The showcase run's sign-offs are the team's (AGENTS.md).

**Decisions needed**
1. Report the held-out result as it came out: 1 of 2 on the first run, then 2 of 2 after the learning fixes, kept apart. *Default: yes.*
2. Count planted bugs as flagged only with the planted diagnosis: 6 of 8 development, 2 of 2 held-out. Report the by-lines figure (8 of 8) beside it. *Default: yes.*
3. Keep both post-freeze fixes in the factory. *Default: yes; they're generic, tested and logged.*

**Starts on approval:** Phase 4:
- the Control Tower checked on every run;
- the showcase published in `runs/showcase/`, and `make demo` tested offline;
- the final scorecard;
- the architecture and Responsible AI notes with final numbers;
- the README proposal;
- a fresh-clone test.

**Accepted** by the agent, overnight run, 12 Nov 2026. Every "done when" in Phase 3 holds:
- 3.3: every job reaches MATCH, or is escalated with a diagnosis (10 of 10 MATCH);
- 3.6: the waves match §7.2;
- 3.7: every planted bug is reproduced (8 of 8), and detection is scored against the answer key;
- 3.9: `lansh run --all` is green, all 5 waves cut over on Delta;
- 3.10: the comparison runs are reported;
- 3.11: the factory was frozen, the held-out jobs ran once, and their first-run results are reported apart from the learning run.

The evidence commands were run:
- `make check`: 666 passed, plus the known failure;
- `lansh audit verify --run dev-estate`: intact;
- `lansh freeze`: unchanged since freeze 2, with freeze 1 reproduced from its files;
- `lansh estate verify`: all 9 T-SQL golden hashes reproduced from a fresh rebuild, X1 and X2 included. The SAS goldens are byte-identical to those G2 verified.

The defaults of decisions 1–3 are taken.

---

## Gate 5: Release candidate

**Asking for:** The team's review of the release candidate, and the five decisions below, which only the team can make before publishing (G6). Everything else in Phase 4 is built and checked.

**Update after the packet was written (12 Nov, at the team's request).**
- Decision 2 is done: the template is restored as `tests/fixtures/.env.example`, and `make setup` copies it again (this undoes change 3 below). `make check` now passes in full: 667 tests.
- The work is committed and pushed to the private repo: ten commits by area on `origin/main`, ending at `b1568b2`, with the two earlier commit messages reworded (same trees and dates). Before the push, every pushed file and both earlier commits were scanned again for the `.env` and `~/.authinfo` values, the home path, key patterns and the organiser's address. Nothing was found apart from the dummy keys in the gateway tests.
- `README.md` and the `.gitignore` are unchanged, so decisions 1, 4 and 5 are still open. Until decision 1 is made, the pushed repo can't be set up from a clone (`uv sync` needs `README.md`).

**Critical review (12 Nov, PLAN Appendix G, checked by an independent review).** The review found more that bears on this gate.
- **The clone failure is reproduced.** A clone of `main` has no Markdown at all, and `uv sync` stops: `failed to open file .../README.md`.
- **The freeze record doesn't verify, and isn't published.**
  - `uv run lansh freeze` prints "CHANGED since the freeze at 2026-11-12T04:13:59+00:00", naming `config.py`. The `.env` template move edited an error message after freeze 2, so this packet's "unchanged" no longer holds.
  - `runs/freeze.json` is git-ignored, and `lansh freeze` reads only that file, so a clone gives no verdict at all.

  *Proposed decision 6:* track `runs/freeze.json` (`!runs/freeze.json` in the `.gitignore`). Then, before any re-publish of the showcase, record freeze 3 with that reason (PLAN step 5.1):

  ```bash
  uv run lansh freeze --write --note "config.py: the .env template's path in one error message; no job's outcome depends on it"
  ```

- **Decision 3's commands would delete evidence.** `lansh showcase` replaces `runs/showcase/` with only what the source run holds, and an estate run writes no `benchmark.json`, `scores.json` or `adjudication.json`. Publishing `showcase-live` straight away would drop the comparison runs, the heal timelines and the answer-key scores. PLAN step 5.3 rebuilds them in `showcase-live` first.
- **The `.gitignore` contradicts itself.** Its comment says "The rest of docs/ is tracked", but the next line ignores all of `docs/`. Decision 1's replacement fixes both. `docs/week2.py`, which has nothing to do with LANSH, stays ignored under it.
- **The proposed README had four errors, now corrected or marked below.**
  - **Its business-case line was an assumption restated.** The saving is about 1 minus the assumed 15% escalation rate, whatever the manual minutes are (PLAN §9.3). The line now waits for scorecard v2's measured and labelled figures (PLAN step 5.4).
  - **"After one generic fix" is wrong:** X1 needed two (PLAN Appendix F).
  - **Its `docs/` row names the plan and the gate packets,** which decision 1 keeps private.
  - **It has no pictures:** add the one-page architecture diagram and one Control Tower screenshot (PLAN step 5.1).

*Proposed decision 7:* retire the "Overnight run" section of `AGENTS.md` before publishing it. PLAN Appendix E keeps the history.

G5's acceptance now also needs PLAN step 5.1's "done when": a fresh clone of the pushed branch runs `make setup`, `make check` and `make demo`, and `lansh freeze` reports unchanged.

**What was built** (Phase 4)
- **4.1, the Control Tower** ([src/lansh/ui/app.py](../src/lansh/ui/app.py)) has four pages: Estate, Job (9 tabs), Scorecard and Audit.
  - It works without Markdown: a missing `evidence.md` is rendered from the JSON.
  - It lists the held-out runs published inside the showcase.
  - It puts LANSH beside the comparison approaches, and shows each heal timeline.
- **4.2, the showcase:** `lansh showcase --from dev-estate --holdout dev-holdout --learning dev-holdout-learn` writes `runs/showcase/`, `held-out/` and `learning/`, plus `freeze.json`.
  - Bulky data stays behind.
  - Absolute paths become repo-relative. The gate logs are copied byte for byte, since their hash chains must verify.
  - Publishing stops if any file still names the home folder.
- **4.3, the scorecard:** `runs/showcase/scorecard.md`. Every number comes with its files and their SHA-256, and the projection onto 1,600 jobs keeps its assumptions labelled.
- **4.4, documentation:**
  - [docs/architecture.md](architecture.md) and [docs/responsible-ai.md](responsible-ai.md), each about a page, with final numbers;
  - `AI_USAGE.md` (the comparison agents and the freeze added);
  - `THIRD_PARTY.md`, current (`make third-party` changes nothing).
- **4.5, the fresh-clone test:** run on a copy of exactly the files git would publish (`git ls-files -co --exclude-standard`), since nothing can be committed overnight.

**Check it yourself** (offline)
```bash
make demo                                                    # T04 through all five gates by replay, then the Control Tower
uv run lansh run --all --run replay-check --mode replay      # the whole estate: 10 MATCH, 5 waves cut over, no live call (about 9 min)
uv run lansh audit verify --run showcase                     # and --run showcase/held-out, --run showcase/learning
uv run lansh scorecard --run showcase --holdout showcase/held-out --learning showcase/learning
```

**Evidence**
- **Control Tower:** under Streamlit AppTest, every page and every job's 9 tabs render without an exception for all 7 runs, and `lansh ui` serves (`/_stcore/health`: ok).
- **`make demo`:** T04 MATCH in 64 s with the SQL Server container stopped and no Claude call. In the fresh copy it takes 90 s.
- **The whole estate by replay:** 10 of 10 MATCH, waves 1–5 cut over, no live call, 8.5 minutes. Every migrated module is byte-identical to the estate run's.
- **The showcase:**
  - 6.6 MB, 336 files, with no home paths;
  - gate logs intact (126, 17 and 20 entries);
  - the scorecard's sources all resolve inside `runs/showcase/`.
- **The fresh copy:** `make setup` works once the README is present. `make check` passes 665 tests, failing only the known `.env.example` test and the `.gitignore` test, which needs a git repository; that one passes after `git init`.
- **The pre-publication scan, a preview of PLAN step 5.13:** 371 files, the code plus the Markdown deliverables, checked against:
  - the secret values in `.env` and `~/.authinfo`;
  - the home path;
  - API-key, AWS-key, GitHub-token and private-key patterns;
  - the owner's email, and EXL addresses.

  No secret was found. The hits:
  - the author email in `pyproject.toml` (the team's entry);
  - dummy keys in `tests/test_llm_gateway.py`;
  - the organiser's address in `docs/PLAN.md` and `docs/tutorial.md`.

**Changes from the plan**
1. **The showcase is the agent's development run, published, not a fresh live run with a person's sign-offs.** The sign-offs are the team's (AGENTS.md). The timings stay honest: the scorecard counts every replayed answer at its recorded live time.
2. **The held-out runs are published inside `runs/showcase/`,** because the `.gitignore` tracks only `runs/showcase/` and `runs/cassettes/`.
3. **`make setup` skips creating `.env` when there's no `.env.example`.** It used to stop there, before the demo could run. (Undone since: the template is back, and `make setup` copies it.)
4. **`README.md` is unchanged** (AGENTS.md); the proposed text is below.

**Risks and open issues**
- **As the `.gitignore` stands, a clone has no Markdown at all.** It lacks the README, `AI_USAGE.md`, `THIRD_PARTY.md`, both one-page notes and the evidence reports. `uv sync` fails, because `pyproject.toml` names `README.md`. This blocks G6 (decision 1).
- **The Control Tower was checked headlessly, not by eye.** Look at it once before recording the video.

**Decisions needed** (the team only)
1. **Publish the Markdown deliverables.** *Default:* in `.gitignore`, delete the `*.md` line and replace `docs/` with:
   ```gitignore
   # EXL material is never committed (plan decision D2); only the two submission notes are published
   docs/*
   !docs/architecture.md
   !docs/responsible-ai.md
   ```
   That publishes:
   - `README.md`, `AI_USAGE.md`, `THIRD_PARTY.md`;
   - `AGENTS.md` and `CLAUDE.md` (trim the overnight-run section if you prefer);
   - `estate/README.md`, `estate/holdout/README.md` and `LABELS.md` (unsealed now);
   - `spikes/README.md`, and the evidence reports in `runs/showcase/`.

   `docs/PLAN.md`, `docs/gates.md` and `docs/tutorial.md` stay private. They carry the organiser's address, so scrub it first if you publish them. Then run the scan again (PLAN step 5.13).
2. **`.env.example`.** *Done:* restored as `tests/fixtures/.env.example`, with `MSSQL_SA_PASSWORD=` and the optional overrides commented out. The smoke test's SQL Server step and `test_env_example_lists_required_settings` expect it.
3. **The showcase run with a person's sign-offs.** *Default:* `uv run lansh run --all --run showcase-live --reviewer person:<name> --interactive --mode replay`, then `uv run lansh showcase --from showcase-live --holdout dev-holdout --learning dev-holdout-learn` and the scorecard command above. *Corrected by the critical review:* between those two commands, rebuild the comparison runs, scores and adjudication in `showcase-live` (PLAN step 5.3, step 2), or publishing deletes them.
   - Replay keeps the recorded answers, so the results are the ones verified here.
   - Use `--mode live` on an account with headroom for a fresh recording.
   - Expect about 120 decisions (45 gates, 47 defects, 29 flows). Read each one: approvals under 20 s are flagged.
4. **The README.** *Default:* adopt the proposed text below, with the video links.
5. **Licence (D3) and the author email** in `pyproject.toml`. *Default:* decide both before going public.

**Not accepted overnight.** Every check that is mine holds. The release candidate still needs the README text and a `.gitignore` that publishes it, both reserved for the team. G5 is ready for their review.

**Decisions taken on the team's instruction (13 Nov).** A team member asked for the decisions the submission needs to be taken on their authority. They are made in the working tree; nothing is committed.
- **Decision 1, the Markdown.** The team published all of it on 12 Nov (`d06694b`, `a2268c6`), the plan and these packets included. That commit's `.gitignore` named `docs/week.py` instead of `docs/week2.py` and dropped the EXL rule, so the EXL deck and the unrelated `docs/week2.py` were pushed too, and `test_secrets_and_exl_material_are_gitignored` failed. Both rules are restored and the test passes. Both files are still tracked and in the history: before the repo goes public, take them out of the index and rewrite the history (the team's to run).
- **Decision 4, the README:** adopted and corrected, with the results, the business case from scorecard v2, the limitations as they stand, the architecture diagram and a Control Tower screenshot. The video links wait in a comment until they exist.
- **Decision 5:** no licence until the hackathon's terms settle ownership (D3). `pyproject.toml` names the three team members, with no personal address; the commits keep their author's address unless the history is rewritten.
- **Decision 6:** `runs/freeze.json` is tracked, and freeze 3 is recorded with its reason; `lansh freeze` reports unchanged.
- **Decisions 3 and 7 stay open.** A person's sign-off can't be given in a person's name by an agent, on anyone's authority, so the pack says plainly that the development runs' approvals are the agent's. `AGENTS.md`'s overnight-run section is the record `AI_USAGE.md` cites, so it stays.

**Status (13 Nov): not accepted yet.** In the working tree, `make check` passes 670 tests, `lansh freeze` reports unchanged and `lansh audit verify` is intact on all three showcase runs. G5 also needs PLAN step 5.1's fresh clone of the pushed branch, after the team's commit and push.

**Proposed README** (replace `README.md` with this; the Setup section stays as it is now)

````markdown
# LANSH

**A reconciliation-first agentic migration factory.** Team LANSH's entry to the EXL × Trinity
Data & AI Hackathon 2026, Challenge 03: agentic data platform modernisation.

LANSH migrates legacy T-SQL (SQL Server) and SAS jobs to PySpark on a Delta lakehouse, and
**proves for every job that the new output matches the legacy output record for record**:
counts, totals and every row, bugs included. Legacy bugs are reproduced exactly and flagged
with their measured impact for a human decision, and a person signs off at each of the five
stages: Discover, Design, Generate, Reconcile, Operate.

> Video: <YouTube (unlisted)> · <OneDrive> · <Google Drive>

<the one-page architecture diagram, as an image> <one Control Tower screenshot>

## Results

Every approach below was reconciled against the same golden outputs captured from SQL Server
2022 and SAS, under the same contracts.

| | LANSH | One-shot Claude | sqlglot alone |
|---|---|---|---|
| Development jobs reaching MATCH (7 T-SQL, 3 SAS) | **10 of 10**, all on the first translation | 8 of 10 | 0 of 10 |
| Outputs that ran cleanly but silently differed from the legacy output | **0** | 2, on 805 rows | 1, on 823 rows |
| Planted legacy bugs reproduced exactly | **8 of 8** | 6 of 8 (2 "fixed" silently) | – |

One-shot Claude is the same model and effort as LANSH's translator, with the same module
interface, but none of LANSH's knowledge (trap cards, language rules, draft) and no healing.
LANSH's heal loop alone then repaired both of its failures in one attempt each.

- **165,412 legacy rows proved record for record,** in a sandbox and again on Delta with
  chained inputs. 8 of 10 outputs have the legacy output's exact content hash; the other two,
  SAS doubles, match within 1e-9.
- **Held-out jobs** were written by an isolated agent and sealed until the factory was frozen.
  On the first run, **1 of 2 matched**. The other was stopped by its own trap test and escalated
  with its root cause, a SQL Server rounding rule that a trap card had wrong. After two generic
  fixes, 2 of 2 match; that second run is reported apart.
- **Detection, scored against a hidden answer key:**
  - 81 of 82 labelled trap occurrences found;
  - all 10 planted bugs (8 development, 2 held-out) flagged at their lines, 8 with the planted
    diagnosis;
  - 47 suspected defects listed, 46 of them measured on the legacy output and 20 with a
    non-zero impact;
  - 55 trap tests whose expected values come from the legacy engine.
- **Per job:** 6 Claude calls, about $1.01 API-equivalent (not billed: subscription) and 5.4
  minutes of machine time.
- **Business case:** projected onto a 1,600-job estate, <the saving from scorecard v2 (PLAN
  step 5.4), as a range over escalation rates from 15% to 50%, from measured manual minutes
  (the team's baseline) and measured reviewer minutes (the person-signed run), each figure
  tagged *measured* or *assumed*>. About $1 of Claude usage per job, at API prices.

Every number traces to a run artifact: `lansh scorecard --run showcase` writes
`runs/showcase/scorecard.md`, each figure with the files it came from and their SHA-256.

## Quick start: the offline demo

No Docker, SAS or Claude access needed: the golden outputs, the agents' answers and the legacy
engine's test results are all recorded in the repository.

```bash
make setup   # Python 3.14 and every dependency, with uv (needs Java 21: see Setup)
make demo    # replays T04 through all five stages and gates (about a minute), then opens the Control Tower
```

The Control Tower shows the whole estate's run (`runs/showcase/`): the waves, each job's legacy
code beside its PySpark, the lineage, the traps, the contract, the reconciliation, the defects
and every gate decision, plus the scorecard, the comparison runs with their heal timelines, and
the gate log's audit trail. The held-out runs are `showcase/held-out` and `showcase/learning`.

Other commands:

```bash
make check                                   # ruff and the offline tests
make test-e2e                                # T04 end to end in replay mode
uv run lansh run-job T04 --mode replay       # one job through the factory, from the command line
uv run lansh run --all --mode replay         # the whole estate, wave by wave
uv run lansh reconcile --job T05 --candidate my_t05.py   # check a hand-written job record for record
uv run lansh audit verify --run showcase     # check the gate log's hash chain
uv run lansh scorecard --run showcase --holdout showcase/held-out --learning showcase/learning
```

## How it works

```text
Discover ─H1─► Design ─H2─► Generate ─H3─► Reconcile ─H4─► Operate ─H5─► cut-over
                               ▲               │
                               └─ heal (≤ 3) ──┘
```

- **Agents propose, deterministic checks verify, people approve.** Seven Claude agents
  (Opus 5.5, through `claude -p` on a subscription; no API key) write lineage, trap findings,
  contracts, suspected defects with impact queries, translations, test inputs and fixes.
  Lineage is checked against the schemas and by sqlglot; code passes guardrails and a literal
  check before it runs, in an isolated worker; tests take their expected values from the legacy
  engine; every output is reconciled against golden outputs captured from SQL Server 2022 and
  SAS. The full design is [docs/architecture.md](docs/architecture.md), with the Azure target
  state.
- **Bugs are reproduced, never silently fixed**, and each is flagged with its impact measured
  on the legacy output, for a person to decide: reproduce, or fix after cut-over.
- **No silent tolerances.** Exact comparison by default; any other policy needs a reason the
  engine justifies and H2 approval.
- **Responsible AI**: synthetic data only, `pii` masked in anything Claude sees, guardrailed and
  sandboxed code, human gates with automation-bias controls, a hash-chained audit log
  ([docs/responsible-ai.md](docs/responsible-ai.md)).

## Where things are

| Path | What |
|---|---|
| `src/lansh/` | The factory: `discover`, `design`, `generate`, `reconcile`, `operate`, `governance`, `llm` (the Claude gateway), `ui` (the Control Tower), `pipeline` |
| `estate/` | The legacy estate: 10 development jobs and 2 held-out jobs (unsealed at the factory freeze), their source data, golden outputs and the answer key ([estate/README.md](estate/README.md)) |
| `migrated/` | The factory's output: the 12 accepted PySpark jobs, their trap tests and their data contracts |
| `runs/showcase/` | The committed estate run (evidence reports, defect register, scorecard, comparison runs, gate log), with the held-out runs in `held-out/` and `learning/` and the factory freeze record |
| `runs/cassettes/` | Every recorded agent answer, and the legacy engine's answers to test inputs |
| `docs/` | The architecture and the Responsible AI note (and the plan and gate packets, if decision 1 is changed to publish them) |

## Setup

<the current README's "Setup" section, steps 1-7, unchanged>

## Limitations

- The legacy estate is synthetic and was written by the team, with AI assistance, including its
  planted bugs; two held-out jobs written by an isolated agent, sealed until the factory was
  frozen, measure how well the factory generalises.
- SAS trap tests check the contract only (SAS isn't run per test case); each SAS job is still
  proved against its real SAS output.
- A live run's agent answers can differ from the recorded ones; reconciliation catches any that
  are wrong, and replay makes the demo reproducible.

## Data statement

All data is **100% synthetic**, produced by a seeded generator (seed 20251231) with fictional
Irish names and addresses (Faker `en_IE`) and `.example` email addresses. There is no personal
data anywhere.

## AI usage and third-party software

The AI tools used to build LANSH, and the ones inside it, are declared in
[AI_USAGE.md](AI_USAGE.md). Third-party packages, services and their licences are listed in
[THIRD_PARTY.md](THIRD_PARTY.md).
````
