# Evidence report: X1

Generated 2026-11-12 03:31 UTC. **Status: ESCALATED.**

- Legacy code: `estate/holdout/X1_usp_broker_production.sql` (SHA-256 `b683ce412ff6786c…`)
- Migrated module: `runs/showcase/held-out/X1/jobs/x1.py` (SHA-256 `04f89c76d2dd6b1a…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 22 (TSQL-01, TSQL-02, TSQL-07, TSQL-08, TSQL-09, TSQL-13)
- Suspected defects: 7; tests: 0/0 passed; heal attempts: 0
- Claude: 6 calls (6 live), 57,251 input and 75,437 output tokens, $1.92 API-equivalent (not billed), 593 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off); warnings read: lineage of rpt.broker_production.broker_code disagrees with sqlglot (agent only: ['stg.policy_snapshots.broker_code']; sqlglot only: ['keys.broker_code']); lineage of rpt.broker_production.gwp_eur disagrees with sqlglot |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: X1-D1 suspected defect: Claims paid limited to claims notified in the same year (87 rows); X1-D2 suspected defect: Broker dimension joined without deduplication (0 rows); X1-D3 suspected defect: Blank broker codes not m |

## Reconciliation (sandbox run, isolated inputs)

**Escalated** (guardrail): 1 of 13 trap tests fail

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| X1-D1 | Claims paid limited to claims notified in the same year | 93-112 | 87 | 1388119.21 | reproduce (agent:lansh-dev) |
| X1-D2 | Broker dimension joined without deduplication | 147-148 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X1-D3 | Blank broker codes not mapped to DIRECT | 52-52 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X1-D4 | Non-EUR premium silently dropped when no FX rate is found | 76-86 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X1-D5 | Recoveries added rather than netted off | 106-107 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X1-D6 | Duplicate claim rows multiply claims notified and claims paid | 94-110 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X1-D7 | Policies expiring on the as-of date counted as in force | 69-71 | 30 | 69.00 | reproduce (agent:lansh-dev) |

## Contract

`gold.broker_production` (gold), from `rpt.broker_production`. Grain: One row per broker (trimmed, upper-cased broker code, with DIRECT for policies that have no broker) and line of business that has any in-force policies, written premium, notified claims or paid claims in the year up to the as-of date.
Key: ['broker_code', 'lob_code']; partitions: ['review_flag'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 48-61 | llm | 0.90 | #pol temp table holding the latest policy snapshot; becomes a DataFrame. |
| TSQL-01 | 58-58 | llm | 0.75 | The products join compares the raw VARCHAR product_code values without any normalisation. Under the CI collation, case variants match; in Spark they would not, so policies would drop out of the inner  |
| TSQL-02 | 58-58 | llm | 0.70 | The product_code join ignores trailing spaces in SQL Server. Spark needs an rtrim on both sides or padded codes miss the inner join. |
| TSQL-13 | 66-72 | llm | 0.90 | #inforce temp table. |
| TSQL-13 | 75-89 | llm | 0.90 | #gwp temp table. |
| TSQL-01 | 76-76 | llm | 0.70 | t.currency is CHAR(3) text, so currency = 'EUR' also matches 'eur'/'Eur' under the CI collation. A binary comparison in Spark would route those rows to the fx rate instead. |
| TSQL-02 | 76-76 | llm | 0.40 | currency is CHAR(3) and the comparison ignores trailing spaces (e.g. 'EUR ' or a padded short code). Spark compares exactly. |
| TSQL-07 | 76-76 | llm | 0.45 | amount DECIMAL(12,2) * rate DECIMAL(18,8), summed. The result's precision and scale must match legacy before the final rounding to 2dp. |
| TSQL-09 | 80-86 | llm | 0.95 | OUTER APPLY TOP 1 picks the latest fx rate on or before txn_date and keeps transactions that have no rate. In Spark this must become a left join plus a row_number window. |
| TSQL-08 | 81-85 | llm | 0.40 | TOP 1 ordered by rate_date DESC, _row_seq DESC. The order is deterministic as long as _row_seq is unique per date, and the Spark window must use the same tie-break. |
| TSQL-01 | 83-83 | llm | 0.70 | The fx lookup matches f.currency = t.currency, two text columns from different sources, case-insensitively. In Spark, case variants would find no rate and the premium would come out NULL. |
| TSQL-02 | 83-83 | llm | 0.50 | The CHAR(3) currency match ignores trailing spaces in SQL Server. Spark matches exactly unless both sides are trimmed. |
| TSQL-13 | 94-99 | llm | 0.90 | #clm temp table. |
| TSQL-13 | 101-104 | llm | 0.90 | #notified temp table. |
| TSQL-13 | 107-113 | llm | 0.90 | #paid temp table. |
| TSQL-13 | 117-120 | llm | 0.90 | #keys temp table built by UNION, which removes duplicates; needs union plus distinct in Spark. |
| TSQL-13 | 123-129 | llm | 0.90 | #ratio temp table. |
| TSQL-07 | 124-124 | llm | 0.60 | DECIMAL(38,2)/DECIMAL(38,2) division is cut down to scale 6 in SQL Server and then rounded to DECIMAL(12,4), so the value is rounded twice. Spark's decimal division and cast must give the same ratio,  |
| TSQL-07 | 142-142 | llm | 0.50 | The high-scale gwp sum is cast to DECIMAL(14,2), rounding half away from zero. Spark must cast the decimal and must not round a double. |
| TSQL-07 | 144-144 | llm | 0.35 | Claims paid is cast to DECIMAL(14,2). Spark must keep decimal types (not double) so the result matches. |
| TSQL-01 | 148-148 | llm | 0.75 | stg.brokers.broker_code is not normalised, but k.broker_code is upper-cased. The CI join still matches lower- or mixed-case broker codes; a binary Spark join would lose broker_name and status. |
| TSQL-02 | 148-148 | llm | 0.80 | stg.brokers.broker_code is CHAR(6), so it is padded with spaces and may also carry stored trailing spaces. SQL Server's join ignores them, while Spark needs rtrim on b.broker_code to match the trimmed |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| as_of_date | parameter @AsOfDate | yes |
| broker_code | constant, stg.policy_snapshots.broker_code | no |
| broker_name | stg.brokers.broker_name | yes |
| broker_status | stg.brokers.status | yes |
| lob_code | stg.products.lob_code | no |
| policies_in_force | constant | yes |
| gwp_eur | constant, stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.currency | no |
| claims_notified | constant | yes |
| claims_paid_eur | constant, stg.claim_payments.amount | yes |
| paid_to_written | stg.claim_payments.amount, stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.currency | no |
| review_flag | constant, stg.claim_payments.amount, stg.fx_rates.rate_to_eur, stg.premium_transactions.amount, stg.premium_transactions.currency | no |

Rows are decided by: stg.brokers.broker_code, stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claims.claim_id, stg.claims.policy_id, stg.claims.reported_date, stg.fx_rates.currency, stg.fx_rates.rate_date, stg.policy_snapshots.cancellation_date, stg.policy_snapshots.expiry_date, stg.policy_snapshots.inception_date, stg.policy_snapshots.policy_id, stg.policy_snapshots.product_code, stg.policy_snapshots.snapshot_date, stg.premium_transactions.currency, stg.premium_transactions.policy_id, stg.premium_transactions.txn_date, stg.products.product_code.

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 1 | 600 | 6 s | $0.050 |
| defect_reviewer | 1 | 1 | 11,324 | 93 s | $0.275 |
| lineage | 1 | 1 | 6,376 | 48 s | $0.178 |
| test_author | 1 | 1 | 35,559 | 261 s | $0.773 |
| translator | 1 | 1 | 17,448 | 146 s | $0.470 |
| trap_scan | 1 | 1 | 4,130 | 39 s | $0.171 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : rpt.usp_broker_production
  Purpose  : Broker production report for distribution MI. One row per broker
             and line of business as at @AsOfDate: policies in force, gross
             written premium in EUR booked in the calendar year, claims notified
             and claims paid in the year, and a review flag for brokers whose
             paid-to-written ratio for the year is above 0.75.
  Author   : PdeB
  Change log
    2014-02-10  PdeB  Initial version (CR-0412)
    2015-09-03  PdeB  GBP/USD premium converted to EUR at the ECB rate (CR-0688)
    2017-11-20  SOK   Direct business reported under broker code DIRECT (CR-1047)
    2019-05-14  AMcG  Inactive brokers kept when they still have business (INC-2231)
    2021-03-08  SOK   Paid-to-written review flag for distribution (CR-1590)
    2022-06-27  AMcG  Broker codes trimmed and upper-cased (INC-3118)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.broker_production', N'U') IS NULL
CREATE TABLE rpt.broker_production (
    as_of_date         DATE           NOT NULL,
    broker_code        VARCHAR(10)    NOT NULL,
    broker_name        NVARCHAR(80)   NULL,
    broker_status      VARCHAR(10)    NULL,
    lob_code           VARCHAR(5)     NOT NULL,
    policies_in_force  INT            NOT NULL,
    gwp_eur            DECIMAL(14,2)  NOT NULL,
    claims_notified    INT            NOT NULL,
    claims_paid_eur    DECIMAL(14,2)  NOT NULL,
    paid_to_written    DECIMAL(12,4)  NULL,
    review_flag        CHAR(1)        NOT NULL
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_broker_production
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job       VARCHAR(128) = 'rpt.usp_broker_production';
    DECLARE @YearStart DATE         = DATEFROMPARTS(YEAR(@AsOfDate), 1, 1);
    DECLARE @rows      INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'start', @status = 'STARTED';

        -- policy attributes from the latest snapshot on or before the as-of date
        SELECT x.policy_id, x.broker_code, x.lob_code, x.inception_date, x.expiry_date, x.cancellation_date
        INTO #pol
        FROM (
            SELECT s.policy_id,
                   ISNULL(UPPER(LTRIM(RTRIM(s.broker_code))), 'DIRECT') AS broker_code,
                   UPPER(RTRIM(p.lob_code)) AS lob_code,
                   s.inception_date, s.expiry_date, s.cancellation_date,
                   ROW_NUMBER() OVER (PARTITION BY s.policy_id
                                      ORDER BY s.snapshot_date DESC, s._row_seq DESC) AS rn
            FROM stg.policy_snapshots s WITH (NOLOCK)
            INNER JOIN stg.products p WITH (NOLOCK) ON p.product_code = s.product_code
            WHERE s.snapshot_date <= @AsOfDate
        ) x
        WHERE x.rn = 1;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'policies', @status = 'INFO', @rows_affected = @rows;

        -- policies in force on the as-of date
        SELECT p.broker_code, p.lob_code, COUNT(*) AS policies_in_force
        INTO #inforce
        FROM #pol p
        WHERE p.inception_date <= @AsOfDate
          AND p.expiry_date >= @AsOfDate
          AND (p.cancellation_date IS NULL OR p.cancellation_date > @AsOfDate)
        GROUP BY p.broker_code, p.lob_code;

        -- premium booked in the year, at the latest rate published on or before the booking date
        SELECT p.broker_code, p.lob_code,
               SUM(t.amount * CASE WHEN t.currency = 'EUR' THEN 1 ELSE fx.rate_to_eur END) AS gwp_eur
        INTO #gwp
        FROM stg.premium_transactions t WITH (NOLOCK)
        INNER JOIN #pol p ON p.policy_id = t.policy_id
        OUTER APPLY (
            SELECT TOP 1 f.rate_to_eur
            FROM stg.fx_rates f WITH (NOLOCK)
            WHERE f.currency = t.currency
              AND f.rate_date <= t.txn_date
            ORDER BY f.rate_date DESC, f._row_seq DESC
        ) fx
        WHERE t.txn_date >= @YearStart
          AND t.txn_date <= @AsOfDate
        GROUP BY p.broker_code, p.lob_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'premium', @status = 'INFO', @rows_affected = @rows;

        -- claims notified in the year
        SELECT c.claim_id, p.broker_code, p.lob_code
        INTO #clm
        FROM stg.claims c WITH (NOLOCK)
        INNER JOIN #pol p ON p.policy_id = c.policy_id
        WHERE c.reported_date >= @YearStart
          AND c.reported_date <= @AsOfDate;

        SELECT c.broker_code, c.lob_code, COUNT(*) AS claims_notified
        INTO #notified
        FROM #clm c
        GROUP BY c.broker_code, c.lob_code;

        -- claims paid in the year, recoveries netted off, unkeyed amounts ignored
        SELECT c.broker_code, c.lob_code, SUM(ISNULL(cp.amount, 0)) AS claims_paid_eur
        INTO #paid
        FROM stg.claim_payments cp WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = cp.claim_id
        WHERE cp.payment_date >= @YearStart
          AND cp.payment_date <= @AsOfDate
        GROUP BY c.broker_code, c.lob_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'claims', @status = 'INFO', @rows_affected = @rows;

        SELECT broker_code, lob_code INTO #keys FROM #inforce
        UNION SELECT broker_code, lob_code FROM #gwp
        UNION SELECT broker_code, lob_code FROM #notified
        UNION SELECT broker_code, lob_code FROM #paid;

        -- paid-to-written ratio over all lines of the broker
        SELECT k.broker_code,
               CAST(SUM(ISNULL(pd.claims_paid_eur, 0)) / NULLIF(SUM(ISNULL(g.gwp_eur, 0)), 0) AS DECIMAL(12,4)) AS paid_to_written
        INTO #ratio
        FROM #keys k
        LEFT JOIN #gwp g   ON g.broker_code = k.broker_code AND g.lob_code = k.lob_code
        LEFT JOIN #paid pd ON pd.broker_code = k.broker_code AND pd.lob_code = k.lob_code
        GROUP BY k.broker_code;

        TRUNCATE TABLE rpt.broker_production;

        INSERT INTO rpt.broker_production
            (as_of_date, broker_code, broker_name, broker_status, lob_code, policies_in_force,
             gwp_eur, claims_notified, claims_paid_eur, paid_to_written, review_flag)
        SELECT @AsOfDate,
               k.broker_code,
               b.broker_name,
               UPPER(RTRIM(b.status)),
               k.lob_code,
               ISNULL(i.policies_in_force, 0),
               CAST(ISNULL(g.gwp_eur, 0) AS DECIMAL(14,2)),
               ISNULL(n.claims_notified, 0),
               CAST(ISNULL(pd.claims_paid_eur, 0) AS DECIMAL(14,2)),
               r.paid_to_written,
               CASE WHEN r.paid_to_written > 0.75 THEN 'Y' ELSE 'N' END
        FROM #keys k
        LEFT JOIN stg.brokers b WITH (NOLOCK) ON b.broker_code = k.broker_code
        LEFT JOIN #inforce i  ON i.broker_code = k.broker_code AND i.lob_code = k.lob_code
        LEFT JOIN #gwp g      ON g.broker_code = k.broker_code AND g.lob_code = k.lob_code
        LEFT JOIN #notified n ON n.broker_code = k.broker_code AND n.lob_code = k.lob_code
        LEFT JOIN #paid pd    ON pd.broker_code = k.broker_code AND pd.lob_code = k.lob_code
        LEFT JOIN #ratio r    ON r.broker_code = k.broker_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'load rpt.broker_production', @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(4000) = ERROR_MESSAGE(), @err INT = ERROR_NUMBER();
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'end', @status = 'FAILED',
             @message = @msg, @error_number = @err;
        THROW;
    END CATCH
END;
GO
```
</details>

