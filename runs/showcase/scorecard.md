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
| Gate decisions reviewed and accepted by people | 50 | decisions | runs/showcase/gates.jsonl, runs/showcase/human_review.json |
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
| S04 risk scores rated HIGH, customers under 25 (legacy output) | 14.3 | % of 168 | estate/golden/S04/rpt.risk_scores.parquet |
| S04 risk scores rated HIGH, customers aged 25-59 (legacy output) | 5.3 | % of 1404 | estate/golden/S04/rpt.risk_scores.parquet |
| S04 risk scores rated HIGH, lowest county (Clare; of 20 counties with 40+ scores) | 1.3 | % | estate/golden/S04/rpt.risk_scores.parquet, estate/golden/T01/dw.dim_customer.parquet |
| S04 risk scores rated HIGH, highest county (Laois; of 20 counties with 40+ scores) | 9.7 | % | estate/golden/S04/rpt.risk_scores.parquet, estate/golden/T01/dw.dim_customer.parquet |

## Business case: the client's 1,600 jobs (a projection)

The notes identify measured inputs and the assumptions used to project them onto the client's estate.

### By hand

| case | hours per job by hand | person-hours | people for 4 months | people for 6 months | cost (EUR) |
|---|---|---|---|---|---|
| manual baseline | 2.6 | 4229 | 6.9 | 4.6 | 362497 |
| low | 4 | 6402 | 10.5 | 7 | 548783 |
| middle | 8 | 12802 | 21 | 14.1 | 1097355 |
| high | 16 | 25602 | 42 | 28.1 | 2194497 |

### Sensitivity: with LANSH

| escalated to a person | review minutes per job | person-hours | people for 4 months | people for 6 months | cost (EUR) |
|---|---|---|---|---|---|
| 15% | 30 | 1436 | 2.4 | 1.6 | 123126 |
| 15% | 60 | 2236 | 3.7 | 2.5 | 191697 |
| 30% | 30 | 2070 | 3.4 | 2.3 | 177469 |
| 30% | 60 | 2870 | 4.7 | 3.2 | 246040 |
| 50% | 30 | 2916 | 4.8 | 3.2 | 249926 |
| 50% | 60 | 3716 | 6.1 | 4.1 | 318497 |

- LANSH person-hours per job = a person's review minutes + escalation rate x manual minutes (2.6 hours) + golden capture; the estate is 1,600 jobs.
- Assumed, not measured: low, middle and high manual effort of 4, 8, 16 hours per job; escalation rates of 15%, 30%, 50%; 30 and 60 minutes of review per job; 7-hour days, 87 working days in 4 months and 130 in 6; EUR 600 a person-day.
- In this run 0% of jobs escalated, and all recorded gate decisions were reviewed and accepted by humans after the run; review minutes in the projection remain labelled assumptions.
- Gate load for the estate: 8,000 decisions with every gate for every job; 1,600 if only the 30% of jobs with warnings get per-job review (in this run 100% had warnings, since every development job carries a planted bug).
- Machine time runs in parallel and needs no people; it is reported separately.
- Claude at API prices for the whole estate: about $1,608 (measured per job here, not billed on a subscription).
- Manual baseline: 158.5 minutes per job, recorded in the completed manual timesheet at baseline/timesheet.csv. The projection uses this recorded effort.
- On their first run, 1 of the 2 held-out jobs escalated to a person (stopped by a failing test, not shipped): a sample too small to replace the assumed rate.

## Bias: S04's legacy risk tiers

S04 loads its risk score for age and county. Share of risk scores rated HIGH (one row per customer and line of business), from the golden output:

| age band | risk scores | rated HIGH (%) |
|---|---|---|
| under 25 | 168 | 14.3 |
| 25-34 | 408 | 6.6 |
| 35-44 | 412 | 4.4 |
| 45-59 | 584 | 5.1 |
| 60+ | 1057 | 5.6 |

- Ages 25-59 together: 5.3% of 1404 risk scores.
- By county (20 counties with at least 40 risk scores, spellings normalised): from 1.3% (Clare) to 9.7% (Laois).
- LANSH reproduces the score; whether a loading is justified is a business and legal decision, taken at the design gate.
