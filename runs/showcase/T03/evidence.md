# Evidence report: T03

Generated 2026-11-12 04:08 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T03_usp_build_fact_premium_earned.sql` (SHA-256 `5fbf16f70c9c202e…`)
- Migrated module: `runs/showcase/T03/jobs/t03.py` (SHA-256 `ba9048a1fa89b01c…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 20 (TSQL-01, TSQL-02, TSQL-03, TSQL-07, TSQL-08, TSQL-09, TSQL-13, TSQL-18)
- Suspected defects: 6; tests: 6/6 passed; heal attempts: 0
- Claude: 6 calls (0 live), 53,182 input and 52,096 output tokens, $1.40 API-equivalent (not billed), 426 s of model time

## Gate decisions

**Human review: completed and accepted after the run.** The team confirmed review of all recorded gate decisions on 2026-11-16. [Review confirmation](../human_review.json) is pinned to the original gate log. Original agent timings are separate from the later human review.

| Gate | Human acceptance | Reviewer | Review scope | Human reason |
|---|---|---|---|---|
| H1 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Scope, source code, lineage and trap findings | Team confirmed acceptance; original individual rationale not recorded |
| H2 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Contract, comparison policies, defect decisions and protected-column flows | Team confirmed acceptance; original individual rationale not recorded |
| H3 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Generated code, literal guardrails and trap-test results | Team confirmed acceptance; original individual rationale not recorded |
| H4 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Record-level reconciliation, differences, totals and reported outcome | Team confirmed acceptance; original individual rationale not recorded |
| H5 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Wave cut-over, Delta reconciliation, upstream dependencies and SLA evidence | Team confirmed acceptance; original individual rationale not recorded |
| H3 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Generated code, literal guardrails and trap-test results | Team confirmed acceptance; original individual rationale not recorded |
| H4 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Record-level reconciliation, differences, totals and reported outcome | Team confirmed acceptance; original individual rationale not recorded |
| H5 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Wave cut-over, Delta reconciliation, upstream dependencies and SLA evidence | Team confirmed acceptance; original individual rationale not recorded |

### Original automated run recordings

| Gate | Outcome | Original recorder | Recorded interval | Recording flags | Original recording note |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: Things to check when matching the PySpark output against the legacy output: 1) earned_pct = earned_days*100/term_days uses integer division |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T03-D1 suspected defect: Earned premium pro-rated over a fixed 365 days instead of the policy term (21145 rows); T03-D2 suspected defect: Earned percentage truncated by integer division (24201 rows); T03-D3 suspected de |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1) The CROSS APPLY window is partitioned by stg.premium_transactions._row_seq, one partition per outer source row. txn_id is not deduplicated, |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: I haven't run this module. Points to check in review:  1) first_due_date: the target month comes from add_months(last_day(d), 1). The day is t |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### dw.fact_premium_earned: MATCH

MATCH: all 67,879 rows agree record for record, compared on the keys ['txn_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 67,879 | 67,879 | ok |
| Total of `txn_id` | 477457288333 | 477457288333 | ok |
| Total of `policy_id` | 36027338916 | 36027338916 | ok |
| Total of `policy_sk` | 2451710359 | 2451710359 | ok |
| Total of `amount` | 23878512.88 | 23878512.88 | ok |
| Total of `fx_rate` | 68243.18983386 | 68243.18983386 | ok |
| Total of `written_eur` | 24033402.72 | 24033402.72 | ok |
| Total of `term_days` | 22352049 | 22352049 | ok |
| Total of `earned_days` | 17376000 | 17376000 | ok |
| Total of `earned_pct` | 5370266 | 5370266 | ok |
| Total of `earned_eur` | 18768844.41 | 18768844.41 | ok |
| Total of `unearned_eur` | 5264558.31 | 5264558.31 | ok |
| Total of `daily_rate_eur` | 79181.1928 | 79181.1928 | ok |
| Total of `monthly_instalment_eur` | 2121880.48 | 2121880.48 | ok |
| Records matched | | | 67,879 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8877a71b1cda` | `8877a71b1cda` | identical |

Keys: ['txn_id'].

## Operate (Delta lakehouse, reconciled again)

### dw.fact_premium_earned: MATCH

MATCH: all 67,879 rows agree record for record, compared on the keys ['txn_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 67,879 | 67,879 | ok |
| Total of `txn_id` | 477457288333 | 477457288333 | ok |
| Total of `policy_id` | 36027338916 | 36027338916 | ok |
| Total of `policy_sk` | 2451710359 | 2451710359 | ok |
| Total of `amount` | 23878512.88 | 23878512.88 | ok |
| Total of `fx_rate` | 68243.18983386 | 68243.18983386 | ok |
| Total of `written_eur` | 24033402.72 | 24033402.72 | ok |
| Total of `term_days` | 22352049 | 22352049 | ok |
| Total of `earned_days` | 17376000 | 17376000 | ok |
| Total of `earned_pct` | 5370266 | 5370266 | ok |
| Total of `earned_eur` | 18768844.41 | 18768844.41 | ok |
| Total of `unearned_eur` | 5264558.31 | 5264558.31 | ok |
| Total of `daily_rate_eur` | 79181.1928 | 79181.1928 | ok |
| Total of `monthly_instalment_eur` | 2121880.48 | 2121880.48 | ok |
| Records matched | | | 67,879 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8877a71b1cda` | `8877a71b1cda` | identical |

Keys: ['txn_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T03-D1 | Earned premium pro-rated over a fixed 365 days instead of the policy term | 93-126 | 21145 | 307279.59 | reproduce (agent:lansh-dev) |
| T03-D2 | Earned percentage truncated by integer division | 36-124 | 24201 | 12045.22 | reproduce (agent:lansh-dev) |
| T03-D3 | First instalment due date: month added to month-end gives an inconsistent date | 129-129 | 67879 |  | reproduce (agent:lansh-dev) |
| T03-D4 | Non-EUR transactions without an FX rate on/before booking date silently dropped | 69-82 | 7 |  | reproduce (agent:lansh-dev) |
| T03-D5 | Transactions dropped when the policy has no current dim_policy row | 132-134 | 0 |  | reproduce (agent:lansh-dev) |
| T03-D6 | Daily rate truncated instead of rounded | 127-127 | 32841 | 3.28 | reproduce (agent:lansh-dev) |

## Contract

`silver.fact_premium_earned` (silver), from `dw.fact_premium_earned`. Grain: One row per premium transaction booked on or before the reporting date whose policy has a current row in dim_policy. Each row holds the written and earned premium in EUR as at @AsOfDate.
Key: ['txn_id']; partitions: ['lob_code', 'currency'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 62-67 | llm | 0.95 | The #txn temp table is built with SELECT INTO and then added to by an INSERT; in Spark it becomes a DataFrame made by unioning the EUR and non-EUR branches. |
| TSQL-01 | 69-69 | llm | 0.80 | currency is CHAR(3) text. Under a CI collation, 'eur' or 'Eur' also matches 'EUR', but Spark's binary compare would drop those rows from the EUR branch. |
| TSQL-02 | 69-69 | llm | 0.60 | currency is CHAR(3), and SQL Server ignores trailing spaces in the comparison. A value like 'EU ' or a padded source value would compare differently in Spark. |
| TSQL-08 | 77-81 | llm | 0.40 | TOP 1 is ordered by rate_date DESC, _row_seq DESC. If _row_seq ties within a date, the row chosen is arbitrary, so the window ordering must match. |
| TSQL-09 | 77-81 | llm | 0.95 | CROSS APPLY TOP 1 picks the latest rate per transaction and drops transactions that have no rate. In Spark this needs a join with a row_number window (inner semantics). |
| TSQL-01 | 79-79 | llm | 0.75 | The rate lookup joins on the CHAR(3) currency columns. The CI collation matches case variants such as 'usd' to 'USD', and Spark's join would miss them. |
| TSQL-02 | 79-79 | llm | 0.60 | The CHAR(3) join on currency ignores trailing spaces in the legacy engine. Spark needs trimmed keys to match the same way. |
| TSQL-01 | 82-82 | llm | 0.80 | The <> 'EUR' test is case-insensitive in the legacy engine. In Spark, lower-case 'eur' rows would go to the FX branch and also be missing from the EUR branch. |
| TSQL-02 | 82-82 | llm | 0.60 | currency is CHAR(3) and the legacy comparison ignores trailing spaces. Spark compares the exact string. |
| TSQL-13 | 89-99 | llm | 0.95 | The #earn temp table holds the intermediate term and earned-day columns; in Spark it becomes a DataFrame or temp view. |
| TSQL-07 | 92-92 | llm | 0.50 | DECIMAL(12,2)*DECIMAL(18,8) is rounded half away from zero to 2 places and cast to DECIMAL(14,2). Spark must keep decimal types and HALF_UP rounding, not doubles. |
| TSQL-03 | 124-124 | llm | 0.95 | earned_days*100/term_days is INT/INT, so the percentage is truncated to a whole number before it is stored in DECIMAL(5,2) (e.g. 33.00, not 33.33). Spark's / would return a fraction. |
| TSQL-07 | 125-125 | llm | 0.60 | Decimal * int / 365 follows SQL Server's precision and scale rules for division, then ROUND to 2 places half away from zero. Spark's decimal division and rounding must reproduce this. |
| TSQL-07 | 126-126 | llm | 0.60 | Unearned is written_eur minus the separately rounded earned amount, so the decimal scale and rounding of the subtrahend must match the legacy result. |
| TSQL-07 | 127-127 | llm | 0.85 | ROUND(x, 4, 1) truncates rather than rounds. Spark needs an explicit truncation of the decimal quotient (e.g. floor-based for positive values, toward zero for negatives), not F.round. |
| TSQL-03 | 128-128 | llm | 0.95 | term_days/30 is integer division, so the instalment count is truncated: 365 days gives 12, and under 30 days gives 0, which falls back to 1. |
| TSQL-07 | 128-128 | llm | 0.60 | Decimal divided by an int count, then ROUND to 2 places half away from zero into DECIMAL(14,2). The decimal types must be kept. |
| TSQL-18 | 129-129 | llm | 0.90 | DATEADD(MONTH,1,EOMONTH(d)) clamps without snapping to month-end: an end of February gives the 28th/29th of March. Spark's add_months on a last-day input returns the 31st, so the result would differ. |
| TSQL-01 | 134-134 | llm | 0.70 | is_current is CHAR(1) text. Under the CI collation a lower-case 'y' also matches, and Spark's exact compare would drop those policies from the inner join. |
| TSQL-02 | 134-134 | llm | 0.30 | is_current is CHAR(1). The trailing-space-insensitive compare is a latent risk only if values are stored with spaces. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| txn_id | stg.premium_transactions.txn_id | - |
| policy_id | stg.premium_transactions.policy_id | - |
| policy_sk | dw.dim_policy.policy_sk | - |
| lob_code | dw.dim_policy.lob_code | - |
| txn_type | stg.premium_transactions.txn_type | - |
| txn_date | stg.premium_transactions.txn_date | - |
| effective_from | stg.premium_transactions.effective_from | - |
| effective_to | stg.premium_transactions.effective_to | - |
| currency | stg.premium_transactions.currency | - |
| amount | stg.premium_transactions.amount | - |
| fx_rate | constant, stg.fx_rates.rate_to_eur | - |
| written_eur | stg.fx_rates.rate_to_eur, stg.premium_transactions.amount | - |
| term_days | stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| earned_days | parameter @AsOfDate, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| earned_pct | constant, parameter @AsOfDate, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| earned_eur | constant, parameter @AsOfDate, stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| unearned_eur | constant, parameter @AsOfDate, stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| daily_rate_eur | stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| monthly_instalment_eur | stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.effective_from, stg.premium_transactions.effective_to | - |
| first_due_date | stg.premium_transactions.effective_from | - |
| as_of_date | parameter @AsOfDate | - |

Rows are decided by: dw.dim_policy.is_current, dw.dim_policy.policy_id, stg.fx_rates.currency, stg.fx_rates.rate_date, stg.premium_transactions.currency, stg.premium_transactions.policy_id, stg.premium_transactions.txn_date.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T03-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Currency case variants: 'eur' and 'Eur' rows belong to the EUR branch (lines 69/82). Under the CI collation they get rate 1, and they must not go to the FX branch. A naive binary compare would drop th |
| T03-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Trailing spaces in CHAR(3) currency keys (lines 69/79/82). Txn currency 'CH' matches fx 'CH ', and txn 'JP ' matches fx 'JP'. The legacy engine pads both and ignores trailing spaces, so the rows find  |
| T03-TSQL-08-3 | TSQL-08 | legacy_engine | pass | FX TOP 1 tie-break (lines 77-81). USD has two rates on 2025-06-01 (0.92 at seq 2, a revision 0.93 at seq 4). GBP has two rates on 2025-06-01 (1.18 at seq 5, 1.17 at seq 6). The legacy engine picks the |
| T03-TSQL-07-4 | TSQL-07 | legacy_engine | pass | Decimal rounding, lines 92 and 125-128. Several amount*rate products land exactly on half a cent: 10.01*0.5=5.005, 2.35*1.5=3.525, -10.01*0.5=-5.005. Rounding half away from zero is required. Doubles  |
| T03-TSQL-03-5 | TSQL-03 | legacy_engine | pass | Integer division, lines 124 and 128. A 3-day term with 1 earned day gives an earned_pct of 1*100/3, truncated to 33 (not 33.33). A 90-day term with 31 days earned gives 34, not 34.44. A 151-day term w |
| T03-TSQL-18-6 | TSQL-18 | legacy_engine | pass | first_due_date = DATEADD(MONTH,1,EOMONTH(effective_from)), line 129. These effective_from dates have month-ends shorter than the following month: Feb 2025 (to Mar 28), Feb 2024 leap (to Mar 29), Apr 3 |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 674 | 9 s | $0.048 |
| defect_reviewer | 1 | 0 | 7,072 | 65 s | $0.181 |
| lineage | 1 | 0 | 7,541 | 54 s | $0.191 |
| test_author | 1 | 0 | 19,226 | 142 s | $0.438 |
| translator | 1 | 0 | 14,027 | 123 s | $0.388 |
| trap_scan | 1 | 0 | 3,556 | 34 s | $0.150 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job       dw.usp_build_fact_premium_earned
  Purpose   Premium fact for finance: one row per premium transaction, converted
            to EUR at the rate published on or before the booking date, with
            the premium earned as at the reporting date.
  Author    MOD
  Run by    FIN_MONTH_END, after dw.usp_load_dim_policy
  Output    dw.fact_premium_earned (full refresh)

  Change log
    2016-01-11  MOD  Initial version (CR-0904)
    2016-07-04  MOD  Sterling and dollar business converted to EUR (CR-0977)
    2018-03-19  PK   Policy surrogate key and line of business from dim_policy (CR-1290)
    2019-09-30  PK   Daily rate and monthly instalment for the cash-flow model (CR-1510)
    2021-02-15  MOD  First instalment due date for the direct debit file (CR-1618)
    2023-05-08  JMcK Earned percentage for the finance dashboard (INC-2301)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.fact_premium_earned', N'U') IS NULL
CREATE TABLE dw.fact_premium_earned (
    txn_id                  INT            NOT NULL,
    policy_id               INT            NOT NULL,
    policy_sk               INT            NOT NULL,
    lob_code                VARCHAR(5)     NOT NULL,
    txn_type                VARCHAR(4)     NOT NULL,
    txn_date                DATE           NOT NULL,
    effective_from          DATE           NOT NULL,
    effective_to            DATE           NOT NULL,
    currency                CHAR(3)        NOT NULL,
    amount                  DECIMAL(12,2)  NOT NULL,
    fx_rate                 DECIMAL(18,8)  NOT NULL,
    written_eur             DECIMAL(14,2)  NOT NULL,
    term_days               INT            NOT NULL,
    earned_days             INT            NOT NULL,
    earned_pct              DECIMAL(5,2)   NOT NULL,
    earned_eur              DECIMAL(14,2)  NOT NULL,
    unearned_eur            DECIMAL(14,2)  NOT NULL,
    daily_rate_eur          DECIMAL(12,4)  NOT NULL,
    monthly_instalment_eur  DECIMAL(14,2)  NOT NULL,
    first_due_date          DATE           NOT NULL,
    as_of_date              DATE           NOT NULL,
    CONSTRAINT pk_dw_fact_premium_earned PRIMARY KEY (txn_id)
);
GO
CREATE OR ALTER PROCEDURE dw.usp_build_fact_premium_earned
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'dw.usp_build_fact_premium_earned',
            @rows      INT,
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Transactions with their EUR rate: EUR as is, other currencies at the
           latest rate on or before the booking date (later row wins on revisions) */
        IF OBJECT_ID('tempdb..#txn') IS NOT NULL DROP TABLE #txn;

        SELECT  t.txn_id, t.policy_id, UPPER(RTRIM(t.txn_type)) AS txn_type, t.txn_date,
                t.effective_from, t.effective_to, t.currency, t.amount,
                CAST(1 AS DECIMAL(18,8)) AS fx_rate
        INTO    #txn
        FROM    stg.premium_transactions t WITH (NOLOCK)
        WHERE   t.currency = 'EUR'
          AND   t.txn_date <= @AsOfDate;

        INSERT INTO #txn (txn_id, policy_id, txn_type, txn_date, effective_from, effective_to,
                          currency, amount, fx_rate)
        SELECT  t.txn_id, t.policy_id, UPPER(RTRIM(t.txn_type)), t.txn_date,
                t.effective_from, t.effective_to, t.currency, t.amount, fx.rate_to_eur
        FROM    stg.premium_transactions t WITH (NOLOCK)
        CROSS APPLY (SELECT TOP 1 r.rate_to_eur
                     FROM   stg.fx_rates r WITH (NOLOCK)
                     WHERE  r.currency = t.currency
                       AND  r.rate_date <= t.txn_date
                     ORDER BY r.rate_date DESC, r._row_seq DESC) fx
        WHERE   t.currency <> 'EUR'
          AND   t.txn_date <= @AsOfDate;

        SELECT @rows = COUNT(*) FROM #txn;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'transactions', @status = 'INFO', @rows_affected = @rows;

        /* Days of cover and days earned by the reporting date */
        IF OBJECT_ID('tempdb..#earn') IS NOT NULL DROP TABLE #earn;

        SELECT  x.*,
                CAST(ROUND(x.amount * x.fx_rate, 2) AS DECIMAL(14,2)) AS written_eur,
                DATEDIFF(DAY, x.effective_from, x.effective_to) + 1  AS term_days,
                CASE WHEN @AsOfDate < x.effective_from THEN 0
                     WHEN @AsOfDate >= x.effective_to  THEN DATEDIFF(DAY, x.effective_from, x.effective_to) + 1
                     ELSE DATEDIFF(DAY, x.effective_from, @AsOfDate) + 1
                END AS earned_days
        INTO    #earn
        FROM    #txn x;

        BEGIN TRANSACTION;

        TRUNCATE TABLE dw.fact_premium_earned;

        INSERT INTO dw.fact_premium_earned
               (txn_id, policy_id, policy_sk, lob_code, txn_type, txn_date, effective_from,
                effective_to, currency, amount, fx_rate, written_eur, term_days, earned_days,
                earned_pct, earned_eur, unearned_eur, daily_rate_eur, monthly_instalment_eur,
                first_due_date, as_of_date)
        SELECT  e.txn_id,
                e.policy_id,
                p.policy_sk,
                p.lob_code,
                e.txn_type,
                e.txn_date,
                e.effective_from,
                e.effective_to,
                e.currency,
                e.amount,
                e.fx_rate,
                e.written_eur,
                e.term_days,
                e.earned_days,
                e.earned_days * 100 / e.term_days,
                ROUND(e.written_eur * e.earned_days / 365, 2),
                e.written_eur - ROUND(e.written_eur * e.earned_days / 365, 2),
                ROUND(e.written_eur / e.term_days, 4, 1),
                ROUND(e.written_eur / ISNULL(NULLIF(e.term_days / 30, 0), 1), 2),
                DATEADD(MONTH, 1, EOMONTH(e.effective_from)),
                @AsOfDate
        FROM    #earn e
        JOIN    dw.dim_policy p WITH (NOLOCK)
                ON p.policy_id = e.policy_id
               AND p.is_current = 'Y';

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'dw.fact_premium_earned', @status = 'INFO', @rows_affected = @rows;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;

        SELECT  @err_msg = ERROR_MESSAGE(),
                @err_no  = ERROR_NUMBER();

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'FAILED',
             @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH
END;
GO
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""T03 usp_build_fact_premium_earned: migrated from estate/tsql/T03_usp_build_fact_premium_earned.sql.

Legacy SHA-256: 5fbf16f70c9c202ea4f177ec504f51992cf11022b0d992bc484b0cfa10e93670
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-03, TSQL-07, TSQL-08, TSQL-09, TSQL-13, TSQL-18
Bugs reproduced on purpose (# LANSH-DEFECT): T03-D1 fixed 365-day earning, T03-D2 truncated earned_pct, T03-D3 month-end first due date, T03-D4 non-EUR rows without FX rate dropped, T03-D5 rows without current policy dropped, T03-D6 daily rate truncated
"""
from pyspark.sql import SparkSession, DataFrame, Window
import pyspark.sql.functions as F


def _trunc(c, scale):
    # T-SQL truncation toward zero at `scale` places (decimal quotient / ROUND(x, n, 1))
    return F.when(c >= 0, F.floor(c, scale)).otherwise(F.ceil(c, scale))


def _div_trunc(num, den, scale):
    # Divide at a higher scale (decimal(38,18) in Spark), then truncate toward zero
    # at the T-SQL result scale, as SQL Server does for a DECIMAL quotient.
    q = num.cast("decimal(30,10)") / den.cast("decimal(10,0)")
    return _trunc(q, scale)


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(params["AsOfDate"]).cast("date")

    t = inputs["stg.premium_transactions"]
    r = inputs["stg.fx_rates"]
    p = inputs["dw.dim_policy"]

    # TSQL-01/02: CI collation, trailing spaces ignored
    cur_key = F.upper(F.rtrim(F.col("currency")))

    base = t.where(F.col("txn_date") <= as_of)

    # #txn, EUR branch (SELECT INTO) - TSQL-13
    eur = base.where(cur_key == "EUR").select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.upper(F.rtrim(F.col("txn_type"))).alias("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.col("currency"),
        F.col("amount"),
        F.lit(1).cast("decimal(18,8)").alias("fx_rate"),
    )

    # #txn, non-EUR branch (INSERT) with CROSS APPLY TOP 1 - TSQL-08/09
    non_eur = base.where(cur_key != "EUR").withColumn("_t_cur_key", cur_key)  # LANSH-DEFECT: T03-D4 NULL currency fails both = 'EUR' and <> 'EUR' and is dropped
    rates = r.select(
        F.upper(F.rtrim(F.col("currency"))).alias("_r_cur_key"),
        F.col("rate_date").alias("_r_rate_date"),
        F.col("rate_to_eur").alias("_r_rate"),
        F.col("_row_seq").alias("_r_seq"),
    )
    joined = non_eur.join(  # LANSH-DEFECT: T03-D4 inner join (CROSS APPLY) silently drops non-EUR transactions without a rate on/before txn_date
        rates,
        (F.col("_t_cur_key") == F.col("_r_cur_key")) & (F.col("_r_rate_date") <= F.col("txn_date")),
        "inner",
    )
    w = Window.partitionBy(F.col("_row_seq")).orderBy(F.col("_r_rate_date").desc(), F.col("_r_seq").desc())
    fx = joined.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.upper(F.rtrim(F.col("txn_type"))).alias("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.col("currency"),
        F.col("amount"),
        F.col("_r_rate").cast("decimal(18,8)").alias("fx_rate"),
    )

    txn = eur.unionByName(fx)

    # #earn - TSQL-13
    term_days = F.datediff(F.col("effective_to"), F.col("effective_from")) + 1
    earn = txn.select(
        "*",
        # TSQL-07: decimal(12,2)*decimal(18,8) -> decimal(31,10), ROUND half away from zero, cast decimal(14,2)
        F.round(F.col("amount") * F.col("fx_rate"), 2).cast("decimal(14,2)").alias("written_eur"),
        term_days.alias("term_days"),
        F.when(as_of < F.col("effective_from"), F.lit(0))
        .when(as_of >= F.col("effective_to"), term_days)
        .otherwise(F.datediff(as_of, F.col("effective_from")) + 1)
        .alias("earned_days"),
    )

    pol = p.where(F.upper(F.rtrim(F.col("is_current"))) == "Y").select(  # TSQL-01/02 on is_current
        F.col("policy_id").alias("_p_policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
    )
    f = earn.join(pol, F.col("policy_id") == F.col("_p_policy_id"), "inner")  # LANSH-DEFECT: T03-D5 transactions without a current dim_policy row are dropped

    written = F.col("written_eur")

    # earned_eur: decimal(25,2) / 365 -> decimal(36,13) truncated, then ROUND 2 half away from zero
    earned_num = (written * F.col("earned_days")).cast("decimal(25,2)")
    earned_eur = F.round(_div_trunc(earned_num, F.lit(365), 13).cast("decimal(36,13)"), 2)  # LANSH-DEFECT: T03-D1 earned pro-rated over fixed 365 days, not term_days

    # daily_rate_eur: decimal(14,2)/int -> decimal(25,13) truncated, then ROUND(x,4,1) truncation
    daily_q = _div_trunc(written, F.col("term_days"), 13).cast("decimal(25,13)")
    daily_rate = _trunc(daily_q, 4)  # LANSH-DEFECT: T03-D6 ROUND(...,4,1) truncates instead of rounding

    # monthly_instalment_eur: ISNULL(NULLIF(term_days/30, 0), 1) with integer division
    n_inst = F.expr("term_days div 30")
    divisor = F.coalesce(F.when(n_inst != 0, n_inst), F.lit(1)).cast("int")
    monthly = F.round(_div_trunc(written, divisor, 13).cast("decimal(25,13)"), 2)

    # first_due_date: DATEADD(MONTH, 1, EOMONTH(effective_from)) - TSQL-18 (no snap to month-end)
    eom = F.last_day(F.col("effective_from"))
    tgt = F.add_months(eom, 1)
    first_due = F.make_date(  # LANSH-DEFECT: T03-D3 month added to a month-end keeps the day number (28 Feb -> 28 Mar)
        F.year(tgt),
        F.month(tgt),
        F.least(F.dayofmonth(eom), F.dayofmonth(F.last_day(tgt))),
    )

    out = f.select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
        F.col("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.rpad(F.col("currency"), 3, " ").alias("currency"),  # TSQL-02 CHAR(3) output
        F.col("amount"),
        F.col("fx_rate"),
        F.col("written_eur"),
        F.col("term_days"),
        F.col("earned_days"),
        F.expr("(earned_days * 100) div term_days").alias("earned_pct"),  # LANSH-DEFECT: T03-D2 INT/INT truncates the percentage
        earned_eur.alias("earned_eur"),  # LANSH-DEFECT: T03-D1 fixed 365-day denominator
        (written - earned_eur).alias("unearned_eur"),  # LANSH-DEFECT: T03-D1 unearned from 365-day earning, can go negative
        daily_rate.alias("daily_rate_eur"),  # LANSH-DEFECT: T03-D6 truncated daily rate
        monthly.alias("monthly_instalment_eur"),
        first_due.alias("first_due_date"),  # LANSH-DEFECT: T03-D3 inconsistent first due date
        as_of.alias("as_of_date"),
    )

    return {"dw.fact_premium_earned": out}
```
</details>

