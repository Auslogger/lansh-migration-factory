"""X2 usp_large_loss_watchlist: migrated from estate/holdout/X2_usp_large_loss_watchlist.sql.

Legacy SHA-256: bc9df85f8e39e93cc102c59e14ed2d6f84543a4a3c5cdc8b445ab1108e162772
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-06, TSQL-07, TSQL-09, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): X2-D1 latest reserve picked across all reserve types; X2-D2 claims closed exactly 90 days ago dropped; X2-D3 CLOSED check uses the raw (untrimmed-left) status
"""
import datetime
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]
    reserves = inputs["stg.claim_reserves"]

    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    prior = as_of - datetime.timedelta(days=90)  # DATEADD(DAY, -90, @AsOfDate)
    as_of_lit = F.lit(as_of)
    prior_lit = F.lit(prior)

    # TSQL-13: #clm -> DataFrame
    # TSQL-01 / TSQL-02: status compared case-insensitively and ignoring trailing spaces only
    clm = (
        claims
        .where(
            (F.col("reported_date") <= as_of_lit)
            & (
                (F.upper(F.rtrim(F.col("status"))) != F.lit("CLOSED"))  # LANSH-DEFECT: X2-D3 raw status compared; leading spaces still count so ' CLOSED' passes
                | (F.col("closed_date") > prior_lit)  # LANSH-DEFECT: X2-D2 strict > drops claims closed exactly 90 days ago
            )
        )
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.upper(F.trim(F.col("lob_code"))).alias("lob_code"),
            F.upper(F.trim(F.col("status"))).alias("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
        )
    )
    clm_ids = clm.select("claim_id")

    # TSQL-13: #paid -> DataFrame
    zero_12_2 = F.lit(0).cast("decimal(12,2)")
    amt = F.coalesce(F.col("amount"), zero_12_2)  # TSQL-06: ISNULL keeps decimal(12,2)
    paid = (
        payments
        .where(F.col("payment_date") <= as_of_lit)
        .join(clm_ids, on="claim_id", how="inner")
        .groupBy("claim_id")
        .agg(
            F.sum(amt).cast("decimal(38,2)").alias("paid_now"),
            F.sum(F.when(F.col("payment_date") <= prior_lit, amt).otherwise(zero_12_2)).cast("decimal(38,2)").alias("paid_prior"),
            F.max(F.when(F.col("amount").isNotNull(), F.col("payment_date"))).alias("last_payment_date"),
        )
    )

    # TSQL-09: CROSS APPLY (VALUES ...) -> cross join with a two-row DataFrame, then the as_at filter
    periods = spark.createDataFrame(
        [("NOW", as_of), ("PRIOR", prior)],
        T.StructType([
            T.StructField("period", T.StringType(), False),
            T.StructField("as_at", T.DateType(), False),
        ]),
    )
    # TSQL-13: #res -> DataFrame
    w_res = Window.partitionBy("period", "claim_id").orderBy(  # LANSH-DEFECT: X2-D1 partition ignores reserve_type, only the single latest reserve row counts
        F.col("reserve_date").desc(), F.col("reserve_id").desc(), F.col("_row_seq").asc()
    )
    res = (
        reserves
        .join(clm_ids, on="claim_id", how="inner")
        .crossJoin(periods)
        .where(F.col("reserve_date") <= F.col("as_at"))
        .select(
            F.col("claim_id"), F.col("period"), F.col("reserve_amount"),
            F.row_number().over(w_res).alias("rn"),
        )
    )

    # TSQL-13: #os -> DataFrame
    os_df = (
        res
        .where(F.col("rn") == 1)  # LANSH-DEFECT: X2-D1 keeps one reserve row per claim and period, other reserve types dropped
        .groupBy("claim_id")
        .agg(
            F.sum(F.when(F.col("period") == F.lit("NOW"), F.col("reserve_amount")).otherwise(zero_12_2)).cast("decimal(38,2)").alias("os_now"),  # LANSH-DEFECT: X2-D1 sums exactly one row (latest of any type)
            F.sum(F.when(F.col("period") == F.lit("PRIOR"), F.col("reserve_amount")).otherwise(zero_12_2)).cast("decimal(38,2)").alias("os_prior"),  # LANSH-DEFECT: X2-D1 sums exactly one row (latest of any type)
        )
    )

    # TSQL-13: #ract -> DataFrame
    ract = (
        reserves
        .where(F.col("reserve_date") <= as_of_lit)
        .join(clm_ids, on="claim_id", how="inner")
        .groupBy("claim_id")
        .agg(
            F.sum(F.when(F.col("reserve_date") > prior_lit, F.lit(1)).otherwise(F.lit(0))).cast("int").alias("reserve_changes_90d"),
            F.max(F.col("reserve_date")).alias("last_reserve_date"),
        )
    )

    # TSQL-13: #inc -> DataFrame
    zero_38_2 = F.lit(0).cast("decimal(38,2)")
    # TSQL-06: ISNULL(date, '19000101') -> typed date literal
    sentinel = F.to_date(F.lit("19000101"), "yyyyMMdd")
    inc = (
        clm_ids
        .join(paid, on="claim_id", how="left")
        .join(os_df, on="claim_id", how="left")
        .join(ract, on="claim_id", how="left")
        .select(
            F.col("claim_id"),
            F.coalesce(F.col("paid_now"), zero_38_2).alias("paid_to_date"),
            F.coalesce(F.col("os_now"), zero_38_2).alias("outstanding_reserve"),
            (F.coalesce(F.col("paid_now"), zero_38_2) + F.coalesce(F.col("os_now"), zero_38_2)).cast("decimal(38,2)").alias("incurred_amount"),
            (F.coalesce(F.col("paid_prior"), zero_38_2) + F.coalesce(F.col("os_prior"), zero_38_2)).cast("decimal(38,2)").alias("incurred_90d_ago"),
            F.coalesce(F.col("reserve_changes_90d"), F.lit(0).cast("int")).alias("reserve_changes_90d"),
            F.when(
                F.coalesce(F.col("last_payment_date"), sentinel) > F.coalesce(F.col("last_reserve_date"), sentinel),
                F.col("last_payment_date"),
            ).otherwise(F.col("last_reserve_date")).alias("last_activity_date"),
        )
    )

    # TSQL-07: exact decimal multipliers
    up = F.lit(Decimal("1.10"))
    down = F.lit(Decimal("0.90"))
    i_inc = F.col("incurred_amount")
    i_prior = F.col("incurred_90d_ago")

    out = (
        inc
        .join(clm, on="claim_id", how="inner")
        .where(i_inc >= F.lit(25000))
        .select(
            as_of_lit.alias("as_of_date"),
            F.col("claim_id"),
            F.col("claim_number"),
            F.col("policy_id"),
            F.col("lob_code"),
            F.col("claim_status"),
            F.col("reported_date"),
            F.col("closed_date"),
            F.col("paid_to_date"),
            F.col("outstanding_reserve"),
            i_inc.alias("incurred_amount"),
            i_prior.alias("incurred_90d_ago"),
            (i_inc - i_prior).cast("decimal(38,2)").alias("movement_90d"),
            F.col("reserve_changes_90d"),
            # TSQL-04: DATEDIFF(DAY, start, end) -> datediff(end, start)
            F.datediff(as_of_lit, F.col("last_activity_date")).alias("days_since_last_activity"),
            F.when(i_prior < F.lit(25000), F.lit("NEW"))
             .when(i_inc > i_prior * up, F.lit("DETERIORATING"))
             .when(i_inc < i_prior * down, F.lit("IMPROVING"))
             .otherwise(F.lit("STABLE")).alias("watch_category"),
        )
    )

    return {"rpt.large_loss_watchlist": out}
