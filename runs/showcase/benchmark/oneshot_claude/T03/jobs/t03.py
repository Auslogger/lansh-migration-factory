"""T03 dw.usp_build_fact_premium_earned -> PySpark.

Rebuilds dw.fact_premium_earned in full: one row per premium transaction booked
on or before AsOfDate. Each row carries its EUR rate, written and earned premium
in EUR, the daily rate, the monthly instalment and the first due date.

Legacy behaviour reproduced on purpose:
  * Currency / is_current comparisons follow the default SQL Server collation
    (case-insensitive, trailing blanks ignored).
  * Non-EUR transactions with no rate on or before txn_date are dropped (CROSS APPLY).
  * Transactions with no current dim_policy row are dropped (inner JOIN).
  * earned_pct uses integer division; earned_eur divides by 365, not term_days;
    first_due_date = DATEADD(MONTH, 1, EOMONTH(effective_from)).
"""
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql import Window


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.to_date(F.lit(params["AsOfDate"]))

    txn = inputs["stg.premium_transactions"]
    fx = inputs["stg.fx_rates"]
    dim = inputs["dw.dim_policy"]

    # Collation-like key: CI comparison, trailing blanks ignored
    t_ccy_key = F.upper(F.rtrim(F.col("currency")))

    base = txn.where(F.col("txn_date") <= as_of).select(
        F.col("_row_seq").alias("t_seq"),
        "txn_id",
        "policy_id",
        F.upper(F.rtrim(F.col("txn_type"))).alias("txn_type"),
        "txn_date",
        "effective_from",
        "effective_to",
        "currency",
        "amount",
        t_ccy_key.alias("t_ccy_key"),
    )

    # EUR transactions at rate 1
    eur = base.where(F.col("t_ccy_key") == F.lit("EUR")).withColumn(
        "fx_rate", F.lit(1).cast(T.DecimalType(18, 8))
    )

    # Non-EUR: CROSS APPLY TOP 1 rate on or before txn_date (rate_date DESC, _row_seq DESC)
    non_eur = base.where(F.col("t_ccy_key") != F.lit("EUR"))
    rates = fx.select(
        F.upper(F.rtrim(F.col("currency"))).alias("r_ccy_key"),
        F.col("rate_date").alias("r_date"),
        F.col("rate_to_eur").alias("r_rate"),
        F.col("_row_seq").alias("r_seq"),
    )
    joined = non_eur.join(
        rates,
        (non_eur["t_ccy_key"] == rates["r_ccy_key"]) & (rates["r_date"] <= non_eur["txn_date"]),
        "inner",
    )
    w = Window.partitionBy("t_seq").orderBy(F.col("r_date").desc(), F.col("r_seq").desc())
    non_eur_rated = (
        joined.withColumn("_rn", F.row_number().over(w))
        .where(F.col("_rn") == 1)
        .withColumn("fx_rate", F.col("r_rate").cast(T.DecimalType(18, 8)))
        .drop("_rn", "r_ccy_key", "r_date", "r_rate", "r_seq")
    )

    txn_all = eur.unionByName(non_eur_rated).drop("t_seq", "t_ccy_key")

    # #earn
    ef = F.col("effective_from")
    et = F.col("effective_to")
    term_days = F.datediff(et, ef) + F.lit(1)
    earn = (
        txn_all.withColumn(
            "written_eur",
            F.round(F.col("amount") * F.col("fx_rate"), 2).cast(T.DecimalType(14, 2)),
        )
        .withColumn("term_days", term_days.cast(T.IntegerType()))
        .withColumn(
            "earned_days",
            F.when(as_of < ef, F.lit(0))
            .when(as_of >= et, F.datediff(et, ef) + F.lit(1))
            .otherwise(F.datediff(as_of, ef) + F.lit(1))
            .cast(T.IntegerType()),
        )
    )

    pol = dim.where(F.upper(F.rtrim(F.col("is_current"))) == F.lit("Y")).select(
        F.col("policy_id").alias("p_policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
    )

    e = earn.join(pol, earn["policy_id"] == pol["p_policy_id"], "inner")

    earned_eur_expr = F.round(F.col("written_eur") * F.col("earned_days") / F.lit(365), 2)  # LANSH-DEFECT: earned premium divides by 365 instead of term_days

    out = e.select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
        F.col("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.col("currency"),
        F.col("amount"),
        F.col("fx_rate"),
        F.col("written_eur"),
        F.col("term_days"),
        F.col("earned_days"),
        F.expr("(earned_days * 100) div term_days").alias("earned_pct"),  # LANSH-DEFECT: integer division truncates earned_pct to a whole percent
        earned_eur_expr.alias("earned_eur"),
        (F.col("written_eur") - earned_eur_expr).alias("unearned_eur"),  # LANSH-DEFECT: unearned derived from the /365 earned amount
        F.expr(
            "CASE WHEN written_eur / term_days >= 0 "
            "THEN floor(written_eur / term_days, 4) "
            "ELSE ceil(written_eur / term_days, 4) END"
        ).alias("daily_rate_eur"),
        F.round(
            F.col("written_eur")
            / F.expr("cast(coalesce(nullif(term_days div 30, 0), 1) as int)"),
            2,
        ).alias("monthly_instalment_eur"),
        F.add_months(F.last_day(F.col("effective_from")), 1).alias("first_due_date"),  # LANSH-DEFECT: DATEADD(MONTH,1,EOMONTH()) keeps day-of-month (Feb 28 -> Mar 28, Apr 30 -> May 30)
        as_of.alias("as_of_date"),
    )

    return {"dw.fact_premium_earned": out}
