# AI usage declaration

The hackathon rules ask every team to declare the AI tools it used and what they did. This
file is kept current as the build goes on; the same declaration goes in the deck and in the
submission email.

## In development

| Tool | Model | What it did |
|---|---|---|
| Claude Code (CLI and VS Code extension) | Claude Opus 5.5 | Helped write the plan and the tutorial; scaffolded the repository; wrote and reviewed factory code, tests and documentation; wrote the synthetic data generator and the legacy T-SQL and SAS jobs (the legacy estate), including the deliberately planted bugs; ran the environment spikes. The team reviewed Phases 0 and 1 at gates G0–G2. |
| Claude Code, one agent working alone (overnight run, from 12 Nov) | Claude Opus 5.5 | Built Phases 2 to 4 under the team's written rules (`AGENTS.md`, "Overnight run"): the factory (Discover, Design, Generate, Reconcile, Operate, the gate log, the Control Tower), its tests, the comparison runs, the scorecard and the draft architecture and Responsible AI notes. It accepted build gates G1 onwards itself, each with a packet in `docs/gates.md`, and recorded its development-run approvals as the agent's, never as a person's. The team reviews everything before submission; the showcase run's sign-offs are theirs. |
| Claude Code subagents | Claude Opus 5.5 | Built the legacy estate and the spikes in parallel. For most legacy jobs one agent wrote the job, its answer-key labels and its check queries, and a second, independent agent reviewed it adversarially (realism, honest-looking bugs, label accuracy, whether each check really proves its claim, determinism). Throwaway PySpark translations then proved several jobs can be reproduced exactly; they were deleted, and none is kept in the repository. |

**How the legacy estate was made.** The synthetic data, the ten development jobs, their planted
traps and bugs, and the answer key were written with AI assistance, following the plan's design
brief. That's why the evaluation also uses jobs the factory's authors never saw: two **sealed
held-out jobs** written by an isolated agent (below), opened only after the factory is frozen.

## In the product

| Component | Model | What it does |
|---|---|---|
| LANSH agents: lineage, trap scan, contract, defect reviewer, translator, test author, diagnoser/fixer | Claude Opus 5.5 through Claude Code's non-interactive mode (`claude -p`) on our subscription, with effort set per agent | Proposes lineage, trap findings, contract descriptions, suspected defects with impact queries, translations, test inputs and fixes. Nothing it produces is trusted until it is checked: lineage against the schemas and sqlglot, keys against the golden output, code by the guardrails and the literal check, tests against expected values from the legacy engine, and every output by record-level reconciliation. Then a person approves at gates H1–H5. |
| The comparison runs "one-shot Claude" and "one-shot Claude, then the heal loop" | Claude Opus 5.5, as above | One translation per job, with the same module interface as LANSH's translator but no trap cards, language rules, draft or healing; then LANSH's fixer alone on the translations that failed. They measure what LANSH's knowledge and proof loop add (plan §9.5). |

Every Claude call is recorded and can be replayed offline, so the demo runs without Claude
access. The agents only ever see synthetic data.

## Held-out jobs

The sealed held-out jobs (plan §7.4) were written by a separate, isolated Claude agent that
saw only short business briefs, the source schema and the legacy style guide. It never saw
the factory code, prompts, trap cards or the planted-bug list. The jobs were unsealed only
after the factory was frozen (12 Nov 2026, 03:29 UTC; `lansh freeze` checks it), and run once.

## Done without AI

The manual baseline (plan §9.1) is done by a person with every AI assistant switched off,
and screen-recorded as evidence.

## Existing code

LANSH reuses no third-party source code. Its dependencies are listed in `THIRD_PARTY.md`.
