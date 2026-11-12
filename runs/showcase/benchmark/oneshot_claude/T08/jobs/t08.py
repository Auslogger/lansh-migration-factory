"""Job T08: rpt.usp_fraud_flags (legacy T-SQL, estate/tsql/T08_usp_fraud_flags.sql).

Fraud indicators for the SIU: one row for each claim notified in the twelve
months to the reporting date, with indicator flags, a score, a referral band, a
yyyymmdd loss day key and reason text. Output: rpt.claim_fraud_flags (full refresh).

Legacy bugs are reproduced on purpose and marked with '# LANSH-DEFECT'.
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
import pyspark.sql.functions as F


def _ci(col):
    # SQL Server default collation (CI, trailing-space-insensitive) for '=' / '<>'
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    claims_src = inputs["stg.claims"]
    ps = inputs["stg.policy_snapshots"]
    dc = inputs["dw.dim_customer"]

    # @snapshot_date = MAX(snapshot_date) WHERE snapshot_date <= @AsOfDate (NULL -> no policy matches)
    snap = ps.filter(F.col("snapshot_date") <= as_of).agg(F.max("snapshot_date").alias("snap_max"))
    pol = (
        ps.join(snap, ps["snapshot_date"] == snap["snap_max"], "inner")
        .select(
            F.col("policy_id").alias("p_policy_id"),
            F.col("policy_number"),
            F.col("inception_date"),
            F.col("expiry_date"),
            F.col("vehicle_reg"),
        )
    )
    cust = dc.select(F.col("customer_id").alias("dc_customer_id"), F.col("customer_since"))

    # 1. #claims
    c = claims_src.filter(
        (F.col("reported_date") > F.add_months(as_of, -12)) & (F.col("reported_date") <= as_of)
    )
    cl = (
        c.join(pol, c["policy_id"] == pol["p_policy_id"], "left")
        .join(cust, c["customer_id"] == cust["dc_customer_id"], "left")
        .select(
            c["claim_id"], c["claim_number"], c["policy_id"], c["customer_id"], c["lob_code"],
            c["loss_date"], c["reported_date"],
            pol["policy_number"], pol["inception_date"], pol["expiry_date"], pol["vehicle_reg"],
            cust["customer_since"],
        )
    )

    # 2. #flags
    days_exp_to_rep = F.datediff(F.col("reported_date"), F.col("expiry_date"))
    # LANSH-DEFECT: measures from expiry_date, not inception_date (cover start)
    early = F.when((days_exp_to_rep >= 0) & (days_exp_to_rep <= 30), F.lit(1)).otherwise(F.lit(0))

    # vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%' (case-insensitive collation; NULL -> unknown -> 0)
    reg_like = F.col("vehicle_reg").rlike("(?s)^[0-9][0-9].*-[A-Za-z].*-[0-9]")
    invalid_reg = F.when(
        (_ci(F.col("lob_code")) == F.lit("MOT")) & (~reg_like), F.lit(1)
    ).otherwise(F.lit(0))

    new_cust = F.when(
        F.datediff(F.col("loss_date"), F.col("customer_since")) < 180, F.lit(1)
    ).otherwise(F.lit(0))

    # T-SQL SUBSTRING(policy_number, 0, 4) returns only characters 1..3
    pol_prefix = F.substring(F.col("policy_number"), 1, 3)  # LANSH-DEFECT: SUBSTRING(...,0,4) yields 3 chars, so lob codes longer than 3 chars always mismatch
    lob_mismatch = F.when(_ci(pol_prefix) != _ci(F.col("lob_code")), F.lit(1)).otherwise(F.lit(0))

    f = cl.select(
        F.col("claim_id").alias("f_claim_id"),
        early.alias("early_notification_flag"),
        invalid_reg.alias("invalid_reg_flag"),
        new_cust.alias("new_customer_flag"),
        lob_mismatch.alias("lob_mismatch_flag"),
    ).withColumn(
        "fraud_score",
        F.col("early_notification_flag") + F.col("invalid_reg_flag")
        + F.col("new_customer_flag") + F.col("lob_mismatch_flag"),
    )

    # 3. Insert: #claims JOIN #flags ON claim_id
    j = cl.join(f, cl["claim_id"] == f["f_claim_id"], "inner")

    score = F.col("fraud_score")
    band = (
        F.when(score >= 2, F.lit("HIGH"))
        .when(score == 1, F.lit("MEDIUM"))
        .otherwise(F.lit("LOW"))
    )
    reason = F.concat(
        F.lit("Notified "),
        F.date_format(F.col("reported_date"), "dd/MM/yyyy"),
        F.when(score == 0, F.lit(" - no indicators")).otherwise(F.lit(" -")),
        F.when(F.col("early_notification_flag") == 1, F.lit(" EARLY")).otherwise(F.lit("")),
        F.when(F.col("invalid_reg_flag") == 1, F.lit(" REG")).otherwise(F.lit("")),
        F.when(F.col("new_customer_flag") == 1, F.lit(" NEWCUST")).otherwise(F.lit("")),
        F.when(F.col("lob_mismatch_flag") == 1, F.lit(" LOB")).otherwise(F.lit("")),
    )

    out = j.select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.col("policy_id"),
        F.col("policy_number"),
        F.col("customer_id"),
        F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
        F.col("loss_date"),
        F.col("reported_date"),
        F.col("early_notification_flag"),
        F.col("invalid_reg_flag"),
        F.col("new_customer_flag"),
        F.col("lob_mismatch_flag"),
        F.col("fraud_score"),
        band.alias("fraud_band"),
        F.date_format(F.col("loss_date"), "yyyyMMdd").alias("loss_day_key"),
        reason.alias("reason_text"),
        as_of.alias("as_of_date"),
    )

    return {"rpt.claim_fraud_flags": out}
