"""T06 usp_loss_triangle: migrated from estate/tsql/T06_usp_loss_triangle.sql.

Legacy SHA-256: cee60f041de5a268d53d966f273fdde67f2a7710f57427e91412a791d568b613
Written by: LANSH translator (Claude)
Traps handled: TSQL-13, TSQL-04, TSQL-17
Bugs reproduced on purpose (# LANSH-DEFECT): T06-D1 same-day payments dropped; T06-D2 lob_code only right-trimmed; T06-D3 duplicate claim rows multiply payments; T06-D4 accident year/LOB with no payments missing
"""
import datetime

from pyspark.sql import DataFrame, SparkSession
import pyspark.sql.functions as F
import pyspark.sql.types as T


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_at_yr = as_of.year
    as_of_lit = F.lit(as_of)

    claims_src = inputs["stg.claims"]
    payments_src = inputs["stg.claim_payments"]

    # ------------------------------------------------------------------
    # 1. #claims (TSQL-13): claims with a loss in the last seven accident years
    # ------------------------------------------------------------------
    claims = (
        claims_src  # LANSH-DEFECT: T06-D3 no dedup by claim_id; duplicate staging rows are all kept
        .where(
            F.year("loss_date").between(as_at_yr - 6, as_at_yr)
            & (F.col("loss_date") <= as_of_lit)
        )
        .select(
            F.col("claim_id"),
            F.col("loss_date"),
            F.year("loss_date").alias("accident_year"),
            F.upper(F.rtrim(F.col("lob_code"))).alias("lob_code"),  # LANSH-DEFECT: T06-D2 RTRIM only; leading spaces split LOB groups
        )
    )

    # ------------------------------------------------------------------
    # 2. #paid (TSQL-13): payments to the as-at date with their dev year
    # ------------------------------------------------------------------
    p = payments_src.alias("p")
    cl = claims.alias("cl")
    paid = (
        cl.join(p, F.col("p.claim_id") == F.col("cl.claim_id"), "inner")  # LANSH-DEFECT: T06-D3 each payment joins every copy of its claim
        .where(
            (F.col("p.payment_date") <= as_of_lit)
            & (F.col("p.payment_date") > F.col("cl.loss_date"))  # LANSH-DEFECT: T06-D1 same-day payments (payment_date = loss_date) dropped
            & F.col("p.amount").isNotNull()
        )
        .select(
            F.col("cl.claim_id").alias("claim_id"),
            F.col("p.payment_id").alias("payment_id"),
            F.col("cl.accident_year").alias("accident_year"),
            F.col("cl.lob_code").alias("lob_code"),
            # TSQL-04: DATEDIFF(YEAR, loss_date, payment_date) counts calendar-year boundaries
            (F.year(F.col("p.payment_date")) - F.year(F.col("cl.loss_date"))).alias("dev_year"),
            F.col("p.amount").alias("amount"),
        )
    )

    # ------------------------------------------------------------------
    # 3. #tri (TSQL-13, TSQL-17): PIVOT grouped by accident_year, lob_code
    # ------------------------------------------------------------------
    tri = (
        paid.select("accident_year", "lob_code", "dev_year", "amount")
        .groupBy("accident_year", "lob_code")  # LANSH-DEFECT: T06-D4 triangle built from #paid only; groups with no payments get no row
        .pivot("dev_year", [0, 1, 2, 3, 4, 5, 6])
        .agg(F.sum("amount"))
        .select(
            F.col("accident_year"),
            F.col("lob_code"),
            F.col("0").alias("d0"),
            F.col("1").alias("d1"),
            F.col("2").alias("d2"),
            F.col("3").alias("d3"),
            F.col("4").alias("d4"),
            F.col("5").alias("d5"),
            F.col("6").alias("d6"),
        )
    )

    # ------------------------------------------------------------------
    # 4. Insert: ISNULL(d0, 0); dev_n NULL after the as-at year
    # ------------------------------------------------------------------
    dec = T.DecimalType(14, 2)

    def dev_cell(n: int):
        if n == 0:
            expr = F.coalesce(F.col("d0"), F.lit(0))
        else:
            expr = F.when(
                (F.col("accident_year") + n) <= F.lit(as_at_yr),
                F.coalesce(F.col("d" + str(n)), F.lit(0)),
            )
        # stored into DECIMAL(14,2) by the INSERT
        return expr.cast(dec).alias("dev_" + str(n))

    inserted = tri.select(
        F.col("accident_year"),
        F.col("lob_code"),
        *[dev_cell(n) for n in range(7)],
        as_of_lit.alias("as_of_date"),
    )

    # UPDATE: cumulative_n = dev_0 + ... + dev_n (NULL propagates)
    cum_cols = []
    for n in range(7):
        expr = F.col("dev_0")
        for k in range(1, n + 1):
            expr = expr + F.col("dev_" + str(k))
        cum_cols.append(expr.alias("cumulative_" + str(n)))

    result = inserted.select(
        F.col("accident_year"),
        F.col("lob_code"),
        *[F.col("dev_" + str(n)) for n in range(7)],
        *cum_cols,
        F.col("as_of_date"),
    )

    return {"rpt.loss_triangle_paid": result}
