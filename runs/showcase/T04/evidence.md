# Evidence report: T04

Generated 2026-11-12 02:16 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T04_usp_build_claims_summary.sql` (SHA-256 `632841c99f0c5919…`)
- Migrated module: `runs/showcase/T04/jobs/t04.py` (SHA-256 `1b8939e774a444bc…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 15 (TSQL-01, TSQL-02, TSQL-04, TSQL-05, TSQL-13, TSQL-16)
- Suspected defects: 4; tests: 12/12 passed; heal attempts: 0
- Claude: 6 calls (0 live), 53,561 input and 35,196 output tokens, $1.10 API-equivalent (not billed), 281 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: 1) Possible legacy bug (row fan-out): #money LEFT JOINs both claim_payments and #reserve on claim_id before GROUP BY (lines 109-115). A cla |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T04-D1 suspected defect: Payment/reserve join fan-out inflates total_paid and incurred (289 rows); T04-D2 suspected defect: claim_ref becomes NULL when handler_code is NULL (109 rows); T04-D3 suspected defect: Open book |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: Things a reviewer should check: 1) In the #reserve ROW_NUMBER, rows that tie on reserve_date DESC and reserve_id DESC are broken by _row_seq a |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.claims_summary: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `policy_id` | 437355285 | 437355285 | ok |
| Total of `days_open` | 285214 | 285214 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 4267583.98 | 4267583.98 | ok |
| Total of `indemnity_reserve` | 5253371.37 | 5253371.37 | ok |
| Total of `expense_reserve` | 271669.04 | 271669.04 | ok |
| Total of `current_reserve` | 5525040.41 | 5525040.41 | ok |
| Total of `incurred` | 9792624.39 | 9792624.39 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `88c866643793` | `88c866643793` | identical |

Keys: ['claim_id'].

## Operate (Delta lakehouse, reconciled again)

### rpt.claims_summary: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `policy_id` | 437355285 | 437355285 | ok |
| Total of `days_open` | 285214 | 285214 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 4267583.98 | 4267583.98 | ok |
| Total of `indemnity_reserve` | 5253371.37 | 5253371.37 | ok |
| Total of `expense_reserve` | 271669.04 | 271669.04 | ok |
| Total of `current_reserve` | 5525040.41 | 5525040.41 | ok |
| Total of `incurred` | 9792624.39 | 9792624.39 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `88c866643793` | `88c866643793` | identical |

Keys: ['claim_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T04-D1 | Payment/reserve join fan-out inflates total_paid and incurred | 103-152 | 289 | 1288029.36 | reproduce (agent:lansh-dev) |
| T04-D2 | claim_ref becomes NULL when handler_code is NULL | 24-136 | 109 |  | reproduce (agent:lansh-dev) |
| T04-D3 | Open book uses current status instead of status at the reporting date | 60-74 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T04-D4 | Policy number taken from a single global snapshot date | 120-159 | 0 |  | reproduce (agent:lansh-dev) |

## Contract

`gold.claims_summary` (gold), from `rpt.claims_summary`. Grain: One row per claim with status OPEN or REOPENED and reported on or before the reporting date (@AsOfDate), with paid to date, latest case reserves and incurred as at that date.
Key: ['claim_id']; partitions: ['lob_code', 'status'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 61-71 | llm | 0.90 | #open_claims temp table becomes a DataFrame. |
| TSQL-01 | 73-73 | llm | 0.90 | status is VARCHAR; IN ('OPEN','REOPENED') matches case variants under CI collation, Spark binary compare drops them. |
| TSQL-02 | 73-73 | llm | 0.80 | status VARCHAR values with trailing spaces ('OPEN ') still match in SQL Server, not in Spark. |
| TSQL-13 | 81-86 | llm | 0.90 | #reserve temp table becomes a DataFrame. |
| TSQL-01 | 90-91 | llm | 0.80 | PARTITION BY reserve_type (VARCHAR) groups case variants together for the latest-reserve pick; Spark would split them. |
| TSQL-02 | 90-91 | llm | 0.70 | PARTITION BY reserve_type ignores trailing spaces in SQL Server; Spark partitions 'EXPENSE ' separately. |
| TSQL-13 | 101-108 | llm | 0.90 | #money temp table becomes a DataFrame. |
| TSQL-01 | 106-106 | llm | 0.85 | reserve_type = 'INDEMNITY' on VARCHAR matches 'Indemnity' under CI collation; Spark would not. |
| TSQL-02 | 106-106 | llm | 0.75 | reserve_type = 'INDEMNITY' ignores trailing spaces in SQL Server. |
| TSQL-01 | 107-107 | llm | 0.85 | reserve_type = 'EXPENSE' on VARCHAR is case-insensitive in legacy. |
| TSQL-02 | 107-107 | llm | 0.75 | reserve_type = 'EXPENSE' ignores trailing spaces in SQL Server. |
| TSQL-05 | 136-136 | llm | 0.90 | handler_code is nullable; '+' concatenation makes claim_ref NULL when handler_code is NULL; must use concat (not concat_ws). |
| TSQL-16 | 143-143 | llm | 0.95 | CONVERT style 103 gives dd/mm/yyyy; Spark needs date_format 'dd/MM/yyyy'. |
| TSQL-16 | 145-145 | llm | 0.95 | CONVERT(CHAR(6), d, 112) truncates yyyymmdd to yyyymm; Spark needs date_format 'yyyyMM'. |
| TSQL-04 | 146-146 | llm | 0.50 | DATEDIFF(DAY) on DATE equals day difference, but Spark datediff(end,start) reverses argument order; naive translation flips the sign. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| claim_id | stg.claims.claim_id | yes |
| claim_number | stg.claims.claim_number | yes |
| claim_ref | constant, stg.claims.claim_number, stg.claims.handler_code, stg.claims.lob_code | yes |
| policy_id | stg.claims.policy_id | yes |
| policy_number | stg.policy_snapshots.policy_number | yes |
| lob_code | stg.claims.lob_code | yes |
| status | stg.claims.status | yes |
| handler_code | stg.claims.handler_code | yes |
| loss_date | stg.claims.loss_date | yes |
| loss_date_text | stg.claims.loss_date | yes |
| reported_date | stg.claims.reported_date | yes |
| reported_period | stg.claims.reported_date | yes |
| days_open | parameter @AsOfDate, stg.claims.reported_date | yes |
| n_payments | stg.claim_payments.payment_id | yes |
| total_paid | constant, stg.claim_payments.amount | yes |
| indemnity_reserve | constant, stg.claim_reserves.reserve_amount, stg.claim_reserves.reserve_type | yes |
| expense_reserve | constant, stg.claim_reserves.reserve_amount, stg.claim_reserves.reserve_type | yes |
| current_reserve | stg.claim_reserves.reserve_amount, stg.claim_reserves.reserve_type | yes |
| incurred | stg.claim_payments.amount, stg.claim_reserves.reserve_amount, stg.claim_reserves.reserve_type | yes |
| as_of_date | parameter @AsOfDate | yes |

Rows are decided by: stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claim_reserves.claim_id, stg.claim_reserves.reserve_date, stg.claims.claim_id, stg.claims.policy_id, stg.claims.reported_date, stg.claims.status, stg.policy_snapshots.policy_id, stg.policy_snapshots.snapshot_date.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T04-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Status filter (line 73) with case variants. 'open' and 'Reopened' match IN ('OPEN','REOPENED') under the CI collation, so legacy keeps them. A naive Spark isin drops them. Canonical OPEN/REOPENED rows |
| T04-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Status filter (line 73) with trailing spaces. 'OPEN ' and 'REOPENED  ' still match in SQL Server because trailing spaces are ignored. A naive Spark isin drops them. Canonical values are included, plus |
| T04-TSQL-01-3 | TSQL-01 | legacy_engine | pass | Latest-reserve pick (PARTITION BY reserve_type, lines 90-91) with case variants. Claim 301 has INDEMNITY 5000 (Jan) and a later 'Indemnity' 2000 (Jun). Legacy puts both in one partition and keeps only |
| T04-TSQL-02-4 | TSQL-02 | legacy_engine | pass | Latest-reserve pick (lines 90-91) with trailing spaces. Claim 401 has EXPENSE 900 (Jan) and a later 'EXPENSE ' 400. Claim 402 has 'INDEMNITY ' 7000 (Feb) and a later INDEMNITY 2500. SQL Server puts ea |
| T04-TSQL-01-5 | TSQL-01 | legacy_engine | pass | Indemnity pivot (line 106) with case variants. Claims 501 and 502 have a single 'Indemnity' and 'indemnity' reserve. Legacy counts them as INDEMNITY. A case-sensitive Spark CASE gives 0. Claim 503 use |
| T04-TSQL-02-6 | TSQL-02 | legacy_engine | pass | Indemnity pivot (line 106) with trailing spaces. 'INDEMNITY ' and 'INDEMNITY   ' equal 'INDEMNITY' in SQL Server, so they count. A naive Spark equality gives 0. Claim 603 uses the canonical value as a |
| T04-TSQL-01-7 | TSQL-01 | legacy_engine | pass | Expense pivot (line 107) with case variants. 'Expense' and 'expense' reserves count as EXPENSE under the CI collation. A case-sensitive Spark CASE gives 0. Claim 703 uses the canonical EXPENSE. |
| T04-TSQL-02-8 | TSQL-02 | legacy_engine | pass | Expense pivot (line 107) with trailing spaces. 'EXPENSE ' and 'EXPENSE  ' match 'EXPENSE' in SQL Server. A naive Spark equality gives 0. Claim 803 uses the canonical value as a control. |
| T04-TSQL-05-9 | TSQL-05 | legacy_engine | pass | claim_ref built with + (line 136). Claims 902 and 904 have a NULL handler_code, so legacy claim_ref is NULL. concat_ws or coalescing to '' would give 'MOT/CLM902/' instead. The other claims have handl |
| T04-TSQL-16-10 | TSQL-16 | legacy_engine | pass | loss_date_text from CONVERT style 103 (line 143), which gives dd/mm/yyyy with leading zeros. Loss dates include single-digit day and month (2025-03-04, 2025-01-09), a day over 12 (2024-11-25) and day= |
| T04-TSQL-16-11 | TSQL-16 | legacy_engine | pass | reported_period from CONVERT(CHAR(6), d, 112) (line 145): yyyymmdd cut to yyyymm. Reported dates cover single-digit months, December, a leap day and a year boundary. The mix catches yyyy-MM, yyyyMMdd, |
| T04-TSQL-04-12 | TSQL-04 | legacy_engine | pass | days_open = DATEDIFF(DAY, reported_date, @AsOfDate) (line 146). Spark's datediff(end, start) takes its arguments in the reverse order, so swapping them gives negative values. Reported dates include th |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 995 | 16 s | $0.064 |
| defect_reviewer | 1 | 0 | 4,875 | 41 s | $0.140 |
| lineage | 1 | 0 | 6,403 | 47 s | $0.187 |
| test_author | 1 | 0 | 12,501 | 90 s | $0.313 |
| translator | 1 | 0 | 7,241 | 58 s | $0.243 |
| trap_scan | 1 | 0 | 3,181 | 29 s | $0.157 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job       rpt.usp_build_claims_summary
  Purpose   Open claims summary for the claims MI pack: one row per claim that
            is open or reopened at the reporting date, with paid, case reserve
            and incurred to date.
  Author    JMcK
  Run by    CLM_MI_NIGHTLY, after the claims extracts have loaded
  Output    rpt.claims_summary (full refresh)

  Change log
    2014-09-03  JMcK  Initial version (CR-0871)
    2015-02-17  JMcK  Policy number from the policy extract (CR-0933)
    2017-06-26  AOS   Claim reference for the handler worklist (CR-1188)
    2018-11-05  RD    Case reserves by type, current reserve and incurred (CR-1402)
    2020-03-30  AOS   Reopened claims reported with the open book (INC-2207)
    2021-08-12  RD    Days open and reported period for the ageing tabs (CR-1655)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claims_summary', N'U') IS NULL
CREATE TABLE rpt.claims_summary (
    claim_id           INT            NOT NULL,
    claim_number       VARCHAR(20)    NOT NULL,
    claim_ref          VARCHAR(40)    NULL,      -- LOB/claim number/handler
    policy_id          INT            NOT NULL,
    policy_number      VARCHAR(20)    NULL,
    lob_code           VARCHAR(5)     NOT NULL,
    status             VARCHAR(12)    NOT NULL,
    handler_code       VARCHAR(8)     NULL,
    loss_date          DATE           NOT NULL,
    loss_date_text     VARCHAR(10)    NOT NULL,  -- dd/mm/yyyy for the MI pack
    reported_date      DATE           NOT NULL,
    reported_period    CHAR(6)        NOT NULL,  -- yyyymm
    days_open          INT            NOT NULL,
    n_payments         INT            NOT NULL,
    total_paid         DECIMAL(14,2)  NOT NULL,
    indemnity_reserve  DECIMAL(14,2)  NOT NULL,
    expense_reserve    DECIMAL(14,2)  NOT NULL,
    current_reserve    DECIMAL(14,2)  NOT NULL,
    incurred           DECIMAL(14,2)  NOT NULL,
    as_of_date         DATE           NOT NULL,
    CONSTRAINT pk_rpt_claims_summary PRIMARY KEY (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_build_claims_summary
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name       VARCHAR(128) = 'rpt.usp_build_claims_summary',
            @rows           INT,
            @snapshot_date  DATE,
            @err_msg        NVARCHAR(4000),
            @err_no         INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Open book: claims open or reopened and notified by the reporting date */
        IF OBJECT_ID('tempdb..#open_claims') IS NOT NULL DROP TABLE #open_claims;

        SELECT  c.claim_id,
                c.claim_number,
                c.policy_id,
                UPPER(RTRIM(c.lob_code))    AS lob_code,
                c.status,
                c.handler_code,
                c.loss_date,
                c.reported_date
        INTO    #open_claims
        FROM    stg.claims c WITH (NOLOCK)
        WHERE   c.status IN ('OPEN', 'REOPENED')
          AND   c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'open claims', @status = 'INFO', @rows_affected = @rows;

        /* Case reserve per claim and reserve type: the latest entry on or before
           the reporting date (a second entry on the same day is a correction) */
        IF OBJECT_ID('tempdb..#reserve') IS NOT NULL DROP TABLE #reserve;

        SELECT  x.claim_id,
                x.reserve_type,
                x.reserve_amount
        INTO    #reserve
        FROM   (SELECT  r.claim_id,
                        r.reserve_type,
                        r.reserve_amount,
                        ROW_NUMBER() OVER (PARTITION BY r.claim_id, r.reserve_type
                                           ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn
                FROM    stg.claim_reserves r WITH (NOLOCK)
                JOIN    #open_claims oc ON oc.claim_id = r.claim_id
                WHERE   r.reserve_date <= @AsOfDate) x
        WHERE   x.rn = 1;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'case reserves', @status = 'INFO', @rows_affected = @rows;

        /* Paid to date and case reserves per claim */
        IF OBJECT_ID('tempdb..#money') IS NOT NULL DROP TABLE #money;

        SELECT  oc.claim_id,
                COUNT(DISTINCT p.payment_id)    AS n_payments,
                ISNULL(SUM(p.amount), 0)        AS total_paid,
                ISNULL(MAX(CASE WHEN r.reserve_type = 'INDEMNITY' THEN r.reserve_amount END), 0) AS indemnity_reserve,
                ISNULL(MAX(CASE WHEN r.reserve_type = 'EXPENSE'   THEN r.reserve_amount END), 0) AS expense_reserve
        INTO    #money
        FROM    #open_claims oc
        LEFT JOIN stg.claim_payments p WITH (NOLOCK)
               ON p.claim_id = oc.claim_id
              AND p.payment_date <= @AsOfDate
        LEFT JOIN #reserve r
               ON r.claim_id = oc.claim_id
        GROUP BY oc.claim_id;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'paid and reserves', @status = 'INFO', @rows_affected = @rows;

        /* Policy number from the latest policy extract on or before the reporting date */
        SELECT  @snapshot_date = MAX(ps.snapshot_date)
        FROM    stg.policy_snapshots ps WITH (NOLOCK)
        WHERE   ps.snapshot_date <= @AsOfDate;

        BEGIN TRANSACTION;

        TRUNCATE TABLE rpt.claims_summary;

        INSERT INTO rpt.claims_summary
               (claim_id, claim_number, claim_ref, policy_id, policy_number, lob_code,
                status, handler_code, loss_date, loss_date_text, reported_date,
                reported_period, days_open, n_payments, total_paid, indemnity_reserve,
                expense_reserve, current_reserve, incurred, as_of_date)
        SELECT  oc.claim_id,
                oc.claim_number,
                oc.lob_code + '/' + oc.claim_number + '/' + oc.handler_code,
                oc.policy_id,
                ps.policy_number,
                oc.lob_code,
                oc.status,
                oc.handler_code,
                oc.loss_date,
                CONVERT(VARCHAR(10), oc.loss_date, 103),
                oc.reported_date,
                CONVERT(CHAR(6), oc.reported_date, 112),
                DATEDIFF(DAY, oc.reported_date, @AsOfDate),
                m.n_payments,
                m.total_paid,
                m.indemnity_reserve,
                m.expense_reserve,
                m.indemnity_reserve + m.expense_reserve,
                m.total_paid + m.indemnity_reserve + m.expense_reserve,
                @AsOfDate
        FROM    #open_claims oc
        JOIN    #money m
                ON m.claim_id = oc.claim_id
        LEFT JOIN stg.policy_snapshots ps WITH (NOLOCK)
               ON ps.policy_id = oc.policy_id
              AND ps.snapshot_date = @snapshot_date;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'rpt.claims_summary', @status = 'INFO', @rows_affected = @rows;
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
"""T04 usp_build_claims_summary: migrated from estate/tsql/T04_usp_build_claims_summary.sql.

Legacy SHA-256: 632841c99f0c5919975c6fd2266ab04b33e1ba87424c55bbfbe7b0223f3bc975
Written by: LANSH translator (Claude)
Traps handled: TSQL-13, TSQL-01, TSQL-02, TSQL-05, TSQL-16, TSQL-04
Bugs reproduced on purpose (# LANSH-DEFECT): T04-D1 payment/reserve join fan-out, T04-D2 NULL claim_ref when handler_code is NULL, T04-D3 open book on current status, T04-D4 policy number from a single global snapshot date
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]
    snapshots = inputs["stg.policy_snapshots"]

    # ---- #open_claims (TSQL-13), lines 63-74 -------------------------------
    # TSQL-01/TSQL-02: status IN (...) is case-insensitive and ignores trailing spaces.
    open_claims = (
        claims
        .where(
            F.upper(F.rtrim(F.col("status"))).isin("OPEN", "REOPENED")  # LANSH-DEFECT: T04-D3 current status, not status at @AsOfDate
            & (F.col("reported_date") <= as_of)
        )
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
            F.col("status"),
            F.col("handler_code"),
            F.col("loss_date"),
            F.col("reported_date"),
        )
    )

    # ---- #reserve (TSQL-13), lines 83-95 -----------------------------------
    r_src = reserves.where(F.col("reserve_date") <= as_of)
    oc_keys = open_claims.select(F.col("claim_id").alias("_oc_claim_id"))
    r_joined = r_src.join(oc_keys, r_src["claim_id"] == oc_keys["_oc_claim_id"], "inner")
    # TSQL-01/TSQL-02: PARTITION BY reserve_type groups case and trailing-space variants together.
    w_res = (
        Window.partitionBy(F.col("claim_id"), F.upper(F.rtrim(F.col("reserve_type"))))
        .orderBy(
            F.col("reserve_date").desc_nulls_last(),
            F.col("reserve_id").desc_nulls_last(),
            F.col("_row_seq").asc(),
        )
    )
    reserve = (
        r_joined
        .withColumn("_rn", F.row_number().over(w_res))
        .where(F.col("_rn") == 1)
        .select(
            F.col("claim_id").alias("_r_claim_id"),
            F.col("reserve_type"),
            F.col("reserve_amount"),
        )
    )

    # ---- #money (TSQL-13), lines 103-115 -----------------------------------
    pay = (
        payments
        .where(F.col("payment_date") <= as_of)
        .select(
            F.col("claim_id").alias("_p_claim_id"),
            F.col("payment_id"),
            F.col("amount"),
        )
    )
    money_base = (
        open_claims.select(F.col("claim_id"))
        .join(pay, F.col("claim_id") == F.col("_p_claim_id"), "left")
        .join(reserve, F.col("claim_id") == F.col("_r_claim_id"), "left")  # LANSH-DEFECT: T04-D1 payments x reserve rows fan-out before GROUP BY
    )
    rtype = F.upper(F.rtrim(F.col("reserve_type")))  # TSQL-01/TSQL-02
    money = (
        money_base
        .groupBy(F.col("claim_id"))
        .agg(
            F.countDistinct(F.col("payment_id")).alias("n_payments"),
            F.coalesce(F.sum(F.col("amount")), F.lit(0)).alias("total_paid"),  # LANSH-DEFECT: T04-D1 SUM over fanned-out rows inflates total_paid
            F.coalesce(F.max(F.when(rtype == "INDEMNITY", F.col("reserve_amount"))), F.lit(0)).alias("indemnity_reserve"),
            F.coalesce(F.max(F.when(rtype == "EXPENSE", F.col("reserve_amount"))), F.lit(0)).alias("expense_reserve"),
        )
        .select(
            F.col("claim_id").alias("_m_claim_id"),
            F.col("n_payments"),
            F.col("total_paid"),
            F.col("indemnity_reserve"),
            F.col("expense_reserve"),
        )
    )

    # ---- @snapshot_date, lines 121-123 -------------------------------------
    snap = (
        snapshots
        .where(F.col("snapshot_date") <= as_of)
        .agg(F.max(F.col("snapshot_date")).alias("_snap_date"))  # LANSH-DEFECT: T04-D4 one global snapshot date for every policy
    )
    ps = (
        snapshots
        .join(snap, snapshots["snapshot_date"] == snap["_snap_date"], "inner")  # LANSH-DEFECT: T04-D4 exact match on the global snapshot date, no fallback
        .select(
            F.col("policy_id").alias("_ps_policy_id"),
            F.col("policy_number"),
        )
    )

    # ---- INSERT INTO rpt.claims_summary, lines 129-159 ---------------------
    joined = (
        open_claims
        .join(money, F.col("claim_id") == F.col("_m_claim_id"), "inner")
        .join(ps, F.col("policy_id") == F.col("_ps_policy_id"), "left")
    )

    result = joined.select(
        F.col("claim_id"),
        F.col("claim_number"),
        # TSQL-05: '+' concatenation is NULL if any part is NULL.
        F.concat(
            F.col("lob_code"), F.lit("/"), F.col("claim_number"), F.lit("/"), F.col("handler_code")
        ).alias("claim_ref"),  # LANSH-DEFECT: T04-D2 NULL handler_code makes claim_ref NULL
        F.col("policy_id"),
        F.col("policy_number"),
        F.col("lob_code"),
        F.col("status"),
        F.col("handler_code"),
        F.col("loss_date"),
        # TSQL-16: CONVERT(VARCHAR(10), d, 103) -> dd/MM/yyyy
        F.date_format(F.col("loss_date"), "dd/MM/yyyy").alias("loss_date_text"),
        F.col("reported_date"),
        # TSQL-16: CONVERT(CHAR(6), d, 112) -> first 6 chars of yyyyMMdd
        F.substring(F.date_format(F.col("reported_date"), "yyyyMMdd"), 1, 6).alias("reported_period"),
        # TSQL-04: DATEDIFF(DAY, start, end) -> datediff(end, start)
        F.datediff(as_of, F.col("reported_date")).alias("days_open"),
        F.col("n_payments"),
        F.col("total_paid"),
        F.col("indemnity_reserve"),
        F.col("expense_reserve"),
        (F.col("indemnity_reserve") + F.col("expense_reserve")).alias("current_reserve"),
        (F.col("total_paid") + F.col("indemnity_reserve") + F.col("expense_reserve")).alias("incurred"),  # LANSH-DEFECT: T04-D1 incurred carries the inflated total_paid
        as_of.alias("as_of_date"),
    )

    return {"rpt.claims_summary": result}
```
</details>

