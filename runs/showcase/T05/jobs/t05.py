"""T05 usp_claim_aging: migrated from estate/tsql/T05_usp_claim_aging.sql.

Legacy SHA-256: f443e5070182d5b723af38f23dc653d53fc43f8eb322f5cdd5e1f6bd1893b12f
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-12, TSQL-13
Bugs reproduced on purpose (# LANSH-DEFECT): T05-D1 ageing band gap at 30 days, T05-D2 weeks_open counts Sunday boundaries, T05-D3 NULL amount makes total_paid NULL, T05-D4 duplicate staged payments double-counted
"""
import datetime

from pyspark.sql import SparkSession, DataFrame
import pyspark.sql.functions as F
import pyspark.sql.types as T
from pyspark.sql import Window


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(datetime.date.fromisoformat(params["AsOfDate"]))

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]

    # 1. #open_claims (TSQL-13): open and re-opened claims notified by the reporting date.
    # TSQL-01 / TSQL-02: the CI collation ignores case and trailing spaces in the IN list.
    open_claims = (
        claims
        .where(F.upper(F.rtrim(F.col("status"))).isin("OPEN", "REOPENED"))
        .where(F.col("reported_date") <= as_of)
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
            F.col("reported_date"),
        )
    )

    # 2. #pay (TSQL-13): payments on those claims up to the reporting date.
    # The clustered index has no Spark equivalent and is not needed.
    pay = (
        payments.alias("p")
        .join(open_claims.select("claim_id").alias("o"),
              F.col("o.claim_id") == F.col("p.claim_id"), "inner")
        .where(F.col("p.payment_date") <= as_of)
        .select(
            F.col("p.claim_id").alias("claim_id"),
            F.col("p.payment_id").alias("payment_id"),
            F.col("p.payment_date").alias("payment_date"),
            F.col("p.amount").alias("amount"),
        )
    )

    # 3. TSQL-12: the claim_cur / pay_cur loops become an aggregation per claim.
    #    n_pay counts every fetched row; @total = @total + @amount goes NULL on any NULL
    #    amount; @last_pay is the date of the last row in (payment_date, payment_id) order,
    #    which is max(payment_date) (payment_date cannot be NULL after the <= filter).
    pay_agg = (
        pay.groupBy("claim_id")
        .agg(
            F.count(F.lit(1)).alias("n_pay"),  # LANSH-DEFECT: T05-D4 duplicate staged payment rows are each counted
            F.sum(F.when(F.col("amount").isNull(), F.lit(1)).otherwise(F.lit(0))).alias("n_null_amount"),
            F.sum(F.col("amount")).alias("sum_amount"),  # LANSH-DEFECT: T05-D4 duplicate staged payment rows are each summed
            F.max(F.col("payment_date")).alias("last_pay"),
        )
    )

    aging = (
        open_claims.alias("o")
        .join(pay_agg.alias("a"), F.col("a.claim_id") == F.col("o.claim_id"), "left")
        .select(
            F.col("o.claim_id").alias("claim_id"),
            F.col("o.claim_number").alias("claim_number"),
            F.col("o.lob_code").alias("lob_code"),
            F.col("o.reported_date").alias("reported_date"),
            F.col("a.n_pay").alias("n_pay"),
            F.col("a.n_null_amount").alias("n_null_amount"),
            F.col("a.sum_amount").alias("sum_amount"),
            F.col("a.last_pay").alias("last_pay"),
        )
    )

    # Claims with no payments: @n_pay = 0, @total = 0, @last_pay = NULL (lines 114-116).
    n_payments = F.coalesce(F.col("n_pay"), F.lit(0)).cast(T.IntegerType())
    total_paid = (
        F.when(F.col("n_pay").isNull(), F.lit(0).cast(T.DecimalType(14, 2)))
        .when(F.col("n_null_amount") > 0, F.lit(None).cast(T.DecimalType(14, 2)))  # LANSH-DEFECT: T05-D3 one NULL amount makes total_paid NULL
        .otherwise(F.col("sum_amount").cast(T.DecimalType(14, 2)))
    )

    # SET @last_act = ISNULL(@last_pay, @reported)
    last_act = F.coalesce(F.col("last_pay"), F.col("reported_date"))

    # TSQL-04: DATEDIFF(DAY, @last_act, @AsOfDate) -> datediff(end, start)
    days = F.datediff(as_of, F.col("last_activity_date"))

    # TSQL-04: DATEDIFF(WEEK, @reported, @AsOfDate) counts Sundays crossed:
    # difference of Sunday-anchored week numbers.
    sunday_anchor = F.lit(datetime.date.fromisoformat("1899-12-31"))
    weeks = (
        F.floor(F.datediff(as_of, sunday_anchor) / F.lit(7))
        - F.floor(F.datediff(F.col("reported_date"), sunday_anchor) / F.lit(7))
    ).cast(T.IntegerType())  # LANSH-DEFECT: T05-D2 weeks_open counts week boundaries, not elapsed weeks

    d = F.col("days_since_activity")
    band = (
        F.when(d < 30, F.lit("0-29"))
        .when(d.between(31, 60), F.lit("31-60"))  # LANSH-DEFECT: T05-D1 30 days matches no band and falls to UNKNOWN
        .when(d > 60, F.lit("61+"))
        .otherwise(F.lit("UNKNOWN"))  # LANSH-DEFECT: T05-D1 30 days gets UNKNOWN
    )

    result = (
        aging
        .withColumn("n_payments", n_payments)
        .withColumn("total_paid", total_paid)
        .withColumn("last_payment_date", F.col("last_pay"))
        .withColumn("last_activity_date", last_act)
        .withColumn("days_since_activity", days.cast(T.IntegerType()))
        .withColumn("weeks_open", weeks)
        .withColumn("aging_band", band)
        .withColumn("as_of_date", as_of)
        .select(
            "claim_id", "claim_number", "lob_code", "reported_date",
            "n_payments", "total_paid", "last_payment_date", "last_activity_date",
            "days_since_activity", "weeks_open", "aging_band", "as_of_date",
        )
    )

    return {"rpt.claim_aging": result}
