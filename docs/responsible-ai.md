# LANSH: Responsible AI note

*Team LANSH: Gregory Korchagin, Vansh Agarwal, Charly Martin Avila · EXL × Trinity Data & AI
Hackathon 2026, Challenge 03*

LANSH uses Claude agents (Opus 5.5) to migrate legacy data jobs. One rule underpins every
safeguard: **nothing an agent produces is trusted until a deterministic check has verified it
and a person has approved it.**

## Data and privacy

- **Synthetic data only:** a seeded generator builds a fictional Irish insurer (232,267 rows,
  Faker's Irish locale, `.example` emails, no real records).
- **Tagged columns.** `pii` (names, email, address, date of birth) and `protected` (age, and
  county as a possible proxy) are tagged in the data dictionary, and lineage carries the tags
  into every output column they feed.
- **Minimal disclosure.** Claude sees code, schemas, difference statistics and at most five
  sample rows per difference, with `pii` values hashed.
- **No API key.** The prototype uses Claude Code on a subscription, acceptable only because
  every row is synthetic; in production, Claude runs in Microsoft Foundry in the client's Azure
  tenancy. Secrets stay in `.env`, and recorded answers are scrubbed.

## Bias

LANSH **reproduces legacy logic faithfully, bias included**, because silently changing a
business rule would be worse. Instead, **every path from a tagged column into an output needs
a decision at H2.** S04's risk score loads for age and county. LANSH traces
`stg.customers.date_of_birth` through T01 into `age_load`, and a person chooses *reproduce
as-is* or *reproduce, and flag for a bias review*.

The scorecard measures what that decision is about, on S04's legacy output: under-25s are rated
HIGH 14.3% of the time (168 risk scores), against 5.3% at ages 25–59; by county, from 1.3% to
9.7% across the 20 counties with at least 40 scores ([runs/showcase/scorecard.md](../runs/showcase/scorecard.md),
"Bias"). Whether a loading is justified is a business and legal decision, not LANSH's.

## Safeguards

- **Verification before trust.**
  - Lineage must name real columns, and sqlglot cross-checks it.
  - Contract keys must be unique in the legacy output.
  - Every output is reconciled record for record against outputs from the real engines.
  - T-SQL tests take their expected values from SQL Server, and SAS tests from the contract;
    never from the model.
  - Bugs are reproduced and flagged with their measured impact, never fixed silently.
- **Sandboxing.** Generated code must pass:
  - an import allowlist;
  - bans on I/O and engine internals;
  - a parse of every SQL string;
  - the **literal check**: every data constant must come from the legacy code, the contract or
    a trap card, so a fixer can't hard-code its way to a match.

  It then runs in a separate process with a timeout and no credentials.
- **Prompt injection.** Legacy code is untrusted input, and agents run with no tools: no files,
  shell or network. An injected instruction can at most steer an answer, and an answer that
  makes the code wrong fails reconciliation. An answer that leaves something out, such as a
  lineage edge or a defect, isn't caught deterministically (see the limitations).
- **People at every stage, with automation-bias controls.**
  - Five gates, passed in order, with hash-pinned evidence shown before any decision.
  - Approving warnings needs a written reason; approvals under 20 seconds are flagged.
  - A seeded 10% of decisions are re-reviewed.
  - Every decision goes into a hash-chained log (`lansh audit verify`).
  - An agent's approval never counts as a person's sign-off.
  - At scale, only jobs with warnings get per-job review; clean jobs are approved per wave.
- **Transparency.** An evidence report per job; every Claude answer recorded and replayable.

## What the runs showed

- **Manual baseline.** T05 and S01 were completed personally, with phase timings recorded in
  `baseline/timesheet.csv`: 148 and 169 minutes respectively, averaging 158.5 minutes per job.
  Both finished with zero differences left at final reconciliation.
- **Why verification matters.** One-shot Claude, the same model without LANSH, ran cleanly on
  all 10 development jobs, but 2 outputs silently changed 805 rows. In both it had "fixed"
  legacy behaviour nobody had decided to change. Reconciliation caught both.
- **Bugs kept visible.** All 8 planted bugs reproduced exactly, 6 flagged with the planted
  diagnosis; 47 suspected defects went to a decision with their measured impact.
- **Generalisation, reported as it came out.** Two held-out jobs, written by an isolated agent
  and unsealed only after the factory was frozen, ran once.
  - One matched first time.
  - The other was stopped by its own trap test and escalated to a person, with the root cause:
    a SQL Server rounding rule that a trap card had wrong. It was not shipped with 3 wrong rows.
  - Both planted bugs were flagged with the right diagnosis.

## Limitations

- The estate is synthetic, and the team wrote it with AI help, planted bugs included. That is
  why the held-out jobs exist.
- SAS tests check the contract only; each SAS output is still proved against real SAS output.
- Model output varies. Replay makes the demo reproducible, and reconciliation catches a live
  run's wrong answers.
- Checks catch wrong code, not omissions: a missed lineage edge or defect isn't caught
  deterministically.
- Every job is proved on one reporting date, 31 December 2025.
- The manual baseline covers two jobs, so the time comparison is indicative.
- The local worker can't block network access; in production, the cluster's policy does.
- In the development runs an agent approved the gates, and the gate log records each approval
  as the agent's; an agent's approval never counts as a person's sign-off.
