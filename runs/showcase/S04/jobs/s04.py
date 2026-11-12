"""S04 risk_scoring: migrated from estate/sas/S04_risk_scoring.sas.

Legacy SHA-256: c1d72f4893edd62876d4761f52b901aa90dfef5174bbc3f8bb269afea9e46504
Written by: LANSH translator (Claude)
Traps handled: SAS-03, SAS-10, SAS-11, SAS-13, SAS-15
Bugs reproduced on purpose (# LANSH-DEFECT): S04-D1 hard-coded line list, S04-D2 missing inputs give missing score and tier LOW, S04-D3 customer dimension join can multiply rows, S04-D4 age by days/365.25, S04-D5 claims not limited to reporting date
"""
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def _sas_char(c):
    # SAS char: trailing blanks never count, a blank value is missing
    t = F.rtrim(c)
    return F.when(t == "", F.lit(None).cast("string")).otherwise(t)


def _sas_round(x, unit: str):
    # SAS round(x, unit) with fuzz: decimal arithmetic, half away from zero (SAS-15)
    u = F.lit(Decimal(unit))
    return (F.round(x.cast("decimal(38,10)") / u, 0) * u).cast("double")


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.to_date(F.lit(params["AsOfDate"]))

    # ---- work.cust (lines 22-34) ----
    dimc = inputs["dw.dim_customer"]
    age_raw = F.datediff(as_of, F.col("date_of_birth")).cast("double") / F.lit(365.25)  # SAS-03
    # int() truncates toward zero
    age = F.when(age_raw >= 0, F.floor(age_raw)).otherwise(F.ceil(age_raw)).cast("double")  # LANSH-DEFECT: S04-D4 age approximated by days/365.25
    cust = dimc.select(
        F.col("customer_id").cast("double").alias("customer_id"),
        F.col("date_of_birth"),
        F.col("county"),
    ).withColumn("age", age)
    cust = cust.withColumn(
        "age_load",
        F.when(F.col("age").isNull(), F.lit(1.00))
        .when(F.col("age") < 25, F.lit(1.40))  # LANSH-DEFECT: S04-D4 age boundary uses approximated age
        .when(F.col("age") >= 70, F.lit(1.25))  # LANSH-DEFECT: S04-D4 age boundary uses approximated age
        .otherwise(F.lit(1.00)),
    )
    cty = F.upper(F.trim(F.col("county")))
    cust = cust.withColumn(
        "county_load",
        F.when(cty == "DUBLIN", F.lit(1.15))
        .when(cty.isin("CORK", "LIMERICK", "GALWAY"), F.lit(1.05))
        .otherwise(F.lit(1.00)),
    ).select("customer_id", "age", "age_load", "county_load")  # LANSH-DEFECT: S04-D3 every dim_customer row kept, no current-version filter

    # ---- work.experience (lines 37-45) ----
    cl = inputs["dw.claims_enriched"].select(
        F.col("customer_id").cast("double").alias("customer_id"),
        _sas_char(F.col("lob_code")).alias("lob_code"),
        F.col("total_paid").cast("double").alias("total_paid"),
        F.col("n_recoveries").cast("double").alias("n_recoveries"),
    )
    experience = cl.groupBy("customer_id", "lob_code").agg(  # LANSH-DEFECT: S04-D5 claims not limited to the reporting date
        F.count(F.lit(1)).cast("double").alias("n_claims"),
        F.sum("total_paid").alias("paid"),
        F.sum("n_recoveries").alias("n_recoveries"),  # LANSH-DEFECT: S04-D2 all-missing n_recoveries gives missing sum
    )

    # ---- work.lob_ratio (lines 48-57) ----
    prem = inputs["rpt.premium_band_summary"].select(
        _sas_char(F.col("lob_code")).alias("lob_code"),
        F.col("earned_eur").cast("double").alias("earned_eur"),
    )
    p = prem.groupBy("lob_code").agg(F.sum("earned_eur").alias("earned"))
    e = experience.select(F.col("lob_code").alias("e_lob"), F.col("paid"))
    lob_ratio = (
        e.join(p, e["e_lob"].eqNullSafe(p["lob_code"]), "inner")  # LANSH-DEFECT: S04-D2 inner join drops lines without premium, so loss_ratio is missing
        .groupBy("e_lob", "earned")
        .agg(F.sum("paid").alias("sum_paid"))
        .select(
            F.col("e_lob").alias("r_lob"),
            F.try_divide(F.col("sum_paid"), F.col("earned")).alias("loss_ratio"),
        )
    )

    # ---- %score_lines(MOT HOM TRV) (lines 60-74), SAS-13 / SAS-10 ----
    scores = None
    for lob in ["MOT", "HOM", "TRV"]:  # LANSH-DEFECT: S04-D1 hard-coded line-of-business list drops other lines
        x = experience.where(F.col("lob_code") == F.lit(lob))
        x = x.select(
            "customer_id", "lob_code", "n_claims", "paid", "n_recoveries",
            F.try_divide(F.col("paid"), F.avg("paid").over(Window.partitionBy())).alias("severity"),
        )
        scores = x if scores is None else scores.unionByName(x)  # LANSH-DEFECT: S04-D1 only the three listed score tables are unioned

    # ---- work.scoring (lines 76-87) ----
    s = scores
    scoring = (
        s.join(cust.withColumnRenamed("customer_id", "c_cid"),
               s["customer_id"].eqNullSafe(F.col("c_cid")), "left")  # LANSH-DEFECT: S04-D3 one row per customer version; S04-D2 unmatched customer gets missing loadings
        .join(lob_ratio, F.col("lob_code").eqNullSafe(F.col("r_lob")), "left")
        .select("customer_id", "lob_code", "n_claims", "paid", "n_recoveries", "severity",
                "age", "age_load", "county_load", "loss_ratio")
    )

    # ---- rpt.risk_scores (lines 90-104) ----
    sev_points = (
        F.when(F.col("severity") >= 2, F.lit(10.0))
        .when(F.col("severity") >= 1, F.lit(5.0))
        .otherwise(F.lit(0.0))
    )
    lob_points = _sas_round(F.lit(2.5) * F.col("loss_ratio"), "0.5")  # LANSH-DEFECT: S04-D2 missing loss_ratio passes through
    out = scoring.withColumn("lob_points", lob_points)
    out = out.withColumn(
        "points",
        F.lit(12.5) * F.least(F.col("n_claims"), F.lit(4.0))
        + F.lit(7.5) * F.col("n_recoveries")
        + sev_points
        + F.col("lob_points"),  # LANSH-DEFECT: S04-D2 + propagates missing components into points
    )
    out = out.withColumn(
        "score",
        _sas_round(F.col("points") * F.col("age_load") * F.col("county_load"), "0.01"),  # LANSH-DEFECT: S04-D2 missing points or loadings give missing score
    )
    out = out.withColumn(
        "tier",
        F.substring(  # SAS-11: tier length fixed at 4 by first assignment 'HIGH'
            F.when(F.col("score") >= 35, F.lit("HIGH"))
            .when(F.col("score") >= 22, F.lit("MEDIUM"))
            .otherwise(F.lit("LOW")),  # LANSH-DEFECT: S04-D2 missing score falls to tier LOW
            1, 4,
        ),
    )
    out = out.withColumn("as_of_date", as_of)  # SAS-03: &as_of day count shown as yymmdd10.

    result = out.select(
        "customer_id", "lob_code", "n_claims", "paid", "n_recoveries", "severity", "age",
        "age_load", "county_load", "loss_ratio", "points", "score", "tier", "as_of_date",
    )
    return {"rpt.risk_scores": result}
