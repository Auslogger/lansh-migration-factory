"""T04 usp_build_claims_summary: migrated from estate/tsql/T04_usp_build_claims_summary.sql.

Legacy SHA-256: 632841c99f0c5919975c6fd2266ab04b33e1ba87424c55bbfbe7b0223f3bc975
Written by: LANSH translator (Claude)
Traps handled: TSQL-13, TSQL-01, TSQL-02, TSQL-05, TSQL-16, TSQL-04
Bugs reproduced on purpose (# LANSH-DEFECT): T04-D1 payment/reserve join fan-out, T04-D2 NULL claim_ref when handler_code is NULL, T04-D3 open book on current status, T04-D4 policy number from a single global snapshot date
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]
    snapshots = inputs["stg.policy_snapshots"]

    # ---- #open_claims (TSQL-13), lines 63-74 -------------------------------
    # TSQL-01/TSQL-02: status IN (...) is case-insensitive and ignores trailing spaces.
    open_claims = (
        claims
        .where(
            F.upper(F.rtrim(F.col("status"))).isin("OPEN", "REOPENED")  # LANSH-DEFECT: T04-D3 current status, not status at @AsOfDate
            & (F.col("reported_date") <= as_of)
        )
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
            F.col("status"),
            F.col("handler_code"),
            F.col("loss_date"),
            F.col("reported_date"),
        )
    )

    # ---- #reserve (TSQL-13), lines 83-95 -----------------------------------
    r_src = reserves.where(F.col("reserve_date") <= as_of)
    oc_keys = open_claims.select(F.col("claim_id").alias("_oc_claim_id"))
    r_joined = r_src.join(oc_keys, r_src["claim_id"] == oc_keys["_oc_claim_id"], "inner")
    # TSQL-01/TSQL-02: PARTITION BY reserve_type groups case and trailing-space variants together.
    w_res = (
        Window.partitionBy(F.col("claim_id"), F.upper(F.rtrim(F.col("reserve_type"))))
        .orderBy(
            F.col("reserve_date").desc_nulls_last(),
            F.col("reserve_id").desc_nulls_last(),
            F.col("_row_seq").asc(),
        )
    )
    reserve = (
        r_joined
        .withColumn("_rn", F.row_number().over(w_res))
        .where(F.col("_rn") == 1)
        .select(
            F.col("claim_id").alias("_r_claim_id"),
            F.col("reserve_type"),
            F.col("reserve_amount"),
        )
    )

    # ---- #money (TSQL-13), lines 103-115 -----------------------------------
    pay = (
        payments
        .where(F.col("payment_date") <= as_of)
        .select(
            F.col("claim_id").alias("_p_claim_id"),
            F.col("payment_id"),
            F.col("amount"),
        )
    )
    money_base = (
        open_claims.select(F.col("claim_id"))
        .join(pay, F.col("claim_id") == F.col("_p_claim_id"), "left")
        .join(reserve, F.col("claim_id") == F.col("_r_claim_id"), "left")  # LANSH-DEFECT: T04-D1 payments x reserve rows fan-out before GROUP BY
    )
    rtype = F.upper(F.rtrim(F.col("reserve_type")))  # TSQL-01/TSQL-02
    money = (
        money_base
        .groupBy(F.col("claim_id"))
        .agg(
            F.countDistinct(F.col("payment_id")).alias("n_payments"),
            F.coalesce(F.sum(F.col("amount")), F.lit(0)).alias("total_paid"),  # LANSH-DEFECT: T04-D1 SUM over fanned-out rows inflates total_paid
            F.coalesce(F.max(F.when(rtype == "INDEMNITY", F.col("reserve_amount"))), F.lit(0)).alias("indemnity_reserve"),
            F.coalesce(F.max(F.when(rtype == "EXPENSE", F.col("reserve_amount"))), F.lit(0)).alias("expense_reserve"),
        )
        .select(
            F.col("claim_id").alias("_m_claim_id"),
            F.col("n_payments"),
            F.col("total_paid"),
            F.col("indemnity_reserve"),
            F.col("expense_reserve"),
        )
    )

    # ---- @snapshot_date, lines 121-123 -------------------------------------
    snap = (
        snapshots
        .where(F.col("snapshot_date") <= as_of)
        .agg(F.max(F.col("snapshot_date")).alias("_snap_date"))  # LANSH-DEFECT: T04-D4 one global snapshot date for every policy
    )
    ps = (
        snapshots
        .join(snap, snapshots["snapshot_date"] == snap["_snap_date"], "inner")  # LANSH-DEFECT: T04-D4 exact match on the global snapshot date, no fallback
        .select(
            F.col("policy_id").alias("_ps_policy_id"),
            F.col("policy_number"),
        )
    )

    # ---- INSERT INTO rpt.claims_summary, lines 129-159 ---------------------
    joined = (
        open_claims
        .join(money, F.col("claim_id") == F.col("_m_claim_id"), "inner")
        .join(ps, F.col("policy_id") == F.col("_ps_policy_id"), "left")
    )

    result = joined.select(
        F.col("claim_id"),
        F.col("claim_number"),
        # TSQL-05: '+' concatenation is NULL if any part is NULL.
        F.concat(
            F.col("lob_code"), F.lit("/"), F.col("claim_number"), F.lit("/"), F.col("handler_code")
        ).alias("claim_ref"),  # LANSH-DEFECT: T04-D2 NULL handler_code makes claim_ref NULL
        F.col("policy_id"),
        F.col("policy_number"),
        F.col("lob_code"),
        F.col("status"),
        F.col("handler_code"),
        F.col("loss_date"),
        # TSQL-16: CONVERT(VARCHAR(10), d, 103) -> dd/MM/yyyy
        F.date_format(F.col("loss_date"), "dd/MM/yyyy").alias("loss_date_text"),
        F.col("reported_date"),
        # TSQL-16: CONVERT(CHAR(6), d, 112) -> first 6 chars of yyyyMMdd
        F.substring(F.date_format(F.col("reported_date"), "yyyyMMdd"), 1, 6).alias("reported_period"),
        # TSQL-04: DATEDIFF(DAY, start, end) -> datediff(end, start)
        F.datediff(as_of, F.col("reported_date")).alias("days_open"),
        F.col("n_payments"),
        F.col("total_paid"),
        F.col("indemnity_reserve"),
        F.col("expense_reserve"),
        (F.col("indemnity_reserve") + F.col("expense_reserve")).alias("current_reserve"),
        (F.col("total_paid") + F.col("indemnity_reserve") + F.col("expense_reserve")).alias("incurred"),  # LANSH-DEFECT: T04-D1 incurred carries the inflated total_paid
        as_of.alias("as_of_date"),
    )

    return {"rpt.claims_summary": result}
