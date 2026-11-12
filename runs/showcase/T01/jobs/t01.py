"""T01 usp_load_dim_customer: migrated from estate/tsql/T01_usp_load_dim_customer.sql.

Legacy SHA-256: d38c02712a8ae80f9e6e8fff845b41ac7d89026778fc03455b34ded21bba4dc6
Written by: LANSH translator (Claude)
Traps handled: TSQL-01, TSQL-02, TSQL-04, TSQL-05, TSQL-13, TSQL-15
Bugs reproduced on purpose (# LANSH-DEFECT): T01-D1 keeps the oldest CRM version; T01-D2 age_at_join counts year boundaries; T01-D3 Eircode check accepts any 7-character value; T01-D4 county spelling variants fall into UNKNOWN
"""
import datetime

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


# Sales regions as agreed with distribution (CR-0412), legacy lines 134-138.
_EAST = ['Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford']
_SOUTH = ['Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow']
_WEST = ['Galway', 'Mayo', 'Clare', 'Roscommon']
_NORTH_WEST = ['Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan']
_MIDLANDS = ['Westmeath', 'Longford', 'Offaly', 'Laois']


def _ci_key(col):
    """Comparison key for the CI collation, ignoring trailing spaces (TSQL-01, TSQL-02)."""
    return F.upper(F.rtrim(col))


def _ci_in(col, values):
    """T-SQL IN against literals under the CI collation, trailing spaces ignored."""
    return _ci_key(col).isin([v.upper() for v in values])


def run(spark: SparkSession, inputs: dict[str, DataFrame], params: dict[str, str]) -> dict[str, DataFrame]:
    as_of = datetime.date.fromisoformat(params["AsOfDate"])
    as_of_lit = F.lit(as_of)

    customers = inputs["stg.customers"]

    # 1. #customer_versions (TSQL-13): versions saved up to the reporting date,
    #    with the version count per customer.
    customer_versions = (
        customers
        .where(F.to_date(F.col("updated_at")) <= as_of_lit)
        .withColumn(
            "version_count",
            F.count(F.lit(1)).over(Window.partitionBy(F.col("customer_id"))),
        )
    )

    # 2. #customer (TSQL-13): one version per customer.
    w_version = (
        Window.partitionBy(F.col("customer_id"))
        .orderBy(F.col("updated_at").asc(), F.col("_row_seq").asc())  # LANSH-DEFECT: T01-D1 ascending order picks the oldest version, not the current one
    )
    customer = (
        customer_versions
        .withColumn("version_no", F.row_number().over(w_version))
        .where(F.col("version_no") == 1)  # LANSH-DEFECT: T01-D1 version_no = 1 is the first version ever saved
    )

    # 3. dw.dim_customer
    w_email = Window.partitionBy(_ci_key(F.col("email")))  # TSQL-01 / TSQL-02 partition by email under the CI collation

    county = F.col("county")
    region = (
        F.when(_ci_in(county, _EAST), F.lit('EAST'))  # LANSH-DEFECT: T01-D4 only exact county names (case/trailing spaces aside) map to a region
        .when(_ci_in(county, _SOUTH), F.lit('SOUTH'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _WEST), F.lit('WEST'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _NORTH_WEST), F.lit('NORTH-WEST'))  # LANSH-DEFECT: T01-D4 exact county names only
        .when(_ci_in(county, _MIDLANDS), F.lit('MIDLANDS'))  # LANSH-DEFECT: T01-D4 exact county names only
        .otherwise(F.lit('UNKNOWN'))  # LANSH-DEFECT: T01-D4 spelling variants such as 'Co. Dublin' land in UNKNOWN
    )

    eircode = F.col("eircode")
    eircode_len = F.length(F.rtrim(eircode))  # TSQL-15 LEN ignores trailing spaces
    eircode_valid = (
        F.when(eircode_len == 7, F.lit('Y'))  # LANSH-DEFECT: T01-D3 any 7-character value passes, whatever its characters
        .when((eircode_len == 8) & (F.substring(eircode, 4, 1) == F.lit(' ')), F.lit('Y'))  # LANSH-DEFECT: T01-D3 only the 8-character form checks the space position
        .otherwise(F.lit('N'))
    )

    dim_customer = customer.select(
        F.col("customer_id").alias("customer_id"),
        F.rtrim(F.col("first_name")).alias("first_name"),
        F.col("last_name").alias("last_name"),
        # TSQL-05: + concatenation is NULL if any part is NULL
        F.concat(F.rtrim(F.col("first_name")), F.lit(' '), F.rtrim(F.col("last_name"))).alias("full_name"),
        # TSQL-15: SUBSTRING(x, 0, 2) returns 1 character; TSQL-05: NULL part gives NULL
        F.upper(
            F.concat(F.substring(F.col("first_name"), 1, 1), F.substring(F.col("last_name"), 1, 1))
        ).alias("initials"),
        F.col("email").alias("email"),
        F.when(F.col("email").isNull(), F.lit(0))
         .otherwise(F.count(F.lit(1)).over(w_email))
         .alias("email_shared_count"),
        F.col("date_of_birth").alias("date_of_birth"),
        # TSQL-04: DATEDIFF(YEAR, a, b) = year(b) - year(a)
        (F.year(F.col("customer_since")) - F.year(F.col("date_of_birth"))).alias("age_at_join"),  # LANSH-DEFECT: T01-D2 counts year boundaries, not completed years
        F.col("address_line1").alias("address_line1"),
        F.col("town").alias("town"),
        F.col("county").alias("county"),
        region.alias("region"),
        F.col("eircode").alias("eircode"),
        F.rpad(eircode_valid, 1, ' ').alias("eircode_valid"),
        # TSQL-02: CHAR(4) output holds the value padded to 4
        F.rpad(F.col("segment_code"), 4, ' ').alias("segment_code"),
        # TSQL-01 / TSQL-02: = 'STD' ignores case and the CHAR padding
        F.rpad(
            F.when(_ci_key(F.col("segment_code")) == F.lit('STD'), F.lit('Y')).otherwise(F.lit('N')),
            1, ' ',
        ).alias("is_standard_segment"),
        # ISNULL(marketing_opt_in, 'N') into CHAR(1)
        F.rpad(F.coalesce(F.col("marketing_opt_in"), F.lit('N')), 1, ' ').alias("marketing_opt_in"),
        F.col("customer_since").alias("customer_since"),
        F.upper(F.rtrim(F.col("source_system"))).alias("source_system"),
        F.col("version_count").alias("version_count"),
        F.col("updated_at").alias("record_updated_at"),
        as_of_lit.alias("as_of_date"),
    )

    return {"dw.dim_customer": dim_customer}
