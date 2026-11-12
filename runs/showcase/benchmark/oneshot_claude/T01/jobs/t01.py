"""Job T01: dw.usp_load_dim_customer (legacy T-SQL, SQL Server 2022) migrated to PySpark.

Customer dimension, one row per CRM customer. Output dw.dim_customer is fully
reloaded on every run. Reproduces the legacy behaviour exactly, including
suspected bugs (marked LANSH-DEFECT).
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def _ci(col):
    # SQL Server default collation: case-insensitive, trailing spaces ignored in comparisons
    return F.lower(F.rtrim(col))


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    c = inputs["stg.customers"]

    # 1. Versions saved up to the reporting date
    v = c.where(F.to_date(F.col("updated_at")) <= F.lit(as_of))
    v = v.withColumn(
        "version_count",
        F.count(F.lit(1)).over(Window.partitionBy("customer_id")),
    )

    # 2. "Keep the current version" -- legacy orders ascending, so it keeps the OLDEST version
    w = Window.partitionBy("customer_id").orderBy(F.col("updated_at").asc(), F.col("_row_seq").asc())  # LANSH-DEFECT: ascending order keeps the oldest version, not the current one
    k = v.withColumn("version_no", F.row_number().over(w)).where(F.col("version_no") == 1)

    # 3. Dimension columns
    email = F.col("email")
    email_count = F.count(F.lit(1)).over(Window.partitionBy(_ci(email)))

    county = _ci(F.col("county"))
    east = [s.lower() for s in ['Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford']]
    south = [s.lower() for s in ['Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow']]
    west = [s.lower() for s in ['Galway', 'Mayo', 'Clare', 'Roscommon']]
    north_west = [s.lower() for s in ['Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan']]
    midlands = [s.lower() for s in ['Westmeath', 'Longford', 'Offaly', 'Laois']]
    region = (
        F.when(county.isin(east), F.lit('EAST'))
        .when(county.isin(south), F.lit('SOUTH'))
        .when(county.isin(west), F.lit('WEST'))
        .when(county.isin(north_west), F.lit('NORTH-WEST'))
        .when(county.isin(midlands), F.lit('MIDLANDS'))
        .otherwise(F.lit('UNKNOWN'))
    )

    eir = F.col("eircode")
    eir_len = F.length(F.rtrim(eir))  # T-SQL LEN ignores trailing spaces
    eircode_valid = (
        F.when(eir_len == 7, F.lit('Y'))
        .when((eir_len == 8) & (F.substring(eir, 4, 1) == F.lit(' ')), F.lit('Y'))
        .otherwise(F.lit('N'))
    )

    # T-SQL SUBSTRING(x, 0, 2) returns only the first character
    initials = F.upper(F.concat(F.substring(F.col("first_name"), 1, 1), F.substring(F.col("last_name"), 1, 1)))

    out = k.select(
        F.col("customer_id").alias("customer_id"),
        F.rtrim(F.col("first_name")).alias("first_name"),
        F.col("last_name").alias("last_name"),
        F.concat(F.rtrim(F.col("first_name")), F.lit(' '), F.rtrim(F.col("last_name"))).alias("full_name"),
        initials.alias("initials"),
        email.alias("email"),
        F.when(email.isNull(), F.lit(0)).otherwise(email_count).cast("int").alias("email_shared_count"),
        F.col("date_of_birth").alias("date_of_birth"),
        (F.year(F.col("customer_since")) - F.year(F.col("date_of_birth"))).cast("int").alias("age_at_join"),  # LANSH-DEFECT: DATEDIFF(YEAR) counts year boundaries, not completed years of age
        F.col("address_line1").alias("address_line1"),
        F.col("town").alias("town"),
        F.col("county").alias("county"),
        region.alias("region"),
        eir.alias("eircode"),
        eircode_valid.alias("eircode_valid"),
        F.col("segment_code").alias("segment_code"),
        F.when(_ci(F.col("segment_code")) == F.lit('STD'.lower()), F.lit('Y')).otherwise(F.lit('N')).alias("is_standard_segment"),
        F.coalesce(F.col("marketing_opt_in"), F.lit('N')).alias("marketing_opt_in"),
        F.col("customer_since").alias("customer_since"),
        F.upper(F.rtrim(F.col("source_system"))).alias("source_system"),
        F.col("version_count").cast("int").alias("version_count"),
        F.col("updated_at").alias("record_updated_at"),
        F.lit(as_of).alias("as_of_date"),
    )

    return {"dw.dim_customer": out}
