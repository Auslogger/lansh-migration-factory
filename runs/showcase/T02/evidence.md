# Evidence report: T02

Generated 2026-11-12 02:19 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T02_usp_load_dim_policy.sql` (SHA-256 `a9565f4f944b98bb…`)
- Migrated module: `runs/showcase/T02/jobs/t02.py` (SHA-256 `fc399a765138ecb7…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 19 (TSQL-01, TSQL-02, TSQL-06, TSQL-11, TSQL-13)
- Suspected defects: 5; tests: 3/3 passed; heal attempts: 0
- Claude: 6 calls (0 live), 56,086 input and 38,053 output tokens, $1.15 API-equivalent (not billed), 313 s of model time

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
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: flagged: 2 statements sqlglot can't parse (lines 82-83, 118-119); the translator works from the code itself; lineage agent notes: dw.dim_policy is both an input and the output: the job never truncates it. The MERGE clos |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: exclude on dw.dim_policy.load_ts: volatile audit column (estate/jobs.yaml): it changes on every run; T02-D1 suspected defect: Row-multiplying joins / duplicate snapshot rows create duplicate current versions (0 rows); T |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: Points for the reviewer:  1. load_ts: the legacy uses SYSDATETIME(); I use F.localtimestamp(). It is one constant per run, but it can never ma |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### dw.dim_policy: MATCH

MATCH: all 69,255 rows agree record for record, compared on the keys ['policy_id', 'valid_from']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 69,255 | 69,255 | ok |
| Total of `policy_sk` | 2398162140 | 2398162140 | ok |
| Total of `policy_id` | 36758184230 | 36758184230 | ok |
| Total of `customer_id` | 7621764273 | 7621764273 | ok |
| Total of `annual_premium` | 27889452.79 | 27889452.79 | ok |
| Total of `ncd_years` | 174050 | 174050 | ok |
| Records matched | | | 69,255 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `47805914e073` | `47805914e073` | identical |

Keys: ['policy_id', 'valid_from'].

## Operate (Delta lakehouse, reconciled again)

### dw.dim_policy: MATCH

MATCH: all 69,255 rows agree record for record, compared on the keys ['policy_id', 'valid_from']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 69,255 | 69,255 | ok |
| Total of `policy_sk` | 2398162140 | 2398162140 | ok |
| Total of `policy_id` | 36758184230 | 36758184230 | ok |
| Total of `customer_id` | 7621764273 | 7621764273 | ok |
| Total of `annual_premium` | 27889452.79 | 27889452.79 | ok |
| Total of `ncd_years` | 174050 | 174050 | ok |
| Records matched | | | 69,255 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `47805914e073` | `47805914e073` | identical |

Keys: ['policy_id', 'valid_from'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T02-D1 | Row-multiplying joins / duplicate snapshot rows create duplicate current versions | 88-160 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T02-D2 | Policies missing from a later snapshot are never closed | 127-137 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T02-D3 | Inner join to stg.products silently drops policies with an unknown product | 106-108 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| T02-D4 | Direct business never gets a broker name | 95-110 | 0 |  | reproduce (agent:lansh-dev) |
| T02-M5 | ISNULL takes VARCHAR(10) of p.broker_code, so 'DIRECT-SALES' becomes 'DIRECT-SAL' |  | not measured |  | reproduce (agent:lansh-dev) |

## Contract

`silver.dim_policy` (silver), from `dw.dim_policy`. Grain: One row per version of a policy (type-2 history): a policy's attributes as they stood from valid_from until valid_to, with a new version opened whenever status, broker, annual premium or vehicle registration changes between snapshots.
Key: ['policy_id', 'valid_from']; partitions: ['lob_code', 'is_current'].
| Column | Policy | Reason |
|---|---|---|
| load_ts | exclude | volatile audit column (estate/jobs.yaml): it changes on every run |

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-02 | 37-37 | llm | 0.45 | customer_segment is CHAR(4), copied from CHAR(4) segment_code, so legacy values are padded to 4 characters. Spark strings never pad, so shorter codes come out without trailing spaces. |
| TSQL-13 | 85-105 | llm | 0.90 | The #src temp table holds the snapshot batch. In Spark it becomes a DataFrame or a temporary view. |
| TSQL-06 | 95-95 | llm | 0.95 | ISNULL takes the type of p.broker_code, which is VARCHAR(10), so 'DIRECT-SALES' (12 chars) is cut to 'DIRECT-SAL'. A Spark coalesce would write the full literal. |
| TSQL-01 | 107-108 | llm | 0.60 | The product join compares VARCHAR product_code values case-insensitively, so case variants still match. A Spark join drops them, and with them the policy row, because this is an inner join. |
| TSQL-02 | 107-108 | llm | 0.50 | The product_code join ignores trailing spaces. In Spark, a code with trailing spaces fails the inner join and the policy is lost. |
| TSQL-01 | 109-110 | llm | 0.60 | The broker join on text matches case variants under the CI collation. A Spark binary join misses them, so broker_name is NULL. |
| TSQL-02 | 109-110 | llm | 0.85 | stg.brokers.broker_code is CHAR(6) and gets padded, while policy broker_code is VARCHAR(10). SQL Server ignores the padding when matching. In Spark the padded values do not match, so broker_name becom |
| TSQL-11 | 127-137 | llm | 0.95 | This MERGE closes the current version of changed policies (valid_to = snapshot - 1, is_current = 'N'). Spark has to rebuild the whole dimension from its previous state and the batch. |
| TSQL-01 | 131-131 | llm | 0.75 | The status <> check is case-insensitive, so a change of letter case only (e.g. 'Active' to 'ACTIVE') opens no new version in legacy. Spark would open one. |
| TSQL-02 | 131-131 | llm | 0.60 | The status <> check ignores trailing spaces, so a change in trailing spaces alone does not close the version in legacy. |
| TSQL-06 | 131-131 | llm | 0.40 | The status change check uses ISNULL(..., ''), so a NULL status and '' count as equal and no new version opens. |
| TSQL-01 | 132-132 | llm | 0.70 | The broker_code <> check is case-insensitive, so a broker code that changes only in letter case does not trigger a new version in legacy. |
| TSQL-02 | 132-132 | llm | 0.55 | The broker_code <> check ignores trailing spaces, so a code that differs only by trailing spaces does not count as a change. |
| TSQL-06 | 132-132 | llm | 0.40 | The broker_code change check treats NULL and '' as the same value. Also, the source side has already been truncated to 'DIRECT-SAL' by the ISNULL at line 95, and Spark must compare against that trunca |
| TSQL-06 | 133-133 | llm | 0.45 | ISNULL(annual_premium, 0) treats a NULL premium and 0 as equal, so that difference opens no new version. |
| TSQL-01 | 134-134 | llm | 0.75 | The vehicle_reg <> check is case-insensitive, so a registration that changes only in case ('ab12cde' to 'AB12CDE') is not a change in legacy. |
| TSQL-02 | 134-134 | llm | 0.60 | The vehicle_reg <> check ignores trailing spaces, so a registration with added trailing spaces is not seen as changed. |
| TSQL-06 | 134-134 | llm | 0.80 | vehicle_reg is nullable. ISNULL(..., '') makes NULL and '' equal, so moving between NULL and empty opens no new version. Spark null-safe comparisons would treat it as a change. |
| TSQL-11 | 142-161 | llm | 0.90 | The insert opens new current versions. The IDENTITY key policy_sk is assigned in policy_id order, continuing from the table's highest existing value, and Spark must reproduce that. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| policy_sk | generated | - |
| policy_id | stg.policy_snapshots.policy_id | yes |
| policy_number | stg.policy_snapshots.policy_number | yes |
| customer_id | stg.policy_snapshots.customer_id | yes |
| customer_segment | dw.dim_customer.segment_code | yes |
| product_code | stg.products.product_code | yes |
| product_name | stg.products.product_name | yes |
| lob_code | stg.products.lob_code | yes |
| broker_code | constant, stg.policy_snapshots.broker_code | yes |
| broker_name | stg.brokers.broker_name | yes |
| status | stg.policy_snapshots.status | yes |
| inception_date | stg.policy_snapshots.inception_date | yes |
| expiry_date | stg.policy_snapshots.expiry_date | yes |
| cancellation_date | stg.policy_snapshots.cancellation_date | yes |
| annual_premium | stg.policy_snapshots.annual_premium | yes |
| currency | stg.policy_snapshots.currency | yes |
| vehicle_reg | stg.policy_snapshots.vehicle_reg | yes |
| ncd_years | stg.policy_snapshots.ncd_years | yes |
| valid_from | parameter @SnapshotDate | yes |
| valid_to | constant, parameter @SnapshotDate | yes |
| is_current | constant | yes |
| source_snapshot_date | parameter @SnapshotDate | yes |
| load_ts | generated | yes |

Rows are decided by: dw.dim_customer.customer_id, dw.dim_policy.annual_premium, dw.dim_policy.broker_code, dw.dim_policy.is_current, dw.dim_policy.policy_id, dw.dim_policy.source_snapshot_date, dw.dim_policy.status, dw.dim_policy.vehicle_reg, stg.brokers.broker_code, stg.policy_snapshots.annual_premium, stg.policy_snapshots.broker_code, stg.policy_snapshots.customer_id, stg.policy_snapshots.policy_id, stg.policy_snapshots.product_code, stg.policy_snapshots.snapshot_date, stg.policy_snapshots.status, stg.policy_snapshots.vehicle_reg, stg.products.product_code.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T02-TSQL-01-1 | TSQL-01 | legacy_engine | pass | Letter-case variants across two runs (2025-06-30, then 2025-12-31). Policy 1001 has product_code 'motor01' and the product register has 'MOTOR01'. The legacy inner join still matches it; a binary Spar |
| T02-TSQL-02-2 | TSQL-02 | legacy_engine | pass | Trailing spaces and CHAR padding across two runs. Policy 2001 has product_code 'MOTOR01 ' with a trailing space. The legacy inner join keeps it; Spark drops the policy. Its broker 'BRK1' matches the C |
| T02-TSQL-06-3 | TSQL-06 | legacy_engine | pass | ISNULL behaviour across two runs. Policies 3001 and 3004 (run 1) and 3005 (new in run 2) have a NULL broker_code. ISNULL takes the VARCHAR(10) type of p.broker_code, so legacy stores 'DIRECT-SAL'; a S |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 606 | 7 s | $0.051 |
| defect_reviewer | 1 | 0 | 5,237 | 50 s | $0.150 |
| lineage | 1 | 0 | 5,769 | 43 s | $0.164 |
| test_author | 1 | 0 | 11,020 | 79 s | $0.282 |
| translator | 1 | 0 | 12,179 | 104 s | $0.355 |
| trap_scan | 1 | 0 | 3,242 | 29 s | $0.146 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : dw.usp_load_dim_policy
  Purpose  : Policy dimension for finance, actuarial and broker reporting. One
             row per version of a policy term, with its product, broker and
             customer segment. A new version starts whenever the status,
             broker, annual premium or vehicle registration changes from one
             policy snapshot to the next (type 2 history).
  Run by   : POL_SNAPSHOT_LOAD, once per policy snapshot, oldest first:
             EXEC dw.usp_load_dim_policy @SnapshotDate = '<snapshot date>'
  Output   : dw.dim_policy. Keeps history, so the procedure never truncates
             it. Deploying this script recreates the table empty: reload every
             snapshot in date order afterwards.
  Author   : MOB

  Change log
    2014-02-10  MOB   Initial version, one row per policy (CR-0655)
    2015-06-22  MOB   Broker name from the broker register (CR-0790)
    2016-09-05  TF    Direct business reported as broker DIRECT-SALES (CR-0961)
    2017-03-13  TF    Type 2 history with MERGE, surrogate key policy_sk
                      (CR-1077)
    2018-10-01  PH    Vehicle registration tracked for motor (CR-1388)
    2019-07-15  PH    Customer segment from dw.dim_customer (CR-1610)
    2020-02-03  TF    Refuse a snapshot older than the last one loaded
                      (INC-2105)
    2021-06-14  KB    Logging through etl.usp_log_step (CR-2003)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.dim_policy', N'U') IS NOT NULL
    DROP TABLE dw.dim_policy;

CREATE TABLE dw.dim_policy (
    policy_sk             INT IDENTITY(1,1) NOT NULL,
    policy_id             INT            NOT NULL,
    policy_number         VARCHAR(20)    NOT NULL,
    customer_id           INT            NOT NULL,
    customer_segment      CHAR(4)        NULL,
    product_code          VARCHAR(10)    NOT NULL,
    product_name          NVARCHAR(60)   NOT NULL,
    lob_code              VARCHAR(5)     NOT NULL,
    broker_code           VARCHAR(12)    NOT NULL,
    broker_name           NVARCHAR(80)   NULL,
    status                VARCHAR(12)    NOT NULL,
    inception_date        DATE           NOT NULL,
    expiry_date           DATE           NOT NULL,
    cancellation_date     DATE           NULL,
    annual_premium        DECIMAL(12,2)  NOT NULL,
    currency              CHAR(3)        NOT NULL,
    vehicle_reg           VARCHAR(12)    NULL,
    ncd_years             INT            NULL,
    valid_from            DATE           NOT NULL,
    valid_to              DATE           NOT NULL,   -- 9999-12-31 while current
    is_current            CHAR(1)        NOT NULL,   -- Y / N
    source_snapshot_date  DATE           NOT NULL,
    load_ts               DATETIME2(3)   NOT NULL,
    CONSTRAINT pk_dim_policy PRIMARY KEY CLUSTERED (policy_sk)
);

CREATE NONCLUSTERED INDEX ix_dim_policy_policy_id ON dw.dim_policy (policy_id, is_current);
GO
CREATE OR ALTER PROCEDURE dw.usp_load_dim_policy
    @SnapshotDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name     VARCHAR(128) = 'dw.usp_load_dim_policy',
            @rows         INT,
            @closed       INT,
            @last_loaded  DATE,
            @err_msg      NVARCHAR(4000),
            @err_no       INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Oldest snapshot first: loading an older snapshot after a newer one
           would reopen versions that are already closed (INC-2105) */
        SELECT  @last_loaded = MAX(d.source_snapshot_date)
        FROM    dw.dim_policy d;

        IF @SnapshotDate < @last_loaded
            THROW 50001, 'dw.dim_policy already holds a later policy snapshot', 1;

        IF OBJECT_ID('tempdb..#src') IS NOT NULL DROP TABLE #src;

        /* 1. This snapshot's policies with product, broker and customer segment */
        SELECT  p.policy_id,
                p.policy_number,
                p.customer_id,
                c.segment_code                          AS customer_segment,
                pr.product_code,
                pr.product_name,
                pr.lob_code,
                ISNULL(p.broker_code, 'DIRECT-SALES')   AS broker_code,
                b.broker_name,
                p.status,
                p.inception_date,
                p.expiry_date,
                p.cancellation_date,
                p.annual_premium,
                p.currency,
                p.vehicle_reg,
                p.ncd_years
        INTO    #src
        FROM    stg.policy_snapshots p WITH (NOLOCK)
        JOIN    stg.products pr WITH (NOLOCK)
                ON pr.product_code = p.product_code
        LEFT JOIN stg.brokers b WITH (NOLOCK)
               ON b.broker_code = p.broker_code
        LEFT JOIN dw.dim_customer c WITH (NOLOCK)
               ON c.customer_id = p.customer_id
        WHERE   p.snapshot_date = @SnapshotDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'policy snapshot', @status = 'INFO', @rows_affected = @rows;

        IF @rows = 0
            THROW 50002, 'No policies found for this snapshot date', 1;

        CREATE CLUSTERED INDEX ix_src_policy_id ON #src (policy_id);

        BEGIN TRANSACTION;

        /* 2. Close the current version of policies whose status, broker, premium
              or vehicle registration has changed since the last snapshot */
        MERGE dw.dim_policy AS tgt
        USING #src AS src
           ON tgt.policy_id = src.policy_id
          AND tgt.is_current = 'Y'
        WHEN MATCHED AND (   ISNULL(src.status, '')        <> ISNULL(tgt.status, '')
                          OR ISNULL(src.broker_code, '')   <> ISNULL(tgt.broker_code, '')
                          OR ISNULL(src.annual_premium, 0) <> ISNULL(tgt.annual_premium, 0)
                          OR ISNULL(src.vehicle_reg, '')   <> ISNULL(tgt.vehicle_reg, ''))
        THEN UPDATE
             SET    tgt.valid_to   = DATEADD(DAY, -1, @SnapshotDate),
                    tgt.is_current = 'N';

        SET @closed = @@ROWCOUNT;

        /* 3. Open a current version for new policies and for those closed above */
        INSERT INTO dw.dim_policy
               (policy_id, policy_number, customer_id, customer_segment, product_code,
                product_name, lob_code, broker_code, broker_name, status, inception_date,
                expiry_date, cancellation_date, annual_premium, currency, vehicle_reg,
                ncd_years, valid_from, valid_to, is_current, source_snapshot_date, load_ts)
        SELECT  s.policy_id, s.policy_number, s.customer_id, s.customer_segment, s.product_code,
                s.product_name, s.lob_code, s.broker_code, s.broker_name, s.status,
                s.inception_date, s.expiry_date, s.cancellation_date, s.annual_premium,
                s.currency, s.vehicle_reg, s.ncd_years,
                @SnapshotDate,
                '9999-12-31',
                'Y',
                @SnapshotDate,
                SYSDATETIME()
        FROM    #src s
        WHERE   NOT EXISTS (SELECT 1
                            FROM   dw.dim_policy d
                            WHERE  d.policy_id = s.policy_id
                              AND  d.is_current = 'Y')
        ORDER BY s.policy_id;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'versions closed', @status = 'INFO', @rows_affected = @closed;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'versions opened', @status = 'INFO', @rows_affected = @rows;
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
"""T02 usp_load_dim_policy: migrated from estate/tsql/T02_usp_load_dim_policy.sql.

Legacy SHA-256: a9565f4f944b98bb52293b124a852c693d5fad0c7accb5793a9499945f0e2b0f
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-06, TSQL-11, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): T02-D1 duplicate current versions from row-multiplying joins, T02-D2 policies missing from a later snapshot never closed, T02-D3 inner join to stg.products drops unknown products, T02-D4 direct business never gets a broker name, DIRECT-SALES truncated to DIRECT-SAL by ISNULL
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


OUTPUT_COLUMNS = [
    "policy_sk", "policy_id", "policy_number", "customer_id", "customer_segment",
    "product_code", "product_name", "lob_code", "broker_code", "broker_name",
    "status", "inception_date", "expiry_date", "cancellation_date",
    "annual_premium", "currency", "vehicle_reg", "ncd_years", "valid_from",
    "valid_to", "is_current", "source_snapshot_date", "load_ts",
]


def _ci(col):
    """Collation key: case-insensitive, trailing spaces ignored (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    snapshots = inputs["stg.policy_snapshots"]
    products = inputs["stg.products"]
    brokers = inputs["stg.brokers"]
    customers = inputs["dw.dim_customer"]
    prev = inputs["dw.dim_policy"]

    snap_text = params["SnapshotDate"]
    snap_py = datetime.date.fromisoformat(snap_text)
    snap = F.lit(snap_text).cast(T.DateType())

    # Guard: refuse a snapshot older than the last one loaded (INC-2105)
    last_loaded = prev.agg(F.max("source_snapshot_date").alias("m")).first()["m"]
    if last_loaded is not None and snap_py < last_loaded:
        raise RuntimeError("dw.dim_policy already holds a later policy snapshot")

    # 1. #src as a DataFrame (TSQL-13)
    p = snapshots.alias("p")
    pr = products.alias("pr")
    b = brokers.alias("b")
    c = customers.alias("c")
    src = (
        p.where(F.col("p.snapshot_date") == snap)
        # LANSH-DEFECT: T02-D3 inner join silently drops policies whose product is not in stg.products
        .join(pr, _ci(F.col("pr.product_code")) == _ci(F.col("p.product_code")), "inner")
        # LANSH-DEFECT: T02-D4 broker lookup on the original (NULL) broker_code, so direct business has no broker_name
        .join(b, _ci(F.col("b.broker_code")) == _ci(F.col("p.broker_code")), "left")
        # LANSH-DEFECT: T02-D1 nothing makes #src unique per policy_id (duplicate staging / lookup rows multiply)
        .join(c, F.col("c.customer_id") == F.col("p.customer_id"), "left")
        .select(
            F.col("p.policy_id").alias("policy_id"),
            F.col("p.policy_number").alias("policy_number"),
            F.col("p.customer_id").alias("customer_id"),
            F.rpad(F.col("c.segment_code"), 4, " ").alias("customer_segment"),
            F.col("pr.product_code").alias("product_code"),
            F.col("pr.product_name").alias("product_name"),
            F.col("pr.lob_code").alias("lob_code"),
            # LANSH-DEFECT: ISNULL takes VARCHAR(10) of p.broker_code, so 'DIRECT-SALES' becomes 'DIRECT-SAL'
            F.coalesce(F.col("p.broker_code"), F.lit("DIRECT-SALES").substr(1, 10)).alias("broker_code"),
            F.col("b.broker_name").alias("broker_name"),
            F.col("p.status").alias("status"),
            F.col("p.inception_date").alias("inception_date"),
            F.col("p.expiry_date").alias("expiry_date"),
            F.col("p.cancellation_date").alias("cancellation_date"),
            F.col("p.annual_premium").alias("annual_premium"),
            F.col("p.currency").alias("currency"),
            F.col("p.vehicle_reg").alias("vehicle_reg"),
            F.col("p.ncd_years").alias("ncd_years"),
            F.col("p._row_seq").alias("_p_seq"),
            F.col("pr._row_seq").alias("_pr_seq"),
            F.col("b._row_seq").alias("_b_seq"),
        )
    )

    if src.isEmpty():
        raise RuntimeError("No policies found for this snapshot date")

    # 2. MERGE: close changed current versions (TSQL-11)
    tgt_current = prev.where(_ci(F.col("is_current")) == "Y").alias("t")
    s = src.alias("s")

    def _txt_changed(name):
        # ISNULL(src, '') <> ISNULL(tgt, '') under CI collation, trailing spaces ignored
        return _ci(F.coalesce(F.col("s." + name), F.lit(""))) != _ci(F.coalesce(F.col("t." + name), F.lit("")))

    changed_cond = (
        _txt_changed("status")
        | _txt_changed("broker_code")
        | (F.coalesce(F.col("s.annual_premium"), F.lit(0)) != F.coalesce(F.col("t.annual_premium"), F.lit(0)))
        | _txt_changed("vehicle_reg")
    )
    updates = (
        tgt_current.join(s, F.col("t.policy_id") == F.col("s.policy_id"), "inner")
        .where(changed_cond)
        .groupBy(F.col("t.policy_sk").alias("policy_sk"))
        .agg(F.count(F.lit(1)).alias("_n"))
    )
    if not updates.where(F.col("_n") > 1).isEmpty():
        # LANSH-DEFECT: T02-D1 duplicate source rows make the legacy MERGE fail on the same target row
        raise RuntimeError(
            "The MERGE statement attempted to UPDATE or DELETE the same row more than once."
        )

    # LANSH-DEFECT: T02-D2 only WHEN MATCHED: current rows of policies absent from the snapshot stay open
    closed = updates.select("policy_sk", F.lit(True).alias("_closed"))
    prev_after = (
        prev.join(closed, "policy_sk", "left")
        .withColumn("valid_to", F.when(F.col("_closed"), F.date_sub(snap, 1)).otherwise(F.col("valid_to")))
        .withColumn("is_current", F.when(F.col("_closed"), F.lit("N")).otherwise(F.col("is_current")))
        .drop("_closed")
    )

    # 3. INSERT new current versions for policies with no current row (TSQL-11)
    current_ids = prev_after.where(_ci(F.col("is_current")) == "Y").select("policy_id").distinct()
    # LANSH-DEFECT: T02-D1 NOT EXISTS only sees rows already in the table, so every duplicate #src row is opened
    to_open = src.join(current_ids, "policy_id", "left_anti")

    max_sk = prev.agg(F.max("policy_sk").alias("m")).first()["m"]
    if max_sk is None:
        max_sk = 0
    w = Window.orderBy(F.col("policy_id"), F.col("_p_seq"), F.col("_pr_seq"), F.col("_b_seq"))

    new_rows = to_open.select(
        (F.lit(max_sk) + F.row_number().over(w)).cast(T.IntegerType()).alias("policy_sk"),
        "policy_id", "policy_number", "customer_id", "customer_segment",
        "product_code", "product_name", "lob_code", "broker_code", "broker_name",
        "status", "inception_date", "expiry_date", "cancellation_date",
        "annual_premium", "currency", "vehicle_reg", "ncd_years",
        snap.alias("valid_from"),
        F.lit("9999-12-31").cast(T.DateType()).alias("valid_to"),
        F.lit("Y").alias("is_current"),
        snap.alias("source_snapshot_date"),
        F.localtimestamp().cast(T.TimestampNTZType()).alias("load_ts"),
    )

    result = (
        prev_after.select(*OUTPUT_COLUMNS)
        .unionByName(new_rows.select(*OUTPUT_COLUMNS))
        .withColumn("customer_segment", F.rpad(F.col("customer_segment"), 4, " "))
        .withColumn("currency", F.rpad(F.col("currency"), 3, " "))
    )

    return {"dw.dim_policy": result}
```
</details>

