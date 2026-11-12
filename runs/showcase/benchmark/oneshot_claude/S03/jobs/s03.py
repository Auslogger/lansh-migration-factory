"""S03 premium_bands.sas -> PySpark.

Written and earned premium by line of business and premium band.
Each policy is banded once, on the written premium of its first transaction
as loaded (PROC SORT NODUPKEY, which keeps the first row in load order), and
all of its transactions are reported in that band and under that LOB.

Output: rpt.premium_band_summary
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F


def _sas_char(col):
    # SAS character semantics: trailing blanks are not significant and an
    # all-blank value is missing.
    trimmed = F.rtrim(col)
    return F.when(trimmed == F.lit(""), F.lit(None).cast("string")).otherwise(trimmed)


def _premband(col):
    # PROC FORMAT value premband; LOW does not include missing for numeric
    # formats, so missing falls to OTHER.
    return (
        F.when(col.isNull(), F.lit("UNKNOWN"))
        .when(col < 0, F.lit("NEGATIVE"))
        .when(col < 250, F.lit("0-249"))
        .when(col < 500, F.lit("250-499"))
        .when(col < 1000, F.lit("500-999"))
        .otherwise(F.lit("1000+"))
    )


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    src = inputs["dw.fact_premium_earned"]
    as_of = datetime.date.fromisoformat(params["AsOfDate"])

    # proc sort nodupkey by policy_id: first row per policy in load order
    # (EQUALS is the default). Missing policy_id values form one BY group.
    w = Window.partitionBy("policy_id").orderBy(F.col("_row_seq").asc())
    opening = (
        src.select("policy_id", "lob_code", "written_eur", "_row_seq")
        .withColumn("_rn", F.row_number().over(w))
        .filter(F.col("_rn") == 1)
    )

    policy_band = opening.select(
        F.col("policy_id").alias("pb_policy_id"),
        _sas_char(F.col("lob_code")).alias("lob_code"),
        _premband(F.col("written_eur")).alias("prem_band"),
    )

    # every transaction, in its policy's band (merge by policy_id; if t)
    txn = src.select(
        F.col("policy_id").alias("t_policy_id"),
        F.col("written_eur"),
        F.col("earned_eur"),
    )
    txn_band = txn.join(
        policy_band,
        txn["t_policy_id"].eqNullSafe(policy_band["pb_policy_id"]),
        "left",
    )

    # proc means nway, class lob_code prem_band (no MISSING option)
    premium_sums = (
        txn_band
        .filter(F.col("lob_code").isNotNull())  # LANSH-DEFECT: CLASS without MISSING drops transactions whose policy LOB is blank
        .groupBy("lob_code", "prem_band")
        .agg(
            F.count(F.col("written_eur")).cast("double").alias("n_transactions"),  # LANSH-DEFECT: n_transactions counts non-missing written_eur, not transactions
            F.sum(F.col("written_eur")).cast("double").alias("written_eur"),
            F.sum(F.col("earned_eur")).cast("double").alias("earned_eur"),
        )
    )

    policy_counts = (
        policy_band
        .filter(F.col("lob_code").isNotNull())  # LANSH-DEFECT: CLASS without MISSING drops policies whose LOB is blank
        .groupBy("lob_code", "prem_band")
        .agg(F.count(F.col("pb_policy_id")).cast("double").alias("n_policies"))
    )

    # merge by lob_code prem_band
    summary = policy_counts.join(premium_sums, on=["lob_code", "prem_band"], how="full")

    result = summary.select(
        F.col("lob_code"),
        F.col("prem_band"),
        F.col("n_policies"),
        F.col("n_transactions"),
        F.col("written_eur"),
        F.col("earned_eur"),
        F.lit(as_of).cast("date").alias("as_of_date"),
    ).orderBy("lob_code", "prem_band")

    return {"rpt.premium_band_summary": result}
