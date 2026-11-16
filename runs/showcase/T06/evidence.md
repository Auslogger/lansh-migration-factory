# Evidence report: T06

Generated 2026-11-12 02:17 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T06_usp_loss_triangle.sql` (SHA-256 `cee60f041de5a268…`)
- Migrated module: `runs/showcase/T06/jobs/t06.py` (SHA-256 `beffffb768446238…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 5 (TSQL-04, TSQL-13, TSQL-17)
- Suspected defects: 4; tests: 1/1 passed; heal attempts: 0
- Claude: 6 calls (0 live), 48,698 input and 24,600 output tokens, $0.81 API-equivalent (not billed), 200 s of model time

## Gate decisions

**Human review: completed and accepted after the run.** The team confirmed review of all recorded gate decisions on 2026-11-16. [Review confirmation](../human_review.json) is pinned to the original gate log. Original agent timings are separate from the later human review.

| Gate | Human acceptance | Reviewer | Review scope | Human reason |
|---|---|---|---|---|
| H1 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Scope, source code, lineage and trap findings | Team confirmed acceptance; original individual rationale not recorded |
| H2 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Contract, comparison policies, defect decisions and protected-column flows | Team confirmed acceptance; original individual rationale not recorded |
| H3 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Generated code, literal guardrails and trap-test results | Team confirmed acceptance; original individual rationale not recorded |
| H4 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Record-level reconciliation, differences, totals and reported outcome | Team confirmed acceptance; original individual rationale not recorded |
| H5 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Wave cut-over, Delta reconciliation, upstream dependencies and SLA evidence | Team confirmed acceptance; original individual rationale not recorded |

### Original automated run recordings

| Gate | Outcome | Original recorder | Recorded interval | Recording flags | Original recording note |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: - Rows: the output has one row per (accident_year, lob_code) group that has at least one qualifying payment. The INNER JOIN to stg.claim_pa |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T06-D1 suspected defect: Same-day payments (payment_date = loss_date) dropped (19 rows); T06-D2 suspected defect: lob_code only right-trimmed; leading spaces split LOB groups (0 rows); T06-D3 suspected defect: Duplicate |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: - Pivot sums come from decimal(12,2) amounts. Spark gives decimal(22,2) and T-SQL gives decimal(38,2); both are exact. dev_n is cast to decima |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.loss_triangle_paid: MATCH

MATCH: all 21 rows agree record for record, compared on the keys ['accident_year', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 21 | 21 | ok |
| Total of `accident_year` | 42462 | 42462 | ok |
| Total of `dev_0` | 7882235.07 | 7882235.07 | ok |
| Total of `dev_1` | 3393699.94 | 3393699.94 | ok |
| Total of `dev_2` | 292335.67 | 292335.67 | ok |
| Total of `dev_3` | 45795.45 | 45795.45 | ok |
| Total of `dev_4` | 9880.56 | 9880.56 | ok |
| Total of `dev_5` | 10353.73 | 10353.73 | ok |
| Total of `dev_6` | 2718.43 | 2718.43 | ok |
| Total of `cumulative_0` | 7882235.07 | 7882235.07 | ok |
| Total of `cumulative_1` | 7559842.22 | 7559842.22 | ok |
| Total of `cumulative_2` | 5073529.77 | 5073529.77 | ok |
| Total of `cumulative_3` | 3157882.77 | 3157882.77 | ok |
| Total of `cumulative_4` | 1692178.97 | 1692178.97 | ok |
| Total of `cumulative_5` | 676988.77 | 676988.77 | ok |
| Total of `cumulative_6` | 95788.47 | 95788.47 | ok |
| Records matched | | | 21 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `799c270f0307` | `799c270f0307` | identical |

Keys: ['accident_year', 'lob_code'].

## Operate (Delta lakehouse, reconciled again)

### rpt.loss_triangle_paid: MATCH

MATCH: all 21 rows agree record for record, compared on the keys ['accident_year', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 21 | 21 | ok |
| Total of `accident_year` | 42462 | 42462 | ok |
| Total of `dev_0` | 7882235.07 | 7882235.07 | ok |
| Total of `dev_1` | 3393699.94 | 3393699.94 | ok |
| Total of `dev_2` | 292335.67 | 292335.67 | ok |
| Total of `dev_3` | 45795.45 | 45795.45 | ok |
| Total of `dev_4` | 9880.56 | 9880.56 | ok |
| Total of `dev_5` | 10353.73 | 10353.73 | ok |
| Total of `dev_6` | 2718.43 | 2718.43 | ok |
| Total of `cumulative_0` | 7882235.07 | 7882235.07 | ok |
| Total of `cumulative_1` | 7559842.22 | 7559842.22 | ok |
| Total of `cumulative_2` | 5073529.77 | 5073529.77 | ok |
| Total of `cumulative_3` | 3157882.77 | 3157882.77 | ok |
| Total of `cumulative_4` | 1692178.97 | 1692178.97 | ok |
| Total of `cumulative_5` | 676988.77 | 676988.77 | ok |
| Total of `cumulative_6` | 95788.47 | 95788.47 | ok |
| Records matched | | | 21 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `799c270f0307` | `799c270f0307` | identical |

Keys: ['accident_year', 'lob_code'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T06-D1 | Same-day payments (payment_date = loss_date) dropped | 13-93 | 19 | 390467.67 | reproduce (agent:lansh-dev) |
| T06-D2 | lob_code only right-trimmed; leading spaces split LOB groups | 18-67 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T06-D3 | Duplicate claim rows in staging multiply payments | 64-91 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T06-D4 | Accident year / LOB with claims but no payments missing from triangle | 105-137 | 0 |  | reproduce (agent:lansh-dev) |

## Contract

`gold.loss_triangle_paid` (gold), from `rpt.loss_triangle_paid`. Grain: One row per accident year and line of business: the paid loss development triangle as at the run's as-of date.
Key: ['accident_year', 'lob_code']; partitions: none.
Every column is compared exactly.

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-13 | 62-68 | llm | 0.90 | The #claims temp table holds the filtered claims with accident_year and the normalised lob_code. In Spark it becomes an intermediate DataFrame. |
| TSQL-13 | 80-88 | llm | 0.90 | The #paid temp table holds the payments joined to claims, with their dev_year. In Spark it becomes an intermediate DataFrame. |
| TSQL-04 | 86-86 | llm | 0.95 | dev_year counts the calendar-year boundaries crossed between loss_date and payment_date, not the full years elapsed. A loss on 2023-12-31 paid on 2024-01-01 lands in dev_1. Spark needs year(payment_da |
| TSQL-13 | 103-109 | llm | 0.90 | The #tri temp table holds the pivoted triangle before the insert. In Spark it becomes an intermediate DataFrame. |
| TSQL-17 | 110-112 | llm | 0.95 | The PIVOT implicitly groups by accident_year and lob_code and keeps only dev_year 0-6, so payments in dev years above 6 are dropped. Spark needs groupBy('accident_year','lob_code').pivot('dev_year',[0 |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| accident_year | stg.claims.loss_date | - |
| lob_code | stg.claims.lob_code | - |
| as_of_date | parameter @AsOfDate | - |
| dev_0 | constant, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_1 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_2 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_3 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_4 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_5 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| dev_6 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_0 | constant, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_1 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_2 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_3 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_4 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_5 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |
| cumulative_6 | constant, parameter @AsOfDate, stg.claim_payments.amount, stg.claim_payments.payment_date, stg.claims.loss_date | - |

Rows are decided by: stg.claim_payments.amount, stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claims.claim_id, stg.claims.loss_date.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T06-TSQL-04-1 | TSQL-04 | legacy_engine | pass | Payments that cross a calendar-year boundary after less than a full year has passed since the loss. For example, a loss on 2023-12-31 paid on 2024-01-01, a loss on 2022-12-15 paid on 2023-06-10, a los |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 452 | 7 s | $0.046 |
| defect_reviewer | 1 | 0 | 5,062 | 45 s | $0.143 |
| lineage | 1 | 0 | 10,524 | 73 s | $0.253 |
| test_author | 1 | 0 | 2,067 | 17 s | $0.083 |
| translator | 1 | 0 | 5,007 | 42 s | $0.179 |
| trap_scan | 1 | 0 | 1,488 | 15 s | $0.107 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : rpt.usp_loss_triangle
  Purpose  : Paid loss development triangle for the actuarial reserving team.
             One row per accident year and line of business, with the amount
             paid in each development year (dev_0 .. dev_6) and the cumulative
             paid to date (cumulative_0 .. cumulative_6) as at @AsOfDate. Feeds
             the chain-ladder workbook for the quarterly reserving review.
  Author   : CNM

  Change log
    2019-04-08  CNM   Initial version (CR-0862)
    2019-10-21  CNM   Travel added to the triangle (CR-0947)
    2020-09-14  PD    Payments keyed with a date before the loss left out
                      (INC-2318)
    2021-02-01  PD    Unkeyed payments (NULL amount) left out
    2022-01-17  EOS   Seven accident years. Cells after the as-at date now NULL
                      instead of 0, as the workbook expects (CR-1405)
    2023-06-26  EOS   lob_code trimmed and upper-cased before grouping
                      (INC-2851)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.loss_triangle_paid', N'U') IS NULL
CREATE TABLE rpt.loss_triangle_paid (
    accident_year  INT            NOT NULL,
    lob_code       VARCHAR(5)     NOT NULL,
    dev_0          DECIMAL(14,2)  NULL,
    dev_1          DECIMAL(14,2)  NULL,
    dev_2          DECIMAL(14,2)  NULL,
    dev_3          DECIMAL(14,2)  NULL,
    dev_4          DECIMAL(14,2)  NULL,
    dev_5          DECIMAL(14,2)  NULL,
    dev_6          DECIMAL(14,2)  NULL,
    cumulative_0   DECIMAL(14,2)  NULL,
    cumulative_1   DECIMAL(14,2)  NULL,
    cumulative_2   DECIMAL(14,2)  NULL,
    cumulative_3   DECIMAL(14,2)  NULL,
    cumulative_4   DECIMAL(14,2)  NULL,
    cumulative_5   DECIMAL(14,2)  NULL,
    cumulative_6   DECIMAL(14,2)  NULL,
    as_of_date     DATE           NOT NULL,
    CONSTRAINT pk_loss_triangle_paid PRIMARY KEY (accident_year, lob_code)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_loss_triangle
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name VARCHAR(128) = 'rpt.usp_loss_triangle',
            @as_at_yr INT          = YEAR(@AsOfDate),
            @rows     INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Start',
             @status = 'STARTED';

        ------------------------------------------------------------------
        -- 1. Claims with a loss in the last seven accident years
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#claims') IS NOT NULL DROP TABLE #claims;

        SELECT c.claim_id,
               c.loss_date,
               YEAR(c.loss_date)        AS accident_year,
               UPPER(RTRIM(c.lob_code)) AS lob_code
        INTO   #claims
        FROM   stg.claims AS c WITH (NOLOCK)
        WHERE  YEAR(c.loss_date) BETWEEN @as_at_yr - 6 AND @as_at_yr
          AND  c.loss_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Load #claims',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 2. Payments to the as-at date, with their development year
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#paid') IS NOT NULL DROP TABLE #paid;

        SELECT cl.claim_id,
               p.payment_id,
               cl.accident_year,
               cl.lob_code,
               DATEDIFF(YEAR, cl.loss_date, p.payment_date) AS dev_year,
               p.amount
        INTO   #paid
        FROM   #claims AS cl
        INNER JOIN stg.claim_payments AS p WITH (NOLOCK)
                ON p.claim_id = cl.claim_id
        WHERE  p.payment_date <= @AsOfDate
          AND  p.payment_date >  cl.loss_date   -- dated before the loss = keying error
          AND  p.amount IS NOT NULL;            -- not keyed yet

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Load #paid',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 3. One column per development year
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#tri') IS NOT NULL DROP TABLE #tri;

        SELECT pv.accident_year,
               pv.lob_code,
               pv.[0] AS d0, pv.[1] AS d1, pv.[2] AS d2, pv.[3] AS d3,
               pv.[4] AS d4, pv.[5] AS d5, pv.[6] AS d6
        INTO   #tri
        FROM  (SELECT accident_year, lob_code, dev_year, amount
               FROM   #paid) AS src
        PIVOT (SUM(amount) FOR dev_year IN ([0], [1], [2], [3], [4], [5], [6])) AS pv;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Pivot #tri',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 4. Reload the triangle. Nothing paid yet = 0; a cell after the
        --    as-at date stays NULL.
        ------------------------------------------------------------------
        TRUNCATE TABLE rpt.loss_triangle_paid;

        INSERT INTO rpt.loss_triangle_paid
               (accident_year, lob_code, dev_0, dev_1, dev_2, dev_3, dev_4, dev_5, dev_6,
                as_of_date)
        SELECT t.accident_year,
               t.lob_code,
               ISNULL(t.d0, 0),
               CASE WHEN t.accident_year + 1 <= @as_at_yr THEN ISNULL(t.d1, 0) END,
               CASE WHEN t.accident_year + 2 <= @as_at_yr THEN ISNULL(t.d2, 0) END,
               CASE WHEN t.accident_year + 3 <= @as_at_yr THEN ISNULL(t.d3, 0) END,
               CASE WHEN t.accident_year + 4 <= @as_at_yr THEN ISNULL(t.d4, 0) END,
               CASE WHEN t.accident_year + 5 <= @as_at_yr THEN ISNULL(t.d5, 0) END,
               CASE WHEN t.accident_year + 6 <= @as_at_yr THEN ISNULL(t.d6, 0) END,
               @AsOfDate
        FROM   #tri AS t;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Insert rpt.loss_triangle_paid',
             @status = 'INFO', @rows_affected = @rows;

        -- cumulative paid (NULL after the as-at date, same as dev_n)
        UPDATE rpt.loss_triangle_paid
           SET cumulative_0 = dev_0,
               cumulative_1 = dev_0 + dev_1,
               cumulative_2 = dev_0 + dev_1 + dev_2,
               cumulative_3 = dev_0 + dev_1 + dev_2 + dev_3,
               cumulative_4 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4,
               cumulative_5 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4 + dev_5,
               cumulative_6 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4 + dev_5 + dev_6;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Cumulative paid',
             @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'End',
             @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        DECLARE @err_msg NVARCHAR(4000) = ERROR_MESSAGE(),
                @err_no  INT            = ERROR_NUMBER();

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Error',
             @status = 'FAILED', @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH;
END;
GO
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""T06 usp_loss_triangle: migrated from estate/tsql/T06_usp_loss_triangle.sql.

Legacy SHA-256: cee60f041de5a268d53d966f273fdde67f2a7710f57427e91412a791d568b613
Written by: LANSH translator (Claude)
Traps handled: TSQL-13, TSQL-04, TSQL-17
Bugs reproduced on purpose (# LANSH-DEFECT): T06-D1 same-day payments dropped; T06-D2 lob_code only right-trimmed; T06-D3 duplicate claim rows multiply payments; T06-D4 accident year/LOB with no payments missing
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
import pyspark.sql.functions as F
import pyspark.sql.types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_at_yr = as_of.year
    as_of_lit = F.lit(as_of)

    claims_src = inputs["stg.claims"]
    payments_src = inputs["stg.claim_payments"]

    # ------------------------------------------------------------------
    # 1. #claims (TSQL-13): claims with a loss in the last seven accident years
    # ------------------------------------------------------------------
    claims = (
        claims_src  # LANSH-DEFECT: T06-D3 no dedup by claim_id; duplicate staging rows are all kept
        .where(
            F.year("loss_date").between(as_at_yr - 6, as_at_yr)
            & (F.col("loss_date") <= as_of_lit)
        )
        .select(
            F.col("claim_id"),
            F.col("loss_date"),
            F.year("loss_date").alias("accident_year"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),  # LANSH-DEFECT: T06-D2 RTRIM only; leading spaces split LOB groups
        )
    )

    # ------------------------------------------------------------------
    # 2. #paid (TSQL-13): payments to the as-at date with their dev year
    # ------------------------------------------------------------------
    p = payments_src.alias("p")
    cl = claims.alias("cl")
    paid = (
        cl.join(p, F.col("p.claim_id") == F.col("cl.claim_id"), "inner")  # LANSH-DEFECT: T06-D3 each payment joins every copy of its claim
        .where(
            (F.col("p.payment_date") <= as_of_lit)
            & (F.col("p.payment_date") > F.col("cl.loss_date"))  # LANSH-DEFECT: T06-D1 same-day payments (payment_date = loss_date) dropped
            & F.col("p.amount").isNotNull()
        )
        .select(
            F.col("cl.claim_id").alias("claim_id"),
            F.col("p.payment_id").alias("payment_id"),
            F.col("cl.accident_year").alias("accident_year"),
            F.col("cl.lob_code").alias("lob_code"),
            # TSQL-04: DATEDIFF(YEAR, loss_date, payment_date) counts calendar-year boundaries
            (F.year(F.col("p.payment_date")) - F.year(F.col("cl.loss_date"))).alias("dev_year"),
            F.col("p.amount").alias("amount"),
        )
    )

    # ------------------------------------------------------------------
    # 3. #tri (TSQL-13, TSQL-17): PIVOT grouped by accident_year, lob_code
    # ------------------------------------------------------------------
    tri = (
        paid.select("accident_year", "lob_code", "dev_year", "amount")
        .groupBy("accident_year", "lob_code")  # LANSH-DEFECT: T06-D4 triangle built from #paid only; groups with no payments get no row
        .pivot("dev_year", [0, 1, 2, 3, 4, 5, 6])
        .agg(F.sum("amount"))
        .select(
            F.col("accident_year"),
            F.col("lob_code"),
            F.col("0").alias("d0"),
            F.col("1").alias("d1"),
            F.col("2").alias("d2"),
            F.col("3").alias("d3"),
            F.col("4").alias("d4"),
            F.col("5").alias("d5"),
            F.col("6").alias("d6"),
        )
    )

    # ------------------------------------------------------------------
    # 4. Insert: ISNULL(d0, 0); dev_n NULL after the as-at year
    # ------------------------------------------------------------------
    dec = T.DecimalType(14, 2)

    def dev_cell(n: int):
        if n == 0:
            expr = F.coalesce(F.col("d0"), F.lit(0))
        else:
            expr = F.when(
                (F.col("accident_year") + n) <= F.lit(as_at_yr),
                F.coalesce(F.col("d" + str(n)), F.lit(0)),
            )
        # stored into DECIMAL(14,2) by the INSERT
        return expr.cast(dec).alias("dev_" + str(n))

    inserted = tri.select(
        F.col("accident_year"),
        F.col("lob_code"),
        *[dev_cell(n) for n in range(7)],
        as_of_lit.alias("as_of_date"),
    )

    # UPDATE: cumulative_n = dev_0 + ... + dev_n (NULL propagates)
    cum_cols = []
    for n in range(7):
        expr = F.col("dev_0")
        for k in range(1, n + 1):
            expr = expr + F.col("dev_" + str(k))
        cum_cols.append(expr.alias("cumulative_" + str(n)))

    result = inserted.select(
        F.col("accident_year"),
        F.col("lob_code"),
        *[F.col("dev_" + str(n)) for n in range(7)],
        *cum_cols,
        F.col("as_of_date"),
    )

    return {"rpt.loss_triangle_paid": result}
```
</details>

