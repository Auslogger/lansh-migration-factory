# Evidence report: T01

Generated 2026-11-12 02:15 UTC. **Status: MATCH.**

- Legacy code: `estate/tsql/T01_usp_load_dim_customer.sql` (SHA-256 `d38c02712a8ae80f…`)
- Migrated module: `runs/showcase/T01/jobs/t01.py` (SHA-256 `cf127dfa3efa1a51…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 24 (TSQL-01, TSQL-02, TSQL-04, TSQL-05, TSQL-13, TSQL-15)
- Suspected defects: 4; tests: 5/5 passed; heal attempts: 0
- Claude: 6 calls (0 live), 52,873 input and 25,971 output tokens, $0.87 API-equivalent (not billed), 247 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: 1) Version pick (lines 101-104): ROW_NUMBER orders by updated_at, _row_seq ascending and keeps version_no = 1. That keeps the OLDEST versio |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: T01-D1 suspected defect: Keeps the oldest CRM version instead of the current one (3224 rows); T01-D2 suspected defect: age_at_join counts calendar-year boundaries, not completed years (8436 rows); T01-D3 suspected defec |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1) Collation emulation: county IN lists, segment_code = 'STD' and the email_shared_count PARTITION BY use upper(rtrim(x)). The IN-list constan |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### dw.dim_customer: MATCH

MATCH: all 20,000 rows agree record for record, compared on the keys ['customer_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 20,000 | 20,000 | ok |
| Total of `customer_id` | 2200010000 | 2200010000 | ok |
| Total of `email_shared_count` | 19336 | 19336 | ok |
| Total of `age_at_join` | 961043 | 961043 | ok |
| Total of `version_count` | 23799 | 23799 | ok |
| Records matched | | | 20,000 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `a0897c3f9194` | `a0897c3f9194` | identical |

Keys: ['customer_id'].

## Operate (Delta lakehouse, reconciled again)

### dw.dim_customer: MATCH

MATCH: all 20,000 rows agree record for record, compared on the keys ['customer_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 20,000 | 20,000 | ok |
| Total of `customer_id` | 2200010000 | 2200010000 | ok |
| Total of `email_shared_count` | 19336 | 19336 | ok |
| Total of `age_at_join` | 961043 | 961043 | ok |
| Total of `version_count` | 23799 | 23799 | ok |
| Records matched | | | 20,000 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `a0897c3f9194` | `a0897c3f9194` | identical |

Keys: ['customer_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| T01-D1 | Keeps the oldest CRM version instead of the current one | 97-104 | 3224 |  | reproduce (agent:lansh-dev) |
| T01-D2 | age_at_join counts calendar-year boundaries, not completed years | 129-129 | 8436 | 8436.00 | reproduce (agent:lansh-dev) |
| T01-D3 | Eircode check accepts any 7-character value, including ones with a misplaced space | 142-145 | 0 |  | reproduce (agent:lansh-dev) |
| T01-D4 | County spelling variants fall into region UNKNOWN | 134-139 | 0 |  | reproduce (agent:lansh-dev) |

## Flows of tagged columns

| Tag | From | Into | Through | Decision |
|---|---|---|---|---|
| pii | stg.customers.address_line1 | dw.dim_customer.address_line1 | T01 | reproduce_accepted |
| pii | stg.customers.date_of_birth | dw.dim_customer.age_at_join | T01 | reproduce_accepted |
| protected | stg.customers.date_of_birth | dw.dim_customer.age_at_join | T01 | reproduce_flagged |
| protected | stg.customers.county | dw.dim_customer.county | T01 | reproduce_flagged |
| pii | stg.customers.date_of_birth | dw.dim_customer.date_of_birth | T01 | reproduce_accepted |
| protected | stg.customers.date_of_birth | dw.dim_customer.date_of_birth | T01 | reproduce_flagged |
| pii | stg.customers.eircode | dw.dim_customer.eircode | T01 | reproduce_accepted |
| pii | stg.customers.eircode | dw.dim_customer.eircode_valid | T01 | reproduce_accepted |
| pii | stg.customers.email | dw.dim_customer.email | T01 | reproduce_accepted |
| pii | stg.customers.email | dw.dim_customer.email_shared_count | T01 | reproduce_accepted |
| pii | stg.customers.first_name | dw.dim_customer.first_name | T01 | reproduce_accepted |
| pii | stg.customers.first_name | dw.dim_customer.full_name | T01 | reproduce_accepted |
| pii | stg.customers.last_name | dw.dim_customer.full_name | T01 | reproduce_accepted |
| pii | stg.customers.first_name | dw.dim_customer.initials | T01 | reproduce_accepted |
| pii | stg.customers.last_name | dw.dim_customer.initials | T01 | reproduce_accepted |
| pii | stg.customers.last_name | dw.dim_customer.last_name | T01 | reproduce_accepted |
| protected | stg.customers.county | dw.dim_customer.region | T01 | reproduce_flagged |
| pii | stg.customers.town | dw.dim_customer.town | T01 | reproduce_accepted |

## Contract

`silver.dim_customer` (silver), from `dw.dim_customer`. Grain: One row per CRM customer (customer_id), taken from one version of the customer's CDC records saved on or before @AsOfDate.
Key: ['customer_id']; partitions: ['region', 'source_system'].
Every column is compared exactly.
Tagged: first_name (pii), last_name (pii), full_name (pii), initials (pii), email (pii), email_shared_count (pii), date_of_birth (pii, protected), age_at_join (pii, protected), address_line1 (pii), town (pii), county (protected), region (protected), eircode (pii), eircode_valid (pii)

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| TSQL-02 | 44-44 | llm | 0.35 | The output segment_code is CHAR(4), so legacy values come back padded to 4 characters. Spark output must keep or add that padding to match exactly. |
| TSQL-13 | 69-70 | llm | 0.70 | These lines drop the #customer_versions and #customer temp tables if they exist. In Spark they become DataFrames, so this code goes away. |
| TSQL-13 | 90-90 | llm | 0.90 | The #customer_versions temp table holds the filtered CRM versions with version_count. In Spark it becomes an intermediate DataFrame. |
| TSQL-13 | 99-99 | llm | 0.90 | The #customer temp table holds one chosen version per customer. In Spark it becomes an intermediate DataFrame. |
| TSQL-05 | 123-123 | llm | 0.60 | full_name is built with + from first_name and last_name. If either is NULL, the legacy result is NULL. The translation must use concat(), which also returns NULL, not concat_ws(), which skips NULLs. T |
| TSQL-05 | 124-124 | llm | 0.40 | The initials are joined with +, so a NULL first or last name makes them NULL. The translation must keep that NULL result. |
| TSQL-15 | 124-124 | llm | 0.95 | SUBSTRING(x, 0, 2) returns only 1 character in T-SQL, so initials are 2 letters. Spark's substring(x, 0, 2) returns 2 characters, which gives 4-letter initials. |
| TSQL-01 | 127-127 | llm | 0.85 | PARTITION BY on the VARCHAR email column groups case variants together under the CI collation, so 'A@x.ie' and 'a@x.ie' count as one shared email. Spark keeps them apart. |
| TSQL-02 | 127-127 | llm | 0.60 | PARTITION BY email also ignores trailing spaces, so 'a@x.ie ' and 'a@x.ie' land in the same partition in SQL Server but not in Spark. |
| TSQL-04 | 129-129 | llm | 0.95 | DATEDIFF(YEAR, ...) counts year boundaries crossed, not full years elapsed. age_at_join must be year(customer_since) - year(date_of_birth), not floor(months_between/12). |
| TSQL-01 | 134-134 | llm | 0.85 | The VARCHAR county is matched with IN against title-case names. SQL Server matches case variants such as 'DUBLIN', but Spark sends them to UNKNOWN. |
| TSQL-02 | 134-134 | llm | 0.70 | The county IN check ignores trailing spaces in SQL Server ('Dublin ' matches). Spark does not. |
| TSQL-01 | 135-135 | llm | 0.85 | The SOUTH county IN list matches case-insensitively in the legacy engine. |
| TSQL-02 | 135-135 | llm | 0.70 | The SOUTH county IN list ignores trailing spaces in the legacy engine. |
| TSQL-01 | 136-136 | llm | 0.85 | The WEST county IN list matches case-insensitively in the legacy engine. |
| TSQL-02 | 136-136 | llm | 0.70 | The WEST county IN list ignores trailing spaces in the legacy engine. |
| TSQL-01 | 137-137 | llm | 0.85 | The NORTH-WEST county IN list matches case-insensitively in the legacy engine. |
| TSQL-02 | 137-137 | llm | 0.70 | The NORTH-WEST county IN list ignores trailing spaces in the legacy engine. |
| TSQL-01 | 138-138 | llm | 0.85 | The MIDLANDS county IN list matches case-insensitively in the legacy engine. |
| TSQL-02 | 138-138 | llm | 0.70 | The MIDLANDS county IN list ignores trailing spaces in the legacy engine. |
| TSQL-15 | 143-143 | llm | 0.85 | LEN(eircode) ignores trailing spaces, so 'D02X285 ' still counts as 7 characters. Spark's length() counts 8 and marks the code invalid. |
| TSQL-15 | 144-144 | llm | 0.80 | LEN(eircode) = 8 ignores trailing spaces. The translation needs rtrim before length() to give the same result. |
| TSQL-01 | 148-148 | llm | 0.80 | segment_code = 'STD' also matches 'std' or 'Std' under the CI collation. Spark's comparison is case-sensitive. |
| TSQL-02 | 148-148 | llm | 0.95 | segment_code is CHAR(4), so it holds 'STD ' padded with a space. SQL Server's = 'STD' ignores the padding, but Spark compares the padded value exactly and gets no match. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| customer_id | stg.customers.customer_id | - |
| first_name | stg.customers.first_name | - |
| last_name | stg.customers.last_name | - |
| full_name | constant, stg.customers.first_name, stg.customers.last_name | - |
| initials | stg.customers.first_name, stg.customers.last_name | - |
| email | stg.customers.email | - |
| email_shared_count | constant, stg.customers.email | - |
| date_of_birth | stg.customers.date_of_birth | - |
| age_at_join | stg.customers.customer_since, stg.customers.date_of_birth | - |
| address_line1 | stg.customers.address_line1 | - |
| town | stg.customers.town | - |
| county | stg.customers.county | - |
| region | constant, stg.customers.county | - |
| eircode | stg.customers.eircode | - |
| eircode_valid | constant, stg.customers.eircode | - |
| segment_code | stg.customers.segment_code | - |
| is_standard_segment | constant, stg.customers.segment_code | - |
| marketing_opt_in | constant, stg.customers.marketing_opt_in | - |
| customer_since | stg.customers.customer_since | - |
| source_system | stg.customers.source_system | - |
| version_count | stg.customers.customer_id | - |
| record_updated_at | stg.customers.updated_at | - |
| as_of_date | parameter @AsOfDate | - |

Rows are decided by: stg.customers.updated_at.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| T01-TSQL-01-1 | TSQL-01 | legacy_engine | pass | County values in the wrong case for every region list (DUBLIN, cork, GALWAY, donegal, LAOIS), a segment_code of 'std', and emails that differ only in case (Mary@x.ie / mary@x.ie / MARY@X.IE). Under th |
| T01-TSQL-02-2 | TSQL-02 | legacy_engine | pass | County values with trailing spaces for every region list ('Dublin ', 'Cork ', 'Mayo ', 'Sligo ', 'Offaly '). Emails that differ only by a trailing space ('pat@x.ie' and 'pat@x.ie '). segment_code valu |
| T01-TSQL-05-3 | TSQL-05 | legacy_engine | pass | Builds full_name and initials with + from first_name and last_name. Both columns are NOT NULL in stg.customers, so a NULL can't be loaded and the NULL case of the trap is latent. The rows cover the ed |
| T01-TSQL-15-4 | TSQL-15 | legacy_engine | pass | Names that give 2-letter initials in T-SQL, because SUBSTRING(x,0,2) returns only the first character. A naive Spark substring(x,0,2) returns 2 characters per name, so it gives 4-letter initials. The  |
| T01-TSQL-04-5 | TSQL-04 | legacy_engine | pass | Birth dates and join dates where counting year boundaries (DATEDIFF YEAR) gives a different age than counting full years elapsed. Examples: born 1990-12-31 and joined 2020-01-01 (boundaries 30, full y |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 761 | 9 s | $0.052 |
| defect_reviewer | 1 | 0 | 4,496 | 56 s | $0.130 |
| lineage | 1 | 0 | 4,820 | 43 s | $0.138 |
| test_author | 1 | 0 | 5,590 | 46 s | $0.167 |
| translator | 1 | 0 | 6,733 | 60 s | $0.231 |
| trap_scan | 1 | 0 | 3,571 | 33 s | $0.153 |

## Code

<details><summary>Legacy code</summary>

```sql
/*==============================================================================
  Job      : dw.usp_load_dim_customer
  Purpose  : Customer dimension for the marketing and pricing teams. One row
             per CRM customer with the customer's current details from the
             CRM extract, plus sales region, Eircode check, initials and
             segment flags for campaigns and the pricing models.
  Output   : dw.dim_customer (truncated and reloaded on every run)
  Author   : DOC

  Change log
    2013-05-20  DOC   Initial version
    2014-11-03  DOC   Sales region from county for the regional reports (CR-0412)
    2015-01-26  DOC   full_name and initials for the mail merge (CR-0538)
    2016-02-18  AMcG  Eircode added, with a format check (CR-0877)
    2017-09-07  AMcG  email_shared_count for the marketing duplicate review
                      (CR-1190)
    2018-05-21  AMcG  Opt-in defaults to N when the customer was never asked
                      (GDPR, CR-1342)
    2019-03-25  SR    age_at_join for the pricing models (CR-1564)
    2019-11-04  KB    CRM extract is now change data capture: one row per
                      saved version, keep the current one (CR-1702)
    2020-10-12  SR    is_standard_segment for the renewal campaign (CR-1841)
    2021-06-14  KB    Logging through etl.usp_log_step (CR-2003)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.dim_customer', N'U') IS NULL
CREATE TABLE dw.dim_customer (
    customer_id          INT            NOT NULL,
    first_name           NVARCHAR(40)   NOT NULL,
    last_name            NVARCHAR(60)   NOT NULL,
    full_name            NVARCHAR(101)  NOT NULL,
    initials             NVARCHAR(2)    NOT NULL,
    email                VARCHAR(120)   NULL,
    email_shared_count   INT            NOT NULL,
    date_of_birth        DATE           NULL,
    age_at_join          INT            NULL,
    address_line1        NVARCHAR(100)  NULL,
    town                 NVARCHAR(50)   NULL,
    county               VARCHAR(30)    NULL,
    region               VARCHAR(12)    NOT NULL,
    eircode              VARCHAR(10)    NULL,
    eircode_valid        CHAR(1)        NOT NULL,
    segment_code         CHAR(4)        NULL,
    is_standard_segment  CHAR(1)        NOT NULL,
    marketing_opt_in     CHAR(1)        NOT NULL,
    customer_since       DATE           NOT NULL,
    source_system        VARCHAR(10)    NOT NULL,
    version_count        INT            NOT NULL,
    record_updated_at    DATETIME2(0)   NOT NULL,
    as_of_date           DATE           NOT NULL,
    CONSTRAINT pk_dim_customer PRIMARY KEY CLUSTERED (customer_id)
);
GO
CREATE OR ALTER PROCEDURE dw.usp_load_dim_customer
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'dw.usp_load_dim_customer',
            @rows      INT,
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        IF OBJECT_ID('tempdb..#customer_versions') IS NOT NULL DROP TABLE #customer_versions;
        IF OBJECT_ID('tempdb..#customer') IS NOT NULL DROP TABLE #customer;

        /* 1. Customer versions saved up to the reporting date. The CRM extract
              writes a new row every time a record is saved. */
        SELECT  c.customer_id,
                c.first_name,
                c.last_name,
                c.email,
                c.date_of_birth,
                c.address_line1,
                c.town,
                c.county,
                c.eircode,
                c.segment_code,
                c.marketing_opt_in,
                c.customer_since,
                c.source_system,
                c.updated_at,
                c._row_seq,
                COUNT(*) OVER (PARTITION BY c.customer_id) AS version_count
        INTO    #customer_versions
        FROM    stg.customers c WITH (NOLOCK)
        WHERE   CAST(c.updated_at AS DATE) <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'customer versions', @status = 'INFO', @rows_affected = @rows;

        /* 2. Keep the current version of each customer */
        SELECT  v.*
        INTO    #customer
        FROM   (SELECT  cv.*,
                        ROW_NUMBER() OVER (PARTITION BY cv.customer_id
                                           ORDER BY cv.updated_at, cv._row_seq) AS version_no
                FROM    #customer_versions cv) v
        WHERE   v.version_no = 1;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'current versions', @status = 'INFO', @rows_affected = @rows;

        /* 3. Reload the dimension */
        BEGIN TRANSACTION;

        TRUNCATE TABLE dw.dim_customer;

        INSERT INTO dw.dim_customer
               (customer_id, first_name, last_name, full_name, initials, email,
                email_shared_count, date_of_birth, age_at_join, address_line1, town,
                county, region, eircode, eircode_valid, segment_code, is_standard_segment,
                marketing_opt_in, customer_since, source_system, version_count,
                record_updated_at, as_of_date)
        SELECT  k.customer_id,
                RTRIM(k.first_name),
                k.last_name,
                RTRIM(k.first_name) + N' ' + RTRIM(k.last_name),
                UPPER(SUBSTRING(k.first_name, 0, 2) + SUBSTRING(k.last_name, 0, 2)),
                k.email,
                CASE WHEN k.email IS NULL THEN 0
                     ELSE COUNT(*) OVER (PARTITION BY k.email) END,
                k.date_of_birth,
                DATEDIFF(YEAR, k.date_of_birth, k.customer_since),
                k.address_line1,
                k.town,
                k.county,
                -- sales regions as agreed with distribution (CR-0412)
                CASE WHEN k.county IN ('Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford') THEN 'EAST'
                     WHEN k.county IN ('Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow') THEN 'SOUTH'
                     WHEN k.county IN ('Galway', 'Mayo', 'Clare', 'Roscommon') THEN 'WEST'
                     WHEN k.county IN ('Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan') THEN 'NORTH-WEST'
                     WHEN k.county IN ('Westmeath', 'Longford', 'Offaly', 'Laois') THEN 'MIDLANDS'
                     ELSE 'UNKNOWN'
                END,
                k.eircode,
                -- routing key (3) and unique identifier (4), keyed with or without the space
                CASE WHEN LEN(k.eircode) = 7 THEN 'Y'
                     WHEN LEN(k.eircode) = 8 AND SUBSTRING(k.eircode, 4, 1) = ' ' THEN 'Y'
                     ELSE 'N'
                END,
                k.segment_code,
                CASE WHEN k.segment_code = 'STD' THEN 'Y' ELSE 'N' END,
                ISNULL(k.marketing_opt_in, 'N'),
                k.customer_since,
                UPPER(RTRIM(k.source_system)),
                k.version_count,
                k.updated_at,
                @AsOfDate
        FROM    #customer k;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'dw.dim_customer', @status = 'INFO', @rows_affected = @rows;
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
"""T01 usp_load_dim_customer: migrated from estate/tsql/T01_usp_load_dim_customer.sql.

Legacy SHA-256: d38c02712a8ae80f9e6e8fff845b41ac7d89026778fc03455b34ded21bba4dc6
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-05, TSQL-13, TSQL-15
Bugs reproduced on purpose (# LANSH-DEFECT): T01-D1 keeps the oldest CRM version; T01-D2 age_at_join counts year boundaries; T01-D3 Eircode check accepts any 7-character value; T01-D4 county spelling variants fall into UNKNOWN
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


# Sales regions as agreed with distribution (CR-0412), legacy lines 134-138.
_EAST = ['Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford']
_SOUTH = ['Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow']
_WEST = ['Galway', 'Mayo', 'Clare', 'Roscommon']
_NORTH_WEST = ['Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan']
_MIDLANDS = ['Westmeath', 'Longford', 'Offaly', 'Laois']


def _ci_key(col):
    """Comparison key for the CI collation, ignoring trailing spaces (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(col))


def _ci_in(col, values):
    """T-SQL IN against literals under the CI collation, trailing spaces ignored."""
    return _ci_key(col).isin([v.upper() for v in values])


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_of_lit = F.lit(as_of)

    customers = inputs["stg.customers"]

    # 1. #customer_versions (TSQL-13): versions saved up to the reporting date,
    #    with the version count per customer.
    customer_versions = (
        customers
        .where(F.to_date(F.col("updated_at")) <= as_of_lit)
        .withColumn(
            "version_count",
            F.count(F.lit(1)).over(Window.partitionBy(F.col("customer_id"))),
        )
    )

    # 2. #customer (TSQL-13): one version per customer.
    w_version = (
        Window.partitionBy(F.col("customer_id"))
        .orderBy(F.col("updated_at").asc(), F.col("_row_seq").asc())  # LANSH-DEFECT: T01-D1 ascending order picks the oldest version, not the current one
    )
    customer = (
        customer_versions
        .withColumn("version_no", F.row_number().over(w_version))
        .where(F.col("version_no") == 1)  # LANSH-DEFECT: T01-D1 version_no = 1 is the first version ever saved
    )

    # 3. dw.dim_customer
    w_email = Window.partitionBy(_ci_key(F.col("email")))  # TSQL-01 / TSQL-02 partition by email under the CI collation

    county = F.col("county")
    region = (
        F.when(_ci_in(county, _EAST), F.lit('EAST'))  # LANSH-DEFECT: T01-D4 only exact county names (case/trailing spaces aside) map to a region
        .when(_ci_in(county, _SOUTH), F.lit('SOUTH'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _WEST), F.lit('WEST'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _NORTH_WEST), F.lit('NORTH-WEST'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _MIDLANDS), F.lit('MIDLANDS'))  # LANSH-DEFECT: T01-D4 exact county names only
        .otherwise(F.lit('UNKNOWN'))  # LANSH-DEFECT: T01-D4 spelling variants such as 'Co. Dublin' land in UNKNOWN
    )

    eircode = F.col("eircode")
    eircode_len = F.length(F.rtrim(eircode))  # TSQL-15 LEN ignores trailing spaces
    eircode_valid = (
        F.when(eircode_len == 7, F.lit('Y'))  # LANSH-DEFECT: T01-D3 any 7-character value passes, whatever its characters
        .when((eircode_len == 8) & (F.substring(eircode, 4, 1) == F.lit(' ')), F.lit('Y'))  # LANSH-DEFECT: T01-D3 only the 8-character form checks the space position
        .otherwise(F.lit('N'))
    )

    dim_customer = customer.select(
        F.col("customer_id").alias("customer_id"),
        F.rtrim(F.col("first_name")).alias("first_name"),
        F.col("last_name").alias("last_name"),
        # TSQL-05: + concatenation is NULL if any part is NULL
        F.concat(F.rtrim(F.col("first_name")), F.lit(' '), F.rtrim(F.col("last_name"))).alias("full_name"),
        # TSQL-15: SUBSTRING(x, 0, 2) returns 1 character; TSQL-05: NULL part gives NULL
        F.upper(
            F.concat(F.substring(F.col("first_name"), 1, 1), F.substring(F.col("last_name"), 1, 1))
        ).alias("initials"),
        F.col("email").alias("email"),
        F.when(F.col("email").isNull(), F.lit(0))
         .otherwise(F.count(F.lit(1)).over(w_email))
         .alias("email_shared_count"),
        F.col("date_of_birth").alias("date_of_birth"),
        # TSQL-04: DATEDIFF(YEAR, a, b) = year(b) - year(a)
        (F.year(F.col("customer_since")) - F.year(F.col("date_of_birth"))).alias("age_at_join"),  # LANSH-DEFECT: T01-D2 counts year boundaries, not completed years
        F.col("address_line1").alias("address_line1"),
        F.col("town").alias("town"),
        F.col("county").alias("county"),
        region.alias("region"),
        F.col("eircode").alias("eircode"),
        F.rpad(eircode_valid, 1, ' ').alias("eircode_valid"),
        # TSQL-02: CHAR(4) output holds the value padded to 4
        F.rpad(F.col("segment_code"), 4, ' ').alias("segment_code"),
        # TSQL-01 / TSQL-02: = 'STD' ignores case and the CHAR padding
        F.rpad(
            F.when(_ci_key(F.col("segment_code")) == F.lit('STD'), F.lit('Y')).otherwise(F.lit('N')),
            1, ' ',
        ).alias("is_standard_segment"),
        # ISNULL(marketing_opt_in, 'N') into CHAR(1)
        F.rpad(F.coalesce(F.col("marketing_opt_in"), F.lit('N')), 1, ' ').alias("marketing_opt_in"),
        F.col("customer_since").alias("customer_since"),
        F.upper(F.rtrim(F.col("source_system"))).alias("source_system"),
        F.col("version_count").alias("version_count"),
        F.col("updated_at").alias("record_updated_at"),
        as_of_lit.alias("as_of_date"),
    )

    return {"dw.dim_customer": dim_customer}
```
</details>

