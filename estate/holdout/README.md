# Sealed held-out jobs (plan §7.4, step 1.5)

`holdout.tar.gz` holds two legacy T-SQL jobs, **X1** and **X2**, written by an isolated agent
that never saw the factory code, prompts, trap cards or planted-bug list. The archive is
**sealed**: nobody opens it until the factory freeze (plan step 3.11). The jobs then run once,
and those first-run results are reported as they come out.

**Factory code must never read this folder** (AGENTS.md; enforced by
`tests/test_holdout_seal.py`).

## What's sealed

| File in the archive | What |
|---|---|
| `X1_usp_broker_production.sql` | Broker production report (166 lines) |
| `X2_usp_large_loss_watchlist.sql` | Large-loss watchlist (147 lines) |
| `LABELS.md` | The author's answer key: one planted bug per job, and the SQL Server behaviours each job relies on, with line numbers |
| `checks.sql` | One check per bug proving it changes the result |
| `jobs.yaml` | Inventory entries for X1 and X2 (`lansh.contracts.JobSpec`, `holdout: true`) |

`SEAL.json` records the archive's SHA-256 and the time it was sealed. The archive is
byte-reproducible (sorted entries, zero timestamps and owners), so the hash identifies the content.

```bash
uv run python -c "from lansh.estate.holdout import verify_seal; print(verify_seal())"   # True
```

## How the author was isolated

- A separate Claude Code session, `claude -p` with **`--setting-sources ""`**: no project
  `CLAUDE.md`, no user settings, memory or plugins. It ran with `--strict-mcp-config`,
  `--no-session-persistence`, `--model opus` and `--effort high`.
- It worked in an empty folder outside the repo, holding only `BRIEFS.md`, the source schema,
  the legacy style guide (`STYLE.md`, now the "Legacy coding style" section of
  `estate/README.md`) and two helper scripts for SQL.
- **`--permission-mode dontAsk`**: file tools only, and Bash only for the two helpers. Anything
  else was refused, and the session record shows one refused command.
- It tested against `HoldoutScratch`, its own copy of the source tables. That database was
  dropped after sealing, and the working folder was deleted.
- The exact prompt and the business briefs are at the end of this file, word for word.
  Neither describes any bug.

The session took 518 seconds and 62 turns on Claude Opus 5.5 (Claude Code also used Haiku for
housekeeping). Its API-equivalent cost was about $2.51, not billed (our subscription).

## Verified before sealing (without reading the code)

A script that prints only verdicts checked that:
- `jobs.yaml` validates against the contract;
- both jobs read only source tables;
- both scripts deploy from scratch;
- each procedure returns identical content hashes on re-run: X1 127 rows, X2 254 rows;
- each bug check is positive: X1 123 rows affected, X2 122.

**Re-verified on 11 Nov**, after the estate was recalibrated to a realistic claim frequency, by the
same verdict-only procedure (the archive read in memory, its SQL sent straight to a scratch
database, only counts printed). The seal still verifies; both jobs deploy and re-run with identical
hashes (X1 126 rows, X2 79 rows); both bug checks stay positive (X1 120 rows affected, X2 43).

## Unsealing (step 3.11 only)

```python
from lansh.estate.holdout import unseal
unseal(Path("estate/holdout"))   # verifies the seal first
```

Then add the `jobs.yaml` entries to the inventory, capture their golden outputs on a fresh
`SynthInsureDW` (`lansh estate golden --job X1 --job X2`), and run them through the frozen
factory once. Report the results as they come out.

## The author's prompt (word for word)

````text
You are a senior SQL Server developer at SynthInsure, a fictional Irish insurer, writing two legacy reporting jobs for its data warehouse. Work ONLY inside the current folder: do not read, list or search anything outside it. Your Bash access is limited to the two helper commands below; use the Read, Write, Edit, Glob and Grep tools for files in this folder.

Read first: BRIEFS.md (what to build), SCHEMA.md and schema_stg.sql (the source tables, schema stg), schema_base.sql (schemas, and etl.usp_log_step for logging), STYLE.md (how SynthInsure code looks; follow it closely).

A copy of the warehouse is available: database HoldoutScratch on the local SQL Server 2022, with the stg tables loaded (the reporting as-of date is 2025-12-31). Helpers (run them exactly like this):
  uv run --no-project --with pymssql==2.4.6 python query.py "SELECT TOP 20 * FROM stg.claims"
  uv run --no-project --with pymssql==2.4.6 python sqlrun.py X1_usp_broker_production.sql
  uv run --no-project --with pymssql==2.4.6 python sqlrun.py --exec rpt.usp_broker_production AsOfDate=2025-12-31
Explore the data before writing: look for case and trailing-space variants, NULLs, gaps and duplicates.

Deliverables, all in this folder:
1. X1_usp_broker_production.sql and X2_usp_large_loss_watchlist.sql: one deployment script per job (header with an invented change log; the output table DDL guarded by IF OBJECT_ID(...) IS NULL; CREATE OR ALTER PROCEDURE rpt.<name> @AsOfDate DATE), 40 to 200 lines each, in SynthInsure legacy style, with batches separated by GO lines.
2. In EACH job, plant exactly ONE realistic bug of your own choosing: the kind of honest mistake a competent but busy developer makes, which visibly changes the output on this data. Don't mark it in the code in any way (no comment hinting at it).
3. LABELS.md: for each job, (a) the bug: what the code does, what was intended, the exact line numbers, and how many output rows it affects on this data; (b) every behaviour of SQL Server your code relies on that another database engine might handle differently (for example how text comparison treats case or trailing spaces, integer division, date functions, string functions, NULL handling, CROSS APPLY or TOP), each with line numbers.
4. checks.sql: for each bug, one query batch (batches separated by GO; each batch starts with a comment line `-- check: X1_bug` or `-- check: X2_bug`) that returns exactly one row with columns check_id and affected, proving the bug changes the result: affected > 0.
5. jobs.yaml: inventory entries for both jobs in exactly this format:
jobs:
  - job_id: X1
    name: usp_broker_production
    language: tsql
    path: estate/holdout/X1_usp_broker_production.sql
    entrypoint: rpt.usp_broker_production
    description: <one line>
    invocations:
      - params: {AsOfDate: '2025-12-31'}
    inputs: [stg.<table>, ...]
    outputs:
      - table: rpt.broker_production
    tier: 1
    holdout: true
  - job_id: X2
    (same shape; path estate/holdout/X2_usp_large_loss_watchlist.sql, entrypoint rpt.usp_large_loss_watchlist, output rpt.large_loss_watchlist)
   `inputs` must list every table the job reads.
6. Both jobs must deploy and run cleanly against HoldoutScratch, finish in under a minute each, and be deterministic: run each twice and confirm identical output (compare COUNT(*) and CHECKSUM_AGG(BINARY_CHECKSUM(*)) of the output table). Every ranking or TOP ends with a unique tiebreaker. Use @AsOfDate, never GETDATE().
No dynamic SQL, no linked servers, nothing outside the database. Leave no other files in the folder.
When finished, reply with the structured result only. It must not describe the bugs.
````

## The business briefs (`BRIEFS.md`, word for word)

````markdown
# Business briefs for two reporting jobs

Write each as a T-SQL stored procedure in schema `rpt`, called as
`EXEC rpt.<procedure> @AsOfDate = '2025-12-31'`, which rebuilds its output table in `rpt`.

## X1: broker production report (`rpt.usp_broker_production` -> `rpt.broker_production`)

For each broker and line of business, as at `@AsOfDate`: the number of policies in force on
that date, the gross written premium in EUR booked in the as-of calendar year (premium
transactions converted at the latest exchange rate published on or before the booking date;
EUR needs no conversion), the number of claims notified in that year and the claims paid in
that year. Business with no broker is reported under broker code `DIRECT`. Brokers whose
paid-to-written ratio for the year exceeds 0.75 are flagged for review. Inactive brokers are
still reported when they have business.

## X2: large-loss watchlist (`rpt.usp_large_loss_watchlist` -> `rpt.large_loss_watchlist`)

For the claims committee: every claim whose incurred amount (paid to date plus the latest
outstanding reserve of each reserve type, both as at `@AsOfDate`) is at least EUR 25,000,
with its incurred amount 90 days before `@AsOfDate`, the movement since then, the number of
reserve changes in the last 90 days, the days since the last payment or reserve change, and a
watch category: NEW (not a large loss 90 days ago), DETERIORATING (incurred up by more than
10%), IMPROVING (down by more than 10%) or STABLE. Closed claims are included only if they
closed in the last 90 days.
````
