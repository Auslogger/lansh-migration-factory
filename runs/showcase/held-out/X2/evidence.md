# Evidence report: X2

Generated 2026-11-12 03:41 UTC. **Status: MATCH.**

- Legacy code: `estate/holdout/X2_usp_large_loss_watchlist.sql` (SHA-256 `bc9df85f8e39e93c…`)
- Migrated module: `runs/showcase/held-out/X2/jobs/x2.py` (SHA-256 `aa82f4c322484824…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 12 (TSQL-01, TSQL-02, TSQL-04, TSQL-06, TSQL-07, TSQL-09, TSQL-13)
- Suspected defects: 3; tests: 5/5 passed; heal attempts: 0
- Claude: 6 calls (6 live), 52,004 input and 34,374 output tokens, $1.03 API-equivalent (not billed), 298 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: The ROW_NUMBER at lines 76-77 groups by (period, claim_id) only, not by reserve_type. So each claim keeps just its single latest reserve ro |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: X2-D1 suspected defect: Latest reserve picked across all reserve types, so only one type counts (43 rows); X2-D2 suspected defect: Claims closed exactly 90 days ago are dropped (0 rows); X2-D3 suspected defect: CLOSED c |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1. Ties in ROW_NUMBER with the same reserve_date and reserve_id are broken by ascending _row_seq. The legacy order is non-deterministic in tha |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.large_loss_watchlist: MATCH

MATCH: all 79 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 79 | 79 | ok |
| Total of `claim_id` | 23860095 | 23860095 | ok |
| Total of `policy_id` | 41899362 | 41899362 | ok |
| Total of `paid_to_date` | 1417688.94 | 1417688.94 | ok |
| Total of `outstanding_reserve` | 1650193.08 | 1650193.08 | ok |
| Total of `incurred_amount` | 3067882.02 | 3067882.02 | ok |
| Total of `incurred_90d_ago` | 2449365.06 | 2449365.06 | ok |
| Total of `movement_90d` | 618516.96 | 618516.96 | ok |
| Total of `reserve_changes_90d` | 128 | 128 | ok |
| Total of `days_since_last_activity` | 4974 | 4974 | ok |
| Records matched | | | 79 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `0978475d9e1d` | `0978475d9e1d` | identical |

Keys: ['claim_id'].

## Operate (Delta lakehouse, reconciled again)

### rpt.large_loss_watchlist: MATCH

MATCH: all 79 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 79 | 79 | ok |
| Total of `claim_id` | 23860095 | 23860095 | ok |
| Total of `policy_id` | 41899362 | 41899362 | ok |
| Total of `paid_to_date` | 1417688.94 | 1417688.94 | ok |
| Total of `outstanding_reserve` | 1650193.08 | 1650193.08 | ok |
| Total of `incurred_amount` | 3067882.02 | 3067882.02 | ok |
| Total of `incurred_90d_ago` | 2449365.06 | 2449365.06 | ok |
| Total of `movement_90d` | 618516.96 | 618516.96 | ok |
| Total of `reserve_changes_90d` | 128 | 128 | ok |
| Total of `days_since_last_activity` | 4974 | 4974 | ok |
| Records matched | | | 79 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `0978475d9e1d` | `0978475d9e1d` | identical |

Keys: ['claim_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| X2-D1 | Latest reserve picked across all reserve types, so only one type counts | 10-89 | 43 | 683219.73 | reproduce (agent:lansh-dev) |
| X2-D2 | Claims closed exactly 90 days ago are dropped | 11-59 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| X2-D3 | CLOSED check uses the raw status, not the trimmed one | 14-59 | 0 | 0.00 | reproduce (agent:lansh-dev) |

## Contract

`gold.large_loss_watchlist` (gold), from `rpt.large_loss_watchlist`. Grain: One row per claim (open, reopened, or closed within the last 90 days) whose incurred amount (paid to date plus latest outstanding reserve) is at least EUR 25,000 as at the as-of date.
Key: ['claim_id']; partitions: ['watch_category', 'lob_code'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 56-56 | llm | 0.95 | Temp table #clm holds the filtered claims; it becomes a DataFrame. |
| TSQL-01 | 59-59 | llm | 0.90 | c.status is VARCHAR(12) and is compared before the trim and upper-case. Under the CI collation, 'Closed' and 'closed' count as CLOSED and are dropped once closed more than 90 days ago. Spark's binary  |
| TSQL-02 | 59-59 | llm | 0.85 | The raw status is compared untrimmed. SQL Server treats 'CLOSED ' as equal to 'CLOSED', but Spark does not, so old closed claims padded with trailing spaces would stay in the Spark result. |
| TSQL-13 | 68-68 | llm | 0.95 | Temp table #paid holds the payment aggregates; it becomes a DataFrame. |
| TSQL-13 | 78-78 | llm | 0.95 | Temp table #res holds the reserve rows ranked per period; it becomes a DataFrame. |
| TSQL-09 | 81-82 | llm | 0.70 | CROSS APPLY (VALUES ...) multiplies each reserve row into a NOW and a PRIOR period. Spark has no APPLY, so this becomes a cross join with a two-row DataFrame, followed by the reserve_date <= as_at fil |
| TSQL-13 | 87-87 | llm | 0.95 | Temp table #os holds the outstanding reserves now and 90 days ago; it becomes a DataFrame. |
| TSQL-13 | 96-96 | llm | 0.95 | Temp table #ract holds the reserve activity; it becomes a DataFrame. |
| TSQL-06 | 108-109 | llm | 0.60 | ISNULL takes the DATE type of its first argument, so '19000101' becomes the date 1900-01-01. In Spark, coalesce(date, '19000101') widens to string or fails to cast that literal, so the replacement mus |
| TSQL-13 | 110-110 | llm | 0.95 | Temp table #inc holds the incurred amounts; it becomes a DataFrame. |
| TSQL-04 | 127-127 | llm | 0.50 | DATEDIFF(DAY, start, end) on DATE values gives the day difference. Spark's datediff takes its arguments in reverse order (end, start), so they must be swapped to avoid a negated result. |
| TSQL-07 | 129-130 | llm | 0.65 | incurred_90d_ago * 1.10 and * 0.90 are exact DECIMAL multiplications in T-SQL. In PySpark, F.lit(1.10) is a double, which can put a claim on the boundary into the wrong DETERIORATING/IMPROVING/STABLE  |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| as_of_date | parameter @AsOfDate | yes |
| claim_id | stg.claims.claim_id | yes |
| claim_number | stg.claims.claim_number | yes |
| policy_id | stg.claims.policy_id | yes |
| lob_code | stg.claims.lob_code | yes |
| claim_status | stg.claims.status | yes |
| reported_date | stg.claims.reported_date | yes |
| closed_date | stg.claims.closed_date | yes |
| paid_to_date | constant, stg.claim_payments.amount | yes |
| outstanding_reserve | constant, stg.claim_reserves.reserve_amount | yes |
| incurred_amount | stg.claim_payments.amount, stg.claim_reserves.reserve_amount | yes |
| incurred_90d_ago | parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claim_reserves.reserve_amount | yes |
| movement_90d | parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claim_reserves.reserve_amount | yes |
| reserve_changes_90d | constant, parameter @AsOfDate, stg.claim_reserves.reserve_date | yes |
| days_since_last_activity | parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claim_reserves.reserve_date | yes |
| watch_category | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claim_reserves.reserve_amount | yes |

Rows are decided by: stg.claim_payments.amount, stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claim_reserves.claim_id, stg.claim_reserves.reserve_amount, stg.claim_reserves.reserve_date, stg.claims.claim_id, stg.claims.closed_date, stg.claims.reported_date, stg.claims.status.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| X2-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Claims with mixed-case CLOSED statuses ('Closed', 'closed', 'clOSed') closed more than 90 days before AsOfDate (PriorDate = 2025-10-02). Under the CI collation, `status <> 'CLOSED'` is false for these |
| X2-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Claims whose raw status has trailing spaces ('CLOSED ', 'CLOSED  ') and was closed before PriorDate 2025-10-02. SQL Server ignores trailing spaces when comparing, so these count as CLOSED and are drop |
| X2-TSQL-06-3 | TSQL-06 | legacy_engine | pass | The last-activity choice with NULL on either side. Claims are set up with payments only (last_reserve_date is NULL), reserves only (last_payment_date is NULL), a later payment than reserve, a later re |
| X2-TSQL-04-4 | TSQL-04 | legacy_engine | pass | Claims whose last activity falls at different distances before AsOfDate 2025-12-31: on AsOfDate itself, one day before, mid-month, across a year boundary (2024-01-15), and one where the latest payment |
| X2-TSQL-07-5 | TSQL-07 | legacy_engine | pass | Claims whose incurred amount is exactly 1.10x or 0.90x of incurred_90d_ago. A reserve on 2025-09-01 sets the prior amount and a reserve on 2025-12-01 sets the current amount. Pairs: 25000.10→27500.11, |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 1 | 475 | 6 s | $0.046 |
| defect_reviewer | 1 | 1 | 6,521 | 58 s | $0.171 |
| lineage | 1 | 1 | 6,736 | 57 s | $0.176 |
| test_author | 1 | 1 | 8,907 | 67 s | $0.223 |
| translator | 1 | 1 | 9,062 | 78 s | $0.283 |
| trap_scan | 1 | 1 | 2,673 | 32 s | $0.132 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : rpt.usp_large_loss_watchlist
  Purpose  : Large-loss watchlist for the claims committee. Every claim with an
             incurred amount (paid to date plus outstanding case reserve) of at
             least EUR 25,000 as at @AsOfDate, compared with 90 days earlier and
             given a watch category (NEW, DETERIORATING, IMPROVING, STABLE).
  Author   : RBy
  Change log
    2013-05-22  RBy   Initial version (CR-0301)
    2015-01-19  RBy   Expense reserves included in incurred (CR-0577)
    2016-10-04  DMcC  Claims closed more than 90 days ago dropped (CR-0912)
    2018-07-30  DMcC  Reserve changes and days since last activity added (CR-1188)
    2020-02-11  NOF   Threshold raised from EUR 20,000 to EUR 25,000 (CR-1402)
    2022-09-05  NOF   Status and LOB codes trimmed and upper-cased (INC-3204)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.large_loss_watchlist', N'U') IS NULL
CREATE TABLE rpt.large_loss_watchlist (
    as_of_date                DATE           NOT NULL,
    claim_id                  INT            NOT NULL,
    claim_number              VARCHAR(20)    NOT NULL,
    policy_id                 INT            NOT NULL,
    lob_code                  VARCHAR(5)     NOT NULL,
    claim_status              VARCHAR(12)    NOT NULL,
    reported_date             DATE           NOT NULL,
    closed_date               DATE           NULL,
    paid_to_date              DECIMAL(14,2)  NOT NULL,
    outstanding_reserve       DECIMAL(14,2)  NOT NULL,
    incurred_amount           DECIMAL(14,2)  NOT NULL,
    incurred_90d_ago          DECIMAL(14,2)  NOT NULL,
    movement_90d              DECIMAL(14,2)  NOT NULL,
    reserve_changes_90d       INT            NOT NULL,
    days_since_last_activity  INT            NULL,
    watch_category            VARCHAR(15)    NOT NULL
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_large_loss_watchlist
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job       VARCHAR(128) = 'rpt.usp_large_loss_watchlist';
    DECLARE @PriorDate DATE         = DATEADD(DAY, -90, @AsOfDate);
    DECLARE @rows      INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'start', @status = 'STARTED';

        -- open and reopened claims, plus claims closed in the last 90 days
        SELECT c.claim_id, c.claim_number, c.policy_id,
               UPPER(LTRIM(RTRIM(c.lob_code))) AS lob_code,
               UPPER(LTRIM(RTRIM(c.status)))   AS claim_status,
               c.reported_date, c.closed_date
        INTO #clm
        FROM stg.claims c WITH (NOLOCK)
        WHERE c.reported_date <= @AsOfDate
          AND (c.status <> 'CLOSED' OR c.closed_date > @PriorDate);
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'claims', @status = 'INFO', @rows_affected = @rows;

        -- payments to date and 90 days ago; unkeyed amounts count as nil
        SELECT p.claim_id,
               SUM(ISNULL(p.amount, 0)) AS paid_now,
               SUM(CASE WHEN p.payment_date <= @PriorDate THEN ISNULL(p.amount, 0) ELSE 0 END) AS paid_prior,
               MAX(CASE WHEN p.amount IS NOT NULL THEN p.payment_date END) AS last_payment_date
        INTO #paid
        FROM stg.claim_payments p WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = p.claim_id
        WHERE p.payment_date <= @AsOfDate
        GROUP BY p.claim_id;

        -- outstanding reserve as at today and 90 days ago
        SELECT r.claim_id, d.period, r.reserve_amount,
               ROW_NUMBER() OVER (PARTITION BY d.period, r.claim_id
                                  ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn
        INTO #res
        FROM stg.claim_reserves r WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = r.claim_id
        CROSS APPLY (VALUES ('NOW', @AsOfDate), ('PRIOR', @PriorDate)) d (period, as_at)
        WHERE r.reserve_date <= d.as_at;

        SELECT claim_id,
               SUM(CASE WHEN period = 'NOW'   THEN reserve_amount ELSE 0 END) AS os_now,
               SUM(CASE WHEN period = 'PRIOR' THEN reserve_amount ELSE 0 END) AS os_prior
        INTO #os
        FROM #res
        WHERE rn = 1
        GROUP BY claim_id;

        -- reserve activity
        SELECT r.claim_id,
               SUM(CASE WHEN r.reserve_date > @PriorDate THEN 1 ELSE 0 END) AS reserve_changes_90d,
               MAX(r.reserve_date) AS last_reserve_date
        INTO #ract
        FROM stg.claim_reserves r WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = r.claim_id
        WHERE r.reserve_date <= @AsOfDate
        GROUP BY r.claim_id;

        SELECT c.claim_id,
               ISNULL(p.paid_now, 0) AS paid_to_date,
               ISNULL(o.os_now, 0) AS outstanding_reserve,
               ISNULL(p.paid_now, 0) + ISNULL(o.os_now, 0) AS incurred_amount,
               ISNULL(p.paid_prior, 0) + ISNULL(o.os_prior, 0) AS incurred_90d_ago,
               ISNULL(a.reserve_changes_90d, 0) AS reserve_changes_90d,
               CASE WHEN ISNULL(p.last_payment_date, '19000101') > ISNULL(a.last_reserve_date, '19000101')
                    THEN p.last_payment_date ELSE a.last_reserve_date END AS last_activity_date
        INTO #inc
        FROM #clm c
        LEFT JOIN #paid p ON p.claim_id = c.claim_id
        LEFT JOIN #os o   ON o.claim_id = c.claim_id
        LEFT JOIN #ract a ON a.claim_id = c.claim_id;

        TRUNCATE TABLE rpt.large_loss_watchlist;

        INSERT INTO rpt.large_loss_watchlist
            (as_of_date, claim_id, claim_number, policy_id, lob_code, claim_status, reported_date,
             closed_date, paid_to_date, outstanding_reserve, incurred_amount, incurred_90d_ago,
             movement_90d, reserve_changes_90d, days_since_last_activity, watch_category)
        SELECT @AsOfDate, c.claim_id, c.claim_number, c.policy_id, c.lob_code, c.claim_status,
               c.reported_date, c.closed_date,
               i.paid_to_date, i.outstanding_reserve, i.incurred_amount, i.incurred_90d_ago,
               i.incurred_amount - i.incurred_90d_ago,
               i.reserve_changes_90d,
               DATEDIFF(DAY, i.last_activity_date, @AsOfDate),
               CASE WHEN i.incurred_90d_ago < 25000 THEN 'NEW'
                    WHEN i.incurred_amount > i.incurred_90d_ago * 1.10 THEN 'DETERIORATING'
                    WHEN i.incurred_amount < i.incurred_90d_ago * 0.90 THEN 'IMPROVING'
                    ELSE 'STABLE' END
        FROM #inc i
        INNER JOIN #clm c ON c.claim_id = i.claim_id
        WHERE i.incurred_amount >= 25000;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'load rpt.large_loss_watchlist', @status = 'INFO', @rows_affected = @rows;

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
"""X2 usp_large_loss_watchlist: migrated from estate/holdout/X2_usp_large_loss_watchlist.sql.

Legacy SHA-256: bc9df85f8e39e93cc102c59e14ed2d6f84543a4a3c5cdc8b445ab1108e162772
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-06, TSQL-07, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X2-D1 latest reserve picked across all reserve types; X2-D2 claims closed exactly 90 days ago dropped; X2-D3 CLOSED check uses the raw (untrimmed-left) status
"""
import datetime
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]

    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    prior = as_of - datetime.timedelta(days=90)  # DATEADD(DAY, -90, @AsOfDate)
    as_of_lit = F.lit(as_of)
    prior_lit = F.lit(prior)

    # TSQL-13: #clm -> DataFrame
    # TSQL-01 / TSQL-02: status compared case-insensitively and ignoring trailing spaces only
    clm = (
        claims
        .where(
            (F.col("reported_date") <= as_of_lit)
            & (
                (F.upper(F.rtrim(F.col("status"))) != F.lit("CLOSED"))  # LANSH-DEFECT: X2-D3 raw status compared; leading spaces still count so ' CLOSED' passes
                | (F.col("closed_date") > prior_lit)  # LANSH-DEFECT: X2-D2 strict > drops claims closed exactly 90 days ago
            )
        )
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.upper(F.trim(F.col("lob_code"))).alias("lob_code"),
            F.upper(F.trim(F.col("status"))).alias("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
        )
    )
    clm_ids = clm.select("claim_id")

    # TSQL-13: #paid -> DataFrame
    zero_12_2 = F.lit(0).cast("decimal(12,2)")
    amt = F.coalesce(F.col("amount"), zero_12_2)  # TSQL-06: ISNULL keeps decimal(12,2)
    paid = (
        payments
        .where(F.col("payment_date") <= as_of_lit)
        .join(clm_ids, on="claim_id", how="inner")
        .groupBy("claim_id")
        .agg(
            F.sum(amt).cast("decimal(38,2)").alias("paid_now"),
            F.sum(F.when(F.col("payment_date") <= prior_lit, amt).otherwise(zero_12_2)).cast("decimal(38,2)").alias("paid_prior"),
            F.max(F.when(F.col("amount").isNotNull(), F.col("payment_date"))).alias("last_payment_date"),
        )
    )

    # TSQL-09: CROSS APPLY (VALUES ...) -> cross join with a two-row DataFrame, then the as_at filter
    periods = spark.createDataFrame(
        [("NOW", as_of), ("PRIOR", prior)],
        T.StructType([
            T.StructField("period", T.StringType(), False),
            T.StructField("as_at", T.DateType(), False),
        ]),
    )
    # TSQL-13: #res -> DataFrame
    w_res = Window.partitionBy("period", "claim_id").orderBy(  # LANSH-DEFECT: X2-D1 partition ignores reserve_type, only the single latest reserve row counts
        F.col("reserve_date").desc(), F.col("reserve_id").desc(), F.col("_row_seq").asc()
    )
    res = (
        reserves
        .join(clm_ids, on="claim_id", how="inner")
        .crossJoin(periods)
        .where(F.col("reserve_date") <= F.col("as_at"))
        .select(
            F.col("claim_id"), F.col("period"), F.col("reserve_amount"),
            F.row_number().over(w_res).alias("rn"),
        )
    )

    # TSQL-13: #os -> DataFrame
    os_df = (
        res
        .where(F.col("rn") == 1)  # LANSH-DEFECT: X2-D1 keeps one reserve row per claim and period, other reserve types dropped
        .groupBy("claim_id")
        .agg(
            F.sum(F.when(F.col("period") == F.lit("NOW"), F.col("reserve_amount")).otherwise(zero_12_2)).cast("decimal(38,2)").alias("os_now"),  # LANSH-DEFECT: X2-D1 sums exactly one row (latest of any type)
            F.sum(F.when(F.col("period") == F.lit("PRIOR"), F.col("reserve_amount")).otherwise(zero_12_2)).cast("decimal(38,2)").alias("os_prior"),  # LANSH-DEFECT: X2-D1 sums exactly one row (latest of any type)
        )
    )

    # TSQL-13: #ract -> DataFrame
    ract = (
        reserves
        .where(F.col("reserve_date") <= as_of_lit)
        .join(clm_ids, on="claim_id", how="inner")
        .groupBy("claim_id")
        .agg(
            F.sum(F.when(F.col("reserve_date") > prior_lit, F.lit(1)).otherwise(F.lit(0))).cast("int").alias("reserve_changes_90d"),
            F.max(F.col("reserve_date")).alias("last_reserve_date"),
        )
    )

    # TSQL-13: #inc -> DataFrame
    zero_38_2 = F.lit(0).cast("decimal(38,2)")
    # TSQL-06: ISNULL(date, '19000101') -> typed date literal
    sentinel = F.to_date(F.lit("19000101"), "yyyyMMdd")
    inc = (
        clm_ids
        .join(paid, on="claim_id", how="left")
        .join(os_df, on="claim_id", how="left")
        .join(ract, on="claim_id", how="left")
        .select(
            F.col("claim_id"),
            F.coalesce(F.col("paid_now"), zero_38_2).alias("paid_to_date"),
            F.coalesce(F.col("os_now"), zero_38_2).alias("outstanding_reserve"),
            (F.coalesce(F.col("paid_now"), zero_38_2) + F.coalesce(F.col("os_now"), zero_38_2)).cast("decimal(38,2)").alias("incurred_amount"),
            (F.coalesce(F.col("paid_prior"), zero_38_2) + F.coalesce(F.col("os_prior"), zero_38_2)).cast("decimal(38,2)").alias("incurred_90d_ago"),
            F.coalesce(F.col("reserve_changes_90d"), F.lit(0).cast("int")).alias("reserve_changes_90d"),
            F.when(
                F.coalesce(F.col("last_payment_date"), sentinel) > F.coalesce(F.col("last_reserve_date"), sentinel),
                F.col("last_payment_date"),
            ).otherwise(F.col("last_reserve_date")).alias("last_activity_date"),
        )
    )

    # TSQL-07: exact decimal multipliers
    up = F.lit(Decimal("1.10"))
    down = F.lit(Decimal("0.90"))
    i_inc = F.col("incurred_amount")
    i_prior = F.col("incurred_90d_ago")

    out = (
        inc
        .join(clm, on="claim_id", how="inner")
        .where(i_inc >= F.lit(25000))
        .select(
            as_of_lit.alias("as_of_date"),
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.col("lob_code"),
            F.col("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
            F.col("paid_to_date"),
            F.col("outstanding_reserve"),
            i_inc.alias("incurred_amount"),
            i_prior.alias("incurred_90d_ago"),
            (i_inc - i_prior).cast("decimal(38,2)").alias("movement_90d"),
            F.col("reserve_changes_90d"),
            # TSQL-04: DATEDIFF(DAY, start, end) -> datediff(end, start)
            F.datediff(as_of_lit, F.col("last_activity_date")).alias("days_since_last_activity"),
            F.when(i_prior < F.lit(25000), F.lit("NEW"))
             .when(i_inc > i_prior * up, F.lit("DETERIORATING"))
             .when(i_inc < i_prior * down, F.lit("IMPROVING"))
             .otherwise(F.lit("STABLE")).alias("watch_category"),
        )
    )

    return {"rpt.large_loss_watchlist": out}
```
</details>

