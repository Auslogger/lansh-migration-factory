"""X1 usp_broker_production: migrated from estate/holdout/X1_usp_broker_production.sql.

Legacy SHA-256: b683ce412ff6786c3d8aa2e3802be8b05f2943d1fb10d7b6093cab40f2ba01d0
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-07, TSQL-08, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X1-D1 claims paid limited to claims notified in the year; X1-D2 broker dimension joined without deduplication; X1-D3 blank broker codes not mapped to DIRECT; X1-D4 non-EUR premium dropped when no FX rate; X1-D5 recoveries added rather than netted off; X1-D6 duplicate claim rows multiply claims; X1-D7 policies expiring on the as-of date counted as in force
"""
import datetime
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def _ci(col):
    # TSQL-01 / TSQL-02: CI collation and trailing-space-insensitive comparison key
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    year_start = datetime.date(as_of.year, 1, 1)  # DATEFROMPARTS(YEAR(@AsOfDate), 1, 1)
    as_of_lit = F.lit(as_of)
    ys_lit = F.lit(year_start)

    snaps = inputs["stg.policy_snapshots"]
    products = inputs["stg.products"]
    txns = inputs["stg.premium_transactions"]
    fx_rates = inputs["stg.fx_rates"]
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    brokers = inputs["stg.brokers"]

    # ---- #pol (TSQL-13): latest snapshot on or before the as-of date
    s = snaps.where(F.col("snapshot_date") <= as_of_lit).alias("s")
    p = products.alias("p")
    pol_src = s.join(
        p,
        _ci(F.col("s.product_code")) == _ci(F.col("p.product_code")),  # TSQL-01 / TSQL-02
        "inner",
    ).select(
        F.col("s.policy_id").alias("policy_id"),
        F.coalesce(F.upper(F.ltrim(F.rtrim(F.col("s.broker_code")))), F.lit("DIRECT")).alias("broker_code"),  # LANSH-DEFECT: X1-D3 blank/all-space broker code stays '' (only NULL becomes DIRECT)
        F.upper(F.rtrim(F.col("p.lob_code"))).alias("lob_code"),
        F.col("s.inception_date").alias("inception_date"),
        F.col("s.expiry_date").alias("expiry_date"),
        F.col("s.cancellation_date").alias("cancellation_date"),
        F.col("s.snapshot_date").alias("snapshot_date"),
        F.col("s._row_seq").alias("s_row_seq"),
        F.col("p._row_seq").alias("p_row_seq"),
    )
    w_pol = Window.partitionBy("policy_id").orderBy(
        F.col("snapshot_date").desc(), F.col("s_row_seq").desc(), F.col("p_row_seq").asc()
    )
    pol = (
        pol_src.withColumn("rn", F.row_number().over(w_pol))
        .where(F.col("rn") == 1)
        .select("policy_id", "broker_code", "lob_code", "inception_date", "expiry_date", "cancellation_date")
    )

    # ---- #inforce (TSQL-13)
    inforce = (
        pol.where(
            (F.col("inception_date") <= as_of_lit)
            & (F.col("expiry_date") >= as_of_lit)  # LANSH-DEFECT: X1-D7 policy expiring on the as-of date counted as in force
            & (F.col("cancellation_date").isNull() | (F.col("cancellation_date") > as_of_lit))
        )
        .groupBy("broker_code", "lob_code")
        .agg(F.count(F.lit(1)).alias("policies_in_force"))
    )

    # ---- #gwp (TSQL-13), OUTER APPLY TOP 1 fx rate (TSQL-09 / TSQL-08)
    t = txns.where((F.col("txn_date") >= ys_lit) & (F.col("txn_date") <= as_of_lit)).select(
        F.col("policy_id").alias("t_policy_id"),
        F.col("txn_date").alias("t_txn_date"),
        F.col("amount").cast("decimal(12,2)").alias("t_amount"),
        F.col("currency").alias("t_currency"),
        F.col("_row_seq").alias("t_row_seq"),
    )
    tp = t.join(
        pol.select("policy_id", "broker_code", "lob_code"),
        F.col("t_policy_id") == F.col("policy_id"),
        "inner",
    )
    fx = fx_rates.select(
        F.col("currency").alias("f_currency"),
        F.col("rate_date").alias("f_rate_date"),
        F.col("rate_to_eur").cast("decimal(18,8)").alias("f_rate"),
        F.col("_row_seq").alias("f_row_seq"),
    )
    tpf = tp.join(
        fx,
        (_ci(F.col("f_currency")) == _ci(F.col("t_currency")))  # TSQL-01 / TSQL-02
        & (F.col("f_rate_date") <= F.col("t_txn_date")),
        "left",  # LANSH-DEFECT: X1-D4 OUTER APPLY keeps transactions with no rate; their NULL product is skipped by SUM
    )
    w_fx = Window.partitionBy("t_row_seq").orderBy(F.col("f_rate_date").desc(), F.col("f_row_seq").desc())
    tpf = tpf.withColumn("fx_rn", F.row_number().over(w_fx)).where(F.col("fx_rn") == 1)
    rate_or_one = F.when(_ci(F.col("t_currency")) == F.lit("EUR"), F.lit(1).cast("decimal(18,8)")).otherwise(
        F.col("f_rate")
    )
    gwp = tpf.groupBy("broker_code", "lob_code").agg(
        # decimal(12,2) * decimal(18,8) -> decimal(31,10); SUM -> decimal(38,10) (TSQL-07)
        F.sum((F.col("t_amount") * rate_or_one).cast("decimal(31,10)")).cast("decimal(38,10)").alias("gwp_eur")  # LANSH-DEFECT: X1-D4 non-EUR premium without fx rate silently dropped
    )

    # ---- #clm (TSQL-13)
    c = claims.where((F.col("reported_date") >= ys_lit) & (F.col("reported_date") <= as_of_lit)).select(  # LANSH-DEFECT: X1-D1 only claims reported in the year
        F.col("claim_id").alias("c_claim_id"),
        F.col("policy_id").alias("c_policy_id"),
    )
    clm = c.join(  # LANSH-DEFECT: X1-D6 stg.claims not deduplicated by claim_id
        pol.select("policy_id", "broker_code", "lob_code"),
        F.col("c_policy_id") == F.col("policy_id"),
        "inner",
    ).select(F.col("c_claim_id").alias("claim_id"), "broker_code", "lob_code")

    # ---- #notified (TSQL-13)
    notified = clm.groupBy("broker_code", "lob_code").agg(F.count(F.lit(1)).alias("claims_notified"))

    # ---- #paid (TSQL-13)
    cp = payments.where((F.col("payment_date") >= ys_lit) & (F.col("payment_date") <= as_of_lit)).select(
        F.col("claim_id").alias("cp_claim_id"),
        F.col("amount").cast("decimal(12,2)").alias("cp_amount"),
    )
    paid = (
        cp.join(clm, F.col("cp_claim_id") == F.col("claim_id"), "inner")  # LANSH-DEFECT: X1-D1 payments on claims reported before the year dropped; X1-D6 duplicate claim rows repeat payments
        .groupBy("broker_code", "lob_code")
        .agg(
            F.sum(F.coalesce(F.col("cp_amount"), F.lit(0).cast("decimal(12,2)")))  # LANSH-DEFECT: X1-D5 all payment types summed, recoveries not netted off
            .cast("decimal(38,2)")
            .alias("claims_paid_eur")
        )
    )

    # ---- #keys (TSQL-13): UNION removes duplicates
    keys = (
        inforce.select("broker_code", "lob_code")
        .union(gwp.select("broker_code", "lob_code"))
        .union(notified.select("broker_code", "lob_code"))
        .union(paid.select("broker_code", "lob_code"))
        .distinct()
    )

    # ---- #ratio (TSQL-13 / TSQL-07)
    ratio_src = (
        keys.join(gwp, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .groupBy("broker_code")
        .agg(
            F.sum(F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)"))).cast("decimal(38,2)").alias("num"),
            F.sum(F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)"))).cast("decimal(38,10)").alias("den"),
        )
    )
    # T-SQL: decimal(38,2) / decimal(38,10) -> decimal(38,6), truncated toward zero; then CAST to decimal(12,4) rounds half up.
    # Exact truncation at 6 places via integral division of num * 1000000 by den (truncates toward zero).
    ratio = (
        ratio_src.withColumn("den_nz", F.when(F.col("den") != 0, F.col("den")))
        .withColumn(
            "q6",
            F.expr("(CAST(num AS DECIMAL(38,10)) * 1000000) div CAST(den_nz AS DECIMAL(38,10))"),
        )
        .withColumn(
            "paid_to_written",
            (F.col("q6").cast("decimal(20,0)") / F.lit(1000000).cast("decimal(10,0)")).cast("decimal(12,4)"),
        )
        .select("broker_code", "paid_to_written")
    )

    # ---- final insert
    b = brokers.select(
        F.col("broker_code").alias("b_broker_code"),
        F.col("broker_name").alias("b_broker_name"),
        F.col("status").alias("b_status"),
    )
    out = (
        keys.join(b, _ci(F.col("broker_code")) == _ci(F.col("b_broker_code")), "left")  # LANSH-DEFECT: X1-D2 brokers joined without dedup, duplicate broker rows repeat output rows; TSQL-01 / TSQL-02
        .join(inforce, ["broker_code", "lob_code"], "left")
        .join(gwp, ["broker_code", "lob_code"], "left")
        .join(notified, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .join(ratio, ["broker_code"], "left")
    )
    result = out.select(
        as_of_lit.alias("as_of_date"),
        F.col("broker_code"),
        F.col("b_broker_name").alias("broker_name"),
        F.upper(F.rtrim(F.col("b_status"))).alias("broker_status"),
        F.col("lob_code"),
        F.coalesce(F.col("policies_in_force").cast("int"), F.lit(0)).alias("policies_in_force"),
        F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)")).cast("decimal(14,2)").alias("gwp_eur"),
        F.coalesce(F.col("claims_notified").cast("int"), F.lit(0)).alias("claims_notified"),
        F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)")).cast("decimal(14,2)").alias("claims_paid_eur"),
        F.col("paid_to_written"),
        F.rpad(
            F.when(F.col("paid_to_written") > F.lit(Decimal("0.75")), F.lit("Y")).otherwise(F.lit("N")), 1, " "
        ).alias("review_flag"),
    )

    return {"rpt.broker_production": result}
