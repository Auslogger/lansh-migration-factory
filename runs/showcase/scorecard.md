# Scorecard: run showcase

| Metric | Value | Unit | From |
|---|---|---|---|
| Jobs migrated | 10 | jobs | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Jobs reconciled record for record (MATCH, zero unexplained differences) | 10 | jobs | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| First-pass MATCH (no healing needed) | 10 | jobs | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Heal attempts | 0 | attempts | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Jobs escalated to a person | 0 | jobs | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Legacy output rows proved record for record | 165412 | rows | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Outputs whose content hash equals the legacy output's | 8 | outputs | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Trap-focused tests passing | 55 | of 55 | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Suspected legacy defects flagged | 47 | defects | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Claude calls per job | 6 | calls | runs/showcase/S01/metrics.json, runs/showcase/S03/metrics.json … |
| API-equivalent cost per job (not billed: subscription) | 1.01 | USD | runs/showcase/S01/metrics.json, runs/showcase/S03/metrics.json … |
| Machine time per job, end to end, with every Claude call live | 5.35 | minutes | runs/showcase/S01/metrics.json, runs/showcase/S03/metrics.json … |
| Claude model time per job | 4.84 | minutes | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |
| Live Claude calls in this run | 71 | calls | runs/showcase/llm_usage.jsonl |
| Gate decisions recorded | 50 | decisions | runs/showcase/gates.jsonl |
| Gate decisions made by people | 0 | decisions | runs/showcase/gates.jsonl |
| Planted bugs flagged with the planted diagnosis (read by the evaluator) | 6 | of 8 | runs/showcase/scores.json |
| Planted bugs reproduced exactly (their jobs MATCH record for record) | 8 | of 8 | runs/showcase/scores.json, runs/showcase/S01/metrics.json … |
| Labelled trap occurrences detected | 81 | of 82 | runs/showcase/scores.json |
| Armed semantic traps detected | 47 | of 47 | runs/showcase/scores.json |
| Trap findings that match the answer key (precision) | 111 | of 135 | runs/showcase/scores.json |
| Answer-key checks giving the legacy result on the migrated output | 41 | of 41 | runs/showcase/scores.json |
| Comparison run, sqlglot alone: jobs reaching MATCH | 0 | of 10 | runs/showcase/benchmark.json |
| Comparison run, one-shot Claude (same model, none of LANSH's knowledge, no healing): jobs reaching MATCH | 8 | of 10 | runs/showcase/benchmark.json |
| Comparison run, one-shot Claude, then LANSH's heal loop alone: jobs reaching MATCH | 10 | of 10 | runs/showcase/benchmark.json |
| One-shot translations that ran cleanly but were wrong (only reconciliation shows it) | 2 | of 10 | runs/showcase/benchmark.json |
| Rows those translations got wrong | 805 | rows | runs/showcase/benchmark.json |
| Held-out jobs (sealed, written by an isolated agent) reaching MATCH on their first run | 1 | of 2 | runs/showcase/held-out/X1/metrics.json, runs/showcase/held-out/X2/metrics.json |
| Held-out planted bugs reproduced exactly (their jobs MATCH record for record) | 1 | of 2 | runs/showcase/held-out/X1/metrics.json, runs/showcase/held-out/X2/metrics.json |
| Held-out planted bugs flagged with the planted diagnosis (read by the evaluator) | 2 | of 2 | runs/showcase/held-out/holdout_scores.json |
| Held-out jobs reaching MATCH after the post-freeze learning fixes (a second run, not a held-out result) | 2 | of 2 | runs/showcase/learning/X1/metrics.json, runs/showcase/learning/X2/metrics.json |
| Golden capture per job (both approaches need it) | 0.09 | minutes | estate/golden/S01/manifest.json, estate/golden/S03/manifest.json … |
| Jobs with warnings in this run (each carries a planted bug by design) | 100 | % | runs/showcase/S01/evidence.json, runs/showcase/S03/evidence.json … |

## Projection onto 1,600 jobs

| manual minutes per job | case | manual: person-hours for the estate | LANSH, every gate reviewed: person-hours | LANSH, risk-based gating: person-hours | hours saved | manual: people for 6 / 4 months | LANSH: people for 6 / 4 months |
|---|---|---|---|---|---|---|---|
| 240 | low | 6402 | 1629 | 1096 | 83% | 7 / 10.5 | 1.2 / 1.8 |
| 480 | middle | 12802 | 2589 | 2056 | 84% | 14.1 / 21 | 2.3 / 3.4 |
| 960 | high | 25602 | 4509 | 3976 | 84% | 28.1 / 42 | 4.4 / 6.5 |

Gate decisions: 8,000 with every gate for every job, 1,600 with risk-based gating.

- LANSH person-hours = reviewer minutes (5 a gate; H2-H4 for jobs with warnings, H1 and H5 per wave of about 20 jobs) + escalation rate x manual minutes + golden capture, per job.
- Manual minutes per job are assumptions (4, 8 and 16 hours) until the team's manual baseline (plan §9.1) is recorded in baseline/timesheet.csv; the baseline row then appears first.
- Risk-based gating assumes 30% of a real estate's jobs carry warnings and get per-job review at H2-H4. That is an assumption: in this run 100% did, because every development job has a planted bug.
- The projection assumes 15% of a real estate's jobs escalate and are migrated by hand (in this run 0% did).
- For reference, EXL reports a 50% efficiency gain from its Code Harbor tooling on a SAS-to-PySpark migration (plan §9.3); LANSH's figure counts person-hours to a proven, record-for-record MATCH.
- Machine time runs in parallel and needs no people; it is reported separately.
- Claude at API prices for the whole estate: about $1,608 (measured per job here, not billed on a subscription).
- On their first run, 1 of the 2 held-out jobs escalated to a person (stopped by a failing test, not shipped): a sample too small to replace the assumed rate.
