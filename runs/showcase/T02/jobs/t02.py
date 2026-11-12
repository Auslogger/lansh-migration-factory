"""T02 usp_load_dim_policy: migrated from estate/tsql/T02_usp_load_dim_policy.sql.

Legacy SHA-256: a9565f4f944b98bb52293b124a852c693d5fad0c7accb5793a9499945f0e2b0f
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-06, TSQL-11, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): T02-D1 duplicate current versions from row-multiplying joins, T02-D2 policies missing from a later snapshot never closed, T02-D3 inner join to stg.products drops unknown products, T02-D4 direct business never gets a broker name, DIRECT-SALES truncated to DIRECT-SAL by ISNULL
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


OUTPUT_COLUMNS = [
    "policy_sk", "policy_id", "policy_number", "customer_id", "customer_segment",
    "product_code", "product_name", "lob_code", "broker_code", "broker_name",
    "status", "inception_date", "expiry_date", "cancellation_date",
    "annual_premium", "currency", "vehicle_reg", "ncd_years", "valid_from",
    "valid_to", "is_current", "source_snapshot_date", "load_ts",
]


def _ci(col):
    """Collation key: case-insensitive, trailing spaces ignored (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    snapshots = inputs["stg.policy_snapshots"]
    products = inputs["stg.products"]
    brokers = inputs["stg.brokers"]
    customers = inputs["dw.dim_customer"]
    prev = inputs["dw.dim_policy"]

    snap_text = params["SnapshotDate"]
    snap_py = datetime.date.fromisoformat(snap_text)
    snap = F.lit(snap_text).cast(T.DateType())

    # Guard: refuse a snapshot older than the last one loaded (INC-2105)
    last_loaded = prev.agg(F.max("source_snapshot_date").alias("m")).first()["m"]
    if last_loaded is not None and snap_py < last_loaded:
        raise RuntimeError("dw.dim_policy already holds a later policy snapshot")

    # 1. #src as a DataFrame (TSQL-13)
    p = snapshots.alias("p")
    pr = products.alias("pr")
    b = brokers.alias("b")
    c = customers.alias("c")
    src = (
        p.where(F.col("p.snapshot_date") == snap)
        # LANSH-DEFECT: T02-D3 inner join silently drops policies whose product is not in stg.products
        .join(pr, _ci(F.col("pr.product_code")) == _ci(F.col("p.product_code")), "inner")
        # LANSH-DEFECT: T02-D4 broker lookup on the original (NULL) broker_code, so direct business has no broker_name
        .join(b, _ci(F.col("b.broker_code")) == _ci(F.col("p.broker_code")), "left")
        # LANSH-DEFECT: T02-D1 nothing makes #src unique per policy_id (duplicate staging / lookup rows multiply)
        .join(c, F.col("c.customer_id") == F.col("p.customer_id"), "left")
        .select(
            F.col("p.policy_id").alias("policy_id"),
            F.col("p.policy_number").alias("policy_number"),
            F.col("p.customer_id").alias("customer_id"),
            F.rpad(F.col("c.segment_code"), 4, " ").alias("customer_segment"),
            F.col("pr.product_code").alias("product_code"),
            F.col("pr.product_name").alias("product_name"),
            F.col("pr.lob_code").alias("lob_code"),
            # LANSH-DEFECT: ISNULL takes VARCHAR(10) of p.broker_code, so 'DIRECT-SALES' becomes 'DIRECT-SAL'
            F.coalesce(F.col("p.broker_code"), F.lit("DIRECT-SALES").substr(1, 10)).alias("broker_code"),
            F.col("b.broker_name").alias("broker_name"),
            F.col("p.status").alias("status"),
            F.col("p.inception_date").alias("inception_date"),
            F.col("p.expiry_date").alias("expiry_date"),
            F.col("p.cancellation_date").alias("cancellation_date"),
            F.col("p.annual_premium").alias("annual_premium"),
            F.col("p.currency").alias("currency"),
            F.col("p.vehicle_reg").alias("vehicle_reg"),
            F.col("p.ncd_years").alias("ncd_years"),
            F.col("p._row_seq").alias("_p_seq"),
            F.col("pr._row_seq").alias("_pr_seq"),
            F.col("b._row_seq").alias("_b_seq"),
        )
    )

    if src.isEmpty():
        raise RuntimeError("No policies found for this snapshot date")

    # 2. MERGE: close changed current versions (TSQL-11)
    tgt_current = prev.where(_ci(F.col("is_current")) == "Y").alias("t")
    s = src.alias("s")

    def _txt_changed(name):
        # ISNULL(src, '') <> ISNULL(tgt, '') under CI collation, trailing spaces ignored
        return _ci(F.coalesce(F.col("s." + name), F.lit(""))) != _ci(F.coalesce(F.col("t." + name), F.lit("")))

    changed_cond = (
        _txt_changed("status")
        | _txt_changed("broker_code")
        | (F.coalesce(F.col("s.annual_premium"), F.lit(0)) != F.coalesce(F.col("t.annual_premium"), F.lit(0)))
        | _txt_changed("vehicle_reg")
    )
    updates = (
        tgt_current.join(s, F.col("t.policy_id") == F.col("s.policy_id"), "inner")
        .where(changed_cond)
        .groupBy(F.col("t.policy_sk").alias("policy_sk"))
        .agg(F.count(F.lit(1)).alias("_n"))
    )
    if not updates.where(F.col("_n") > 1).isEmpty():
        # LANSH-DEFECT: T02-D1 duplicate source rows make the legacy MERGE fail on the same target row
        raise RuntimeError(
            "The MERGE statement attempted to UPDATE or DELETE the same row more than once."
        )

    # LANSH-DEFECT: T02-D2 only WHEN MATCHED: current rows of policies absent from the snapshot stay open
    closed = updates.select("policy_sk", F.lit(True).alias("_closed"))
    prev_after = (
        prev.join(closed, "policy_sk", "left")
        .withColumn("valid_to", F.when(F.col("_closed"), F.date_sub(snap, 1)).otherwise(F.col("valid_to")))
        .withColumn("is_current", F.when(F.col("_closed"), F.lit("N")).otherwise(F.col("is_current")))
        .drop("_closed")
    )

    # 3. INSERT new current versions for policies with no current row (TSQL-11)
    current_ids = prev_after.where(_ci(F.col("is_current")) == "Y").select("policy_id").distinct()
    # LANSH-DEFECT: T02-D1 NOT EXISTS only sees rows already in the table, so every duplicate #src row is opened
    to_open = src.join(current_ids, "policy_id", "left_anti")

    max_sk = prev.agg(F.max("policy_sk").alias("m")).first()["m"]
    if max_sk is None:
        max_sk = 0
    w = Window.orderBy(F.col("policy_id"), F.col("_p_seq"), F.col("_pr_seq"), F.col("_b_seq"))

    new_rows = to_open.select(
        (F.lit(max_sk) + F.row_number().over(w)).cast(T.IntegerType()).alias("policy_sk"),
        "policy_id", "policy_number", "customer_id", "customer_segment",
        "product_code", "product_name", "lob_code", "broker_code", "broker_name",
        "status", "inception_date", "expiry_date", "cancellation_date",
        "annual_premium", "currency", "vehicle_reg", "ncd_years",
        snap.alias("valid_from"),
        F.lit("9999-12-31").cast(T.DateType()).alias("valid_to"),
        F.lit("Y").alias("is_current"),
        snap.alias("source_snapshot_date"),
        F.localtimestamp().cast(T.TimestampNTZType()).alias("load_ts"),
    )

    result = (
        prev_after.select(*OUTPUT_COLUMNS)
        .unionByName(new_rows.select(*OUTPUT_COLUMNS))
        .withColumn("customer_segment", F.rpad(F.col("customer_segment"), 4, " "))
        .withColumn("currency", F.rpad(F.col("currency"), 3, " "))
    )

    return {"dw.dim_policy": result}
