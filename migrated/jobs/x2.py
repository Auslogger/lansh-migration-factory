"""X2 usp_large_loss_watchlist: migrated from estate/holdout/X2_usp_large_loss_watchlist.sql.

Legacy SHA-256: bc9df85f8e39e93cc102c59e14ed2d6f84543a4a3c5cdc8b445ab1108e162772
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-06, TSQL-07, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X2-D1 latest reserve picked across all reserve types; X2-D2 claims closed exactly 90 days ago dropped; X2-D3 CLOSED check on raw (untrimmed) status
"""
import datetime
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of_date = datetime.date.fromisoformat(params["AsOfDate"].strip())
    # DECLARE @PriorDate DATE = DATEADD(DAY, -90, @AsOfDate)
    prior_date = as_of_date - datetime.timedelta(days=90)
    as_of = F.lit(as_of_date)
    prior = F.lit(prior_date)

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]

    # ---- #clm (TSQL-13): open and reopened claims, plus claims closed in the last 90 days
    # TSQL-01 / TSQL-02: CI collation and trailing spaces ignored -> upper(rtrim()); leading spaces still count.
    status_key = F.upper(F.rtrim(F.col("status")))  # LANSH-DEFECT: X2-D3 raw status compared (no LTRIM), so ' CLOSED' passes <> 'CLOSED'
    clm = (
        claims
        .where(
            (F.col("reported_date") <= as_of)
            & (
                (status_key != F.lit("CLOSED"))  # LANSH-DEFECT: X2-D3 CLOSED check uses the untrimmed status
                | (F.col("closed_date") > prior)  # LANSH-DEFECT: X2-D2 strict > drops claims closed exactly 90 days ago
            )
        )
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.upper(F.ltrim(F.rtrim(F.col("lob_code")))).alias("lob_code"),
            F.upper(F.ltrim(F.rtrim(F.col("status")))).alias("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
        )
    )
    clm_keys = clm.select(F.col("claim_id").alias("c_claim_id"))

    # ---- #paid (TSQL-13): payments to date and 90 days ago; unkeyed amounts count as nil
    dec12_zero = F.lit(0).cast("decimal(12,2)")
    amt0 = F.coalesce(F.col("amount"), dec12_zero)
    paid = (
        payments
        .join(clm_keys, payments["claim_id"] == clm_keys["c_claim_id"], "inner")
        .where(F.col("payment_date") <= as_of)
        .groupBy(F.col("claim_id"))
        .agg(
            F.sum(amt0).cast("decimal(38,2)").alias("paid_now"),
            F.sum(F.when(F.col("payment_date") <= prior, amt0).otherwise(dec12_zero)).cast("decimal(38,2)").alias("paid_prior"),
            F.max(F.when(F.col("amount").isNotNull(), F.col("payment_date"))).alias("last_payment_date"),
        )
    )

    # ---- #res (TSQL-13, TSQL-09): CROSS APPLY (VALUES ('NOW', @AsOfDate), ('PRIOR', @PriorDate))
    periods = spark.createDataFrame(
        [("NOW", as_of_date), ("PRIOR", prior_date)],
        T.StructType([
            T.StructField("period", T.StringType(), False),
            T.StructField("as_at", T.DateType(), False),
        ]),
    )
    w_res = Window.partitionBy("period", "claim_id").orderBy(  # LANSH-DEFECT: X2-D1 partition ignores reserve_type, one row per claim/period
        F.col("reserve_date").desc_nulls_last(),
        F.col("reserve_id").desc_nulls_last(),
        F.col("_row_seq").asc(),
    )
    res = (
        reserves
        .join(clm_keys, reserves["claim_id"] == clm_keys["c_claim_id"], "inner")
        .crossJoin(periods)
        .where(F.col("reserve_date") <= F.col("as_at"))
        .select(
            F.col("claim_id"),
            F.col("period"),
            F.col("reserve_amount"),
            F.row_number().over(w_res).alias("rn"),
        )
    )

    # ---- #os (TSQL-13): outstanding reserve now and 90 days ago
    os_ = (
        res
        .where(F.col("rn") == 1)  # LANSH-DEFECT: X2-D1 only the single latest reserve row (any type) is kept
        .groupBy(F.col("claim_id"))
        .agg(
            F.sum(F.when(F.col("period") == F.lit("NOW"), F.col("reserve_amount")).otherwise(dec12_zero)).cast("decimal(38,2)").alias("os_now"),  # LANSH-DEFECT: X2-D1 sums one row only
            F.sum(F.when(F.col("period") == F.lit("PRIOR"), F.col("reserve_amount")).otherwise(dec12_zero)).cast("decimal(38,2)").alias("os_prior"),  # LANSH-DEFECT: X2-D1 sums one row only
        )
    )

    # ---- #ract (TSQL-13): reserve activity
    ract = (
        reserves
        .join(clm_keys, reserves["claim_id"] == clm_keys["c_claim_id"], "inner")
        .where(F.col("reserve_date") <= as_of)
        .groupBy(F.col("claim_id"))
        .agg(
            F.sum(F.when(F.col("reserve_date") > prior, F.lit(1)).otherwise(F.lit(0))).cast("int").alias("reserve_changes_90d"),
            F.max(F.col("reserve_date")).alias("last_reserve_date"),
        )
    )

    # ---- #inc (TSQL-13, TSQL-06)
    dec38_zero = F.lit(0).cast("decimal(38,2)")
    sentinel = F.to_date(F.lit("19000101"), "yyyyMMdd")  # TSQL-06: ISNULL(date, '19000101') -> typed date
    paid_now = F.coalesce(F.col("paid_now"), dec38_zero)
    os_now = F.coalesce(F.col("os_now"), dec38_zero)
    paid_prior = F.coalesce(F.col("paid_prior"), dec38_zero)
    os_prior = F.coalesce(F.col("os_prior"), dec38_zero)
    inc = (
        clm.select("claim_id")
        .join(paid, "claim_id", "left")
        .join(os_, "claim_id", "left")
        .join(ract, "claim_id", "left")
        .select(
            F.col("claim_id"),
            paid_now.cast("decimal(38,2)").alias("paid_to_date"),
            os_now.cast("decimal(38,2)").alias("outstanding_reserve"),
            (paid_now + os_now).cast("decimal(38,2)").alias("incurred_amount"),
            (paid_prior + os_prior).cast("decimal(38,2)").alias("incurred_90d_ago"),
            F.coalesce(F.col("reserve_changes_90d"), F.lit(0).cast("int")).alias("reserve_changes_90d"),
            F.when(
                F.coalesce(F.col("last_payment_date"), sentinel) > F.coalesce(F.col("last_reserve_date"), sentinel),
                F.col("last_payment_date"),
            ).otherwise(F.col("last_reserve_date")).alias("last_activity_date"),
        )
    )

    # ---- INSERT INTO rpt.large_loss_watchlist
    inc_amt = F.col("incurred_amount")
    inc_prior = F.col("incurred_90d_ago")
    watch = (
        F.when(inc_prior < F.lit(25000), F.lit("NEW"))
        .when(inc_amt > inc_prior * F.lit(Decimal("1.10")), F.lit("DETERIORATING"))  # TSQL-07 decimal literal
        .when(inc_amt < inc_prior * F.lit(Decimal("0.90")), F.lit("IMPROVING"))  # TSQL-07 decimal literal
        .otherwise(F.lit("STABLE"))
    )
    out = (
        inc
        .join(clm, "claim_id", "inner")
        .where(inc_amt >= F.lit(25000))
        .select(
            as_of.alias("as_of_date"),
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.col("lob_code"),
            F.col("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
            F.col("paid_to_date"),
            F.col("outstanding_reserve"),
            F.col("incurred_amount"),
            F.col("incurred_90d_ago"),
            (inc_amt - inc_prior).alias("movement_90d"),
            F.col("reserve_changes_90d"),
            F.datediff(as_of, F.col("last_activity_date")).alias("days_since_last_activity"),  # TSQL-04: args swapped
            watch.alias("watch_category"),
        )
    )

    return {"rpt.large_loss_watchlist": out}
