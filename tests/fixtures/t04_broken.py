# test fixture for the heal loop (plan step 2.7)
"""T04 usp_build_claims_summary: migrated from estate/tsql/T04_usp_build_claims_summary.sql.

Legacy SHA-256: 632841c99f0c5919975c6fd2266ab04b33e1ba87424c55bbfbe7b0223f3bc975
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-05, TSQL-13, TSQL-16
Bugs reproduced on purpose (# LANSH-DEFECT): payment/reserve join fan-out inflates total_paid and incurred
"""
from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]
    snapshots = inputs["stg.policy_snapshots"]

    as_of = F.to_date(F.lit(params["AsOfDate"]))

    # TSQL-13: #open_claims -> DataFrame (lines 63-74)
    # TSQL-01 / TSQL-02: status IN (...) ignores case and trailing spaces under the CI collation
    open_claims = (
        claims
        .where(
            F.col("status").isin("OPEN", "REOPENED")
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

    oc_ids = open_claims.select("claim_id")

    # TSQL-13: #reserve -> DataFrame (lines 83-95)
    # TSQL-01 / TSQL-02: PARTITION BY reserve_type puts case / trailing-space variants together
    w_res = (
        Window.partitionBy(F.col("claim_id"), F.upper(F.rtrim(F.col("reserve_type"))))
        .orderBy(F.col("reserve_date").desc(), F.col("reserve_id").desc(), F.col("_row_seq").asc())
    )
    reserve = (
        reserves
        .where(F.col("reserve_date") <= as_of)
        .join(oc_ids, on="claim_id", how="inner")
        .withColumn("rn", F.row_number().over(w_res))
        .where(F.col("rn") == 1)
        .select("claim_id", "reserve_type", "reserve_amount")
    )

    # TSQL-13: #money -> DataFrame (lines 103-115)
    pay = (
        payments
        .where(F.col("payment_date") <= as_of)
        .select(F.col("claim_id").alias("p_claim_id"), F.col("payment_id"), F.col("amount"))
    )
    rsv = reserve.select(
        F.col("claim_id").alias("r_claim_id"), F.col("reserve_type"), F.col("reserve_amount")
    )
    rtype = F.upper(F.rtrim(F.col("reserve_type")))  # TSQL-01 / TSQL-02 on lines 106-107
    money = (
        oc_ids
        .join(pay, F.col("claim_id") == F.col("p_claim_id"), "left")
        .join(rsv, F.col("claim_id") == F.col("r_claim_id"), "left")  # LANSH-DEFECT: payments x reserve rows fan-out before GROUP BY
        .groupBy("claim_id")
        .agg(
            F.countDistinct(F.col("payment_id")).alias("n_payments"),
            F.coalesce(F.sum(F.col("amount")), F.lit(0)).alias("total_paid"),  # LANSH-DEFECT: SUM counts each payment once per reserve row
            F.coalesce(
                F.max(F.when(rtype == "INDEMNITY", F.col("reserve_amount"))), F.lit(0)
            ).alias("indemnity_reserve"),
            F.coalesce(
                F.max(F.when(rtype == "EXPENSE", F.col("reserve_amount"))), F.lit(0)
            ).alias("expense_reserve"),
        )
    )

    # @snapshot_date = MAX(snapshot_date) <= @AsOfDate (lines 121-123); NULL matches nothing
    snap = (
        snapshots
        .where(F.col("snapshot_date") <= as_of)
        .agg(F.max(F.col("snapshot_date")).alias("snap_date"))
    )
    ps = (
        snapshots
        .join(snap, F.col("snapshot_date") == F.col("snap_date"), "inner")
        .select(F.col("policy_id").alias("ps_policy_id"), F.col("policy_number"))
    )

    joined = (
        open_claims
        .join(money, on="claim_id", how="inner")
        .join(ps, F.col("policy_id") == F.col("ps_policy_id"), "left")
    )

    result = joined.select(
        F.col("claim_id"),
        F.col("claim_number"),
        # TSQL-05: '+' concatenation is NULL if any part (e.g. handler_code) is NULL
        F.concat(
            F.col("lob_code"), F.lit("/"), F.col("claim_number"), F.lit("/"), F.col("handler_code")
        ).alias("claim_ref"),
        F.col("policy_id"),
        F.col("policy_number"),
        F.col("lob_code"),
        F.col("status"),
        F.col("handler_code"),
        F.col("loss_date"),
        # TSQL-16: CONVERT(VARCHAR(10), d, 103) -> dd/MM/yyyy
        F.date_format(F.col("loss_date"), "MM/dd/yyyy").alias("loss_date_text"),
        F.col("reported_date"),
        # TSQL-16: CONVERT(CHAR(6), d, 112) -> first 6 chars of yyyyMMdd; TSQL-02 CHAR(6) padding
        F.rpad(
            F.substring(F.date_format(F.col("reported_date"), "yyyyMMdd"), 1, 6), 6, " "
        ).alias("reported_period"),
        # TSQL-04: DATEDIFF(DAY, start, end) -> datediff(end, start)
        F.datediff(as_of, F.col("reported_date")).alias("days_open"),
        F.col("n_payments"),
        F.col("total_paid"),
        F.col("indemnity_reserve"),
        F.col("expense_reserve"),
        (F.col("indemnity_reserve") + F.col("expense_reserve")).alias("current_reserve"),
        (F.col("total_paid") + F.col("indemnity_reserve") + F.col("expense_reserve")).alias("incurred"),  # LANSH-DEFECT: incurred carries the fanned-out total_paid
        as_of.alias("as_of_date"),
    )

    return {"rpt.claims_summary": result}
