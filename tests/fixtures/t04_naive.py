"""
T04, translated naively on purpose: a test fixture for reconciliation, never a migrated job.

It makes three classic mistakes, each of which reconciliation must catch and name:

- the open-status filter compares case-sensitively and keeps trailing spaces (TSQL-01, TSQL-02),
  so claims keyed 'Open' or 'OPEN ' go missing;
- the claim reference uses ``concat_ws``, which skips a NULL handler, where T-SQL's ``+``
  gives NULL (TSQL-05);
- it "fixes" BUG-03 by totalling payments before joining the reserves, so total paid and
  incurred no longer double on claims with two reserve types.
"""

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def run(
    spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]
) -> dict[str, DataFrame]:
    """
    Build the open-claims summary with the three mistakes above.
    """
    as_of = F.to_date(F.lit(params["AsOfDate"]))
    claims = (
        inputs["stg.claims"]
        .where(F.col("status").isin("OPEN", "REOPENED") & (F.col("reported_date") <= as_of))
        .withColumn("lob_code", F.upper(F.rtrim("lob_code")))
    )
    reserves = inputs["stg.claim_reserves"].where(F.col("reserve_date") <= as_of)
    latest = Window.partitionBy("claim_id", "reserve_type").orderBy(
        F.col("reserve_date").desc(), F.col("reserve_id").desc()
    )
    reserves = reserves.withColumn("rn", F.row_number().over(latest)).where("rn = 1")
    reserve_money = reserves.groupBy("claim_id").agg(
        F.max(F.when(F.col("reserve_type") == "INDEMNITY", F.col("reserve_amount"))).alias("ind"),
        F.max(F.when(F.col("reserve_type") == "EXPENSE", F.col("reserve_amount"))).alias("exp"),
    )
    paid = (
        inputs["stg.claim_payments"]
        .where(F.col("payment_date") <= as_of)
        .groupBy("claim_id")
        .agg(F.countDistinct("payment_id").alias("n"), F.sum("amount").alias("paid"))
    )
    snapshots = inputs["stg.policy_snapshots"]
    snapshot = (
        snapshots.where(F.col("snapshot_date") <= as_of).agg(F.max("snapshot_date")).first()[0]
    )
    policies = snapshots.where(F.col("snapshot_date") == F.lit(snapshot)).select(
        "policy_id", "policy_number"
    )
    out = (
        claims.join(paid, "claim_id", "left")
        .join(reserve_money, "claim_id", "left")
        .join(policies, "policy_id", "left")
        .select(
            "claim_id",
            "claim_number",
            F.concat_ws("/", "lob_code", "claim_number", "handler_code").alias("claim_ref"),
            "policy_id",
            "policy_number",
            "lob_code",
            "status",
            "handler_code",
            "loss_date",
            F.date_format("loss_date", "dd/MM/yyyy").alias("loss_date_text"),
            "reported_date",
            F.date_format("reported_date", "yyyyMM").alias("reported_period"),
            F.datediff(as_of, "reported_date").alias("days_open"),
            F.coalesce("n", F.lit(0)).alias("n_payments"),
            F.coalesce("paid", F.lit(0)).alias("total_paid"),
            F.coalesce("ind", F.lit(0)).alias("indemnity_reserve"),
            F.coalesce("exp", F.lit(0)).alias("expense_reserve"),
            (F.coalesce("ind", F.lit(0)) + F.coalesce("exp", F.lit(0))).alias("current_reserve"),
            (
                F.coalesce("paid", F.lit(0))
                + F.coalesce("ind", F.lit(0))
                + F.coalesce("exp", F.lit(0))
            ).alias("incurred"),
            as_of.alias("as_of_date"),
        )
    )
    return {"rpt.claims_summary": out}
