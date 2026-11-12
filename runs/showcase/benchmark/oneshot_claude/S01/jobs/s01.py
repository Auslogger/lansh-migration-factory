"""S01 claims_enrich.sas -> PySpark.

Claim-level payment history and indicators (dw.claims_enriched).
Reproduces the legacy SAS DATA step semantics exactly, including SAS missing-value
ordering (missing < any number), RETAIN/sum-statement accumulation in keyed order
(_row_seq) using double arithmetic, and MERGE ... IF c (left join, missing keys match).
"""
import datetime

from pyspark.sql import SparkSession, DataFrame
import pyspark.sql.functions as F


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])

    # proc sort stg.claims(keep=...) -> work.claims
    claims = inputs["stg.claims"].select(
        "claim_id", "claim_number", "policy_id", "customer_id", "lob_code",
        "loss_date", "reported_date", "status",
    )

    # proc sort stg.claim_payments(where=(payment_date <= &as_of)) -> work.payments
    pay = inputs["stg.claim_payments"].select(
        "claim_id", "payment_date", "amount", "payment_type", "_row_seq"
    )
    pay = pay.where(
        F.col("payment_date").isNull()  # LANSH-DEFECT: SAS missing date sorts below any date, so undated payments pass the as_of filter
        | (F.col("payment_date") <= F.lit(as_of))
    )

    # data work.pay_summary: by claim_id, rows in _row_seq (keyed) order
    elem = F.struct(
        F.col("_row_seq").alias("seq"),
        F.col("payment_date").alias("pdate"),
        F.col("amount").cast("double").alias("amt"),
        F.upper(F.trim(F.col("payment_type"))).alias("ptype"),
    )
    grouped = pay.groupBy("claim_id").agg(F.array_sort(F.collect_list(elem)).alias("rows"))

    init = F.struct(
        F.lit(0.0).cast("double").alias("n_payments"),
        F.lit(0.0).cast("double").alias("n_recoveries"),
        F.lit(0.0).cast("double").alias("total_paid"),
        F.lit(0.0).cast("double").alias("indemnity_amt"),
        F.lit(0.0).cast("double").alias("expense_amt"),
        F.lit(0.0).cast("double").alias("recovery_amt"),
        F.lit(0.0).cast("double").alias("recovery_flag"),
    )

    def step(acc, x):
        amt = x["amt"]
        ptype = x["ptype"]
        is_rec = amt.isNull() | (amt < F.lit(0.0))  # LANSH-DEFECT: SAS 'amount < 0' is true for missing amount, counted/flagged as a recovery
        return F.struct(
            (acc["n_payments"] + F.lit(1.0)).alias("n_payments"),
            F.when(is_rec, acc["n_recoveries"] + F.lit(1.0)).otherwise(acc["n_recoveries"]).alias("n_recoveries"),
            # sum statement: missing amount treated as 0
            (acc["total_paid"] + F.coalesce(amt, F.lit(0.0))).alias("total_paid"),
            # plain '+': a missing amount makes the running bucket missing for the rest of the claim
            F.when(ptype == F.lit("INDEMNITY"), acc["indemnity_amt"] + amt).otherwise(acc["indemnity_amt"]).alias("indemnity_amt"),
            F.when(ptype == F.lit("EXPENSE"), acc["expense_amt"] + amt).otherwise(acc["expense_amt"]).alias("expense_amt"),
            F.when(ptype == F.lit("RECOVERY"), acc["recovery_amt"] + amt).otherwise(acc["recovery_amt"]).alias("recovery_amt"),
            F.when(is_rec, F.lit(1.0)).otherwise(acc["recovery_flag"]).alias("recovery_flag"),
        )

    summ = grouped.select(
        F.col("claim_id").alias("p_claim_id"),
        F.aggregate(F.col("rows"), init, step).alias("s"),
        F.element_at(F.col("rows"), 1)["pdate"].alias("first_payment_date"),  # LANSH-DEFECT: first payment in keyed order, not earliest date
        F.element_at(F.col("rows"), -1)["pdate"].alias("last_payment_date"),  # LANSH-DEFECT: last payment in keyed order, not latest date
        F.lit(1.0).alias("p_flag"),
    ).select(
        "p_claim_id",
        F.col("s.n_payments").alias("n_payments"),
        F.col("s.n_recoveries").alias("n_recoveries"),
        F.col("s.total_paid").alias("total_paid"),
        F.col("s.indemnity_amt").alias("indemnity_amt"),
        F.col("s.expense_amt").alias("expense_amt"),
        F.col("s.recovery_amt").alias("recovery_amt"),
        F.col("s.recovery_flag").alias("recovery_flag"),
        "first_payment_date", "last_payment_date", "p_flag",
    )

    # merge work.claims(in=c) work.pay_summary(in=p); by claim_id; if c;
    j = claims.join(summ, claims["claim_id"].eqNullSafe(summ["p_claim_id"]), "left")
    p = F.col("p_flag").isNotNull()

    ind = F.col("indemnity_amt")  # LANSH-DEFECT: not zeroed for claims without payments -> stays missing
    exp = F.col("expense_amt")
    rec = F.col("recovery_amt")

    net_paid = F.when(
        ind.isNull() & exp.isNull() & rec.isNull(), F.lit(None).cast("double")
    ).otherwise(F.coalesce(ind, F.lit(0.0)) + F.coalesce(exp, F.lit(0.0)) + F.coalesce(rec, F.lit(0.0)))

    out = j.select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.col("policy_id"),
        F.col("customer_id"),
        F.upper(F.trim(F.col("lob_code"))).alias("lob_code"),
        F.col("loss_date"),
        F.col("reported_date"),
        F.upper(F.trim(F.col("status"))).alias("status"),
        F.when(p, F.col("n_payments")).otherwise(F.lit(0.0)).alias("n_payments"),
        F.when(p, F.col("n_recoveries")).otherwise(F.lit(0.0)).alias("n_recoveries"),
        F.when(p, F.col("total_paid")).otherwise(F.lit(0.0)).alias("total_paid"),
        ind.alias("indemnity_amt"),
        exp.alias("expense_amt"),
        rec.alias("recovery_amt"),
        F.col("first_payment_date"),
        F.col("last_payment_date"),
        F.when(p, F.col("recovery_flag")).otherwise(F.lit(0.0)).alias("recovery_flag"),
        F.when(p, F.lit(1.0)).otherwise(F.lit(0.0)).alias("has_payment"),
        (ind + exp).alias("gross_paid"),  # LANSH-DEFECT: missing for unpaid claims (and when a bucket went missing)
        net_paid.alias("net_paid"),
    )

    return {"dw.claims_enriched": out}
