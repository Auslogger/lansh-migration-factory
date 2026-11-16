# Evidence report: S01

Generated 2026-11-12 02:15 UTC. **Status: MATCH.**

- Legacy code: `estate/sas/S01_claims_enrich.sas` (SHA-256 `a71a8c747de8420f…`)
- Migrated module: `runs/showcase/S01/jobs/s01.py` (SHA-256 `cef22a14495b21a6…`), written by claude (claude-opus-5-5), heal attempt 0
- Traps found: 17 (SAS-01, SAS-02, SAS-03, SAS-05, SAS-06, SAS-07)
- Suspected defects: 7; tests: 5/5 passed; heal attempts: 0
- Claude: 6 calls (0 live), 36,466 input and 32,570 output tokens, $0.89 API-equivalent (not billed), 292 s of model time

## Gate decisions

**Human review: completed and accepted after the run.** The team confirmed review of all recorded gate decisions on 2026-11-16. [Review confirmation](../human_review.json) is pinned to the original gate log. Original agent timings are separate from the later human review.

| Gate | Human acceptance | Reviewer | Review scope | Human reason |
|---|---|---|---|---|
| H1 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Scope, source code, lineage and trap findings | Team confirmed acceptance; original individual rationale not recorded |
| H2 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Contract, comparison policies, defect decisions and protected-column flows | Team confirmed acceptance; original individual rationale not recorded |
| H3 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Generated code, literal guardrails and trap-test results | Team confirmed acceptance; original individual rationale not recorded |
| H4 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Record-level reconciliation, differences, totals and reported outcome | Team confirmed acceptance; original individual rationale not recorded |
| H5 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Wave cut-over, Delta reconciliation, upstream dependencies and SLA evidence | Team confirmed acceptance; original individual rationale not recorded |
| H5 | accepted after the run | Gregory Korchagin, Vansh Agarwal, Charly Martin Avila | Wave cut-over, Delta reconciliation, upstream dependencies and SLA evidence | Team confirmed acceptance; original individual rationale not recorded |

### Original automated run recordings

| Gate | Outcome | Original recorder | Recorded interval | Recording flags | Original recording note |
|---|---|---|---|---|---|
| H1 Scope and lineage | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: lineage agent notes: The payment_date <= &as_of filter (line 36) controls which payments are summed. It does not drop claim rows: every claim on stg.claims appe |
| H2 Contract and bug decisions | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: blank_is_null on dw.claims_enriched.claim_number: SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank val; float_rel on dw.claims_enriched.policy_id: SAS stores eve |
| H3 Code review | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off); warnings read: translator notes: 1. The running sums use ordered windows from the first row to the current one, partitioned by claim_id and ordered by _row_seq. This keeps the |
| H4 Evidence acceptance | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast | development run, approved by the agent (not a person's sign-off) |
| H5 Cut-over | approve | agent:lansh-dev | 0 s | fast, spot-check | development run, approved by the agent (not a person's sign-off) |

## Reconciliation (sandbox run, isolated inputs)

### dw.claims_enriched: MATCH

MATCH: all 2,911 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 2,911 | 2,911 | ok |
| Total of `claim_id` | 877538416.0 | 877538416.0 | ok |
| Total of `policy_id` | 1545784723.0 | 1545784723.0 | ok |
| Total of `customer_id` | 320603454.0 | 320603454.0 | ok |
| Total of `n_payments` | 10200.0 | 10200.0 | ok |
| Total of `n_recoveries` | 218.0 | 218.0 | ok |
| Total of `total_paid` | 12027486.519999985 | 12027486.519999985 | ok |
| Total of `indemnity_amt` | 11425755.96999996 | 11425755.96999996 | ok |
| Total of `expense_amt` | 504317.45999999985 | 504317.45999999985 | ok |
| Total of `recovery_amt` | -197021.5599999999 | -197021.5599999999 | ok |
| Total of `recovery_flag` | 213.0 | 213.0 | ok |
| Total of `has_payment` | 2466.0 | 2466.0 | ok |
| Total of `gross_paid` | 11857100.749999985 | 11857100.749999985 | ok |
| Total of `net_paid` | 11733051.86999999 | 11733051.86999999 | ok |
| Records matched | | | 2,911 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `ad9abf25a1f0` | `ad9abf25a1f0` | identical |

Keys: ['claim_id'].

## Operate (Delta lakehouse, reconciled again)

### dw.claims_enriched: MATCH

MATCH: all 2,911 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 2,911 | 2,911 | ok |
| Total of `claim_id` | 877538416.0 | 877538416.0 | ok |
| Total of `policy_id` | 1545784723.0 | 1545784723.0 | ok |
| Total of `customer_id` | 320603454.0 | 320603454.0 | ok |
| Total of `n_payments` | 10200.0 | 10200.0 | ok |
| Total of `n_recoveries` | 218.0 | 218.0 | ok |
| Total of `total_paid` | 12027486.519999985 | 12027486.519999985 | ok |
| Total of `indemnity_amt` | 11425755.96999996 | 11425755.96999996 | ok |
| Total of `expense_amt` | 504317.45999999985 | 504317.45999999985 | ok |
| Total of `recovery_amt` | -197021.5599999999 | -197021.5599999999 | ok |
| Total of `recovery_flag` | 213.0 | 213.0 | ok |
| Total of `has_payment` | 2466.0 | 2466.0 | ok |
| Total of `gross_paid` | 11857100.749999985 | 11857100.749999985 | ok |
| Total of `net_paid` | 11733051.86999999 | 11733051.86999999 | ok |
| Records matched | | | 2,911 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `ad9abf25a1f0` | `ad9abf25a1f0` | identical |

Keys: ['claim_id'].

## Suspected legacy defects

| Id | Defect | Lines | Rows affected | Amount | Decision |
|---|---|---|---|---|---|
| S01-D1 | Split amounts, gross_paid and net_paid left missing for claims with no payments | 96-104 | 445 | 0.00 | reproduce (agent:lansh-dev) |
| S01-D2 | A missing payment amount wipes out the payment-type bucket for the rest of the claim | 64-103 | 86 | 294434.65 | reproduce (agent:lansh-dev) |
| S01-D3 | First and last payment dates taken from keying order, not from the dates | 35-78 | 73 |  | reproduce (agent:lansh-dev) |
| S01-D4 | Payments with a missing payment_date get past the reporting-date filter | 36-78 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S01-D5 | Recoveries identified by a negative amount, not by payment_type | 67-75 | 0 |  | reproduce (agent:lansh-dev) |
| S01-D6 | Payment types outside the three known values are dropped from the split and from gross/net paid | 67-104 | 0 | 0.00 | reproduce (agent:lansh-dev) |
| S01-D7 | Duplicate claim_id on the register produces repeated output rows | 28-90 | 0 | 0.00 | reproduce (agent:lansh-dev) |

## Contract

`silver.claims_enriched` (silver), from `dw.claims_enriched`. Grain: One row per claim on the claims register (stg.claims), with its payment history rolled up to the reporting date (as_of); claims with no payments yet are kept too.
Key: ['claim_id']; partitions: ['lob_code', 'status'].
| Column | Policy | Reason |
|---|---|---|
| claim_number | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| policy_id | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| customer_id | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| lob_code | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| status | blank_is_null | SAS character values are blank-padded and SAS has no empty string: trailing blanks are padding and a blank value is missing, so blank and NULL are the same value |
| n_payments | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| n_recoveries | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| total_paid | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| indemnity_amt | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| expense_amt | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| recovery_amt | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| recovery_flag | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| has_payment | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| gross_paid | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |
| net_paid | float_rel | SAS stores every number as an 8-byte double and adds them in input order; a migrated sum or ratio may differ in the last bits, so values agree within a relative 1e-9 |

## Traps found

| Trap | Lines | Found by | Confidence | Note |
|---|---|---|---|---|
| SAS-01 | 36-36 | llm | 0.75 | In SAS a missing payment_date counts as smaller than any date, so payment_date <= &as_of keeps rows with no date. A Spark filter drops them, so the translation needs an explicit isNull() OR. |
| SAS-03 | 36-36 | llm | 0.70 | &as_of is a SAS day count (days since 1960) compared with payment_date. In Spark it has to become a date literal, or the column has to be converted, before the comparison. |
| SAS-06 | 48-49 | llm | 0.90 | The accumulators and the first/last dates are retained across rows and reset at first.claim_id. The result depends on the row order (claim_id, _row_seq), so Spark needs an ordered window or an aggrega |
| SAS-07 | 52-52 | llm | 0.90 | first.claim_id resets the counters, and first_payment_date is the payment_date of the first row in _row_seq order, not the earliest date. Spark needs a window ordered by _row_seq. |
| SAS-06 | 63-63 | llm | 0.70 | The sum statement n_payments + 1 is implicitly retained and counts every row, including rows kept with a missing date. |
| SAS-02 | 64-64 | llm | 0.80 | The sum statement treats a missing amount as 0, so total_paid is never missing. In Spark this means a NULL-skipping F.sum or a coalesce. |
| SAS-06 | 64-64 | llm | 0.80 | The sum statement total_paid + amount is retained and accumulates in row order within the claim. |
| SAS-02 | 68-68 | llm | 0.80 | indemnity_amt = indemnity_amt + amount uses plain +, so one missing amount makes indemnity_amt missing for the rest of the claim. F.sum would skip the NULL and give a different result. |
| SAS-02 | 69-69 | llm | 0.80 | In expense_amt = expense_amt + amount, + propagates a missing amount for the rest of the claim. F.sum would not reproduce this. |
| SAS-02 | 70-70 | llm | 0.80 | In recovery_amt = recovery_amt + amount, + propagates a missing amount for the rest of the claim. F.sum would not reproduce this. |
| SAS-01 | 73-73 | llm | 0.85 | In SAS, amount < 0 is true when amount is missing, so a payment with no amount sets recovery_flag and adds to n_recoveries. A Spark when() treats it as false. |
| SAS-06 | 75-75 | llm | 0.70 | n_recoveries + 1 is retained and reset per claim. It is part of the carried state that has to become a conditional count. |
| SAS-07 | 78-79 | llm | 0.90 | last_payment_date is the payment_date of the last row in _row_seq order (not the maximum date), and it is output at last.claim_id. Spark needs a last value over a window ordered by _row_seq. |
| SAS-01 | 88-89 | llm | 0.35 | Latent: MERGE BY matches a missing claim_id with a missing claim_id, but a Spark equi-join never matches NULL keys. The translation would need a null-safe join if any keys are missing. |
| SAS-05 | 88-90 | llm | 0.90 | This MERGE with in= flags and 'if c' is a left join from claims to pay_summary. has_payment = p comes from the in= flag, and claims with no payments keep missing values in the pay_summary columns. |
| SAS-02 | 103-103 | llm | 0.85 | gross_paid uses +, so it is missing for claims with no payments (their indemnity_amt and expense_amt are not reset to 0) and for claims where an amount was missing. The translation must not coalesce. |
| SAS-02 | 104-104 | llm | 0.85 | sum() skips missing arguments and is missing only if all three are missing, so it is missing for claims with no payments. Spark needs coalesce logic that keeps NULL only when every argument is NULL. |

## Lineage

| Output column | Derived from | sqlglot agrees |
|---|---|---|
| claim_id | stg.claims.claim_id | - |
| claim_number | stg.claims.claim_number | - |
| policy_id | stg.claims.policy_id | - |
| customer_id | stg.claims.customer_id | - |
| lob_code | stg.claims.lob_code | - |
| loss_date | stg.claims.loss_date | - |
| reported_date | stg.claims.reported_date | - |
| status | stg.claims.status | - |
| n_payments | constant, stg.claim_payments.claim_id | - |
| n_recoveries | constant, stg.claim_payments.amount | - |
| total_paid | constant, stg.claim_payments.amount | - |
| indemnity_amt | stg.claim_payments.amount, stg.claim_payments.payment_type | - |
| expense_amt | stg.claim_payments.amount, stg.claim_payments.payment_type | - |
| recovery_amt | stg.claim_payments.amount, stg.claim_payments.payment_type | - |
| first_payment_date | stg.claim_payments.payment_date | - |
| last_payment_date | stg.claim_payments.payment_date | - |
| recovery_flag | constant, stg.claim_payments.amount | - |
| has_payment | stg.claim_payments.claim_id | - |
| gross_paid | stg.claim_payments.amount, stg.claim_payments.payment_type | - |
| net_paid | stg.claim_payments.amount, stg.claim_payments.payment_type | - |

Rows are decided by: stg.claim_payments.claim_id, stg.claim_payments.payment_date, stg.claims.claim_id.

## Tests

| Test | Trap | Expected from | Status | What it sets up |
|---|---|---|---|---|
| S01-SAS-01-1 | SAS-01 | contract | pass | Several payments have no amount (payment_date is NOT NULL, so the testable missing-value case is line 73). In SAS, amount < 0 is true when amount is missing, so those payments set recovery_flag=1 and  |
| S01-SAS-03-2 | SAS-03 | contract | pass | Payment dates sit on both sides of AsOfDate=2025-12-31: exactly on the date (kept), the day after (dropped), well after (dropped), and one before 1960-01-01, which is a negative SAS day count. If &as_ |
| S01-SAS-06-3 | SAS-06 | contract | pass | Payments were keyed out of date order, and the rows of different claims are interleaved in _row_seq. The retained first_payment_date and last_payment_date take the dates of the first and last rows by  |
| S01-SAS-02-4 | SAS-02 | contract | pass | Some typed payments have a missing amount. The sum statement treats it as 0 in total_paid. But the plain + in indemnity_amt, expense_amt and recovery_amt makes that bucket missing for the rest of the  |
| S01-SAS-05-5 | SAS-05 | contract | pass | The MERGE with in= flags and 'if c' is a left join from the register. Claims 3 and 5 have no payments, and claim 6 has only payments after the cutoff. All three must be kept with has_payment=0, the fo |

## Claude usage

| Agent | Calls | Live | Output tokens | Model time | API-equivalent |
|---|---|---|---|---|---|
| contract | 1 | 0 | 789 | 24 s | $0.039 |
| defect_reviewer | 1 | 0 | 6,769 | 59 s | $0.162 |
| lineage | 1 | 0 | 4,889 | 39 s | $0.126 |
| test_author | 1 | 0 | 7,574 | 59 s | $0.189 |
| translator | 1 | 0 | 9,840 | 84 s | $0.271 |
| trap_scan | 1 | 0 | 2,709 | 27 s | $0.105 |

## Code

<details><summary>Legacy code</summary>

```sas
/******************************************************************************
  Program  : claims_enrich.sas
  Purpose  : Claim-level payment history for the risk team. One row per claim
             on the claims register with its payments up to the reporting
             date: payment and recovery counts, paid to date, the paid split
             by payment type (gross, and net of recoveries), the first and
             last payment dates and a recovery marker. Read by the customer
             risk scoring (risk_scoring.sas).
  Inputs   : stg.claims, stg.claim_payments
  Output   : dw.claims_enriched (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : DOS

  Change log
    2014-03-10  DOS   Initial version
    2015-08-24  DOS   Recoveries counted and flagged for the subrogation desk
                      (CR-0611)
    2017-01-16  AK    Paid split by payment type; gross and net paid (CR-1042)
    2018-11-05  AK    Payments dated after the reporting date left out
                      (INC-1677)
    2019-09-30  AK    Line of business and status tidied for the MI pack
                      (CR-1502)
    2021-06-14  SMcC  Claims with nothing paid yet kept, with has_payment, for
                      risk_scoring.sas (CR-1873)
******************************************************************************/

/* claims register */
proc sort data=stg.claims(keep=claim_id claim_number policy_id customer_id lob_code
                               loss_date reported_date status)
          out=work.claims;
  by claim_id;
run;

/* payments to the reporting date, claim by claim in the order they were keyed */
proc sort data=stg.claim_payments(keep=claim_id payment_date amount payment_type _row_seq
                                  where=(payment_date <= &as_of))
          out=work.payments;
  by claim_id _row_seq;
run;

/* roll the payments up to one row per claim */
data work.pay_summary(keep=claim_id n_payments n_recoveries total_paid indemnity_amt
                           expense_amt recovery_amt first_payment_date last_payment_date
                           recovery_flag);
  set work.payments;
  by claim_id;
  length ptype $12;
  retain n_payments n_recoveries total_paid indemnity_amt expense_amt recovery_amt
         first_payment_date last_payment_date recovery_flag;
  format first_payment_date last_payment_date date9.;

  if first.claim_id then do;
    n_payments    = 0;
    n_recoveries  = 0;
    total_paid    = 0;
    indemnity_amt = 0;
    expense_amt   = 0;
    recovery_amt  = 0;
    recovery_flag = 0;
    first_payment_date = payment_date;
  end;

  n_payments + 1;
  total_paid + amount;

  /* paid split by payment type (keyed in mixed case) */
  ptype = upcase(strip(payment_type));
  if ptype = 'INDEMNITY' then indemnity_amt = indemnity_amt + amount;
  else if ptype = 'EXPENSE' then expense_amt = expense_amt + amount;
  else if ptype = 'RECOVERY' then recovery_amt = recovery_amt + amount;

  /* recoveries (salvage, third-party) come through as negative amounts */
  if amount < 0 then do;
    recovery_flag = 1;
    n_recoveries + 1;
  end;

  last_payment_date = payment_date;
  if last.claim_id then output;
run;

/* enrich the register: every claim is reported, paid or not */
data dw.claims_enriched(keep=claim_id claim_number policy_id customer_id lob_code
                             loss_date reported_date status n_payments n_recoveries
                             total_paid indemnity_amt expense_amt recovery_amt gross_paid
                             net_paid first_payment_date last_payment_date recovery_flag
                             has_payment);
  merge work.claims(in=c) work.pay_summary(in=p);
  by claim_id;
  if c;

  lob_code = upcase(strip(lob_code));
  status   = upcase(strip(status));

  has_payment = p;
  if not p then do;
    n_payments    = 0;
    n_recoveries  = 0;
    total_paid    = 0;
    recovery_flag = 0;
  end;

  gross_paid = indemnity_amt + expense_amt;
  net_paid   = sum(indemnity_amt, expense_amt, recovery_amt);
run;

proc datasets lib=work nolist;
  delete claims payments pay_summary;
quit;
```
</details>

<details><summary>Migrated PySpark</summary>

```python
"""S01 claims_enrich: migrated from estate/sas/S01_claims_enrich.sas.

Legacy SHA-256: a71a8c747de8420f546fc5f245477ce9bcd7afe35d35e74a57235ce04d145b1b
Written by: LANSH translator (Claude)
Traps handled: SAS-01, SAS-02, SAS-03, SAS-05, SAS-06, SAS-07
Bugs reproduced on purpose (# LANSH-DEFECT): S01-D1 split/gross/net missing for unpaid claims; S01-D2 missing amount wipes the type bucket; S01-D3 first/last dates from keying order; S01-D4 undated payments pass the as-of filter; S01-D5 recoveries by negative amount; S01-D6 unknown payment types dropped from split; S01-D7 duplicate claim_id rows repeated
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


def _sas_char(col):
    # SAS char: trailing blanks never count, a blank value is missing (NULL)
    c = F.rtrim(col)
    return F.when(c == F.lit(""), F.lit(None).cast(T.StringType())).otherwise(c)


def _upcase_strip(col):
    # upcase(strip(x)); a blank result is missing
    c = F.upper(F.trim(col))
    return F.when(c == F.lit(""), F.lit(None).cast(T.StringType())).otherwise(c)


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    # SAS-03: &as_of (a SAS day count) becomes a date literal
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    # ---- lines 28-32: proc sort stg.claims by claim_id (no NODUPKEY) ----
    claims = inputs["stg.claims"].select(  # LANSH-DEFECT: S01-D7 duplicate claim_id rows are kept (no NODUPKEY)
        "claim_id", "claim_number", "policy_id", "customer_id", "lob_code",
        "loss_date", "reported_date", "status",
    )

    # ---- lines 35-39: payments up to the reporting date ----
    pay = inputs["stg.claim_payments"].select(
        F.col("claim_id"),
        F.col("payment_date"),
        F.col("amount").cast(T.DoubleType()).alias("amount"),
        F.col("payment_type"),
        F.col("_row_seq"),
    )
    # SAS-01: a missing payment_date is smaller than any date, so it passes <=
    pay = pay.filter(
        F.col("payment_date").isNull() | (F.col("payment_date") <= as_of)  # LANSH-DEFECT: S01-D4 undated payments pass the reporting-date filter
    )

    # ---- lines 42-80: roll up per claim in (claim_id, _row_seq) order ----
    amount = F.col("amount")
    ptype = F.upper(F.trim(F.col("payment_type")))
    # LANSH-DEFECT: S01-D6 payment types other than INDEMNITY/EXPENSE/RECOVERY (or missing) go into no split bucket
    is_ind = F.coalesce(ptype == F.lit("INDEMNITY"), F.lit(False))
    is_exp = F.coalesce(ptype == F.lit("EXPENSE"), F.lit(False))
    is_rec = F.coalesce(ptype == F.lit("RECOVERY"), F.lit(False))

    # SAS-06 / SAS-07: ordered running window, reset per claim (first.claim_id)
    w = (
        Window.partitionBy("claim_id")
        .orderBy(F.col("_row_seq").asc())
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    w_last = Window.partitionBy("claim_id").orderBy(F.col("_row_seq").desc())

    def _bucket(cond):
        # SAS-02: x = x + amount starting from 0; one missing amount makes x missing for the rest of the claim
        running = F.sum(F.when(cond, amount)).over(w)
        hit_null = F.max(F.when(cond & amount.isNull(), F.lit(1)).otherwise(F.lit(0))).over(w)
        return F.when(hit_null == F.lit(1), F.lit(None).cast(T.DoubleType())).otherwise(  # LANSH-DEFECT: S01-D2 a missing amount wipes out the bucket for the rest of the claim
            F.coalesce(running, F.lit(0.0))
        )

    # SAS-01: amount < 0 is true when amount is missing
    neg_amt = amount.isNull() | (amount < F.lit(0.0))  # LANSH-DEFECT: S01-D5 recoveries counted by negative (or missing) amount, not by payment_type

    rolled = pay.select(
        F.col("claim_id"),
        # SAS-06: n_payments + 1 counts every row (including undated ones)
        F.count(F.lit(1)).over(w).cast(T.DoubleType()).alias("n_payments"),
        F.sum(F.when(neg_amt, F.lit(1.0)).otherwise(F.lit(0.0))).over(w).alias("n_recoveries"),
        # SAS-02 / SAS-06: sum statement treats a missing amount as 0, accumulated in _row_seq order
        F.sum(F.coalesce(amount, F.lit(0.0))).over(w).alias("total_paid"),
        _bucket(is_ind).alias("indemnity_amt"),
        _bucket(is_exp).alias("expense_amt"),
        _bucket(is_rec).alias("recovery_amt"),
        # SAS-07: first row's payment_date in _row_seq order (may be missing)
        F.first(F.col("payment_date"), ignorenulls=False).over(w).alias("first_payment_date"),  # LANSH-DEFECT: S01-D3 first payment date from keying order, not earliest date
        F.col("payment_date").alias("last_payment_date"),  # LANSH-DEFECT: S01-D3 last payment date from keying order, not latest date
        F.max(F.when(neg_amt, F.lit(1.0)).otherwise(F.lit(0.0))).over(w).alias("recovery_flag"),
        F.row_number().over(w_last).alias("_rn_last"),
    )
    # SAS-07: output at last.claim_id
    pay_summary = rolled.filter(F.col("_rn_last") == F.lit(1)).select(
        F.col("claim_id").alias("_p_claim_id"),
        "n_payments", "n_recoveries", "total_paid", "indemnity_amt", "expense_amt",
        "recovery_amt", "first_payment_date", "last_payment_date", "recovery_flag",
        F.lit(1).alias("_p"),
    )

    # ---- lines 83-105: merge claims(in=c) pay_summary(in=p); by claim_id; if c ----
    # SAS-05: left join from claims; SAS-01: MERGE BY matches missing keys, so null-safe join
    j = claims.join(
        pay_summary,
        claims["claim_id"].eqNullSafe(pay_summary["_p_claim_id"]),
        "left",
    )
    p = F.col("_p").isNotNull()

    indemnity = F.col("indemnity_amt")  # LANSH-DEFECT: S01-D1 split amounts left missing for claims with no payments
    expense = F.col("expense_amt")
    recovery = F.col("recovery_amt")

    # SAS-02: gross_paid uses + (missing propagates)
    gross_paid = indemnity + expense  # LANSH-DEFECT: S01-D1/S01-D2 gross_paid missing for unpaid claims or after a missing amount
    # SAS-02: sum() skips missing values, missing only when all are missing
    net_paid = F.when(  # LANSH-DEFECT: S01-D1 net_paid missing for unpaid claims
        indemnity.isNull() & expense.isNull() & recovery.isNull(),
        F.lit(None).cast(T.DoubleType()),
    ).otherwise(
        F.coalesce(indemnity, F.lit(0.0)) + F.coalesce(expense, F.lit(0.0)) + F.coalesce(recovery, F.lit(0.0))
    )

    out = j.select(
        F.col("claim_id").cast(T.DoubleType()).alias("claim_id"),
        _sas_char(F.col("claim_number")).alias("claim_number"),
        F.col("policy_id").cast(T.DoubleType()).alias("policy_id"),
        F.col("customer_id").cast(T.DoubleType()).alias("customer_id"),
        _upcase_strip(F.col("lob_code")).alias("lob_code"),
        F.col("loss_date").alias("loss_date"),
        F.col("reported_date").alias("reported_date"),
        _upcase_strip(F.col("status")).alias("status"),
        F.when(p, F.col("n_payments")).otherwise(F.lit(0.0)).alias("n_payments"),
        F.when(p, F.col("n_recoveries")).otherwise(F.lit(0.0)).alias("n_recoveries"),
        F.when(p, F.col("total_paid")).otherwise(F.lit(0.0)).alias("total_paid"),
        indemnity.alias("indemnity_amt"),
        expense.alias("expense_amt"),
        recovery.alias("recovery_amt"),
        F.col("first_payment_date").alias("first_payment_date"),
        F.col("last_payment_date").alias("last_payment_date"),
        F.when(p, F.col("recovery_flag")).otherwise(F.lit(0.0)).alias("recovery_flag"),
        F.when(p, F.lit(1.0)).otherwise(F.lit(0.0)).alias("has_payment"),
        gross_paid.alias("gross_paid"),
        net_paid.alias("net_paid"),
    )

    # ---- lines 107-109: work data sets deleted (nothing to do) ----
    return {"dw.claims_enriched": out}
```
</details>

