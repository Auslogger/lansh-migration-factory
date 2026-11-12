"""X1 usp_broker_production: migrated from estate/holdout/X1_usp_broker_production.sql.

Legacy SHA-256: b683ce412ff6786c3d8aa2e3802be8b05f2943d1fb10d7b6093cab40f2ba01d0
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-07, TSQL-08, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X1-D1 claims paid limited to claims notified in the year, X1-D2 broker dimension joined without deduplication, X1-D3 blank broker codes not mapped to DIRECT, X1-D4 non-EUR premium dropped when no FX rate, X1-D5 recoveries added not netted, X1-D6 duplicate claim rows multiply counts and payments, X1-D7 policies expiring on the as-of date counted in force
"""
import datetime
import decimal

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
    fx = inputs["stg.fx_rates"]
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    brokers = inputs["stg.brokers"]

    # ---- #pol (TSQL-13): latest snapshot on or before the as-of date ----
    s = snaps.where(F.col("snapshot_date") <= as_of_lit).alias("s")
    p = products.alias("p")
    sp = s.join(p, _ci(F.col("s.product_code")) == _ci(F.col("p.product_code")), "inner")  # TSQL-01/02
    w_pol = Window.partitionBy(F.col("s.policy_id")).orderBy(
        F.col("s.snapshot_date").desc(), F.col("s._row_seq").desc(), F.col("p._row_seq").desc()
    )
    pol = (
        sp.select(
            F.col("s.policy_id").alias("policy_id"),
            F.coalesce(F.upper(F.ltrim(F.rtrim(F.col("s.broker_code")))), F.lit("DIRECT")).alias("broker_code"),  # LANSH-DEFECT: X1-D3 blank/space-only broker code becomes '' not DIRECT
            F.upper(F.rtrim(F.col("p.lob_code"))).alias("lob_code"),
            F.col("s.inception_date").alias("inception_date"),
            F.col("s.expiry_date").alias("expiry_date"),
            F.col("s.cancellation_date").alias("cancellation_date"),
            F.row_number().over(w_pol).alias("rn"),
        )
        .where(F.col("rn") == 1)
        .drop("rn")
    )
    pol_keys = pol.select("policy_id", "broker_code", "lob_code")

    # ---- #inforce (TSQL-13) ----
    inforce = (
        pol.where(
            (F.col("inception_date") <= as_of_lit)
            & (F.col("expiry_date") >= as_of_lit)  # LANSH-DEFECT: X1-D7 policy expiring on the as-of date counted in force
            & (F.col("cancellation_date").isNull() | (F.col("cancellation_date") > as_of_lit))
        )
        .groupBy("broker_code", "lob_code")
        .agg(F.count(F.lit(1)).cast("int").alias("policies_in_force"))
    )

    # ---- #gwp (TSQL-13): OUTER APPLY TOP 1 fx rate (TSQL-09, TSQL-08) ----
    t = txns.where((F.col("txn_date") >= ys_lit) & (F.col("txn_date") <= as_of_lit)).alias("t")
    f = fx.alias("f")
    tf = t.join(
        f,
        (_ci(F.col("f.currency")) == _ci(F.col("t.currency")))  # TSQL-01/02
        & (F.col("f.rate_date") <= F.col("t.txn_date")),
        "left",  # LANSH-DEFECT: X1-D4 OUTER APPLY keeps transactions with no rate (rate NULL)
    )
    w_fx = Window.partitionBy(F.col("t._row_seq")).orderBy(F.col("f.rate_date").desc(), F.col("f._row_seq").desc())
    tf = (
        tf.select(
            F.col("t.policy_id").alias("policy_id"),
            F.col("t.amount").alias("amount"),
            F.col("t.currency").alias("currency"),
            F.col("f.rate_to_eur").alias("rate_to_eur"),
            F.row_number().over(w_fx).alias("rn"),
        )
        .where(F.col("rn") == 1)
        .drop("rn")
    )
    # TSQL-07: CASE -> decimal(18,8); decimal(12,2) * decimal(18,8) -> decimal(31,10); SUM -> decimal(38,10)
    rate = F.when(_ci(F.col("currency")) == F.lit("EUR"), F.lit(1).cast("decimal(18,8)")).otherwise(
        F.col("rate_to_eur").cast("decimal(18,8)")
    )
    gwp_line = (F.col("amount").cast("decimal(12,2)") * rate).cast("decimal(31,10)")  # LANSH-DEFECT: X1-D4 NULL rate makes the product NULL and SUM skips it
    gwp = (
        tf.join(pol_keys, "policy_id", "inner")
        .groupBy("broker_code", "lob_code")
        .agg(F.sum(gwp_line).cast("decimal(38,10)").alias("gwp_eur"))
    )

    # ---- #clm (TSQL-13) ----
    clm = (
        claims.where((F.col("reported_date") >= ys_lit) & (F.col("reported_date") <= as_of_lit))  # LANSH-DEFECT: X1-D1 only claims reported in the year
        .select("claim_id", "policy_id")  # LANSH-DEFECT: X1-D6 claims not deduplicated by claim_id
        .join(pol_keys, "policy_id", "inner")
        .select("claim_id", "broker_code", "lob_code")
    )

    # ---- #notified (TSQL-13) ----
    notified = clm.groupBy("broker_code", "lob_code").agg(F.count(F.lit(1)).cast("int").alias("claims_notified"))

    # ---- #paid (TSQL-13): ISNULL(amount,0) decimal(12,2), SUM -> decimal(38,2) ----
    paid = (
        payments.where((F.col("payment_date") >= ys_lit) & (F.col("payment_date") <= as_of_lit))
        .select("claim_id", "amount")
        .join(clm, "claim_id", "inner")  # LANSH-DEFECT: X1-D1 payments on claims reported in earlier years dropped; X1-D6 duplicate claims multiply payments
        .groupBy("broker_code", "lob_code")
        .agg(
            F.sum(
                F.coalesce(F.col("amount"), F.lit(0).cast("decimal(12,2)")).cast("decimal(38,2)")  # LANSH-DEFECT: X1-D5 every payment_type summed, recoveries not netted
            ).cast("decimal(38,2)").alias("claims_paid_eur")
        )
    )

    # ---- #keys (TSQL-13): UNION removes duplicates ----
    keys = (
        inforce.select("broker_code", "lob_code")
        .union(gwp.select("broker_code", "lob_code"))
        .union(notified.select("broker_code", "lob_code"))
        .union(paid.select("broker_code", "lob_code"))
        .distinct()
    )

    # ---- #ratio (TSQL-13, TSQL-07) ----
    ratio_base = (
        keys.join(gwp, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .groupBy("broker_code")
        .agg(
            F.sum(F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)"))).cast("decimal(38,2)").alias("sum_paid"),
            F.sum(F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)"))).cast("decimal(38,10)").alias("sum_gwp"),
        )
    )
    # NULLIF(sum_gwp, 0); decimal(38,2) / decimal(38,10) -> decimal(38,6) (rounded), then DECIMAL(12,4) (rounded again)
    den = F.when(F.col("sum_gwp") != F.lit(0), F.col("sum_gwp"))
    ratio = ratio_base.select(
        F.col("broker_code"),
        (F.col("sum_paid") / den).cast("decimal(38,6)").cast("decimal(12,4)").alias("paid_to_written"),
    )

    # ---- final insert ----
    b = brokers.select(
        _ci(F.col("broker_code")).alias("_b_key"),  # TSQL-01/02: CHAR(6) padded, case variants
        F.col("broker_name").alias("broker_name"),
        F.upper(F.rtrim(F.col("status"))).alias("broker_status"),
    )
    out = (
        keys.join(b, _ci(F.col("broker_code")) == F.col("_b_key"), "left")  # LANSH-DEFECT: X1-D2 several broker rows per code repeat output rows
        .join(inforce, ["broker_code", "lob_code"], "left")
        .join(gwp, ["broker_code", "lob_code"], "left")
        .join(notified, ["broker_code", "lob_code"], "left")
        .join(paid, ["broker_code", "lob_code"], "left")
        .join(ratio, ["broker_code"], "left")
    )
    result = out.select(
        F.lit(as_of).alias("as_of_date"),
        F.col("broker_code"),
        F.col("broker_name"),
        F.col("broker_status"),
        F.col("lob_code"),
        F.coalesce(F.col("policies_in_force"), F.lit(0)).cast("int").alias("policies_in_force"),
        F.coalesce(F.col("gwp_eur"), F.lit(0).cast("decimal(38,10)")).cast("decimal(14,2)").alias("gwp_eur"),
        F.coalesce(F.col("claims_notified"), F.lit(0)).cast("int").alias("claims_notified"),
        F.coalesce(F.col("claims_paid_eur"), F.lit(0).cast("decimal(38,2)")).cast("decimal(14,2)").alias("claims_paid_eur"),
        F.col("paid_to_written"),
        F.when(F.col("paid_to_written") > F.lit(decimal.Decimal("0.75")), F.lit("Y")).otherwise(F.lit("N")).alias("review_flag"),
    )

    return {"rpt.broker_production": result}
