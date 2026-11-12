# Evidence report: S03

Generated 2026-11-12 02:46 UTC. **Status: MATCH.**

- Legacy code: `estate/sas/S03_premium_bands.sas` (SHA-256 `c40650f2177f8a28…`)
- Migrated module: `runs/showcase/S03/jobs/s03.py` (SHA-256 `12217d640e36100f…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 7 (SAS-03, SAS-05, SAS-09, SAS-12, SAS-14)
- Suspected defects: 3; tests: 5/5 passed; heal attempts: 0
- Claude: 6 calls (0 live), 29,035 input and 29,636 output tokens, $0.75 API-equivalent (not billed), 248 s of model time

## Gate decisions

| Gate | Outcome | Reviewer | Review time | Flags | Reason |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: The only input is dw.fact_premium_earned. lob_code and prem_band come from each policy's first row. PROC SORT NODUPKEY keeps the first row  |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: blank_is_null on rpt.premium_band_summary.lob_code: SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank v; blank_is_null on rpt.premium_band_summary.prem_band: SAS  |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: - I take load order to be _row_seq (the lineage agent's inference, confidence 0.55). It decides which row sets each policy's band and lob_code |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### rpt.premium_band_summary: MATCH

MATCH: all 13 rows agree record for record, compared on the keys ['lob_code', 'prem_band']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 13 | 13 | ok |
| Total of `n_policies` | 61441.0 | 61441.0 | ok |
| Total of `n_transactions` | 67879.0 | 67879.0 | ok |
| Total of `written_eur` | 24033402.720000003 | 24033402.720000003 | ok |
| Total of `earned_eur` | 18768844.409999955 | 18768844.409999955 | ok |
| Records matched | | | 13 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `9c0afce322a3` | `da9d1d500854` | - |

Keys: ['lob_code', 'prem_band'].

## Operate (Delta lakehouse, reconciled again)

### rpt.premium_band_summary: MATCH

MATCH: all 13 rows agree record for record, compared on the keys ['lob_code', 'prem_band']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 13 | 13 | ok |
| Total of `n_policies` | 61441.0 | 61441.0 | ok |
| Total of `n_transactions` | 67879.0 | 67879.0 | ok |
| Total of `written_eur` | 24033402.720000003 | 24033402.720000003 | ok |
| Total of `earned_eur` | 18768844.409999955 | 18768844.409999955 | ok |
| Records matched | | | 13 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `9c0afce322a3` | `da9d1d500854` | - |

Keys: ['lob_code', 'prem_band'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| S03-D1 | Policies with missing lob_code silently dropped by PROC MEANS CLASS | 37-71 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S03-D2 | No as-of cut-off: transactions after the reporting date included | 32-74 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S03-D3 | Policy band taken from first-loaded row, not the earliest (opening) transaction | 31-40 | 0 | 0.00 | reproduce (agent:lansh-dev) |

## Contract

`gold.premium_band_summary` (gold), from `rpt.premium_band_summary`. Grain: One row per line of business and premium band. Each policy is put in one band, based on the written premium of its first transaction in load order, and all of that policy's transactions are summed in that band.
Key: ['lob_code', 'prem_band']; partitions: none.
| Column | Policy | Reason |
|---|---|---|
| lob_code | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| prem_band | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| n_policies | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| n_transactions | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| written_eur | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| earned_eur | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| SAS-12 | 23-28 | llm | 0.90 | Each band includes its lower bound and excludes its upper one (-<), and '1000 - high' includes 1000. LOW does not match a missing numeric, so a missing written_eur falls to OTHER and gets 'UNKNOWN'. T |
| SAS-09 | 32-34 | llm | 0.90 | NODUPKEY keeps each policy's first transaction in load order (the stable sort), and that row sets the band. Spark needs a window ordered by load order (_row_seq), not dropDuplicates. |
| SAS-05 | 50-52 | llm | 0.75 | A one-to-many MERGE with an IN= subset is a left join from txn to policy_band. lob_code and prem_band come only from policy_band and stay missing for unmatched keys. |
| SAS-14 | 55-61 | llm | 0.85 | PROC MEANS NWAY with CLASS drops rows whose lob_code or prem_band is missing, but a Spark groupBy keeps NULL groups. Those groups must be filtered out. N() and SUM() are named by the OUTPUT statement. |
| SAS-14 | 63-67 | llm | 0.85 | The second PROC MEANS NWAY counts policies per lob_code/prem_band and also excludes missing class values, which Spark's groupBy would keep. |
| SAS-05 | 71-72 | llm | 0.70 | A MERGE with no IN= keeps keys from both inputs, so it acts as a full outer join on lob_code and prem_band. Columns missing on one side stay missing, and the output is ordered by the BY keys. |
| SAS-03 | 73-74 | llm | 0.80 | &as_of is a SAS date number (days since 1960-01-01). In Spark it must be turned into a DATE, e.g. date_add('1960-01-01', as_of). |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| lob_code | dw.fact_premium_earned.lob_code | - |
| prem_band | constant, dw.fact_premium_earned.written_eur | - |
| n_policies | dw.fact_premium_earned.policy_id | - |
| n_transactions | dw.fact_premium_earned.written_eur | - |
| written_eur | dw.fact_premium_earned.written_eur | - |
| earned_eur | dw.fact_premium_earned.earned_eur | - |
| as_of_date | parameter @AsOfDate | - |

Rows are decided by: dw.fact_premium_earned.lob_code, dw.fact_premium_earned.policy_id.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| S03-SAS-12-1 | SAS-12 | contract | pass | One policy per row, each with written_eur exactly on or just beside a band edge: -10.00 and -0.01 (NEGATIVE), 0.00 (lower bound of 0-249, included), 249.99 and 250.00 (either side of the 250 edge), 49 |
| S03-SAS-09-2 | SAS-09 | contract | pass | Three policies, each with several transactions in different bands. For every policy, the first row in load order is not the row with the lowest txn_id or the earliest txn_date, and it falls in a diffe |
| S03-SAS-05-3 | SAS-05 | contract | pass | Lines 50-52: some policies have transactions loaded with a different lob_code from their first (opening) row. Policy 301 opens as MOTOR and later has HOME rows. Policy 302 opens as HOME and later has  |
| S03-SAS-05-4 | SAS-05 | contract | pass | Lines 71-72: rows are loaded in no particular order and cover several LOBs, each with several bands, including NEGATIVE and 1000+. The final MERGE BY lob_code prem_band is a full outer join, and its o |
| S03-SAS-03-5 | SAS-03 | contract | pass | A few policies whose input as_of_date column holds 2025-11-30, not the run parameter AsOfDate=2025-12-31. The output as_of_date must be the SAS date number &as_of turned into the DATE 2025-12-31. A na |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 662 | 9 s | $0.029 |
| defect_reviewer | 1 | 0 | 6,058 | 53 s | $0.139 |
| lineage | 1 | 0 | 2,568 | 22 s | $0.070 |
| test_author | 1 | 0 | 12,371 | 91 s | $0.270 |
| translator | 1 | 0 | 6,235 | 54 s | $0.172 |
| trap_scan | 1 | 0 | 1,742 | 18 s | $0.075 |

## Code

<details><summary>Legacy code</summary>

```sas
/******************************************************************************
  Program  : premium_bands.sas
  Purpose  : Written and earned premium by line of business and premium band
             for the pricing committee. Each policy is banded once, on the
             premium of its first transaction as loaded, and all of its
             transactions are reported in that band.
  Inputs   : dw.fact_premium_earned
  Output   : rpt.premium_band_summary (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : RN

  Change log
    2016-02-22  RN    Initial version
    2017-05-08  RN    Top band split: 1000 and over (CR-1077)
    2019-10-14  CB    Transactions reported in their policy's band, not their
                      own (CR-1520)
    2022-03-07  CB    Policy count per band (CR-1951)
******************************************************************************/

/* premium bands used by pricing since 2017 */
proc format;
  value premband
    low  -< 0    = 'NEGATIVE'
    0    -< 250  = '0-249'
    250  -< 500  = '250-499'
    500  -< 1000 = '500-999'
    1000 - high  = '1000+'
    other        = 'UNKNOWN';
run;

/* one row per policy: its opening transaction, as loaded */
proc sort data=dw.fact_premium_earned(keep=policy_id lob_code written_eur)
          out=work.opening nodupkey;
  by policy_id;
run;

data work.policy_band(keep=policy_id lob_code prem_band);
  set work.opening;
  length prem_band $8;
  prem_band = put(written_eur, premband.);
run;

/* every transaction, in its policy's band */
proc sort data=dw.fact_premium_earned(keep=policy_id written_eur earned_eur)
          out=work.txn;
  by policy_id;
run;

data work.txn_band;
  merge work.txn(in=t) work.policy_band;
  by policy_id;
  if t;
run;

proc means data=work.txn_band noprint nway;
  class lob_code prem_band;
  var written_eur earned_eur;
  output out=work.premium_sums(drop=_type_ _freq_)
         n(written_eur)=n_transactions sum(written_eur)=written_eur
         sum(earned_eur)=earned_eur;
run;

proc means data=work.policy_band noprint nway;
  class lob_code prem_band;
  var policy_id;
  output out=work.policy_counts(drop=_type_ _freq_) n(policy_id)=n_policies;
run;

data rpt.premium_band_summary(keep=lob_code prem_band n_policies n_transactions
                                   written_eur earned_eur as_of_date);
  merge work.policy_counts work.premium_sums;
  by lob_code prem_band;
  format as_of_date yymmdd10.;
  as_of_date = &as_of;
run;
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""S03 premium_bands: migrated from estate/sas/S03_premium_bands.sas.

Legacy SHA-256: c40650f2177f8a2808693aa0e79675464a0df999a505a2fcad32c4f9c4bf0132
Written by: LANSH translator (Claude)
Traps handled: SAS-03, SAS-05, SAS-09, SAS-12, SAS-14
Bugs reproduced on purpose (# LANSH-DEFECT): S03-D1 missing lob_code policies dropped by PROC MEANS CLASS; S03-D2 no as-of cut-off on transactions; S03-D3 policy band taken from first-loaded row
"""

import re

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


def _sas_char(col_name: str):
    """SAS character semantics: trailing blanks never count, a blank value is missing."""
    trimmed = F.rtrim(F.col(col_name))
    return F.when(trimmed == "", F.lit(None).cast(T.StringType())).otherwise(trimmed)


def _as_of_date(value: str):
    """SAS-03: &as_of is a SAS date (days since 1960-01-01); the harness passes ISO text."""
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return F.date_add(F.to_date(F.lit("1960-01-01")), int(text))
    return F.to_date(F.lit(text), "yyyy-MM-dd")


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    # LANSH-DEFECT: S03-D2 no filter on txn_date <= as_of; every transaction, including those after the reporting date, is read
    src = inputs["dw.fact_premium_earned"]

    base = src.select(
        F.col("policy_id").cast(T.DoubleType()).alias("policy_id"),
        _sas_char("lob_code").alias("lob_code"),
        F.col("written_eur").cast(T.DoubleType()).alias("written_eur"),
        F.col("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        F.col("_row_seq"),
    )

    # SAS-09: PROC SORT NODUPKEY BY policy_id keeps the first row of each policy in load order.
    w_first = Window.partitionBy("policy_id").orderBy(F.col("_row_seq").asc())
    opening = (
        base.withColumn("_rn", F.row_number().over(w_first))  # LANSH-DEFECT: S03-D3 band and lob_code come from the first-loaded row, not the earliest transaction
        .where(F.col("_rn") == 1)
        .select("policy_id", "lob_code", "written_eur")
    )

    # SAS-12: PROC FORMAT premband, lower bound included, upper excluded; missing goes to OTHER.
    we = F.col("written_eur")
    prem_band = (
        F.when(we < 0, F.lit("NEGATIVE"))
        .when(we < 250, F.lit("0-249"))
        .when(we < 500, F.lit("250-499"))
        .when(we < 1000, F.lit("500-999"))
        .when(we >= 1000, F.lit("1000+"))
        .otherwise(F.lit("UNKNOWN"))
    )
    policy_band = opening.select("policy_id", "lob_code", prem_band.alias("prem_band"))

    # Every transaction (PROC SORT without NODUPKEY keeps all rows).
    txn = base.select("policy_id", "written_eur", "earned_eur")

    # SAS-05: one-to-many MERGE with "if t" acts as a left join from txn; missing BY keys match each other.
    t = txn.alias("t")
    p = policy_band.alias("p")
    txn_band = t.join(p, F.col("t.policy_id").eqNullSafe(F.col("p.policy_id")), "left").select(
        F.col("t.policy_id").alias("policy_id"),
        F.col("t.written_eur").alias("written_eur"),
        F.col("t.earned_eur").alias("earned_eur"),
        F.col("p.lob_code").alias("lob_code"),
        F.col("p.prem_band").alias("prem_band"),
    )

    # SAS-14: PROC MEANS NWAY CLASS lob_code prem_band (no MISSING option) leaves out missing class values.
    premium_sums = (
        txn_band.where(F.col("lob_code").isNotNull() & F.col("prem_band").isNotNull())  # LANSH-DEFECT: S03-D1 transactions of policies with missing lob_code dropped
        .groupBy("lob_code", "prem_band")
        .agg(
            F.count("written_eur").cast(T.DoubleType()).alias("n_transactions"),
            F.sum("written_eur").cast(T.DoubleType()).alias("written_eur"),
            F.sum("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        )
    )

    # SAS-14: second PROC MEANS NWAY, N(policy_id) per class combination, missing class values left out.
    policy_counts = (
        policy_band.where(F.col("lob_code").isNotNull() & F.col("prem_band").isNotNull())  # LANSH-DEFECT: S03-D1 policies with missing lob_code dropped
        .groupBy("lob_code", "prem_band")
        .agg(F.count("policy_id").cast(T.DoubleType()).alias("n_policies"))
    )

    # SAS-05: MERGE without IN= is a full outer join on the BY keys.
    merged = policy_counts.join(premium_sums, ["lob_code", "prem_band"], "full")

    # SAS-03: as_of_date stamped from the parameter.
    result = merged.select(
        F.col("lob_code").cast(T.StringType()).alias("lob_code"),
        F.col("prem_band").cast(T.StringType()).alias("prem_band"),
        F.col("n_policies").cast(T.DoubleType()).alias("n_policies"),
        F.col("n_transactions").cast(T.DoubleType()).alias("n_transactions"),
        F.col("written_eur").cast(T.DoubleType()).alias("written_eur"),
        F.col("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        _as_of_date(params["AsOfDate"]).alias("as_of_date"),
    ).orderBy(F.col("lob_code").asc(), F.col("prem_band").asc())

    return {"rpt.premium_band_summary": result}
```
</details>

