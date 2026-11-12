"""T08 usp_fraud_flags: migrated from estate/tsql/T08_usp_fraud_flags.sql.

Legacy SHA-256: 6e90a4a5ad66f2169982f70407d488edd7b7e0053a0617f71b9e9947cb9de886
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-13, TSQL-14, TSQL-15, TSQL-16, TSQL-18
Bugs reproduced on purpose (# LANSH-DEFECT): T08-D1 early notification from expiry date, T08-D2 policies missing from latest snapshot score 0, T08-D3 new-customer window hard-coded 180 days, T08-D4 LOB prefix only 3 characters, T08-D5 missing motor registration not flagged
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
import pyspark.sql.functions as F


def _dateadd_month(d: datetime.date, n: int) -> datetime.date:
    """T-SQL DATEADD(MONTH, n, d): clamp the day only when the target month is shorter (TSQL-18)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    if mo == 12:
        nxt = datetime.date(y + 1, 1, 1)
    else:
        nxt = datetime.date(y, mo + 1, 1)
    last_day = (nxt - datetime.timedelta(days=1)).day
    return datetime.date(y, mo, min(d.day, last_day))


def _ci(c):
    """Comparison key under the CI collation, ignoring trailing spaces (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(c))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_of_lit = F.lit(as_of)
    # TSQL-18: DATEADD(MONTH, -12, @AsOfDate) computed with T-SQL clamping rules
    window_start = F.lit(_dateadd_month(as_of, -12))

    claims_src = inputs["stg.claims"]
    ps = inputs["stg.policy_snapshots"]
    dc = inputs["dw.dim_customer"]

    # @snapshot_date = MAX(snapshot_date) on or before @AsOfDate (NULL if none -> no policy rows match)
    snap = (ps.where(F.col("snapshot_date") <= as_of_lit)
              .agg(F.max("snapshot_date").alias("_snapshot_date")))  # LANSH-DEFECT: T08-D2 single global latest snapshot for every claim
    pol = (ps.join(snap, F.col("snapshot_date") == F.col("_snapshot_date"), "inner")
             .select(F.col("policy_id").alias("_p_policy_id"),
                     F.col("policy_number"),
                     F.col("inception_date"),
                     F.col("expiry_date"),
                     F.col("vehicle_reg")))

    cust = dc.select(F.col("customer_id").alias("_dc_customer_id"), F.col("customer_since"))

    # 1. #claims (TSQL-13): claims notified in the 12 months to the reporting date
    c = claims_src.where((F.col("reported_date") > window_start) & (F.col("reported_date") <= as_of_lit))
    claims = (c.join(pol, F.col("policy_id") == F.col("_p_policy_id"), "left")  # LANSH-DEFECT: T08-D2 policy missing from snapshot leaves NULL policy details
               .join(cust, F.col("customer_id") == F.col("_dc_customer_id"), "left")
               .select(F.col("claim_id"),
                       F.col("claim_number"),
                       F.col("policy_id"),
                       F.col("customer_id"),
                       F.col("lob_code"),
                       F.col("loss_date"),
                       F.col("reported_date"),
                       F.col("policy_number"),
                       F.col("inception_date"),
                       F.col("expiry_date"),
                       F.col("vehicle_reg"),
                       F.col("customer_since")))

    # 2. #flags (TSQL-13)
    early_flag = F.when(
        F.datediff(F.col("reported_date"), F.col("expiry_date")).between(0, 30), F.lit(1)  # LANSH-DEFECT: T08-D1 measured from expiry_date, not inception_date
    ).otherwise(F.lit(0))

    is_motor = _ci(F.col("lob_code")) == F.lit("MOT")  # TSQL-01 / TSQL-02
    # TSQL-14: LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%' as an anchored, case-insensitive regex (% matches anything, incl. newlines)
    reg_matches = F.col("vehicle_reg").rlike("(?is)^[0-9][0-9].*-[A-Z].*-[0-9]")
    invalid_reg_flag = F.when(is_motor & ~reg_matches, F.lit(1)).otherwise(F.lit(0))  # LANSH-DEFECT: T08-D5 NULL vehicle_reg is UNKNOWN -> 0 (also T08-D2)

    new_customer_flag = F.when(
        F.datediff(F.col("loss_date"), F.col("customer_since")) < 180, F.lit(1)  # LANSH-DEFECT: T08-D3 six months hard-coded as 180 days
    ).otherwise(F.lit(0))

    # TSQL-15: SUBSTRING(policy_number, 0, 4) returns the first 3 characters
    lob_mismatch_flag = F.when(
        _ci(F.substring(F.col("policy_number"), 1, 3)) != _ci(F.col("lob_code")), F.lit(1)  # LANSH-DEFECT: T08-D4 only 3-char prefix compared; NULL policy_number -> 0 (T08-D2)
    ).otherwise(F.lit(0))

    flags = (claims.select(F.col("claim_id").alias("_f_claim_id"),
                           early_flag.alias("early_notification_flag"),
                           invalid_reg_flag.alias("invalid_reg_flag"),
                           new_customer_flag.alias("new_customer_flag"),
                           lob_mismatch_flag.alias("lob_mismatch_flag"))
                   .withColumn("fraud_score",
                               F.col("early_notification_flag") + F.col("invalid_reg_flag")
                               + F.col("new_customer_flag") + F.col("lob_mismatch_flag")))

    # 3. Insert: #claims JOIN #flags ON claim_id
    joined = claims.join(flags, F.col("claim_id") == F.col("_f_claim_id"), "inner")

    fraud_band = (F.when(F.col("fraud_score") >= 2, F.lit("HIGH"))
                   .when(F.col("fraud_score") == 1, F.lit("MEDIUM"))
                   .otherwise(F.lit("LOW")))

    # TSQL-16: style 112 -> yyyyMMdd, CHAR(8) padded (TSQL-02)
    loss_day_key = F.rpad(F.date_format(F.col("loss_date"), "yyyyMMdd"), 8, " ")

    # TSQL-16: style 103 -> dd/MM/yyyy; + concatenation is NULL if any part is NULL (F.concat)
    reason_text = F.concat(
        F.lit("Notified "),
        F.substring(F.date_format(F.col("reported_date"), "dd/MM/yyyy"), 1, 10),
        F.when(F.col("fraud_score") == 0, F.lit(" - no indicators")).otherwise(F.lit(" -")),
        F.when(F.col("early_notification_flag") == 1, F.lit(" EARLY")).otherwise(F.lit("")),
        F.when(F.col("invalid_reg_flag") == 1, F.lit(" REG")).otherwise(F.lit("")),
        F.when(F.col("new_customer_flag") == 1, F.lit(" NEWCUST")).otherwise(F.lit("")),
        F.when(F.col("lob_mismatch_flag") == 1, F.lit(" LOB")).otherwise(F.lit("")),
    )

    out = joined.select(
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
        fraud_band.alias("fraud_band"),
        loss_day_key.alias("loss_day_key"),
        reason_text.alias("reason_text"),
        as_of_lit.alias("as_of_date"),
    )

    return {"rpt.claim_fraud_flags": out}
