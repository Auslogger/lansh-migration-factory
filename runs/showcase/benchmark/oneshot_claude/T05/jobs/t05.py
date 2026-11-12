"""T05 rpt.usp_claim_aging -> PySpark.

Ages the open book (claims with status OPEN or REOPENED, notified on or before
@AsOfDate) on the days since last activity. Last activity is the last payment
up to @AsOfDate, or the reported date when nothing has been paid.
Output: rpt.claim_aging, truncated and reloaded on every run.
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_of_lit = F.lit(as_of)

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]

    # 1. open book. The default SQL Server collation is case-insensitive and
    #    ignores trailing spaces, so IN ('OPEN','REOPENED') matches 'open ' as well.
    #    A NULL status or reported_date is filtered out.
    open_claims = (
        claims
        .where(F.upper(F.rtrim(F.col("status"))).isin("OPEN", "REOPENED"))
        .where(F.col("reported_date") <= as_of_lit)
        .select(
            F.col("claim_id"),
            F.col("claim_number"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
            F.col("reported_date"),
        )
    )

    # 2. payments on those claims up to the reporting date (a NULL payment_date is dropped)
    pay = (
        payments.alias("p")
        .join(open_claims.select("claim_id").alias("o"),
              F.col("p.claim_id") == F.col("o.claim_id"), "inner")
        .where(F.col("p.payment_date") <= as_of_lit)
        .select(F.col("p.claim_id").alias("claim_id"),
                F.col("p.payment_id").alias("payment_id"),
                F.col("p.payment_date").alias("payment_date"),
                F.col("p.amount").alias("amount"))
    )

    # 3. cursor loop, replaced by an aggregate that gives the same result:
    #    n_pay counts every fetched row; @total = @total + @amount becomes NULL
    #    for good once any amount is NULL; @last_pay is the payment_date of the
    #    last row in (payment_date, payment_id) order, i.e. the max payment_date.
    pay_agg = (
        pay.groupBy("claim_id")
        .agg(
            F.count(F.lit(1)).alias("_n"),
            F.count(F.col("amount")).alias("_nn"),
            F.sum(F.col("amount")).alias("_s"),
            F.max(F.col("payment_date")).alias("_last"),
        )
    )

    a = open_claims.join(pay_agg, on="claim_id", how="left")

    n_payments = F.coalesce(F.col("_n"), F.lit(0)).cast("int")
    total_paid = (
        F.when(F.col("_n").isNull(), F.lit(0).cast("decimal(14,2)"))  # SET @total = 0 when there are no payments
        .when(F.col("_nn") < F.col("_n"), F.lit(None).cast("decimal(22,2)"))  # NULL amount turns the running total NULL
        .otherwise(F.col("_s"))
    )
    last_pay = F.col("_last")
    last_act = F.coalesce(last_pay, F.col("reported_date"))
    days = F.datediff(as_of_lit, last_act)

    # DATEDIFF(WEEK, ...) counts the Sunday boundaries crossed, whatever DATEFIRST is.
    # Spark dayofweek: Sunday = 1, so date_sub(d, dayofweek(d) - 1) is the Sunday on or before d.
    def _week_sunday(c):
        return F.date_sub(c, F.dayofweek(c) - 1)

    weeks = (F.datediff(_week_sunday(as_of_lit), _week_sunday(F.col("reported_date"))) / 7).cast("int")

    band = (
        F.when(days < 30, F.lit("0-29"))
        .when(days.between(31, 60), F.lit("31-60"))  # LANSH-DEFECT: day 30 is in no band and falls through to 'UNKNOWN'
        .when(days > 60, F.lit("61+"))
        .otherwise(F.lit("UNKNOWN"))
    )

    # 4. reload the report table
    result = a.select(
        F.col("claim_id"),
        F.col("claim_number"),
        F.col("lob_code"),
        F.col("reported_date"),
        n_payments.alias("n_payments"),
        total_paid.alias("total_paid"),
        last_pay.alias("last_payment_date"),
        last_act.alias("last_activity_date"),
        days.alias("days_since_activity"),
        weeks.alias("weeks_open"),
        band.alias("aging_band"),
        as_of_lit.alias("as_of_date"),
    )

    return {"rpt.claim_aging": result}
