"""Job T02: dw.usp_load_dim_policy (T-SQL) migrated to PySpark.

Policy dimension with type-2 history, loaded once per policy snapshot.
Input dw.dim_policy is the previous state of the output; the whole new table
is returned.
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T  # noqa: F401


_OUT_COLS = [
    "policy_sk", "policy_id", "policy_number", "customer_id", "customer_segment",
    "product_code", "product_name", "lob_code", "broker_code", "broker_name",
    "status", "inception_date", "expiry_date", "cancellation_date",
    "annual_premium", "currency", "vehicle_reg", "ncd_years", "valid_from",
    "valid_to", "is_current", "source_snapshot_date", "load_ts",
]

_NOT_NULL_COLS = [
    "policy_id", "policy_number", "customer_id", "product_code", "product_name",
    "lob_code", "broker_code", "status", "inception_date", "expiry_date",
    "annual_premium", "currency",
]


def _key(c):
    # SQL Server default collation (case-insensitive) with trailing-space-insensitive '='
    return F.upper(F.rtrim(c))


def _ci_isnull(c):
    # ISNULL(x, '') compared under case-insensitive / trailing-space-insensitive rules
    return F.upper(F.rtrim(F.coalesce(c, F.lit(""))))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    snap = datetime.date.fromisoformat(params["SnapshotDate"])
    snap_lit = F.lit(snap)

    dim = inputs["dw.dim_policy"]
    ps = inputs["stg.policy_snapshots"]
    pr = inputs["stg.products"]
    br = inputs["stg.brokers"]
    cu = inputs["dw.dim_customer"]

    # INC-2105: refuse a snapshot older than the last one loaded (THROW 50001)
    last_loaded = dim.agg(F.max("source_snapshot_date").alias("m")).first()["m"]
    if last_loaded is not None and snap < last_loaded:
        raise ValueError("dw.dim_policy already holds a later policy snapshot")

    # 1. #src
    p = ps.filter(F.col("snapshot_date") == snap_lit).select(
        F.col("policy_id"), F.col("policy_number"), F.col("customer_id"),
        F.col("product_code").alias("p_product_code"),
        F.col("broker_code").alias("p_broker_code"),
        F.col("status"), F.col("inception_date"), F.col("expiry_date"),
        F.col("cancellation_date"), F.col("annual_premium"), F.col("currency"),
        F.col("vehicle_reg"), F.col("ncd_years"),
        F.col("_row_seq").alias("p_row_seq"),
    )
    prd = pr.select(
        F.col("product_code").alias("pr_product_code"),
        F.col("product_name"), F.col("lob_code"),
        F.col("_row_seq").alias("pr_row_seq"),
    )
    brk = br.select(
        F.col("broker_code").alias("b_broker_code"),
        F.col("broker_name"),
        F.col("_row_seq").alias("b_row_seq"),
    )
    cus = cu.select(
        F.col("customer_id").alias("c_customer_id"),
        F.col("segment_code").alias("customer_segment"),
    )

    j = (
        p.join(prd, _key(F.col("pr_product_code")) == _key(F.col("p_product_code")), "inner")
        .join(brk, _key(F.col("b_broker_code")) == _key(F.col("p_broker_code")), "left")
        .join(cus, F.col("c_customer_id") == F.col("customer_id"), "left")
    )

    src = j.select(
        F.col("policy_id"), F.col("policy_number"), F.col("customer_id"),
        F.col("customer_segment"),
        F.col("pr_product_code").alias("product_code"),
        F.col("product_name"), F.col("lob_code"),
        # ISNULL returns the type of its first argument (VARCHAR(10)), so the
        # replacement 'DIRECT-SALES' is truncated to 10 characters.
        F.coalesce(F.col("p_broker_code"), F.substring(F.lit("DIRECT-SALES"), 1, 10)).alias("broker_code"),  # LANSH-DEFECT: ISNULL truncates 'DIRECT-SALES' to VARCHAR(10) 'DIRECT-SAL'
        F.col("broker_name"), F.col("status"), F.col("inception_date"),
        F.col("expiry_date"), F.col("cancellation_date"), F.col("annual_premium"),
        F.col("currency"), F.col("vehicle_reg"), F.col("ncd_years"),
        F.col("p_row_seq"), F.col("pr_row_seq"), F.col("b_row_seq"),
    )

    if src.limit(1).count() == 0:
        raise ValueError("No policies found for this snapshot date")

    # 2. MERGE: close current versions whose tracked attributes changed
    s_cmp = src.select(
        F.col("policy_id").alias("s_policy_id"),
        F.col("status").alias("s_status"),
        F.col("broker_code").alias("s_broker_code"),
        F.col("annual_premium").alias("s_annual_premium"),
        F.col("vehicle_reg").alias("s_vehicle_reg"),
    )
    t_cur = dim.filter(F.col("is_current") == F.lit("Y")).select(
        F.col("policy_sk"), F.col("policy_id").alias("t_policy_id"),
        F.col("status").alias("t_status"),
        F.col("broker_code").alias("t_broker_code"),
        F.col("annual_premium").alias("t_annual_premium"),
        F.col("vehicle_reg").alias("t_vehicle_reg"),
    )
    pairs = t_cur.join(s_cmp, F.col("t_policy_id") == F.col("s_policy_id"), "inner")
    changed = (
        (_ci_isnull(F.col("s_status")) != _ci_isnull(F.col("t_status")))
        | (_ci_isnull(F.col("s_broker_code")) != _ci_isnull(F.col("t_broker_code")))
        | (F.coalesce(F.col("s_annual_premium"), F.lit(0)) != F.coalesce(F.col("t_annual_premium"), F.lit(0)))
        | (_ci_isnull(F.col("s_vehicle_reg")) != _ci_isnull(F.col("t_vehicle_reg")))
    )
    closed = pairs.filter(changed)

    # MERGE raises error 8672 when one target row would be updated more than once
    multi = closed.groupBy("policy_sk").count().filter(F.col("count") > 1)
    if multi.limit(1).count() > 0:
        raise ValueError("The MERGE statement attempted to UPDATE or DELETE the same row more than once.")

    closed_sk = closed.select("policy_sk").distinct().withColumn("_closed", F.lit(True))

    upd = (
        dim.join(closed_sk, "policy_sk", "left")
        .withColumn("valid_to", F.when(F.col("_closed"), F.date_sub(snap_lit, 1)).otherwise(F.col("valid_to")))
        .withColumn("is_current", F.when(F.col("_closed"), F.lit("N")).otherwise(F.col("is_current")))
        .drop("_closed")
    )

    # 3. Open a current version for new policies and for those closed above
    cur_after = upd.filter(F.col("is_current") == F.lit("Y")).select(
        F.col("policy_id").alias("cur_policy_id")
    ).distinct()
    new_rows = src.join(cur_after, F.col("policy_id") == F.col("cur_policy_id"), "left_anti")

    # INSERT into NOT NULL columns fails the whole batch (rolled back)
    null_cond = None
    for c in _NOT_NULL_COLS:
        cond = F.col(c).isNull()
        null_cond = cond if null_cond is None else (null_cond | cond)
    if new_rows.filter(null_cond).limit(1).count() > 0:
        raise ValueError("Cannot insert the value NULL into a NOT NULL column of dw.dim_policy")

    max_sk = dim.agg(F.max("policy_sk").alias("m")).first()["m"]
    base = 0 if max_sk is None else int(max_sk)

    w = Window.orderBy(
        F.col("policy_id").asc(), F.col("p_row_seq").asc(),
        F.col("pr_row_seq").asc(), F.col("b_row_seq").asc(),
    )
    ins = (
        new_rows.withColumn("policy_sk", F.row_number().over(w) + F.lit(base))
        .withColumn("valid_from", snap_lit)
        .withColumn("valid_to", F.lit(datetime.date(9999, 12, 31)))
        .withColumn("is_current", F.lit("Y"))
        .withColumn("source_snapshot_date", snap_lit)
        .withColumn("load_ts", F.localtimestamp())
    )

    schema = {f.name: f.dataType for f in dim.schema.fields}
    ins_out = ins.select([F.col(c).cast(schema[c]).alias(c) for c in _OUT_COLS])
    upd_out = upd.select([F.col(c).cast(schema[c]).alias(c) for c in _OUT_COLS])

    result = upd_out.unionByName(ins_out)
    return {"dw.dim_policy": result}
