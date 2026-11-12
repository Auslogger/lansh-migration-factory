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
