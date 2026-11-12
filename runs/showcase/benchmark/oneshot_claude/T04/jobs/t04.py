"""T04 rpt.usp_build_claims_summary -> rpt.claims_summary (full refresh).

PySpark translation of estate/tsql/T04_usp_build_claims_summary.sql
(SHA-256 632841c99f0c5919975c6fd2266ab04b33e1ba87424c55bbfbe7b0223f3bc975).

The output is the open book: one row per claim that is open or reopened and was
reported on or before @AsOfDate. Each row carries paid to date, the case
reserves and incurred to date. Legacy behaviour is kept as it is, bugs included.
"""
import datetime

from pyspark.sql import SparkSession, DataFrame, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


def _ci(col):
    # SQL Server default collation (CI, trailing spaces ignored) for '=' / IN / PARTITION BY
    return F.upper(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"])).cast(T.DateType())

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]
    snaps = inputs["stg.policy_snapshots"]

    # ---- #open_claims ------------------------------------------------------
    oc = claims.where(
        _ci(F.col("status")).isin("OPEN", "REOPENED")
        & (F.col("reported_date") <= as_of)
    ).select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.col("policy_id"),
        F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
        F.col("status"),
        F.col("handler_code"),
        F.col("loss_date"),
        F.col("reported_date"),
    )

    # ---- #reserve: latest entry per claim and reserve type ---------------------
    oc_ids = oc.select(F.col("claim_id").alias("oc_claim_id"))
    r = reserves.where(F.col("reserve_date") <= as_of).join(
        oc_ids, F.col("claim_id") == F.col("oc_claim_id"), "inner"
    )
    w = Window.partitionBy(F.col("claim_id"), _ci(F.col("reserve_type"))).orderBy(
        F.col("reserve_date").desc_nulls_last(),
        F.col("reserve_id").desc_nulls_last(),
        F.col("_row_seq").asc(),
    )
    reserve = (
        r.withColumn("rn", F.row_number().over(w))
        .where(F.col("rn") == 1)
        .select(
            F.col("claim_id").alias("r_claim_id"),
            F.col("reserve_type").alias("r_reserve_type"),
            F.col("reserve_amount").alias("r_reserve_amount"),
        )
    )

    # ---- #money --------------------------------------------------------------
    pay = payments.select(
        F.col("payment_id").alias("p_payment_id"),
        F.col("claim_id").alias("p_claim_id"),
        F.col("payment_date").alias("p_payment_date"),
        F.col("amount").alias("p_amount"),
    )
    m_base = oc.select(F.col("claim_id").alias("m_claim_id"))
    joined = m_base.join(
        pay,
        (F.col("p_claim_id") == F.col("m_claim_id")) & (F.col("p_payment_date") <= as_of),
        "left",
    ).join(  # LANSH-DEFECT: payments x reserve rows fan-out, so SUM(amount) is multiplied by the claim's reserve row count
        reserve, F.col("r_claim_id") == F.col("m_claim_id"), "left"
    )
    zero = F.lit(0)
    money = joined.groupBy(F.col("m_claim_id")).agg(
        F.countDistinct(F.col("p_payment_id")).alias("n_payments"),
        F.coalesce(F.sum(F.col("p_amount")), zero.cast(T.DecimalType(38, 2))).alias("total_paid"),  # LANSH-DEFECT: inflated by reserve fan-out
        F.coalesce(
            F.max(F.when(_ci(F.col("r_reserve_type")) == "INDEMNITY", F.col("r_reserve_amount"))),
            zero.cast(T.DecimalType(12, 2)),
        ).alias("indemnity_reserve"),
        F.coalesce(
            F.max(F.when(_ci(F.col("r_reserve_type")) == "EXPENSE", F.col("r_reserve_amount"))),
            zero.cast(T.DecimalType(12, 2)),
        ).alias("expense_reserve"),
    )

    # ---- @snapshot_date and the latest policy extract -------------------------------
    snap_max = snaps.where(F.col("snapshot_date") <= as_of).agg(
        F.max(F.col("snapshot_date")).alias("max_snap")
    )
    ps_latest = snaps.join(
        snap_max, F.col("snapshot_date") == F.col("max_snap"), "inner"
    ).select(
        F.col("policy_id").alias("ps_policy_id"),
        F.col("policy_number").alias("ps_policy_number"),
    )

    # ---- final insert ----------------------------------------------------------
    final = oc.join(money, F.col("m_claim_id") == F.col("claim_id"), "inner").join(
        ps_latest, F.col("ps_policy_id") == F.col("policy_id"), "left"
    )

    out = final.select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.concat(  # LANSH-DEFECT: '+' concatenation gives NULL claim_ref when handler_code is NULL
            F.col("lob_code"), F.lit("/"), F.col("claim_number"), F.lit("/"), F.col("handler_code")
        ).alias("claim_ref"),
        F.col("policy_id"),
        F.col("ps_policy_number").alias("policy_number"),
        F.col("lob_code"),
        F.col("status"),
        F.col("handler_code"),
        F.col("loss_date"),
        F.date_format(F.col("loss_date"), "dd/MM/yyyy").alias("loss_date_text"),
        F.col("reported_date"),
        F.date_format(F.col("reported_date"), "yyyyMM").alias("reported_period"),
        F.datediff(as_of, F.col("reported_date")).alias("days_open"),
        F.col("n_payments"),
        F.col("total_paid"),
        F.col("indemnity_reserve"),
        F.col("expense_reserve"),
        (F.col("indemnity_reserve") + F.col("expense_reserve")).alias("current_reserve"),
        (F.col("total_paid") + F.col("indemnity_reserve") + F.col("expense_reserve")).alias("incurred"),  # LANSH-DEFECT: incurred carries the inflated total_paid
        as_of.alias("as_of_date"),
    )

    return {"rpt.claims_summary": out}
