"""T03 usp_build_fact_premium_earned: migrated from estate/tsql/T03_usp_build_fact_premium_earned.sql.

Legacy SHA-256: 5fbf16f70c9c202ea4f177ec504f51992cf11022b0d992bc484b0cfa10e93670
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-03, TSQL-07, TSQL-08, TSQL-09, TSQL-13, TSQL-18
Bugs reproduced on purpose (# LANSH-DEFECT): T03-D1 fixed 365-day earning, T03-D2 truncated earned_pct, T03-D3 month-end first due date, T03-D4 non-EUR rows without FX rate dropped, T03-D5 rows without current policy dropped, T03-D6 daily rate truncated
"""
from pyspark.sql import SparkSession, DataFrame, Window
import pyspark.sql.functions as F


def _trunc(c, scale):
    # T-SQL truncation toward zero at `scale` places (decimal quotient / ROUND(x, n, 1))
    return F.when(c >= 0, F.floor(c, scale)).otherwise(F.ceil(c, scale))


def _div_trunc(num, den, scale):
    # Divide at a higher scale (decimal(38,18) in Spark), then truncate toward zero
    # at the T-SQL result scale, as SQL Server does for a DECIMAL quotient.
    q = num.cast("decimal(30,10)") / den.cast("decimal(10,0)")
    return _trunc(q, scale)


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.lit(params["AsOfDate"]).cast("date")

    t = inputs["stg.premium_transactions"]
    r = inputs["stg.fx_rates"]
    p = inputs["dw.dim_policy"]

    # TSQL-01/02: CI collation, trailing spaces ignored
    cur_key = F.upper(F.rtrim(F.col("currency")))

    base = t.where(F.col("txn_date") <= as_of)

    # #txn, EUR branch (SELECT INTO) - TSQL-13
    eur = base.where(cur_key == "EUR").select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.upper(F.rtrim(F.col("txn_type"))).alias("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.col("currency"),
        F.col("amount"),
        F.lit(1).cast("decimal(18,8)").alias("fx_rate"),
    )

    # #txn, non-EUR branch (INSERT) with CROSS APPLY TOP 1 - TSQL-08/09
    non_eur = base.where(cur_key != "EUR").withColumn("_t_cur_key", cur_key)  # LANSH-DEFECT: T03-D4 NULL currency fails both = 'EUR' and <> 'EUR' and is dropped
    rates = r.select(
        F.upper(F.rtrim(F.col("currency"))).alias("_r_cur_key"),
        F.col("rate_date").alias("_r_rate_date"),
        F.col("rate_to_eur").alias("_r_rate"),
        F.col("_row_seq").alias("_r_seq"),
    )
    joined = non_eur.join(  # LANSH-DEFECT: T03-D4 inner join (CROSS APPLY) silently drops non-EUR transactions without a rate on/before txn_date
        rates,
        (F.col("_t_cur_key") == F.col("_r_cur_key")) & (F.col("_r_rate_date") <= F.col("txn_date")),
        "inner",
    )
    w = Window.partitionBy(F.col("_row_seq")).orderBy(F.col("_r_rate_date").desc(), F.col("_r_seq").desc())
    fx = joined.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.upper(F.rtrim(F.col("txn_type"))).alias("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.col("currency"),
        F.col("amount"),
        F.col("_r_rate").cast("decimal(18,8)").alias("fx_rate"),
    )

    txn = eur.unionByName(fx)

    # #earn - TSQL-13
    term_days = F.datediff(F.col("effective_to"), F.col("effective_from")) + 1
    earn = txn.select(
        "*",
        # TSQL-07: decimal(12,2)*decimal(18,8) -> decimal(31,10), ROUND half away from zero, cast decimal(14,2)
        F.round(F.col("amount") * F.col("fx_rate"), 2).cast("decimal(14,2)").alias("written_eur"),
        term_days.alias("term_days"),
        F.when(as_of < F.col("effective_from"), F.lit(0))
        .when(as_of >= F.col("effective_to"), term_days)
        .otherwise(F.datediff(as_of, F.col("effective_from")) + 1)
        .alias("earned_days"),
    )

    pol = p.where(F.upper(F.rtrim(F.col("is_current"))) == "Y").select(  # TSQL-01/02 on is_current
        F.col("policy_id").alias("_p_policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
    )
    f = earn.join(pol, F.col("policy_id") == F.col("_p_policy_id"), "inner")  # LANSH-DEFECT: T03-D5 transactions without a current dim_policy row are dropped

    written = F.col("written_eur")

    # earned_eur: decimal(25,2) / 365 -> decimal(36,13) truncated, then ROUND 2 half away from zero
    earned_num = (written * F.col("earned_days")).cast("decimal(25,2)")
    earned_eur = F.round(_div_trunc(earned_num, F.lit(365), 13).cast("decimal(36,13)"), 2)  # LANSH-DEFECT: T03-D1 earned pro-rated over fixed 365 days, not term_days

    # daily_rate_eur: decimal(14,2)/int -> decimal(25,13) truncated, then ROUND(x,4,1) truncation
    daily_q = _div_trunc(written, F.col("term_days"), 13).cast("decimal(25,13)")
    daily_rate = _trunc(daily_q, 4)  # LANSH-DEFECT: T03-D6 ROUND(...,4,1) truncates instead of rounding

    # monthly_instalment_eur: ISNULL(NULLIF(term_days/30, 0), 1) with integer division
    n_inst = F.expr("term_days div 30")
    divisor = F.coalesce(F.when(n_inst != 0, n_inst), F.lit(1)).cast("int")
    monthly = F.round(_div_trunc(written, divisor, 13).cast("decimal(25,13)"), 2)

    # first_due_date: DATEADD(MONTH, 1, EOMONTH(effective_from)) - TSQL-18 (no snap to month-end)
    eom = F.last_day(F.col("effective_from"))
    tgt = F.add_months(eom, 1)
    first_due = F.make_date(  # LANSH-DEFECT: T03-D3 month added to a month-end keeps the day number (28 Feb -> 28 Mar)
        F.year(tgt),
        F.month(tgt),
        F.least(F.dayofmonth(eom), F.dayofmonth(F.last_day(tgt))),
    )

    out = f.select(
        F.col("txn_id"),
        F.col("policy_id"),
        F.col("policy_sk"),
        F.col("lob_code"),
        F.col("txn_type"),
        F.col("txn_date"),
        F.col("effective_from"),
        F.col("effective_to"),
        F.rpad(F.col("currency"), 3, " ").alias("currency"),  # TSQL-02 CHAR(3) output
        F.col("amount"),
        F.col("fx_rate"),
        F.col("written_eur"),
        F.col("term_days"),
        F.col("earned_days"),
        F.expr("(earned_days * 100) div term_days").alias("earned_pct"),  # LANSH-DEFECT: T03-D2 INT/INT truncates the percentage
        earned_eur.alias("earned_eur"),  # LANSH-DEFECT: T03-D1 fixed 365-day denominator
        (written - earned_eur).alias("unearned_eur"),  # LANSH-DEFECT: T03-D1 unearned from 365-day earning, can go negative
        daily_rate.alias("daily_rate_eur"),  # LANSH-DEFECT: T03-D6 truncated daily rate
        monthly.alias("monthly_instalment_eur"),
        first_due.alias("first_due_date"),  # LANSH-DEFECT: T03-D3 inconsistent first due date
        as_of.alias("as_of_date"),
    )

    return {"dw.fact_premium_earned": out}
