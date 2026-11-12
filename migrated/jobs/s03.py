"""S03 premium_bands: migrated from estate/sas/S03_premium_bands.sas.

Legacy SHA-256: c40650f2177f8a2808693aa0e79675464a0df999a505a2fcad32c4f9c4bf0132
Written by: LANSH translator (Claude)
Traps handled: SAS-03, SAS-05, SAS-09, SAS-12, SAS-14
Bugs reproduced on purpose (# LANSH-DEFECT): S03-D1 missing lob_code policies dropped by PROC MEANS CLASS; S03-D2 no as-of cut-off on transactions; S03-D3 policy band taken from first-loaded row
"""

import re

from pyspark.sql import DataFrame, SparkSession, Window
import pyspark.sql.functions as F
import pyspark.sql.types as T


def _sas_char(col_name: str):
    """SAS character semantics: trailing blanks never count, a blank value is missing."""
    trimmed = F.rtrim(F.col(col_name))
    return F.when(trimmed == "", F.lit(None).cast(T.StringType())).otherwise(trimmed)


def _as_of_date(value: str):
    """SAS-03: &as_of is a SAS date (days since 1960-01-01); the harness passes ISO text."""
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return F.date_add(F.to_date(F.lit("1960-01-01")), int(text))
    return F.to_date(F.lit(text), "yyyy-MM-dd")


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    # LANSH-DEFECT: S03-D2 no filter on txn_date <= as_of; every transaction, including those after the reporting date, is read
    src = inputs["dw.fact_premium_earned"]

    base = src.select(
        F.col("policy_id").cast(T.DoubleType()).alias("policy_id"),
        _sas_char("lob_code").alias("lob_code"),
        F.col("written_eur").cast(T.DoubleType()).alias("written_eur"),
        F.col("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        F.col("_row_seq"),
    )

    # SAS-09: PROC SORT NODUPKEY BY policy_id keeps the first row of each policy in load order.
    w_first = Window.partitionBy("policy_id").orderBy(F.col("_row_seq").asc())
    opening = (
        base.withColumn("_rn", F.row_number().over(w_first))  # LANSH-DEFECT: S03-D3 band and lob_code come from the first-loaded row, not the earliest transaction
        .where(F.col("_rn") == 1)
        .select("policy_id", "lob_code", "written_eur")
    )

    # SAS-12: PROC FORMAT premband, lower bound included, upper excluded; missing goes to OTHER.
    we = F.col("written_eur")
    prem_band = (
        F.when(we < 0, F.lit("NEGATIVE"))
        .when(we < 250, F.lit("0-249"))
        .when(we < 500, F.lit("250-499"))
        .when(we < 1000, F.lit("500-999"))
        .when(we >= 1000, F.lit("1000+"))
        .otherwise(F.lit("UNKNOWN"))
    )
    policy_band = opening.select("policy_id", "lob_code", prem_band.alias("prem_band"))

    # Every transaction (PROC SORT without NODUPKEY keeps all rows).
    txn = base.select("policy_id", "written_eur", "earned_eur")

    # SAS-05: one-to-many MERGE with "if t" acts as a left join from txn; missing BY keys match each other.
    t = txn.alias("t")
    p = policy_band.alias("p")
    txn_band = t.join(p, F.col("t.policy_id").eqNullSafe(F.col("p.policy_id")), "left").select(
        F.col("t.policy_id").alias("policy_id"),
        F.col("t.written_eur").alias("written_eur"),
        F.col("t.earned_eur").alias("earned_eur"),
        F.col("p.lob_code").alias("lob_code"),
        F.col("p.prem_band").alias("prem_band"),
    )

    # SAS-14: PROC MEANS NWAY CLASS lob_code prem_band (no MISSING option) leaves out missing class values.
    premium_sums = (
        txn_band.where(F.col("lob_code").isNotNull() & F.col("prem_band").isNotNull())  # LANSH-DEFECT: S03-D1 transactions of policies with missing lob_code dropped
        .groupBy("lob_code", "prem_band")
        .agg(
            F.count("written_eur").cast(T.DoubleType()).alias("n_transactions"),
            F.sum("written_eur").cast(T.DoubleType()).alias("written_eur"),
            F.sum("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        )
    )

    # SAS-14: second PROC MEANS NWAY, N(policy_id) per class combination, missing class values left out.
    policy_counts = (
        policy_band.where(F.col("lob_code").isNotNull() & F.col("prem_band").isNotNull())  # LANSH-DEFECT: S03-D1 policies with missing lob_code dropped
        .groupBy("lob_code", "prem_band")
        .agg(F.count("policy_id").cast(T.DoubleType()).alias("n_policies"))
    )

    # SAS-05: MERGE without IN= is a full outer join on the BY keys.
    merged = policy_counts.join(premium_sums, ["lob_code", "prem_band"], "full")

    # SAS-03: as_of_date stamped from the parameter.
    result = merged.select(
        F.col("lob_code").cast(T.StringType()).alias("lob_code"),
        F.col("prem_band").cast(T.StringType()).alias("prem_band"),
        F.col("n_policies").cast(T.DoubleType()).alias("n_policies"),
        F.col("n_transactions").cast(T.DoubleType()).alias("n_transactions"),
        F.col("written_eur").cast(T.DoubleType()).alias("written_eur"),
        F.col("earned_eur").cast(T.DoubleType()).alias("earned_eur"),
        _as_of_date(params["AsOfDate"]).alias("as_of_date"),
    ).orderBy(F.col("lob_code").asc(), F.col("prem_band").asc())

    return {"rpt.premium_band_summary": result}
