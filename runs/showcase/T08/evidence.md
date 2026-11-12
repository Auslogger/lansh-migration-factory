# Evidence report: T08

Generated 2026-11-12 02:45 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T08_usp_fraud_flags.sql` (SHA-256 `6e90a4a5ad66f216…`)
- Migrated module: `runs/showcase/T08/jobs/t08.py` (SHA-256 `51554b00b50d6e9b…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 11 (TSQL-01, TSQL-02, TSQL-13, TSQL-14, TSQL-15, TSQL-16, TSQL-18)
- Suspected defects: 5; tests: 9/9 passed; heal attempts: 0
- Claude: 6 calls (0 live), 54,810 input and 47,607 output tokens, $1.28 API-equivalent (not billed), 362 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: 1) The policy and customer joins (lines 88-92) are LEFT JOINs. They decide which policy and customer values get attached, but they never dr |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T08-D1 suspected defect: Early notification measured from policy expiry instead of inception (146 rows); T08-D2 suspected defect: Policies missing from the single latest snapshot get blank details and silently score 0 ( |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1) DATEADD(MONTH, -12, @AsOfDate) is worked out in Python using T-SQL's rule: the day is clamped only when the target month is shorter. For 20 |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.claim_fraud_flags: MATCH

MATCH: all 1,042 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 1,042 | 1,042 | ok |
| Total of `claim_id` | 315090901 | 315090901 | ok |
| Total of `policy_id` | 553100929 | 553100929 | ok |
| Total of `customer_id` | 114690369 | 114690369 | ok |
| Total of `early_notification_flag` | 72 | 72 | ok |
| Total of `invalid_reg_flag` | 11 | 11 | ok |
| Total of `new_customer_flag` | 51 | 51 | ok |
| Total of `lob_mismatch_flag` | 1 | 1 | ok |
| Total of `fraud_score` | 135 | 135 | ok |
| Records matched | | | 1,042 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `dbeb53828d46` | `dbeb53828d46` | identical |

Keys: ['claim_id'].

## Operate (Delta lakehouse, reconciled again)

### rpt.claim_fraud_flags: MATCH

MATCH: all 1,042 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 1,042 | 1,042 | ok |
| Total of `claim_id` | 315090901 | 315090901 | ok |
| Total of `policy_id` | 553100929 | 553100929 | ok |
| Total of `customer_id` | 114690369 | 114690369 | ok |
| Total of `early_notification_flag` | 72 | 72 | ok |
| Total of `invalid_reg_flag` | 11 | 11 | ok |
| Total of `new_customer_flag` | 51 | 51 | ok |
| Total of `lob_mismatch_flag` | 1 | 1 | ok |
| Total of `fraud_score` | 135 | 135 | ok |
| Records matched | | | 1,042 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `dbeb53828d46` | `dbeb53828d46` | identical |

Keys: ['claim_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T08-D1 | Early notification measured from policy expiry instead of inception | 83-108 | 146 |  | reproduce (agent:lansh-dev) |
| T08-D2 | Policies missing from the single latest snapshot get blank details and silently score 0 | 66-118 | 0 |  | reproduce (agent:lansh-dev) |
| T08-D3 | Six-month new-customer window hard-coded as 180 days | 114-115 | 3 |  | reproduce (agent:lansh-dev) |
| T08-D4 | LOB mismatch compares only the first 3 characters of the policy number | 117-118 | 0 |  | reproduce (agent:lansh-dev) |
| T08-D5 | Motor claims with a missing registration are not flagged | 111-112 | 3 |  | reproduce (agent:lansh-dev) |

## Contract

`gold.claim_fraud_flags` (gold), from `rpt.claim_fraud_flags`. Grain: One row per claim reported in the 12 months up to the reporting date (@AsOfDate), with its SIU fraud flags, score and referral band.
Key: ['claim_id']; partitions: ['lob_code', 'fraud_band'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 72-86 | llm | 0.90 | The #claims temp table holds the claims enriched with policy and customer data; in Spark it becomes a DataFrame. |
| TSQL-18 | 93-93 | llm | 0.70 | DATEADD(MONTH,-12,@AsOfDate) only clamps to a month-end when it has to. Spark add_months also moves a month-end input to a month-end, so @AsOfDate = 2025-02-28 gives 2024-02-29 instead of 2024-02-28 a |
| TSQL-13 | 100-105 | llm | 0.90 | The #flags temp table holds the indicator flags and score; in Spark it becomes a DataFrame. |
| TSQL-01 | 111-111 | llm | 0.85 | lob_code is VARCHAR(5). Under the CI collation, 'mot' and 'Mot' match 'MOT', so those claims get the motor registration check; a plain Spark equality would skip them. The later UPPER() suggests mixed- |
| TSQL-02 | 111-111 | llm | 0.80 | lob_code is VARCHAR(5), and the RTRIM at line 140 shows it can carry trailing spaces. 'MOT ' = 'MOT' in SQL Server but not in Spark. |
| TSQL-14 | 112-112 | llm | 0.95 | The LIKE pattern uses the [0-9] and [A-Z] character classes, and [A-Z] is case-insensitive under the CI collation. Spark LIKE would read them as literal text, so it must become an rlike with case-inse |
| TSQL-01 | 118-118 | llm | 0.75 | The <> compares text with text: a substring of policy_number (VARCHAR) against lob_code (VARCHAR). Under the CI collation, a case difference such as 'mot' vs 'MOT' is not a mismatch; in Spark it is. |
| TSQL-02 | 118-118 | llm | 0.75 | SQL Server ignores trailing spaces when comparing, so a lob_code of 'MOT ' equals the 3-character prefix 'MOT'. Spark would raise the mismatch flag. |
| TSQL-15 | 118-118 | llm | 0.95 | SUBSTRING(policy_number, 0, 4) returns only 3 characters in T-SQL. Spark substring(x, 0, 4) returns 4, which would change every lob_mismatch_flag. |
| TSQL-16 | 152-152 | llm | 0.85 | CONVERT style 112 gives yyyymmdd and needs date_format 'yyyyMMdd'. A plain cast would give yyyy-MM-dd, which also breaks the CHAR(8) key. |
| TSQL-16 | 153-153 | llm | 0.90 | CONVERT style 103 gives dd/mm/yyyy in the reason text and needs date_format 'dd/MM/yyyy'. A string cast would give yyyy-MM-dd. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| claim_id | stg.claims.claim_id | - |
| claim_number | stg.claims.claim_number | - |
| policy_id | stg.claims.policy_id | - |
| policy_number | stg.policy_snapshots.policy_number | - |
| customer_id | stg.claims.customer_id | - |
| lob_code | stg.claims.lob_code | - |
| loss_date | stg.claims.loss_date | - |
| reported_date | stg.claims.reported_date | - |
| early_notification_flag | stg.claims.reported_date, stg.policy_snapshots.expiry_date | - |
| invalid_reg_flag | constant, stg.claims.lob_code, stg.policy_snapshots.vehicle_reg | - |
| new_customer_flag | dw.dim_customer.customer_since, stg.claims.loss_date | - |
| lob_mismatch_flag | stg.claims.lob_code, stg.policy_snapshots.policy_number | - |
| fraud_score | dw.dim_customer.customer_since, stg.claims.lob_code, stg.claims.loss_date, stg.claims.reported_date, stg.policy_snapshots.expiry_date, stg.policy_snapshots.policy_number, stg.policy_snapshots.vehicle_reg | - |
| fraud_band | constant, dw.dim_customer.customer_since, stg.claims.lob_code, stg.claims.loss_date, stg.claims.reported_date, stg.policy_snapshots.expiry_date, stg.policy_snapshots.policy_number, stg.policy_snapshots.vehicle_reg | - |
| loss_day_key | stg.claims.loss_date | - |
| reason_text | constant, dw.dim_customer.customer_since, stg.claims.lob_code, stg.claims.loss_date, stg.claims.reported_date, stg.policy_snapshots.expiry_date, stg.policy_snapshots.policy_number, stg.policy_snapshots.vehicle_reg | - |
| as_of_date | parameter @AsOfDate | - |

Rows are decided by: dw.dim_customer.customer_id, stg.claims.customer_id, stg.claims.policy_id, stg.claims.reported_date, stg.policy_snapshots.policy_id, stg.policy_snapshots.snapshot_date.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T08-TSQL-18-1 | TSQL-18 | legacy_engine | pass | Claims reported on both sides of the 12-month window: 2024-12-31 (excluded, it is exactly DATEADD(MONTH,-12,AsOfDate)), 2025-01-01 (first day in), mid-year, 2025-12-31 (last day in) and 2026-01-01 (af |
| T08-TSQL-01-2 | TSQL-01 | legacy_engine | pass | Line 111: motor claims with lob_code 'mot', 'Mot' and 'MOT' on policies whose vehicle_reg is not in the Irish format ('ABC123'), plus one 'MOT' with a valid reg and one 'HOM' control. Under the CI col |
| T08-TSQL-02-3 | TSQL-02 | legacy_engine | pass | Line 111: lob_code values 'MOT ' and 'MOT  ' (trailing spaces) on policies with an invalid reg 'XYZ999', next to a plain 'MOT' with the same invalid reg, a 'MOT' with a valid reg, and a 'HOM' control. |
| T08-TSQL-14-4 | TSQL-14 | legacy_engine | pass | Motor claims whose vehicle_reg tests the LIKE character classes: '191-D-12345' (valid), '191-d-12345' (lowercase county, which [A-Z] matches under CI), '12-KY-9' (valid), 'ABC-123' (invalid, starts wi |
| T08-TSQL-01-5 | TSQL-01 | legacy_engine | pass | Line 118: policy_number prefixes that differ from lob_code only in case: 'mot/2025/...' against 'MOT', 'Hom/2025/...' against 'HOM', and 'MOT/...' against lob 'mot'. Controls: an exact 'MOT' match and |
| T08-TSQL-02-6 | TSQL-02 | legacy_engine | pass | Line 118: claims with lob_code 'MOT ', 'MOT  ' and 'HOM ' (trailing spaces) on policies whose numbers start with the matching 3-character prefix. Controls: an unpadded 'MOT' and a real mismatch. SQL S |
| T08-TSQL-15-7 | TSQL-15 | legacy_engine | pass | Line 118: policy numbers in the standard 'LOB/yyyy/nnnnnn' form, so T-SQL SUBSTRING(x,0,4) returns the 3-character prefix ('MOT', 'HOM', 'TRV') and matching claims get lob_mismatch_flag = 0. Spark sub |
| T08-TSQL-16-8 | TSQL-16 | legacy_engine | pass | Line 152: loss dates with single-digit months and days (2025-01-02, 2025-03-07, 2025-09-09) and two-digit ones (2025-11-30, 2025-12-25), all in the reporting window. CONVERT style 112 gives an 8-chara |
| T08-TSQL-16-9 | TSQL-16 | legacy_engine | pass | Line 153: reported dates where day and month are both 12 or less (2025-03-04, 2025-04-05, 2025-12-01) and some where they are not (2025-07-25, 2025-10-31), so a day/month swap or a yyyy-MM-dd cast sho |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 974 | 11 s | $0.057 |
| defect_reviewer | 1 | 0 | 5,495 | 49 s | $0.154 |
| lineage | 1 | 0 | 7,241 | 52 s | $0.149 |
| test_author | 1 | 0 | 22,264 | 151 s | $0.500 |
| translator | 1 | 0 | 9,274 | 78 s | $0.290 |
| trap_scan | 1 | 0 | 2,359 | 22 s | $0.126 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job       rpt.usp_fraud_flags
  Purpose   Fraud indicators for the Special Investigations Unit (SIU): one row
            per claim notified in the twelve months to the reporting date, with
            the indicator flags, a score and a referral band for the SIU
            worklist and case tool.
  Author    MOB
  Run by    SIU_WEEKLY, after the claims and policy extracts and dw.dim_customer
            have loaded
  Output    rpt.claim_fraud_flags (full refresh)

  Change log
    2016-05-09  MOB   Initial version: early notification and new customer
                      indicators (CR-0954)
    2016-11-21  MOB   Motor claims: registration not in the Irish format
                      (CR-1012)
    2017-04-03  SB    Claim keyed against a policy from another line of
                      business (INC-1530)
    2018-08-27  SB    fraud_score and referral bands agreed with SIU (CR-1377)
    2019-02-11  NF    Policy dates from the latest policy extract on or before
                      the reporting date, not the old policy master (CR-1529)
    2020-06-15  NF    loss_day_key and reason text for the SIU case tool
                      (CR-1810)
    2021-10-04  SB    lob_code upper-cased for the SIU dashboard (INC-2389)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claim_fraud_flags', N'U') IS NULL
CREATE TABLE rpt.claim_fraud_flags (
    claim_id                 INT            NOT NULL,
    claim_number             VARCHAR(20)    NOT NULL,
    policy_id                INT            NOT NULL,
    policy_number            VARCHAR(20)    NULL,
    customer_id              INT            NOT NULL,
    lob_code                 VARCHAR(5)     NOT NULL,
    loss_date                DATE           NOT NULL,
    reported_date            DATE           NOT NULL,
    early_notification_flag  INT            NOT NULL,
    invalid_reg_flag         INT            NOT NULL,
    new_customer_flag        INT            NOT NULL,
    lob_mismatch_flag        INT            NOT NULL,
    fraud_score              INT            NOT NULL,
    fraud_band               VARCHAR(6)     NOT NULL,  -- HIGH / MEDIUM / LOW
    loss_day_key             CHAR(8)        NOT NULL,  -- yyyymmdd, day key in the case tool
    reason_text              VARCHAR(100)   NOT NULL,
    as_of_date               DATE           NOT NULL,
    CONSTRAINT pk_rpt_claim_fraud_flags PRIMARY KEY (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_fraud_flags
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name       VARCHAR(128) = 'rpt.usp_fraud_flags',
            @rows           INT,
            @snapshot_date  DATE,
            @err_msg        NVARCHAR(4000),
            @err_no         INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Policy details from the latest policy extract on or before the reporting date */
        SELECT  @snapshot_date = MAX(ps.snapshot_date)
        FROM    stg.policy_snapshots ps WITH (NOLOCK)
        WHERE   ps.snapshot_date <= @AsOfDate;

        /* 1. Claims notified in the twelve months to the reporting date, with the
              policy they were made under and when the policyholder became a customer */
        IF OBJECT_ID('tempdb..#claims') IS NOT NULL DROP TABLE #claims;

        SELECT  c.claim_id,
                c.claim_number,
                c.policy_id,
                c.customer_id,
                c.lob_code,
                c.loss_date,
                c.reported_date,
                p.policy_number,
                p.inception_date,
                p.expiry_date,
                p.vehicle_reg,
                dc.customer_since
        INTO    #claims
        FROM    stg.claims c WITH (NOLOCK)
        LEFT JOIN stg.policy_snapshots p WITH (NOLOCK)
               ON p.policy_id = c.policy_id
              AND p.snapshot_date = @snapshot_date
        LEFT JOIN dw.dim_customer dc WITH (NOLOCK)
               ON dc.customer_id = c.customer_id
        WHERE   c.reported_date >  DATEADD(MONTH, -12, @AsOfDate)
          AND   c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claims notified', @status = 'INFO', @rows_affected = @rows;

        /* 2. SIU indicators, one point each (CR-0954, CR-1012, INC-1530) */
        IF OBJECT_ID('tempdb..#flags') IS NOT NULL DROP TABLE #flags;

        SELECT  f.*,
                f.early_notification_flag + f.invalid_reg_flag
                  + f.new_customer_flag + f.lob_mismatch_flag     AS fraud_score
        INTO    #flags
        FROM   (SELECT  cl.claim_id,
                        -- claim notified within 30 days of the cover starting
                        CASE WHEN DATEDIFF(DAY, cl.expiry_date, cl.reported_date) BETWEEN 0 AND 30
                             THEN 1 ELSE 0 END                    AS early_notification_flag,
                        -- motor: registration not in the Irish format, e.g. 191-D-12345
                        CASE WHEN cl.lob_code = 'MOT'
                              AND cl.vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'
                             THEN 1 ELSE 0 END                    AS invalid_reg_flag,
                        -- customer for less than six months at the date of loss
                        CASE WHEN DATEDIFF(DAY, cl.customer_since, cl.loss_date) < 180
                             THEN 1 ELSE 0 END                    AS new_customer_flag,
                        -- policy number starts with its line of business (MOT/2024/500001)
                        CASE WHEN SUBSTRING(cl.policy_number, 0, 4) <> cl.lob_code
                             THEN 1 ELSE 0 END                    AS lob_mismatch_flag
                FROM    #claims cl) f;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'indicators', @status = 'INFO', @rows_affected = @rows;

        /* 3. Reload the SIU table: bands agreed with SIU (CR-1377) */
        BEGIN TRANSACTION;

        TRUNCATE TABLE rpt.claim_fraud_flags;

        INSERT INTO rpt.claim_fraud_flags
               (claim_id, claim_number, policy_id, policy_number, customer_id, lob_code,
                loss_date, reported_date, early_notification_flag, invalid_reg_flag,
                new_customer_flag, lob_mismatch_flag, fraud_score, fraud_band,
                loss_day_key, reason_text, as_of_date)
        SELECT  cl.claim_id,
                cl.claim_number,
                cl.policy_id,
                cl.policy_number,
                cl.customer_id,
                UPPER(RTRIM(cl.lob_code)),
                cl.loss_date,
                cl.reported_date,
                f.early_notification_flag,
                f.invalid_reg_flag,
                f.new_customer_flag,
                f.lob_mismatch_flag,
                f.fraud_score,
                CASE WHEN f.fraud_score >= 2 THEN 'HIGH'
                     WHEN f.fraud_score = 1  THEN 'MEDIUM'
                     ELSE 'LOW'
                END,
                CONVERT(CHAR(8), cl.loss_date, 112),
                'Notified ' + CONVERT(VARCHAR(10), cl.reported_date, 103)
                    + CASE WHEN f.fraud_score = 0 THEN ' - no indicators' ELSE ' -' END
                    + CASE WHEN f.early_notification_flag = 1 THEN ' EARLY'   ELSE '' END
                    + CASE WHEN f.invalid_reg_flag        = 1 THEN ' REG'     ELSE '' END
                    + CASE WHEN f.new_customer_flag       = 1 THEN ' NEWCUST' ELSE '' END
                    + CASE WHEN f.lob_mismatch_flag       = 1 THEN ' LOB'     ELSE '' END,
                @AsOfDate
        FROM    #claims cl
        JOIN    #flags f
                ON f.claim_id = cl.claim_id;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'rpt.claim_fraud_flags', @status = 'INFO', @rows_affected = @rows;
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
"""T08 usp_fraud_flags: migrated from estate/tsql/T08_usp_fraud_flags.sql.

Legacy SHA-256: 6e90a4a5ad66f2169982f70407d488edd7b7e0053a0617f71b9e9947cb9de886
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-13, TSQL-14, TSQL-15, TSQL-16, TSQL-18
Bugs reproduced on purpose (# LANSH-DEFECT): T08-D1 early notification from expiry date, T08-D2 policies missing from latest snapshot score 0, T08-D3 new-customer window hard-coded 180 days, T08-D4 LOB prefix only 3 characters, T08-D5 missing motor registration not flagged
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
import pyspark.sql.functions as F


def _dateadd_month(d: datetime.date, n: int) -> datetime.date:
    """T-SQL DATEADD(MONTH, n, d): clamp the day only when the target month is shorter (TSQL-18)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    if mo == 12:
        nxt = datetime.date(y + 1, 1, 1)
    else:
        nxt = datetime.date(y, mo + 1, 1)
    last_day = (nxt - datetime.timedelta(days=1)).day
    return datetime.date(y, mo, min(d.day, last_day))


def _ci(c):
    """Comparison key under the CI collation, ignoring trailing spaces (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(c))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_of_lit = F.lit(as_of)
    # TSQL-18: DATEADD(MONTH, -12, @AsOfDate) computed with T-SQL clamping rules
    window_start = F.lit(_dateadd_month(as_of, -12))

    claims_src = inputs["stg.claims"]
    ps = inputs["stg.policy_snapshots"]
    dc = inputs["dw.dim_customer"]

    # @snapshot_date = MAX(snapshot_date) on or before @AsOfDate (NULL if none -> no policy rows match)
    snap = (ps.where(F.col("snapshot_date") <= as_of_lit)
              .agg(F.max("snapshot_date").alias("_snapshot_date")))  # LANSH-DEFECT: T08-D2 single global latest snapshot for every claim
    pol = (ps.join(snap, F.col("snapshot_date") == F.col("_snapshot_date"), "inner")
             .select(F.col("policy_id").alias("_p_policy_id"),
                     F.col("policy_number"),
                     F.col("inception_date"),
                     F.col("expiry_date"),
                     F.col("vehicle_reg")))

    cust = dc.select(F.col("customer_id").alias("_dc_customer_id"), F.col("customer_since"))

    # 1. #claims (TSQL-13): claims notified in the 12 months to the reporting date
    c = claims_src.where((F.col("reported_date") > window_start) & (F.col("reported_date") <= as_of_lit))
    claims = (c.join(pol, F.col("policy_id") == F.col("_p_policy_id"), "left")  # LANSH-DEFECT: T08-D2 policy missing from snapshot leaves NULL policy details
               .join(cust, F.col("customer_id") == F.col("_dc_customer_id"), "left")
               .select(F.col("claim_id"),
                       F.col("claim_number"),
                       F.col("policy_id"),
                       F.col("customer_id"),
                       F.col("lob_code"),
                       F.col("loss_date"),
                       F.col("reported_date"),
                       F.col("policy_number"),
                       F.col("inception_date"),
                       F.col("expiry_date"),
                       F.col("vehicle_reg"),
                       F.col("customer_since")))

    # 2. #flags (TSQL-13)
    early_flag = F.when(
        F.datediff(F.col("reported_date"), F.col("expiry_date")).between(0, 30), F.lit(1)  # LANSH-DEFECT: T08-D1 measured from expiry_date, not inception_date
    ).otherwise(F.lit(0))

    is_motor = _ci(F.col("lob_code")) == F.lit("MOT")  # TSQL-01 / TSQL-02
    # TSQL-14: LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%' as an anchored, case-insensitive regex (% matches anything, incl. newlines)
    reg_matches = F.col("vehicle_reg").rlike("(?is)^[0-9][0-9].*-[A-Z].*-[0-9]")
    invalid_reg_flag = F.when(is_motor & ~reg_matches, F.lit(1)).otherwise(F.lit(0))  # LANSH-DEFECT: T08-D5 NULL vehicle_reg is UNKNOWN -> 0 (also T08-D2)

    new_customer_flag = F.when(
        F.datediff(F.col("loss_date"), F.col("customer_since")) < 180, F.lit(1)  # LANSH-DEFECT: T08-D3 six months hard-coded as 180 days
    ).otherwise(F.lit(0))

    # TSQL-15: SUBSTRING(policy_number, 0, 4) returns the first 3 characters
    lob_mismatch_flag = F.when(
        _ci(F.substring(F.col("policy_number"), 1, 3)) != _ci(F.col("lob_code")), F.lit(1)  # LANSH-DEFECT: T08-D4 only 3-char prefix compared; NULL policy_number -> 0 (T08-D2)
    ).otherwise(F.lit(0))

    flags = (claims.select(F.col("claim_id").alias("_f_claim_id"),
                           early_flag.alias("early_notification_flag"),
                           invalid_reg_flag.alias("invalid_reg_flag"),
                           new_customer_flag.alias("new_customer_flag"),
                           lob_mismatch_flag.alias("lob_mismatch_flag"))
                   .withColumn("fraud_score",
                               F.col("early_notification_flag") + F.col("invalid_reg_flag")
                               + F.col("new_customer_flag") + F.col("lob_mismatch_flag")))

    # 3. Insert: #claims JOIN #flags ON claim_id
    joined = claims.join(flags, F.col("claim_id") == F.col("_f_claim_id"), "inner")

    fraud_band = (F.when(F.col("fraud_score") >= 2, F.lit("HIGH"))
                   .when(F.col("fraud_score") == 1, F.lit("MEDIUM"))
                   .otherwise(F.lit("LOW")))

    # TSQL-16: style 112 -> yyyyMMdd, CHAR(8) padded (TSQL-02)
    loss_day_key = F.rpad(F.date_format(F.col("loss_date"), "yyyyMMdd"), 8, " ")

    # TSQL-16: style 103 -> dd/MM/yyyy; + concatenation is NULL if any part is NULL (F.concat)
    reason_text = F.concat(
        F.lit("Notified "),
        F.substring(F.date_format(F.col("reported_date"), "dd/MM/yyyy"), 1, 10),
        F.when(F.col("fraud_score") == 0, F.lit(" - no indicators")).otherwise(F.lit(" -")),
        F.when(F.col("early_notification_flag") == 1, F.lit(" EARLY")).otherwise(F.lit("")),
        F.when(F.col("invalid_reg_flag") == 1, F.lit(" REG")).otherwise(F.lit("")),
        F.when(F.col("new_customer_flag") == 1, F.lit(" NEWCUST")).otherwise(F.lit("")),
        F.when(F.col("lob_mismatch_flag") == 1, F.lit(" LOB")).otherwise(F.lit("")),
    )

    out = joined.select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.col("policy_id"),
        F.col("policy_number"),
        F.col("customer_id"),
        F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
        F.col("loss_date"),
        F.col("reported_date"),
        F.col("early_notification_flag"),
        F.col("invalid_reg_flag"),
        F.col("new_customer_flag"),
        F.col("lob_mismatch_flag"),
        F.col("fraud_score"),
        fraud_band.alias("fraud_band"),
        loss_day_key.alias("loss_day_key"),
        reason_text.alias("reason_text"),
        as_of_lit.alias("as_of_date"),
    )

    return {"rpt.claim_fraud_flags": out}
```
</details>

