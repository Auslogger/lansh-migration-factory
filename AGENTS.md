# AGENTS.md: working standards for LANSH

These rules apply to everyone working on this repo, AI coding agents included. They condense
§12 of the master plan, [docs/PLAN.md](docs/PLAN.md). Read the plan's step before you start it.

## Overnight run (from 12 Nov 2026): read this first

The team has handed the build to one agent, working alone and without them. Where these rules
conflict with anything below or in the plan, these win.

- **Goal:** take LANSH as far as you can towards a winning Challenge 03 submission: Phase 2
  onwards in `docs/PLAN.md`, through to everything the submission needs. Nobody will answer
  questions, so use your best judgement throughout, measured against the challenge's standards
  below.
- **Work alone.** No subagents, parallel agents or workflows. Do every step yourself, one after
  another; steps the plan marks *independent* simply run in sequence.
- **Accept gates yourself.** At each gate:
  1. write its packet into `docs/gates.md` (the PLAN Appendix C format);
  2. check every "done when" and run the evidence commands;
  3. if they hold, record the acceptance in PLAN Appendix D ("accepted by the agent, overnight run, <date>; evidence: ...") and carry on.

  Never accept a gate whose checks fail: fix the work, then check again.
- **The plan is yours to change.** Edit `docs/PLAN.md`, or depart from it, whenever your
  judgement says the submission is better for it. Record each change and its reason in Appendix
  E.
- **Don't commit unless the team asks.** At the team's request the overnight work was committed
  and pushed on 12 Nov, with the history reworded (`b1568b2` on `origin/main`; the old `c870e52`
  no longer exists). Leave every new change in the working tree for them to review. No
  `git commit`, `push`, `branch`, `stash`, `reset` or `rebase`, and no other history change,
  unless they ask. `git status` and `git diff` are fine.
- **Keep the codebase small and readable.** Change existing files rather than add new ones.
  - Write no new READMEs or notes files, and don't update `README.md`.
  - Keep `docs/PLAN.md` (tracker and progress log) and `docs/gates.md` current.
  - New Markdown is only for the submission's own deliverables (see "The challenge's standards").
- **Checkpoint after every step.** Tick it in Appendix D and add one line to Appendix E, so
  the team, or a resumed session, can see exactly where you stopped. The Claude subscription's
  5-hour usage window can end the run without warning, and those two appendices are the handover.
- **Not yours to do.** Prepare these, then list them for the team in Appendix E:
  - making anything public (the repo's visibility, the video);
  - the submission email;
  - the manual baseline (§9.1: a person migrates T05 and S01 by hand, with every AI tool off);
  - recording the demo video;
  - the human sign-offs in the showcase run. H1–H5 are the product's proof that a person approved each stage. In development runs, record your approvals as the agent's, never as a person's.

### Where things stand
- **Phases 0–4 are built, and G1–G4 are accepted** (by the agent, overnight run, 12 Nov).
  - Development estate: 10 of 10 jobs MATCH on the first translation. Comparison runs: sqlglot
    0/10, one-shot Claude 8/10, one-shot plus our heal loop 10/10.
  - Held-out: first run 1 of 2 (X1 escalated), then 2 of 2 after two generic post-freeze fixes,
    reported apart.
  - Numbers with their sources: `runs/showcase/scorecard.md`. The details are in PLAN
    Appendix E.
- **Committed and pushed** (private repo): the code, `migrated/`, `runs/showcase/`,
  `runs/cassettes/` and the held-out jobs. The `.gitignore` still keeps every `*.md` out of git,
  so this file, `docs/` and `README.md` exist only in this working tree.
- **`make check` passes in full** (667 tests). The `.env` template now lives at
  `tests/fixtures/.env.example`, and `make setup` copies it to `.env`.
- **G5 is ready but not accepted.** Its packet is in `docs/gates.md`. It waits on the team's
  decisions about the README and the `.gitignore`; until the Markdown is tracked, a fresh clone
  can't `uv sync`, because `pyproject.toml` names `README.md`.
- **A critical review (12 Nov),** checked by an independent review, rewrote Phase 5 in priority
  order: PLAN §4, with the findings in Appendix G.
  - `lansh freeze` reports CHANGED (`config.py`, after the `.env` template move), and its
    record, `runs/freeze.json`, isn't in git. Step 5.1 tracks it and records freeze 3.
  - The business case's 83–84% is roughly 1 minus the assumed escalation rate. Step 5.4
    measures what can be measured and labels the rest.
  - **Don't re-publish the showcase with G5 decision 3's commands alone:** they delete the
    comparison and scoring evidence. Step 5.3 rebuilds it first.
- **Next:** PLAN Phase 5, P0 steps first.
  - The team's: 5.2 (manual baseline), 5.3 (person-signed showcase run), 5.10 (video), 5.14
    (go public) and 5.15 (submit), plus the G5 decisions that 5.1 applies.
  - An agent can do 5.1 once those decisions are made, plus 5.4–5.9 and 5.11–5.13.

### Environment for the night
- **Keep the Mac awake.** First thing, run `caffeinate -dimsu -t 43200` in the background. It's on mains power.
- **SQL Server** runs in OrbStack as container `lansh-sql`; `make legacy-up` starts it. The legacy database is `SynthInsureDW`, and `make load` rebuilds it.
- **SAS OnDemand** logs in headless through saspy and `~/.authinfo` on every run. It's needed only to re-verify the frozen SAS golden outputs (`make legacy-verify-all`).
- **Claude.** LANSH's own agents call `claude -p` on the same subscription you run on, through `lansh.llm`. It replays by default, and live calls are capped at 150 per run (decision D5). Record live only what the demo and the evidence need, and replay the rest.

### The challenge's standards
- **The brief** is `docs/EXL_Trinity_Data_AI_Hackathon_2026.pptx`, slide 8 (Challenge 03):
  - migrate 10–15 legacy jobs (T-SQL and SAS) to PySpark;
  - use agents to map column-level lineage, translate the logic and generate tests;
  - prove reconciliation record for record;
  - go through five stages, each behind a human gate: Discover, Design, Generate, Reconcile, Operate.
- **The rubric:** Business Impact 30, Technical 25, Innovation 20, Responsible AI 15, Presentation and Q&A 10. Ties go to Business Impact, so every claim needs a number traced to a run artifact (plan §9).
- **The submission is due 14 Nov, 23:59 Irish time.** It needs:
  - a deck of at most 10 slides;
  - a demo video of at most 3 minutes;
  - the GitHub repo, with a README and setup;
  - a one-page architecture diagram;
  - a one-page Responsible AI note;
  - the AI tools and reused code declared;
  - synthetic data only.

  Draft the documents as single files in `docs/` (the plan names `docs/architecture.md` and `docs/responsible-ai.md`). The plan's §17 checklist is the bar for the repo.

## Gates
- Every phase ends at a gate (G0–G6), reviewed against the PLAN Appendix C packet in
  [docs/gates.md](docs/gates.md). During the overnight run you accept gates yourself (above).
- Keep PLAN Appendix D (step tracker) and Appendix E (progress log) current.

## Decisions
These normally need the team: scope, contract changes after G1 (`src/lansh/contracts.py`), new
external services, anything made public, licence and declarations, and legacy-bug decisions
(reproduce or fix). Overnight, decide them yourself and record the reason in the gate packet,
with two exceptions: making anything public, and anything that costs money (a paid API, a paid
service).

## Stack
- Python 3.14 with uv. Java 21: the Makefile sets `JAVA_HOME`, and `lansh.spark` falls back to it.
- Pinned: `pyspark==4.2.0`, `delta-spark==4.4.1`, `pandas>=2.3,<3`. Re-test before changing a pin.
- ruff and pytest. Type hints throughout. Pydantic v2 models from `lansh.contracts` between
  modules. Use `logging`, not `print` (scripts and spikes excepted).
- Spark: always `lansh.spark.get_spark()` (Delta, UTC, ANSI on, few partitions).
- Claude: only through the gateway in `lansh.llm`, which runs `claude -p` on our subscription.
  Never use an API key, never `--bare`.

## Code style
- **Docstrings** on every module, class and function. The opening `"""` sits on its own line,
  then a one-line summary, then (when it adds something) a short paragraph on what isn't
  obvious from the code, then `Args:`, `Returns:` and `Raises:` sections as needed:

  ```python
  def fetch_table(conn, table):
      """
      Read a whole table with exact Arrow types.

      DECIMAL stays decimal and DATETIME2 keeps its microseconds, so the result can be
      hashed and compared without float rounding.

      Args:
          conn: Open pymssql connection.
          table: Schema-qualified table name, such as ``rpt.claims_summary``.

      Returns:
          The column definitions, and the rows as a pyarrow Table in that column order.
      """
  ```

- **Comments** are short, start in lower case and say *why*, not what the line does:
  `# exclude the header row without dropping the first observation`.
- **Sections** inside a long module start with a `### Section name` comment.
- Exceptions: a Typer command's docstring is its `--help` text, so it stays one plain
  sentence. Don't change the docstring of a Pydantic model used as a Claude answer: its JSON
  schema, docstring included, is part of the hash that finds a recorded answer.
- Legacy code in `estate/` keeps its own deliberate legacy style; never restyle it.

## Docs
Documentation lives in the files that already exist: this file, `docs/PLAN.md`, `docs/gates.md`
(gate packets), `estate/README.md`, `estate/holdout/README.md` and `spikes/README.md`.
- Don't add Markdown files for results, reviews or notes, and leave `README.md` alone.
- Put a finding where its reader will look: the gate packet, the plan's progress log, or the docstring of the code it's about.
- The `.gitignore` keeps Markdown out of git, so these files live only in the working tree.

## Tests
- `make check` runs ruff and the offline tests. Everything must pass.
- Integration tests are marked `mssql`, `sas` or `live_llm` and run with `make test-mssql`,
  `make test-sas` or `make test-live`. Unit tests never need Docker, SAS or Claude.

## Git
- During the overnight run: no commits and no history changes (above).
- Always: no AI signatures anywhere. That means no `Co-Authored-By:` trailers, "generated with"
  lines or similar tags in commits, pull requests or code. AI use is declared once, in `AI_USAGE.md`.

## Secrets
Only in `.env` (gitignored) and `~/.authinfo`. Never in code, logs, recorded answers or commits.

## "Done" means
The step's "done when" holds, tests are added, `make check` passes, the plan and gate packet are updated, and the step is ticked in PLAN Appendix D.

## Never
- commit, push or change git history during the overnight run, or change the repo's visibility
- read `estate/holdout/` or `estate/labels/` from factory code (only evaluation code reads labels)
- edit golden outputs (`estate/golden/`); a change means a fresh capture approved at a gate
- write job-specific factory code (`if job_id == ...`); fix the factory, never the job
- fix a legacy bug inside a migrated job; reproduce it and flag it
- stage a failure for the demo, or record an agent's approval as a person's
- switch off Spark's ANSI mode (`spark.sql.ansi.enabled`) or Delta's type checks
  (`spark.databricks.delta.schema.typeCheck.enabled`) to make an error go away; both
  error messages suggest it, and both would hide real differences

## Where things live
| Path | What |
|---|---|
| `src/lansh/` | the factory. Built so far: `contracts`, `llm` (Claude gateway), `engines` (SQL Server, SAS), `estate` (legacy estate tooling and the `lansh estate` commands), `cli`. Still to come: discover, design, generate, reconcile, operate, governance, ui |
| `estate/` | the legacy estate: `jobs.yaml`, `data/`, `tsql/`, `sas/`, `golden/`, `holdout/` (sealed), `labels/` (answer key). Start with `estate/README.md` |
| `tests/` | pytest suites; markers as above |
| `spikes/` | Phase 0 spike scripts; `spikes/README.md` has their findings and the decisions for Phase 2 |
| `docs/` | `PLAN.md` (the plan), `gates.md` (gate packets), `tutorial.md` (for people new to the ideas), the challenge deck, and later the submission documents |
| `scripts/` | `smoke_test.py` (`make smoke`) and `third_party.py` (`make third-party`) |
| `compose.yaml` | SQL Server 2022 for the legacy T-SQL jobs (`make legacy-up`) |
