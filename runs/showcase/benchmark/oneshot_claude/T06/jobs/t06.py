"""T06 rpt.usp_loss_triangle -> PySpark.

Paid loss development triangle by accident year and line of business, as at
params["AsOfDate"]. This reproduces the legacy T-SQL procedure exactly, legacy
defects included.
"""
import datetime
from functools import reduce

from pyspark.sql import SparkSession, DataFrame
import pyspark.sql.functions as F
import pyspark.sql.types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"].strip()[:10])
    as_at_yr = as_of.year
    as_of_lit = F.lit(as_of)

    claims = inputs["stg.claims"]
    payments = inputs["stg.claim_payments"]

    # 1. Claims with a loss in the last seven accident years
    cl = (
        claims
        .where(
            F.year("loss_date").between(as_at_yr - 6, as_at_yr)
            & (F.col("loss_date") <= as_of_lit)
        )
        .select(
            F.col("claim_id"),
            F.col("loss_date"),
            F.year("loss_date").alias("accident_year"),
            # T-SQL RTRIM strips trailing spaces only; leading spaces are kept
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),
        )
    )

    # 2. Payments to the as-at date, with their development year
    p = payments.select(
        F.col("claim_id").alias("p_claim_id"),
        F.col("payment_id"),
        F.col("payment_date"),
        F.col("amount"),
    )
    paid = (
        cl.join(p, p["p_claim_id"] == cl["claim_id"], "inner")
        .where(
            (F.col("payment_date") <= as_of_lit)
            & (F.col("payment_date") > F.col("loss_date"))  # LANSH-DEFECT: strict '>' drops payments made on the loss date itself, not only the ones dated before the loss
            & F.col("amount").isNotNull()
        )
        .select(
            F.col("accident_year"),
            F.col("lob_code"),
            # DATEDIFF(YEAR, a, b) counts calendar-year boundaries crossed
            (F.year("payment_date") - F.year("loss_date")).alias("dev_year"),
            F.col("amount"),
        )
    )

    # 3. PIVOT SUM(amount) FOR dev_year IN ([0]..[6]), grouped by accident_year, lob_code
    aggs = [
        F.sum(F.when(F.col("dev_year") == k, F.col("amount"))).alias("d%d" % k)
        for k in range(7)
    ]
    tri = paid.groupBy("accident_year", "lob_code").agg(*aggs)

    # 4. Insert: nothing paid yet = 0; a cell after the as-at year stays NULL
    dec = T.DecimalType(14, 2)
    zero = F.lit(0).cast(dec)

    def dev_cell(k: int):
        filled = F.coalesce(F.col("d%d" % k).cast(dec), zero)
        if k == 0:
            return filled
        return F.when(F.col("accident_year") + F.lit(k) <= F.lit(as_at_yr), filled)

    # lob_code is NOT NULL in the target: a NULL lob_code group makes the legacy INSERT fail
    lob_checked = F.when(
        F.col("lob_code").isNull(),
        F.raise_error(F.lit("Cannot insert the value NULL into column 'lob_code', table 'rpt.loss_triangle_paid'")),
    ).otherwise(F.col("lob_code"))

    ins = tri.select(
        F.col("accident_year").cast(T.IntegerType()).alias("accident_year"),
        lob_checked.alias("lob_code"),
        *[dev_cell(k).cast(dec).alias("dev_%d" % k) for k in range(7)],
    )

    # cumulative paid (NULL propagates after the as-at year, same as dev_n)
    cum_cols = []
    for k in range(7):
        expr = reduce(lambda a, b: a + b, [F.col("dev_%d" % i) for i in range(k + 1)])
        cum_cols.append(expr.alias("cumulative_%d" % k))

    out = ins.select(
        F.col("accident_year"),
        F.col("lob_code"),
        *[F.col("dev_%d" % k) for k in range(7)],
        *cum_cols,
        as_of_lit.alias("as_of_date"),
    )

    return {"rpt.loss_triangle_paid": out}
