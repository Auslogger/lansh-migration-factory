# Evidence report: T05

Generated 2026-11-12 02:16 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T05_usp_claim_aging.sql` (SHA-256 `f443e5070182d5b7…`)
- Migrated module: `runs/showcase/T05/jobs/t05.py` (SHA-256 `5cb945e3b84952df…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 10 (TSQL-01, TSQL-02, TSQL-04, TSQL-12, TSQL-13)
- Suspected defects: 4; tests: 3/3 passed; heal attempts: 0
- Claude: 6 calls (0 live), 48,923 input and 20,365 output tokens, $0.73 API-equivalent (not billed), 178 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off); warnings read: flagged: 6 statements sqlglot can't parse (lines 104-107, 110-110, 118-122, 125-125, 133-133, 155-155); the translator works from the code itself; lineage of rpt.claim_aging.aging_band disagrees with sqlglot (agent only |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T05-D1 suspected defect: Ageing band gap: 30 days falls into UNKNOWN (31 rows); T05-D2 suspected defect: weeks_open counts week boundaries, not elapsed weeks (361 rows); T05-D3 suspected defect: A NULL payment amount ma |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: The two cursor loops are replaced by one aggregation per claim on #pay, which is then left-joined to #open_claims: - n_payments = count(*), or |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.claim_aging: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 2904669.63 | 2904669.63 | ok |
| Total of `days_since_activity` | 118343 | 118343 | ok |
| Total of `weeks_open` | 40753 | 40753 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `52e8d5320a5c` | `52e8d5320a5c` | identical |

Keys: ['claim_id'].

## Operate (Delta lakehouse, reconciled again)

### rpt.claim_aging: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 2904669.63 | 2904669.63 | ok |
| Total of `days_since_activity` | 118343 | 118343 | ok |
| Total of `weeks_open` | 40753 | 40753 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `52e8d5320a5c` | `52e8d5320a5c` | identical |

Keys: ['claim_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T05-D1 | Ageing band gap: 30 days falls into UNKNOWN | 145-148 | 31 |  | reproduce (agent:lansh-dev) |
| T05-D2 | weeks_open counts week boundaries, not elapsed weeks | 142-142 | 361 | 361.00 | reproduce (agent:lansh-dev) |
| T05-D3 | A NULL payment amount makes total_paid NULL | 28-130 | 23 | 74884.99 | reproduce (agent:lansh-dev) |
| T05-D4 | Duplicate staged payment rows are double-counted | 81-130 | 0 | 0.00 | reproduce (agent:lansh-dev) |

## Contract

`gold.claim_aging` (gold), from `rpt.claim_aging`. Grain: One row per open or re-opened claim notified on or before the reporting date (@AsOfDate), aged on the days since its last payment up to that date, or since its reported date if nothing has been paid.
Key: ['claim_id']; partitions: ['lob_code', 'aging_band'].
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 67-74 | llm | 0.90 | The #open_claims temp table becomes a DataFrame. |
| TSQL-01 | 73-73 | llm | 0.90 | status is VARCHAR(12). Under the CI collation, IN ('OPEN','REOPENED') also matches 'Open' and 'reopened'. Spark's isin is case-sensitive and would drop those claims. |
| TSQL-02 | 73-73 | llm | 0.85 | status is VARCHAR. Values stored with trailing spaces, such as 'OPEN ', still match in SQL Server but not with an exact match in Spark. |
| TSQL-13 | 81-88 | llm | 0.90 | The #pay temp table and its clustered index become a DataFrame. The index has no Spark equivalent. |
| TSQL-13 | 92-101 | llm | 0.85 | The #aging temp table is filled row by row and becomes a DataFrame. |
| TSQL-12 | 104-156 | llm | 0.95 | The claim_cur cursor loop handles one claim at a time and inserts into #aging. It becomes a set-based left join and aggregation per claim. |
| TSQL-12 | 118-137 | llm | 0.90 | The nested pay_cur loop carries n_pay, total and last_pay from row to row in payment_date, payment_id order. It becomes count, sum and max per claim. Claims with no payments must get n_payments=0, tot |
| TSQL-12 | 129-131 | llm | 0.60 | Latent: amount is nullable. One NULL amount makes @total NULL for the rest of that claim's loop and in the output, while Spark's sum skips NULLs. n_pay still counts that row. last_pay is the date of t |
| TSQL-04 | 141-141 | llm | 0.40 | DATEDIFF(DAY) on DATE values is the plain day difference, so the value is safe. But Spark's datediff(end, start) takes its arguments in reverse order. |
| TSQL-04 | 142-142 | llm | 0.95 | DATEDIFF(WEEK) counts the Sundays crossed between reported_date and @AsOfDate, not elapsed weeks. floor(datediff/7) would be wrong. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| claim_id | stg.claims.claim_id | yes |
| claim_number | stg.claims.claim_number | yes |
| lob_code | stg.claims.lob_code | yes |
| reported_date | stg.claims.reported_date | yes |
| n_payments | constant, stg.claim_payments.payment_id | no |
| total_paid | constant, stg.claim_payments.amount | no |
| last_payment_date | stg.claim_payments.payment_date | no |
| last_activity_date | stg.claim_payments.payment_date, stg.claims.reported_date | no |
| days_since_activity | parameter @AsOfDate, stg.claim_payments.payment_date, stg.claims.reported_date | no |
| weeks_open | parameter @AsOfDate, stg.claims.reported_date | no |
| aging_band | constant, parameter @AsOfDate, stg.claim_payments.payment_date, stg.claims.reported_date | no |
| as_of_date | parameter @AsOfDate | yes |

Rows are decided by: stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claims.claim_id, stg.claims.reported_date, stg.claims.status.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T05-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Open-book filter with mixed-case status values. Claims 1 and 2 use the canonical 'OPEN' and 'REOPENED'. Claims 3, 4 and 5 hold 'Open', 'reopened' and 'ReOpened'; the case-insensitive collation keeps t |
| T05-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Status values stored with trailing spaces. Claims 1 and 2 are the canonical 'OPEN' and 'REOPENED'. Claims 3, 4 and 5 are 'OPEN ', 'REOPENED  ' and 'OPEN   '. SQL Server ignores trailing spaces when co |
| T05-TSQL-04-3 | TSQL-04 | legacy_engine | pass | DATEDIFF semantics on lines 141 and 142, with AsOfDate 2025-12-31 (a Wednesday). Every claim has a non-zero day gap, so a Spark datediff(start, end) with the arguments reversed would give negative day |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 728 | 8 s | $0.049 |
| defect_reviewer | 1 | 0 | 3,994 | 39 s | $0.120 |
| lineage | 1 | 0 | 4,484 | 36 s | $0.131 |
| test_author | 1 | 0 | 4,089 | 33 s | $0.125 |
| translator | 1 | 0 | 5,360 | 47 s | $0.197 |
| trap_scan | 1 | 0 | 1,710 | 17 s | $0.105 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : rpt.usp_claim_aging
  Purpose  : Ageing of the open claims book for claims operations: each open or
             re-opened claim is aged on the days since its last activity (its
             last payment up to the reporting date, or the date it was notified
             when nothing has been paid yet). Feeds the weekly diary review.
  Output   : rpt.claim_aging (truncated and reloaded on every run)
  Author   : BMcG

  Change log
    2013-10-07  BMcG  Initial version
    2014-05-19  BMcG  weeks_open added for the handler workload report (CR-0317)
    2016-02-08  RF    Re-opened claims aged as well (CR-0852)
    2017-09-25  RF    Payments staged in #pay first; nightly run down from
                      40 min to 2 min (INC-1904)
    2019-04-01  NK    Payments dated after the reporting date ignored (CR-1488)
    2020-11-16  NK    Ageing bands added for the claims MI pack (CR-1951)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claim_aging', N'U') IS NULL
CREATE TABLE rpt.claim_aging (
    claim_id             INT            NOT NULL,
    claim_number         VARCHAR(20)    NOT NULL,
    lob_code             VARCHAR(5)     NOT NULL,
    reported_date        DATE           NOT NULL,
    n_payments           INT            NOT NULL,
    total_paid           DECIMAL(14,2)  NULL,
    last_payment_date    DATE           NULL,
    last_activity_date   DATE           NOT NULL,
    days_since_activity  INT            NOT NULL,
    weeks_open           INT            NOT NULL,
    aging_band           VARCHAR(10)    NOT NULL,
    as_of_date           DATE           NOT NULL,
    CONSTRAINT pk_claim_aging PRIMARY KEY CLUSTERED (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_claim_aging
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'rpt.usp_claim_aging',
            @rows      INT,
            @claim_id  INT,
            @reported  DATE,
            @pay_date  DATE,
            @amount    DECIMAL(12,2),
            @n_pay     INT,
            @total     DECIMAL(14,2),
            @last_pay  DATE,
            @last_act  DATE,
            @days      INT,
            @weeks     INT,
            @band      VARCHAR(10),
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        IF OBJECT_ID('tempdb..#open_claims') IS NOT NULL DROP TABLE #open_claims;
        IF OBJECT_ID('tempdb..#pay') IS NOT NULL DROP TABLE #pay;

        -- 1. open book: open and re-opened claims notified by the reporting date
        SELECT c.claim_id,
               c.claim_number,
               UPPER(RTRIM(c.lob_code)) AS lob_code,
               c.reported_date
        INTO   #open_claims
        FROM   stg.claims AS c WITH (NOLOCK)
        WHERE  c.status IN ('OPEN', 'REOPENED')
          AND  c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'open claims',
             @status = 'INFO', @rows_affected = @rows;

        -- 2. payments on those claims up to the reporting date
        SELECT p.claim_id, p.payment_id, p.payment_date, p.amount
        INTO   #pay
        FROM   stg.claim_payments AS p WITH (NOLOCK)
        INNER JOIN #open_claims AS o ON o.claim_id = p.claim_id
        WHERE  p.payment_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        CREATE CLUSTERED INDEX ix_pay ON #pay (claim_id, payment_date, payment_id);
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'payments',
             @status = 'INFO', @rows_affected = @rows;

        CREATE TABLE #aging (
            claim_id             INT            NOT NULL PRIMARY KEY,
            n_payments           INT            NOT NULL,
            total_paid           DECIMAL(14,2)  NULL,
            last_payment_date    DATE           NULL,
            last_activity_date   DATE           NOT NULL,
            days_since_activity  INT            NOT NULL,
            weeks_open           INT            NOT NULL,
            aging_band           VARCHAR(10)    NOT NULL
        );

        -- 3. age each claim on its payment history
        DECLARE claim_cur CURSOR LOCAL FAST_FORWARD FOR
            SELECT claim_id, reported_date
            FROM   #open_claims
            ORDER  BY claim_id;

        OPEN claim_cur;
        FETCH NEXT FROM claim_cur INTO @claim_id, @reported;

        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @n_pay    = 0;
            SET @total    = 0;
            SET @last_pay = NULL;

            DECLARE pay_cur CURSOR LOCAL FAST_FORWARD FOR
                SELECT payment_date, amount
                FROM   #pay
                WHERE  claim_id = @claim_id
                ORDER  BY payment_date, payment_id;

            OPEN pay_cur;
            FETCH NEXT FROM pay_cur INTO @pay_date, @amount;

            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @n_pay    = @n_pay + 1;
                SET @total    = @total + @amount;
                SET @last_pay = @pay_date;

                FETCH NEXT FROM pay_cur INTO @pay_date, @amount;
            END

            CLOSE pay_cur;
            DEALLOCATE pay_cur;

            -- last activity: the last payment, or notification if nothing paid yet
            SET @last_act = ISNULL(@last_pay, @reported);
            SET @days     = DATEDIFF(DAY, @last_act, @AsOfDate);
            SET @weeks    = DATEDIFF(WEEK, @reported, @AsOfDate);

            -- ageing band for the MI pack
            SET @band = CASE WHEN @days < 30 THEN '0-29'
                             WHEN @days BETWEEN 31 AND 60 THEN '31-60'
                             WHEN @days > 60 THEN '61+'
                             ELSE 'UNKNOWN'
                        END;

            INSERT INTO #aging (claim_id, n_payments, total_paid, last_payment_date,
                                last_activity_date, days_since_activity, weeks_open, aging_band)
            VALUES (@claim_id, @n_pay, @total, @last_pay, @last_act, @days, @weeks, @band);

            FETCH NEXT FROM claim_cur INTO @claim_id, @reported;
        END

        CLOSE claim_cur;
        DEALLOCATE claim_cur;

        SELECT @rows = COUNT(*) FROM #aging;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claim loop',
             @status = 'INFO', @rows_affected = @rows;

        -- 4. reload the report table
        TRUNCATE TABLE rpt.claim_aging;

        INSERT INTO rpt.claim_aging (claim_id, claim_number, lob_code, reported_date,
               n_payments, total_paid, last_payment_date, last_activity_date,
               days_since_activity, weeks_open, aging_band, as_of_date)
        SELECT o.claim_id, o.claim_number, o.lob_code, o.reported_date,
               a.n_payments, a.total_paid, a.last_payment_date, a.last_activity_date,
               a.days_since_activity, a.weeks_open, a.aging_band, @AsOfDate
        FROM   #aging AS a
        INNER JOIN #open_claims AS o ON o.claim_id = a.claim_id;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'load rpt.claim_aging',
             @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        SELECT @err_msg = ERROR_MESSAGE(), @err_no = ERROR_NUMBER();
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claim aging',
             @status = 'FAILED', @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH
END;
GO
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""T05 usp_claim_aging: migrated from estate/tsql/T05_usp_claim_aging.sql.

Legacy SHA-256: f443e5070182d5b723af38f23dc653d53fc43f8eb322f5cdd5e1f6bd1893b12f
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-12, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): T05-D1 ageing band gap at 30 days, T05-D2 weeks_open counts Sunday boundaries, T05-D3 NULL amount makes total_paid NULL, T05-D4 duplicate staged payments double-counted
"""
import datetime

from pyspark.sql import SparkSession, DataFrame
import pyspark.sql.functions as F
import pyspark.sql.types as T
from pyspark.sql import Window


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]

    # 1. #open_claims (TSQL-13): open and re-opened claims notified by the reporting date.
    # TSQL-01 / TSQL-02: the CI collation ignores case and trailing spaces in the IN list.
    open_claims = (
        claims
        .where(F.upper(F.rtrim(F.col("status"))).isin("OPEN", "REOPENED"))
        .where(F.col("reported_date") <= as_of)
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
            F.col("reported_date"),
        )
    )

    # 2. #pay (TSQL-13): payments on those claims up to the reporting date.
    # The clustered index has no Spark equivalent and is not needed.
    pay = (
        payments.alias("p")
        .join(open_claims.select("claim_id").alias("o"),
              F.col("o.claim_id") == F.col("p.claim_id"), "inner")
        .where(F.col("p.payment_date") <= as_of)
        .select(
            F.col("p.claim_id").alias("claim_id"),
            F.col("p.payment_id").alias("payment_id"),
            F.col("p.payment_date").alias("payment_date"),
            F.col("p.amount").alias("amount"),
        )
    )

    # 3. TSQL-12: the claim_cur / pay_cur loops become an aggregation per claim.
    #    n_pay counts every fetched row; @total = @total + @amount goes NULL on any NULL
    #    amount; @last_pay is the date of the last row in (payment_date, payment_id) order,
    #    which is max(payment_date) (payment_date cannot be NULL after the <= filter).
    pay_agg = (
        pay.groupBy("claim_id")
        .agg(
            F.count(F.lit(1)).alias("n_pay"),  # LANSH-DEFECT: T05-D4 duplicate staged payment rows are each counted
            F.sum(F.when(F.col("amount").isNull(), F.lit(1)).otherwise(F.lit(0))).alias("n_null_amount"),
            F.sum(F.col("amount")).alias("sum_amount"),  # LANSH-DEFECT: T05-D4 duplicate staged payment rows are each summed
            F.max(F.col("payment_date")).alias("last_pay"),
        )
    )

    aging = (
        open_claims.alias("o")
        .join(pay_agg.alias("a"), F.col("a.claim_id") == F.col("o.claim_id"), "left")
        .select(
            F.col("o.claim_id").alias("claim_id"),
            F.col("o.claim_number").alias("claim_number"),
            F.col("o.lob_code").alias("lob_code"),
            F.col("o.reported_date").alias("reported_date"),
            F.col("a.n_pay").alias("n_pay"),
            F.col("a.n_null_amount").alias("n_null_amount"),
            F.col("a.sum_amount").alias("sum_amount"),
            F.col("a.last_pay").alias("last_pay"),
        )
    )

    # Claims with no payments: @n_pay = 0, @total = 0, @last_pay = NULL (lines 114-116).
    n_payments = F.coalesce(F.col("n_pay"), F.lit(0)).cast(T.IntegerType())
    total_paid = (
        F.when(F.col("n_pay").isNull(), F.lit(0).cast(T.DecimalType(14, 2)))
        .when(F.col("n_null_amount") > 0, F.lit(None).cast(T.DecimalType(14, 2)))  # LANSH-DEFECT: T05-D3 one NULL amount makes total_paid NULL
        .otherwise(F.col("sum_amount").cast(T.DecimalType(14, 2)))
    )

    # SET @last_act = ISNULL(@last_pay, @reported)
    last_act = F.coalesce(F.col("last_pay"), F.col("reported_date"))

    # TSQL-04: DATEDIFF(DAY, @last_act, @AsOfDate) -> datediff(end, start)
    days = F.datediff(as_of, F.col("last_activity_date"))

    # TSQL-04: DATEDIFF(WEEK, @reported, @AsOfDate) counts Sundays crossed:
    # difference of Sunday-anchored week numbers.
    sunday_anchor = F.lit(datetime.date.fromisoformat("1899-12-31"))
    weeks = (
        F.floor(F.datediff(as_of, sunday_anchor) / F.lit(7))
        - F.floor(F.datediff(F.col("reported_date"), sunday_anchor) / F.lit(7))
    ).cast(T.IntegerType())  # LANSH-DEFECT: T05-D2 weeks_open counts week boundaries, not elapsed weeks

    d = F.col("days_since_activity")
    band = (
        F.when(d < 30, F.lit("0-29"))
        .when(d.between(31, 60), F.lit("31-60"))  # LANSH-DEFECT: T05-D1 30 days matches no band and falls to UNKNOWN
        .when(d > 60, F.lit("61+"))
        .otherwise(F.lit("UNKNOWN"))  # LANSH-DEFECT: T05-D1 30 days gets UNKNOWN
    )

    result = (
        aging
        .withColumn("n_payments", n_payments)
        .withColumn("total_paid", total_paid)
        .withColumn("last_payment_date", F.col("last_pay"))
        .withColumn("last_activity_date", last_act)
        .withColumn("days_since_activity", days.cast(T.IntegerType()))
        .withColumn("weeks_open", weeks)
        .withColumn("aging_band", band)
        .withColumn("as_of_date", as_of)
        .select(
            "claim_id", "claim_number", "lob_code", "reported_date",
            "n_payments", "total_paid", "last_payment_date", "last_activity_date",
            "days_since_activity", "weeks_open", "aging_band", "as_of_date",
        )
    )

    return {"rpt.claim_aging": result}
```
</details>

