# Evidence report: X1

Generated 2026-11-12 04:09 UTC. **Status: MATCH.**

- Legacy code: `estate/holdout/X1_usp_broker_production.sql` (SHA-256 `b683ce412ff6786c…`)
- Migrated module: `runs/showcase/learning/X1/jobs/x1.py` (SHA-256 `6782bba02ba9fce3…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 22 (TSQL-01, TSQL-02, TSQL-07, TSQL-08, TSQL-09, TSQL-13)
- Suspected defects: 7; tests: 13/13 passed; heal attempts: 0
- Claude: 6 calls (0 live), 57,514 input and 79,320 output tokens, $1.99 API-equivalent (not billed), 633 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage of rpt.broker_production.broker_code disagrees with sqlglot (agent only: ['stg.policy_snapshots.broker_code']; sqlglot only: ['keys.broker_code']); lineage of rpt.broker_production.gwp_eur disagrees with sqlglot |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: X1-D1 suspected defect: Claims paid limited to claims notified in the same year (87 rows); X1-D2 suspected defect: Broker dimension joined without deduplication (0 rows); X1-D3 suspected defect: Blank broker codes not m |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1) #pol: if stg.products has more than one row matching a product_code (case or trailing-space variants, or duplicates), the legacy ROW_NUMBER |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.broker_production: MATCH

MATCH: all 126 rows agree record for record, compared on the keys ['broker_code', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 126 | 126 | ok |
| Total of `policies_in_force` | 21466 | 21466 | ok |
| Total of `gwp_eur` | 9177239.83 | 9177239.83 | ok |
| Total of `claims_notified` | 1042 | 1042 | ok |
| Total of `claims_paid_eur` | 4010931.67 | 4010931.67 | ok |
| Total of `paid_to_written` | 60.0255 | 60.0255 | ok |
| Records matched | | | 126 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8db4e15fa848` | `8db4e15fa848` | identical |

Keys: ['broker_code', 'lob_code'].

## Operate (Delta lakehouse, reconciled again)

### rpt.broker_production: MATCH

MATCH: all 126 rows agree record for record, compared on the keys ['broker_code', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 126 | 126 | ok |
| Total of `policies_in_force` | 21466 | 21466 | ok |
| Total of `gwp_eur` | 9177239.83 | 9177239.83 | ok |
| Total of `claims_notified` | 1042 | 1042 | ok |
| Total of `claims_paid_eur` | 4010931.67 | 4010931.67 | ok |
| Total of `paid_to_written` | 60.0255 | 60.0255 | ok |
| Records matched | | | 126 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8db4e15fa848` | `8db4e15fa848` | identical |

Keys: ['broker_code', 'lob_code'].

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

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| X1-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Line 58: the snapshots carry product_code in different cases ('mot01', 'Mot01', 'hom01', 'pRODUCT' style), but stg.products only has upper-case codes. Under the CI collation, SQL Server joins all of t |
| X1-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Line 58: some snapshot product_codes carry trailing spaces ('MOT01 ', 'MOT01  ', 'HOM01 '), and one products row is stored as 'PET01 ' while its snapshot says 'PET01'. SQL Server ignores the trailing  |
| X1-TSQL-01-3 | TSQL-01 | legacy_engine | pass | Line 76: premium transactions in currency 'eur', 'Eur' and 'eUR'. Under CI, they match currency = 'EUR' and are taken at a factor of 1. fx_rates also holds an EUR rate of 1.1. A binary CASE sends thes |
| X1-TSQL-02-4 | TSQL-02 | legacy_engine | pass | Line 76: currency is CHAR(3), so a full 'EUR' cannot also carry a trailing space within the column length. The case uses padded short codes instead: 'US ' and 'GB ' are compared against 'EUR' in the C |
| X1-TSQL-07-5 | TSQL-07 | legacy_engine | pass | Line 76: amount DECIMAL(12,2) times rate DECIMAL(18,8), summed per broker and LOB. For BRK001/MOTOR, 0.50*1.001 plus 0.50*1.009 sums to exactly 1.005. For BRK001/HOME, three 333.33*0.33333333 pieces s |
| X1-TSQL-08-6 | TSQL-08 | legacy_engine | pass | Lines 81-85: fx_rates has two GBP rows dated 2025-03-01 (1.15, then 1.17) and two USD rows dated 2025-03-01 (0.90, then 0.92). The TOP 1 picks the row with the higher _row_seq on the tied date. There  |
| X1-TSQL-01-7 | TSQL-01 | legacy_engine | pass | Line 83: the transaction currencies 'gbp' and 'Gbp' must match fx 'GBP', and transaction 'USD' must match fx rows stored as 'Usd' and 'usd'. Under CI, SQL Server finds the latest rate for each. A bina |
| X1-TSQL-02-8 | TSQL-02 | legacy_engine | pass | Line 83: CHAR(3) padded short codes. Transaction 'GB ' must match fx 'GB', transaction 'GB' must match the later fx 'GB ' row, and transaction 'US' must match fx 'US '. SQL Server ignores the trailing |
| X1-TSQL-07-9 | TSQL-07 | legacy_engine | pass | Line 124: the broker-level paid/written ratio sits right at the 0.75 threshold. BRK001: 15000.99/20000 = 0.7500495, which is rounded to 6dp by the division and then to 4dp by the cast. BRK002: 7500.01 |
| X1-TSQL-07-10 | TSQL-07 | legacy_engine | pass | Line 142: each group's high-scale gwp lands exactly on a half cent. 1.00*1.125 = 1.125 should give 1.13, -1.00*1.125 = -1.125 should give -1.13 (half away from zero), 5.00*1.125 = 5.625 should give 5. |
| X1-TSQL-07-11 | TSQL-07 | legacy_engine | pass | Line 144: claims paid summed as decimal. Claim 1 has ten payments of 0.10, which sum to 0.9999999999999999 in double. Claim 2 has 100.00, a -25.50 recovery and a NULL amount. Claim 3 has three payment |
| X1-TSQL-01-12 | TSQL-01 | legacy_engine | pass | Line 148: the report key broker_code is trimmed and upper-cased, but stg.brokers stores 'brk001', 'Brk002', 'bRK003' and 'direct'. Under CI, SQL Server joins them and fills broker_name and status. A b |
| X1-TSQL-02-13 | TSQL-02 | legacy_engine | pass | Line 148: brokers.broker_code is CHAR(6) and holds space-padded values ('BRK01 ', 'BRK2  ', 'AB    ', 'DIRECT') that must match the trimmed keys 'BRK01', 'BRK2' and 'AB'. Policy 2's snapshot code ' BR |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 600 | 6 s | $0.050 |
| defect_reviewer | 1 | 0 | 11,324 | 93 s | $0.275 |
| lineage | 1 | 0 | 6,376 | 48 s | $0.178 |
| test_author | 1 | 0 | 35,559 | 261 s | $0.773 |
| translator | 1 | 0 | 21,331 | 185 s | $0.541 |
| trap_scan | 1 | 0 | 4,130 | 39 s | $0.171 |

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

<details><summary>Migrated PySpark</summary>

```python
"""X1 usp_broker_production: migrated from estate/holdout/X1_usp_broker_production.sql.

Legacy SHA-256: b683ce412ff6786c3d8aa2e3802be8b05f2943d1fb10d7b6093cab40f2ba01d0
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-07, TSQL-08, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X1-D1 claims paid limited to claims notified in the year; X1-D2 broker dimension joined without deduplication; X1-D3 blank broker codes not mapped to DIRECT; X1-D4 non-EUR premium dropped when no FX rate; X1-D5 recoveries added rather than netted off; X1-D6 duplicate claim rows multiply claims; X1-D7 policies expiring on the as-of date counted as in force
"""
import datetime
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def _ci(col):
    # TSQL-01 / TSQL-02: CI collation and trailing-space-insensitive comparison key
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    year_start = datetime.date(as_of.year, 1, 1)  # DATEFROMPARTS(YEAR(@AsOfDate), 1, 1)
    as_of_lit = F.lit(as_of)
    ys_lit = F.lit(year_start)

    snaps = inputs["stg.policy_snapshots"]
    products = inputs["stg.products"]
    txns = inputs["stg.premium_transactions"]
    fx_rates = inputs["stg.fx_rates"]
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    brokers = inputs["stg.brokers"]

    # ---- #pol (TSQL-13): latest snapshot on or before the as-of date
    s = snaps.where(F.col("snapshot_date") <= as_of_lit).alias("s")
    p = products.alias("p")
    pol_src = s.join(
        p,
        _ci(F.col("s.product_code")) == _ci(F.col("p.product_code")),  # TSQL-01 / TSQL-02
        "inner",
    ).select(
        F.col("s.policy_id").alias("policy_id"),
        F.coalesce(F.upper(F.ltrim(F.rtrim(F.col("s.broker_code")))), F.lit("DIRECT")).alias("broker_code"),  # LANSH-DEFECT: X1-D3 blank/all-space broker code stays '' (only NULL becomes DIRECT)
        F.upper(F.rtrim(F.col("p.lob_code"))).alias("lob_code"),
        F.col("s.inception_date").alias("inception_date"),
        F.col("s.expiry_date").alias("expiry_date"),
        F.col("s.cancellation_date").alias("cancellation_date"),
        F.col("s.snapshot_date").alias("snapshot_date"),
        F.col("s._row_seq").alias("s_row_seq"),
        F.col("p._row_seq").alias("p_row_seq"),
    )
    w_pol = Window.partitionBy("policy_id").orderBy(
        F.col("snapshot_date").desc(), F.col("s_row_seq").desc(), F.col("p_row_seq").asc()
    )
    pol = (
        pol_src.withColumn("rn", F.row_number().over(w_pol))
        .where(F.col("rn") == 1)
        .select("policy_id", "broker_code", "lob_code", "inception_date", "expiry_date", "cancellation_date")
    )

    # ---- #inforce (TSQL-13)
    inforce = (
        pol.where(
            (F.col("inception_date") <= as_of_lit)
            & (F.col("expiry_date") >= as_of_lit)  # LANSH-DEFECT: X1-D7 policy expiring on the as-of date counted as in force
            & (F.col("cancellation_date").isNull() | (F.col("cancellation_date") > as_of_lit))
        )
        .groupBy("broker_code", "lob_code")
        .agg(F.count(F.lit(1)).alias("policies_in_force"))
    )

    # ---- #gwp (TSQL-13), OUTER APPLY TOP 1 fx rate (TSQL-09 / TSQL-08)
    t = txns.where((F.col("txn_date") >= ys_lit) & (F.col("txn_date") <= as_of_lit)).select(
        F.col("policy_id").alias("t_policy_id"),
        F.col("txn_date").alias("t_txn_date"),
        F.col("amount").cast("decimal(12,2)").alias("t_amount"),
        F.col("currency").alias("t_currency"),
        F.col("_row_seq").alias("t_row_seq"),
    )
    tp = t.join(
        pol.select("policy_id", "broker_code", "lob_code"),
        F.col("t_policy_id") == F.col("policy_id"),
        "inner",
    )
    fx = fx_rates.select(
        F.col("currency").alias("f_currency"),
        F.col("rate_date").alias("f_rate_date"),
        F.col("rate_to_eur").cast("decimal(18,8)").alias("f_rate"),
        F.col("_row_seq").alias("f_row_seq"),
    )
    tpf = tp.join(
        fx,
        (_ci(F.col("f_currency")) == _ci(F.col("t_currency")))  # TSQL-01 / TSQL-02
        & (F.col("f_rate_date") <= F.col("t_txn_date")),
        "left",  # LANSH-DEFECT: X1-D4 OUTER APPLY keeps transactions with no rate; their NULL product is skipped by SUM
    )
    w_fx = Window.partitionBy("t_row_seq").orderBy(F.col("f_rate_date").desc(), F.col("f_row_seq").desc())
    tpf = tpf.withColumn("fx_rn", F.row_number().over(w_fx)).where(F.col("fx_rn") == 1)
    rate_or_one = F.when(_ci(F.col("t_currency")) == F.lit("EUR"), F.lit(1).cast("decimal(18,8)")).otherwise(
        F.col("f_rate")
    )
    gwp = tpf.groupBy("broker_code", "lob_code").agg(
        # decimal(12,2) * decimal(18,8) -> decimal(31,10); SUM -> decimal(38,10) (TSQL-07)
        F.sum((F.col("t_amount") * rate_or_one).cast("decimal(31,10)")).cast("decimal(38,10)").alias("gwp_eur")  # LANSH-DEFECT: X1-D4 non-EUR premium without fx rate silently dropped
    )

    # ---- #clm (TSQL-13)
    c = claims.where((F.col("reported_date") >= ys_lit) & (F.col("reported_date") <= as_of_lit)).select(  # LANSH-DEFECT: X1-D1 only claims reported in the year
        F.col("claim_id").alias("c_claim_id"),
        F.col("policy_id").alias("c_policy_id"),
    )
    clm = c.join(  # LANSH-DEFECT: X1-D6 stg.claims not deduplicated by claim_id
        pol.select("policy_id", "broker_code", "lob_code"),
        F.col("c_policy_id") == F.col("policy_id"),
        "inner",
    ).select(F.col("c_claim_id").alias("claim_id"), "broker_code", "lob_code")

    # ---- #notified (TSQL-13)
    notified = clm.groupBy("broker_code", "lob_code").agg(F.count(F.lit(1)).alias("claims_notified"))

    # ---- #paid (TSQL-13)
    cp = payments.where((F.col("payment_date") >= ys_lit) & (F.col("payment_date") <= as_of_lit)).select(
        F.col("claim_id").alias("cp_claim_id"),
        F.col("amount").cast("decimal(12,2)").alias("cp_amount"),
    )
    paid = (
        cp.join(clm, F.col("cp_claim_id") == F.col("claim_id"), "inner")  # LANSH-DEFECT: X1-D1 payments on claims reported before the year dropped; X1-D6 duplicate claim rows repeat payments
        .groupBy("broker_code", "lob_code")
        .agg(
            F.sum(F.coalesce(F.col("cp_amount"), F.lit(0).cast("decimal(12,2)")))  # LANSH-DEFECT: X1-D5 all payment types summed, recoveries not netted off
            .cast("decimal(38,2)")
            .alias("claims_paid_eur")
        )
    )

    # ---- #keys (TSQL-13): UNION removes duplicates
    keys = (
        inforce.select("broker_code", "lob_code")
        .union(gwp.select("broker_code", "lob_code"))
        .union(notified.select("broker_code", "lob_code"))
        .union(paid.select("broker_code", "lob_code"))
        .distinct()
    )

    # ---- #ratio (TSQL-13 / TSQL-07)
    ratio_src = (
        keys.join(gwp, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .groupBy("broker_code")
        .agg(
            F.sum(F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)"))).cast("decimal(38,2)").alias("num"),
            F.sum(F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)"))).cast("decimal(38,10)").alias("den"),
        )
    )
    # T-SQL: decimal(38,2) / decimal(38,10) -> decimal(38,6), truncated toward zero; then CAST to decimal(12,4) rounds half up.
    # Exact truncation at 6 places via integral division of num * 1000000 by den (truncates toward zero).
    ratio = (
        ratio_src.withColumn("den_nz", F.when(F.col("den") != 0, F.col("den")))
        .withColumn(
            "q6",
            F.expr("(CAST(num AS DECIMAL(38,10)) * 1000000) div CAST(den_nz AS DECIMAL(38,10))"),
        )
        .withColumn(
            "paid_to_written",
            (F.col("q6").cast("decimal(20,0)") / F.lit(1000000).cast("decimal(10,0)")).cast("decimal(12,4)"),
        )
        .select("broker_code", "paid_to_written")
    )

    # ---- final insert
    b = brokers.select(
        F.col("broker_code").alias("b_broker_code"),
        F.col("broker_name").alias("b_broker_name"),
        F.col("status").alias("b_status"),
    )
    out = (
        keys.join(b, _ci(F.col("broker_code")) == _ci(F.col("b_broker_code")), "left")  # LANSH-DEFECT: X1-D2 brokers joined without dedup, duplicate broker rows repeat output rows; TSQL-01 / TSQL-02
        .join(inforce, ["broker_code", "lob_code"], "left")
        .join(gwp, ["broker_code", "lob_code"], "left")
        .join(notified, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .join(ratio, ["broker_code"], "left")
    )
    result = out.select(
        as_of_lit.alias("as_of_date"),
        F.col("broker_code"),
        F.col("b_broker_name").alias("broker_name"),
        F.upper(F.rtrim(F.col("b_status"))).alias("broker_status"),
        F.col("lob_code"),
        F.coalesce(F.col("policies_in_force").cast("int"), F.lit(0)).alias("policies_in_force"),
        F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)")).cast("decimal(14,2)").alias("gwp_eur"),
        F.coalesce(F.col("claims_notified").cast("int"), F.lit(0)).alias("claims_notified"),
        F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)")).cast("decimal(14,2)").alias("claims_paid_eur"),
        F.col("paid_to_written"),
        F.rpad(
            F.when(F.col("paid_to_written") > F.lit(Decimal("0.75")), F.lit("Y")).otherwise(F.lit("N")), 1, " "
        ).alias("review_flag"),
    )

    return {"rpt.broker_production": result}
```
</details>

