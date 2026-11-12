"""S04 risk_scoring.sas: migrated from risk_scoring.sas.

Legacy SHA-256: not provided
Written by: LANSH translator (Claude)
Traps handled: SAS-11
Bugs reproduced on purpose (# LANSH-DEFECT): age approximated by days/365.25; '+' propagates missing into points/score; missing score tiered LOW; tier truncated to $4 so 'MEDIUM' becomes 'MEDI'

Customer risk score and referral tier by line of business, worked out from
claims experience, the line's loss ratio and the policyholder's age and county
loadings. Output: rpt.risk_scores, rebuilt on every run.

Legacy behaviours reproduced on purpose:
  * PROC SQL remerge: x.paid / mean(x.paid) with no GROUP BY divides each
    customer's paid by the mean over the whole line (a window over lob_code).
  * PROC SQL division by zero or by a missing value gives missing (try_divide).
  * SAS joins treat missing = missing as a match (eqNullSafe on customer_id).
  * The SAS '+' operator carries a missing value through, so a missing
    loss_ratio or n_recoveries makes points and score missing, and the tier
    falls through to 'LOW'.
  * SAS MIN() skips missing values (F.least does the same).
  * SAS ROUND(x, unit) fuzzes near the half: values a hair below .5 of the
    unit (floating-point representation) still round up.
  * tier has no LENGTH statement: its first assignment 'HIGH' fixes it at $4.
"""
from pyspark.sql import SparkSession, DataFrame, Window
import pyspark.sql.functions as F


def _sas_round(x, unit: float):
    # SAS ROUND(x, unit): x / unit rounded to the nearest integer, half away
    # from zero, with a small fuzz so representation error just below the
    # half still rounds up; then multiplied back by the unit.
    q = x / F.lit(unit)
    q_fuzzed = F.round(q, 7)
    return F.round(q_fuzzed, 0) * F.lit(unit)


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = F.to_date(F.lit(params["AsOfDate"]))

    # ---- work.cust: policyholder loadings -------------------------------
    cust_src = inputs["dw.dim_customer"]
    # LANSH-DEFECT: age approximated as int(days / 365.25), truncated toward zero; can be one year out around birthdays
    age = (F.datediff(as_of, F.col("date_of_birth")).cast("double") / F.lit(365.25)).cast("bigint").cast("double")
    county_u = F.upper(F.trim(F.col("county")))
    cust = (
        cust_src
        .select(
            F.col("customer_id").cast("double").alias("c_customer_id"),
            age.alias("age"),
            county_u.alias("county_u"),
        )
        .select(
            "c_customer_id",
            "age",
            F.when(F.col("age").isNull(), F.lit(1.00))
             .when(F.col("age") < 25, F.lit(1.40))
             .when(F.col("age") >= 70, F.lit(1.25))
             .otherwise(F.lit(1.00)).cast("double").alias("age_load"),
            F.when(F.col("county_u") == "DUBLIN", F.lit(1.15))
             .when(F.col("county_u").isin("CORK", "LIMERICK", "GALWAY"), F.lit(1.05))
             .otherwise(F.lit(1.00)).cast("double").alias("county_load"),
        )
    )

    # ---- work.experience --------------------------------------------------
    claims = inputs["dw.claims_enriched"]
    experience = (
        claims
        .select(
            F.col("customer_id").cast("double").alias("customer_id"),
            F.rtrim(F.col("lob_code")).alias("lob_code"),  # SAS char compare ignores trailing blanks
            F.col("total_paid").cast("double").alias("total_paid"),
            F.col("n_recoveries").cast("double").alias("n_recoveries"),
        )
        .groupBy("customer_id", "lob_code")
        .agg(
            F.count(F.lit(1)).cast("double").alias("n_claims"),
            F.sum("total_paid").alias("paid"),
            F.sum("n_recoveries").alias("n_recoveries"),
        )
    )

    # ---- work.lob_ratio -----------------------------------------------------
    prem = (
        inputs["rpt.premium_band_summary"]
        .select(
            F.rtrim(F.col("lob_code")).alias("lob_code"),
            F.col("earned_eur").cast("double").alias("earned_eur"),
        )
        .groupBy("lob_code")
        .agg(F.sum("earned_eur").alias("earned"))
    )
    lob_ratio = (
        experience.select("lob_code", "paid")
        .join(prem, on="lob_code", how="inner")
        .groupBy("lob_code", "earned")
        .agg(F.sum("paid").alias("sum_paid"))
        .select(
            F.col("lob_code").alias("r_lob_code"),
            F.try_divide(F.col("sum_paid"), F.col("earned")).alias("loss_ratio"),  # PROC SQL: x/0 -> missing
        )
    )

    # ---- work.score_MOT / HOM / TRV (remerged mean per line), UNION ALL ----
    w_lob = Window.partitionBy("lob_code")
    scores = (
        experience
        .filter(F.col("lob_code").isin("MOT", "HOM", "TRV"))
        .withColumn("severity", F.try_divide(F.col("paid"), F.avg("paid").over(w_lob)))
    )

    # ---- work.scoring -------------------------------------------------------
    scoring = (
        scores
        .join(cust, scores["customer_id"].eqNullSafe(cust["c_customer_id"]), "left")
        .join(lob_ratio, F.col("lob_code") == F.col("r_lob_code"), "left")
    )

    # ---- rpt.risk_scores ----------------------------------------------------
    sev_points = (
        F.when(F.col("severity") >= 2, F.lit(10.0))
         .when(F.col("severity") >= 1, F.lit(5.0))
         .otherwise(F.lit(0.0))
    )
    # SAS ROUND(x, 0.5), half away from zero with fuzz
    lob_points = _sas_round(F.lit(2.5) * F.col("loss_ratio"), 0.5)
    # LANSH-DEFECT: '+' carries missing through: a missing lob_points (no loss ratio) or n_recoveries makes points missing
    points = (
        F.lit(12.5) * F.least(F.col("n_claims"), F.lit(4.0))
        + F.lit(7.5) * F.col("n_recoveries")
        + sev_points
        + lob_points
    )
    out = scoring.withColumn("points", points)
    # SAS ROUND(x, 0.01) with fuzz: e.g. 44.27499999999999 rounds to 44.28 as in SAS
    out = out.withColumn(
        "score",
        _sas_round(F.col("points") * F.col("age_load") * F.col("county_load"), 0.01),
    )
    # LANSH-DEFECT: missing score fails both comparisons and is tiered 'LOW'
    tier = (
        F.when(F.col("score") >= 35, F.lit("HIGH"))
         .when(F.col("score") >= 22, F.lit("MEDIUM"))
         .otherwise(F.lit("LOW"))
    )
    # LANSH-DEFECT: tier length fixed at $4 by its first assignment 'HIGH', so 'MEDIUM' is stored as 'MEDI'
    tier = F.substring(tier, 1, 4)
    out = out.withColumn("tier", tier).withColumn("as_of_date", as_of)

    result = out.select(
        F.col("customer_id").cast("double").alias("customer_id"),
        F.col("lob_code"),
        F.col("n_claims").cast("double").alias("n_claims"),
        F.col("paid").cast("double").alias("paid"),
        F.col("n_recoveries").cast("double").alias("n_recoveries"),
        F.col("severity").cast("double").alias("severity"),
        F.col("age").cast("double").alias("age"),
        F.col("age_load").cast("double").alias("age_load"),
        F.col("county_load").cast("double").alias("county_load"),
        F.col("loss_ratio").cast("double").alias("loss_ratio"),
        F.col("points").cast("double").alias("points"),
        F.col("score").cast("double").alias("score"),
        F.col("tier"),
        F.col("as_of_date"),
    )
    return {"rpt.risk_scores": result}
