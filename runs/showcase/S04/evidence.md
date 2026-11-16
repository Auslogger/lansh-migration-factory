# Evidence report: S04

Generated 2026-11-12 02:47 UTC. **Status: MATCH.**

- Legacy code: `estate/sas/S04_risk_scoring.sas` (SHA-256 `c1d72f4893edd628…`)
- Migrated module: `runs/showcase/S04/jobs/s04.py` (SHA-256 `29cd1747fbf6fdb5…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 7 (SAS-03, SAS-10, SAS-11, SAS-13, SAS-15)
- Suspected defects: 5; tests: 6/6 passed; heal attempts: 0
- Claude: 6 calls (0 live), 36,886 input and 42,284 output tokens, $1.07 API-equivalent (not billed), 360 s of model time

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
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: - n_claims is COUNT(*). No input column feeds its value, so I recorded it as coming from dw.claims_enriched.customer_id (a grouping key) at |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: blank_is_null on rpt.risk_scores.lob_code: SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is m; float_rel on rpt.risk_scores.n_claims: SAS stores every n |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: as_of_date: built from the text parameter with to_date instead of a SAS day count; the value is the same. Joins: SAS PROC SQL joins treat miss |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.risk_scores: MATCH

MATCH: all 2,645 rows agree record for record, compared on the keys ['customer_id', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 2,645 | 2,645 | ok |
| Total of `customer_id` | 291480785.0 | 291480785.0 | ok |
| Total of `n_claims` | 2911.0 | 2911.0 | ok |
| Total of `paid` | 12027486.519999988 | 12027486.519999987 | ok |
| Total of `n_recoveries` | 218.0 | 218.0 | ok |
| Total of `severity` | 2644.999999999999 | 2645.000000000001 | ok |
| Total of `age` | 140368.0 | 140368.0 | ok |
| Total of `age_load` | 2881.2000000000103 | 2881.20000000001 | ok |
| Total of `county_load` | 2780.0500000000507 | 2780.0500000000475 | ok |
| Total of `loss_ratio` | 1706.2735739276122 | 1706.273573927684 | ok |
| Total of `points` | 48141.5 | 48141.5 | ok |
| Total of `score` | 55003.30999999925 | 55003.30999999939 | ok |
| Records matched | | | 2,645 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `71253df91213` | `8e6b9e55ce0d` | - |

Keys: ['customer_id', 'lob_code'].

## Operate (Delta lakehouse, reconciled again)

### rpt.risk_scores: MATCH

MATCH: all 2,645 rows agree record for record, compared on the keys ['customer_id', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 2,645 | 2,645 | ok |
| Total of `customer_id` | 291480785.0 | 291480785.0 | ok |
| Total of `n_claims` | 2911.0 | 2911.0 | ok |
| Total of `paid` | 12027486.519999988 | 12027486.519999987 | ok |
| Total of `n_recoveries` | 218.0 | 218.0 | ok |
| Total of `severity` | 2644.999999999999 | 2645.000000000001 | ok |
| Total of `age` | 140368.0 | 140368.0 | ok |
| Total of `age_load` | 2881.2000000000103 | 2881.20000000001 | ok |
| Total of `county_load` | 2780.0500000000507 | 2780.0500000000475 | ok |
| Total of `loss_ratio` | 1706.2735739276122 | 1706.273573927684 | ok |
| Total of `points` | 48141.5 | 48141.5 | ok |
| Total of `score` | 55003.30999999925 | 55003.30999999939 | ok |
| Records matched | | | 2,645 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `71253df91213` | `8e6b9e55ce0d` | - |

Keys: ['customer_id', 'lob_code'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| S04-D1 | Hard-coded line-of-business list drops other lines | 60-83 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S04-D2 | Missing inputs make the score missing and silently tier the row LOW | 25-101 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S04-D3 | Customer dimension join can multiply score rows | 22-84 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S04-D4 | Age approximated by days/365.25 | 24-27 | 4 |  | reproduce (agent:lansh-dev) |
| S04-D5 | Claims experience not limited to the reporting date | 9-44 | 0 | 0.00 | reproduce (agent:lansh-dev) |

## Flows of tagged columns

| Tag | From | Into | Through | Decision |
|---|---|---|---|---|
| pii | dw.dim_customer.date_of_birth | rpt.risk_scores.age | S04 | reproduce_accepted |
| protected | dw.dim_customer.date_of_birth | rpt.risk_scores.age | S04 | reproduce_flagged |
| pii | dw.dim_customer.date_of_birth | rpt.risk_scores.age_load | S04 | reproduce_accepted |
| protected | dw.dim_customer.date_of_birth | rpt.risk_scores.age_load | S04 | reproduce_flagged |
| protected | dw.dim_customer.county | rpt.risk_scores.county_load | S04 | reproduce_flagged |
| protected | dw.dim_customer.county | rpt.risk_scores.score | S04 | reproduce_flagged |
| pii | dw.dim_customer.date_of_birth | rpt.risk_scores.score | S04 | reproduce_accepted |
| protected | dw.dim_customer.date_of_birth | rpt.risk_scores.score | S04 | reproduce_flagged |
| protected | dw.dim_customer.county | rpt.risk_scores.tier | S04 | reproduce_flagged |
| pii | dw.dim_customer.date_of_birth | rpt.risk_scores.tier | S04 | reproduce_accepted |
| protected | dw.dim_customer.date_of_birth | rpt.risk_scores.tier | S04 | reproduce_flagged |

## Contract

`gold.risk_scores` (gold), from `rpt.risk_scores`. Grain: One row per customer and line of business (MOT, HOM, TRV) that has claims in dw.claims_enriched, scored as of the reporting date.
Key: ['customer_id', 'lob_code']; partitions: ['tier'].
| Column | Policy | Reason |
|---|---|---|
| lob_code | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| n_claims | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| paid | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| n_recoveries | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| severity | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| age | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| age_load | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| county_load | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| loss_ratio | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| points | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| score | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| tier | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
Tagged: age (pii, protected), age_load (pii, protected), county_load (protected), score (pii, protected), tier (pii, protected)

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| SAS-03 | 24-24 | llm | 0.90 | Age comes from plain arithmetic on SAS day counts (&as_of minus date_of_birth, divided by 365.25). In Spark, date_of_birth is a DATE and as_of must be turned into a date, so this needs datediff or dat |
| SAS-13 | 60-74 | llm | 0.90 | The %do loop writes one PROC SQL per line of business (MOT, HOM, TRV), and lines 79-83 union the results. In Spark this becomes a Python loop or a single query grouped by line of business, filtered to |
| SAS-10 | 66-69 | llm | 0.95 | mean(x.paid) is mixed with ungrouped columns, so SAS remerges the mean over the rows the WHERE keeps (one line of business) back onto every row. Spark needs a window or a join to the per-line average  |
| SAS-15 | 96-96 | llm | 0.90 | round(2.5*loss_ratio, 0.5) rounds to the nearest half, half away from zero, with fuzz. F.round takes decimal places, so this needs something like floor(x*2+0.5)/2 plus fuzz handling. |
| SAS-15 | 98-98 | llm | 0.85 | round(points*age_load*county_load, 0.01) is applied to a computed double. SAS's fuzz rounds near-half values up, but Spark's F.round on the binary value can round them down. |
| SAS-11 | 99-100 | llm | 0.95 | The first assignment, 'HIGH', fixes tier at length 4, so 'MEDIUM' is silently cut to 'MEDI' (the output schema has tier as char 4). Spark must reproduce 'MEDI' on purpose. |
| SAS-03 | 102-103 | llm | 0.70 | as_of_date is the number &as_of (a SAS day count) shown with yymmdd10. In Spark it must be converted from days since 1960-01-01 to a date. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| customer_id | dw.claims_enriched.customer_id | - |
| lob_code | dw.claims_enriched.lob_code | - |
| n_claims | dw.claims_enriched.customer_id | - |
| paid | dw.claims_enriched.total_paid | - |
| n_recoveries | dw.claims_enriched.n_recoveries | - |
| severity | dw.claims_enriched.lob_code, dw.claims_enriched.total_paid | - |
| age | dw.dim_customer.date_of_birth, parameter @AsOfDate | - |
| age_load | constant, dw.dim_customer.date_of_birth, parameter @AsOfDate | - |
| county_load | constant, dw.dim_customer.county | - |
| loss_ratio | dw.claims_enriched.total_paid, rpt.premium_band_summary.earned_eur | - |
| points | constant, dw.claims_enriched.customer_id, dw.claims_enriched.n_recoveries, dw.claims_enriched.total_paid, rpt.premium_band_summary.earned_eur | - |
| score | dw.claims_enriched.customer_id, dw.claims_enriched.n_recoveries, dw.claims_enriched.total_paid, dw.dim_customer.county, dw.dim_customer.date_of_birth, parameter @AsOfDate, rpt.premium_band_summary.earned_eur | - |
| tier | constant, dw.claims_enriched.customer_id, dw.claims_enriched.n_recoveries, dw.claims_enriched.total_paid, dw.dim_customer.county, dw.dim_customer.date_of_birth, parameter @AsOfDate, rpt.premium_band_summary.earned_eur | - |
| as_of_date | parameter @AsOfDate | - |

Rows are decided by: dw.claims_enriched.customer_id, dw.claims_enriched.lob_code, dw.dim_customer.customer_id, rpt.premium_band_summary.lob_code.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| S04-SAS-03-1 | SAS-03 | contract | pass | Line 24: dates of birth near the 25 and 70 boundaries at AsOfDate 2025-12-31. SAS divides the day count by 365.25 and truncates, so DOB 2000-12-31 (25 by the calendar) gets age 24 and the 1.40 load. D |
| S04-SAS-10-2 | SAS-10 | contract | pass | Lines 66-69: severity is paid divided by the remerged mean of paid within one line. MOT customers paid 100, 300 and 800 (line mean 400, so severity 0.25, 0.75 and 2.0). HOM customers paid 2000 and 100 |
| S04-SAS-15-3 | SAS-15 | contract | pass | Line 96: the line loss ratios put 2.5*loss_ratio exactly on a half-unit boundary (MOT about 0.3 → 0.75, HOM 0.1 → 0.25, TRV 0.7 → 1.75), with decimal paid sums that carry binary error. SAS round(x, 0. |
| S04-SAS-15-4 | SAS-15 | contract | pass | Line 98: points multiplied by binary loads land on half-cents. Young Dublin customers give 12.5*1.4*1.15 = 20.125 and 17.5*1.4*1.15 = 28.175. A Dublin customer aged 40 gives 12.5*1.15 = 14.375 and 37. |
| S04-SAS-11-5 | SAS-11 | contract | pass | Lines 99-100: scores fall in all three tiers. One customer is LOW (12.5), three are MEDIUM (25, 23 for a Dublin customer with a recovery, 25) and one is HIGH (60). SAS fixes tier at length 4 from 'HIG |
| S04-SAS-03-6 | SAS-03 | contract | pass | Lines 102-103: as_of_date is the SAS day count for 2025-12-31 (23740) shown with yymmdd10. Every output row carries it. A naive translation that writes the raw number, or counts days from the 1970 epo |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 561 | 7 s | $0.033 |
| defect_reviewer | 1 | 0 | 6,245 | 63 s | $0.151 |
| lineage | 1 | 0 | 5,854 | 48 s | $0.145 |
| test_author | 1 | 0 | 18,348 | 142 s | $0.400 |
| translator | 1 | 0 | 9,179 | 79 s | $0.248 |
| trap_scan | 1 | 0 | 2,097 | 22 s | $0.093 |

## Code

<details><summary>Legacy code</summary>

```sas
/******************************************************************************
  Program  : risk_scoring.sas
  Purpose  : Customer risk score and referral tier by line of business for
             underwriting. Claims experience (claim count, recoveries and
             severity against the line's average) plus the line's loss ratio,
             loaded for the policyholder's age and county.
  Inputs   : dw.claims_enriched, rpt.premium_band_summary, dw.dim_customer
  Output   : rpt.risk_scores (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : TF

  Change log
    2015-06-02  TF    Initial version (motor only)
    2016-11-21  TF    Home and travel added; scoring per line in a macro
                      (CR-0998)
    2018-04-09  GH    Age and county loadings from the pricing review (CR-1302)
    2020-01-27  GH    Line loss ratio from premium_bands.sas (CR-1544)
    2022-09-12  TF    Referral tiers for the underwriting queue (CR-2011)
******************************************************************************/

/* policyholder loadings: age at the reporting date and county */
data work.cust(keep=customer_id age age_load county_load);
  set dw.dim_customer(keep=customer_id date_of_birth county);
  age = int((&as_of - date_of_birth) / 365.25);
  if missing(age) then age_load = 1.00;
  else if age < 25 then age_load = 1.40;
  else if age >= 70 then age_load = 1.25;
  else age_load = 1.00;
  select (upcase(strip(county)));
    when ('DUBLIN') county_load = 1.15;
    when ('CORK', 'LIMERICK', 'GALWAY') county_load = 1.05;
    otherwise county_load = 1.00;
  end;
run;

/* claims experience per customer and line of business */
proc sql;
  create table work.experience as
  select customer_id, lob_code,
         count(*)          as n_claims,
         sum(total_paid)   as paid,
         sum(n_recoveries) as n_recoveries
  from   dw.claims_enriched
  group  by customer_id, lob_code;
quit;

/* loss ratio per line: paid on the claims book over earned premium */
proc sql;
  create table work.lob_ratio as
  select e.lob_code, sum(e.paid) / p.earned as loss_ratio
  from   work.experience e,
         (select lob_code, sum(earned_eur) as earned
          from   rpt.premium_band_summary
          group  by lob_code) p
  where  e.lob_code = p.lob_code
  group  by e.lob_code, p.earned;
quit;

/* each customer against the average for the line */
%macro score_lines(lobs);
  %local i lob;
  %do i = 1 %to %sysfunc(countw(&lobs));
    %let lob = %scan(&lobs, &i);
    proc sql;
      create table work.score_&lob as
      select x.customer_id, x.lob_code, x.n_claims, x.paid, x.n_recoveries,
             x.paid / mean(x.paid) as severity
      from   work.experience x
      where  x.lob_code = "&lob";
    quit;
  %end;
%mend score_lines;

%score_lines(MOT HOM TRV);

proc sql;
  create table work.scoring as
  select s.*, c.age, c.age_load, c.county_load, r.loss_ratio
  from   (select * from work.score_mot
          union all
          select * from work.score_hom
          union all
          select * from work.score_trv) s
         left join work.cust c on c.customer_id = s.customer_id
         left join work.lob_ratio r on r.lob_code = s.lob_code
  order  by s.customer_id, s.lob_code;
quit;

/* points, loadings and the referral tier */
data rpt.risk_scores(keep=customer_id lob_code n_claims paid n_recoveries severity age
                          age_load county_load loss_ratio points score tier as_of_date);
  set work.scoring;
  sev_points = 0;
  if severity >= 2 then sev_points = 10;
  else if severity >= 1 then sev_points = 5;
  lob_points = round(2.5 * loss_ratio, 0.5);
  points = 12.5 * min(n_claims, 4) + 7.5 * n_recoveries + sev_points + lob_points;
  score  = round(points * age_load * county_load, 0.01);
  if score >= 35 then tier = 'HIGH';
  else if score >= 22 then tier = 'MEDIUM';
  else tier = 'LOW';
  format as_of_date yymmdd10.;
  as_of_date = &as_of;
run;
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""S04 risk_scoring: migrated from estate/sas/S04_risk_scoring.sas.

Legacy SHA-256: c1d72f4893edd62876d4761f52b901aa90dfef5174bbc3f8bb269afea9e46504
Written by: LANSH translator (Claude)
Traps handled: SAS-03, SAS-10, SAS-11, SAS-13, SAS-15
Bugs reproduced on purpose (# LANSH-DEFECT): S04-D1 hard-coded line list, S04-D2 missing inputs give missing score and tier LOW, S04-D3 customer dimension join can multiply rows, S04-D4 age by days/365.25, S04-D5 claims not limited to reporting date
"""
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def _sas_char(c):
    # SAS char: trailing blanks never count, a blank value is missing
    t = F.rtrim(c)
    return F.when(t == "", F.lit(None).cast("string")).otherwise(t)


def _sas_round(x, unit: str):
    # SAS round(x, unit) with fuzz: decimal arithmetic, half away from zero (SAS-15)
    u = F.lit(Decimal(unit))
    return (F.round(x.cast("decimal(38,10)") / u, 0) * u).cast("double")


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.to_date(F.lit(params["AsOfDate"]))

    # ---- work.cust (lines 22-34) ----
    dimc = inputs["dw.dim_customer"]
    age_raw = F.datediff(as_of, F.col("date_of_birth")).cast("double") / F.lit(365.25)  # SAS-03
    # int() truncates toward zero
    age = F.when(age_raw >= 0, F.floor(age_raw)).otherwise(F.ceil(age_raw)).cast("double")  # LANSH-DEFECT: S04-D4 age approximated by days/365.25
    cust = dimc.select(
        F.col("customer_id").cast("double").alias("customer_id"),
        F.col("date_of_birth"),
        F.col("county"),
    ).withColumn("age", age)
    cust = cust.withColumn(
        "age_load",
        F.when(F.col("age").isNull(), F.lit(1.00))
        .when(F.col("age") < 25, F.lit(1.40))  # LANSH-DEFECT: S04-D4 age boundary uses approximated age
        .when(F.col("age") >= 70, F.lit(1.25))  # LANSH-DEFECT: S04-D4 age boundary uses approximated age
        .otherwise(F.lit(1.00)),
    )
    cty = F.upper(F.trim(F.col("county")))
    cust = cust.withColumn(
        "county_load",
        F.when(cty == "DUBLIN", F.lit(1.15))
        .when(cty.isin("CORK", "LIMERICK", "GALWAY"), F.lit(1.05))
        .otherwise(F.lit(1.00)),
    ).select("customer_id", "age", "age_load", "county_load")  # LANSH-DEFECT: S04-D3 every dim_customer row kept, no current-version filter

    # ---- work.experience (lines 37-45) ----
    cl = inputs["dw.claims_enriched"].select(
        F.col("customer_id").cast("double").alias("customer_id"),
        _sas_char(F.col("lob_code")).alias("lob_code"),
        F.col("total_paid").cast("double").alias("total_paid"),
        F.col("n_recoveries").cast("double").alias("n_recoveries"),
    )
    experience = cl.groupBy("customer_id", "lob_code").agg(  # LANSH-DEFECT: S04-D5 claims not limited to the reporting date
        F.count(F.lit(1)).cast("double").alias("n_claims"),
        F.sum("total_paid").alias("paid"),
        F.sum("n_recoveries").alias("n_recoveries"),  # LANSH-DEFECT: S04-D2 all-missing n_recoveries gives missing sum
    )

    # ---- work.lob_ratio (lines 48-57) ----
    prem = inputs["rpt.premium_band_summary"].select(
        _sas_char(F.col("lob_code")).alias("lob_code"),
        F.col("earned_eur").cast("double").alias("earned_eur"),
    )
    p = prem.groupBy("lob_code").agg(F.sum("earned_eur").alias("earned"))
    e = experience.select(F.col("lob_code").alias("e_lob"), F.col("paid"))
    lob_ratio = (
        e.join(p, e["e_lob"].eqNullSafe(p["lob_code"]), "inner")  # LANSH-DEFECT: S04-D2 inner join drops lines without premium, so loss_ratio is missing
        .groupBy("e_lob", "earned")
        .agg(F.sum("paid").alias("sum_paid"))
        .select(
            F.col("e_lob").alias("r_lob"),
            F.try_divide(F.col("sum_paid"), F.col("earned")).alias("loss_ratio"),
        )
    )

    # ---- %score_lines(MOT HOM TRV) (lines 60-74), SAS-13 / SAS-10 ----
    scores = None
    for lob in ["MOT", "HOM", "TRV"]:  # LANSH-DEFECT: S04-D1 hard-coded line-of-business list drops other lines
        x = experience.where(F.col("lob_code") == F.lit(lob))
        x = x.select(
            "customer_id", "lob_code", "n_claims", "paid", "n_recoveries",
            F.try_divide(F.col("paid"), F.avg("paid").over(Window.partitionBy())).alias("severity"),
        )
        scores = x if scores is None else scores.unionByName(x)  # LANSH-DEFECT: S04-D1 only the three listed score tables are unioned

    # ---- work.scoring (lines 76-87) ----
    s = scores
    scoring = (
        s.join(cust.withColumnRenamed("customer_id", "c_cid"),
               s["customer_id"].eqNullSafe(F.col("c_cid")), "left")  # LANSH-DEFECT: S04-D3 one row per customer version; S04-D2 unmatched customer gets missing loadings
        .join(lob_ratio, F.col("lob_code").eqNullSafe(F.col("r_lob")), "left")
        .select("customer_id", "lob_code", "n_claims", "paid", "n_recoveries", "severity",
                "age", "age_load", "county_load", "loss_ratio")
    )

    # ---- rpt.risk_scores (lines 90-104) ----
    sev_points = (
        F.when(F.col("severity") >= 2, F.lit(10.0))
        .when(F.col("severity") >= 1, F.lit(5.0))
        .otherwise(F.lit(0.0))
    )
    lob_points = _sas_round(F.lit(2.5) * F.col("loss_ratio"), "0.5")  # LANSH-DEFECT: S04-D2 missing loss_ratio passes through
    out = scoring.withColumn("lob_points", lob_points)
    out = out.withColumn(
        "points",
        F.lit(12.5) * F.least(F.col("n_claims"), F.lit(4.0))
        + F.lit(7.5) * F.col("n_recoveries")
        + sev_points
        + F.col("lob_points"),  # LANSH-DEFECT: S04-D2 + propagates missing components into points
    )
    out = out.withColumn(
        "score",
        _sas_round(F.col("points") * F.col("age_load") * F.col("county_load"), "0.01"),  # LANSH-DEFECT: S04-D2 missing points or loadings give missing score
    )
    out = out.withColumn(
        "tier",
        F.substring(  # SAS-11: tier length fixed at 4 by first assignment 'HIGH'
            F.when(F.col("score") >= 35, F.lit("HIGH"))
            .when(F.col("score") >= 22, F.lit("MEDIUM"))
            .otherwise(F.lit("LOW")),  # LANSH-DEFECT: S04-D2 missing score falls to tier LOW
            1, 4,
        ),
    )
    out = out.withColumn("as_of_date", as_of)  # SAS-03: &as_of day count shown as yymmdd10.

    result = out.select(
        "customer_id", "lob_code", "n_claims", "paid", "n_recoveries", "severity", "age",
        "age_load", "county_load", "loss_ratio", "points", "score", "tier", "as_of_date",
    )
    return {"rpt.risk_scores": result}
```
</details>

