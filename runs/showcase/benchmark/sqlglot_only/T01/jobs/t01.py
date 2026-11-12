"""
T01: sqlglot's translation alone, made runnable (a LANSH comparison run, plan §9.5).
"""


import datetime
import decimal


def _bind(sql, args):
    """Put each parameter's value into the SQL text as a literal, longest name first."""
    for name in sorted(args, key=len, reverse=True):
        value = args[name]
        if value is None:
            text = "NULL"
        elif isinstance(value, (int, float, decimal.Decimal)):
            text = str(value)
        elif isinstance(value, datetime.date):
            text = "DATE'" + value.isoformat()[:10] + "'"
        else:
            text = "'" + str(value).replace("'", "''") + "'"
        sql = sql.replace(":" + name, text)
    return sql


def run(spark, inputs, params):
    for name, frame in inputs.items():
        frame.createOrReplaceTempView(name.replace(".", "_"))
    args = dict(params)
    spark.sql(_bind('SELECT c.customer_id AS customer_id, c.first_name AS first_name, c.last_name AS last_name, c.email AS email, c.date_of_birth AS date_of_birth, c.address_line1 AS address_line1, c.town AS town, c.county AS county, c.eircode AS eircode, c.segment_code AS segment_code, c.marketing_opt_in AS marketing_opt_in, c.customer_since AS customer_since, c.source_system AS source_system, c.updated_at AS updated_at, c._row_seq AS _row_seq, COUNT(*) OVER (PARTITION BY c.customer_id) AS version_count FROM stg_customers AS c WHERE CAST(c.updated_at AS DATE) <= :AsOfDate', args)).createOrReplaceTempView('customer_versions')
    spark.sql(_bind('SELECT v.customer_id AS customer_id, v.first_name AS first_name, v.last_name AS last_name, v.email AS email, v.date_of_birth AS date_of_birth, v.address_line1 AS address_line1, v.town AS town, v.county AS county, v.eircode AS eircode, v.segment_code AS segment_code, v.marketing_opt_in AS marketing_opt_in, v.customer_since AS customer_since, v.source_system AS source_system, v.updated_at AS updated_at, v._row_seq AS _row_seq, v.version_count AS version_count, v.version_no AS version_no FROM (SELECT cv.customer_id AS customer_id, cv.first_name AS first_name, cv.last_name AS last_name, cv.email AS email, cv.date_of_birth AS date_of_birth, cv.address_line1 AS address_line1, cv.town AS town, cv.county AS county, cv.eircode AS eircode, cv.segment_code AS segment_code, cv.marketing_opt_in AS marketing_opt_in, cv.customer_since AS customer_since, cv.source_system AS source_system, cv.updated_at AS updated_at, cv._row_seq AS _row_seq, cv.version_count AS version_count, ROW_NUMBER() OVER (PARTITION BY cv.customer_id ORDER BY cv.updated_at, cv._row_seq) AS version_no FROM customer_versions AS cv) AS v WHERE v.version_no = 1', args)).createOrReplaceTempView('customer')
    return {'dw.dim_customer': spark.sql(_bind("SELECT k.customer_id AS customer_id, RTRIM(k.first_name) AS first_name, k.last_name AS last_name, RTRIM(k.first_name) + ' ' + RTRIM(k.last_name) AS full_name, UPPER(CONCAT(SUBSTRING(k.first_name, 0, 2), SUBSTRING(k.last_name, 0, 2))) AS initials, k.email AS email, CASE WHEN k.email IS NULL THEN 0 ELSE COUNT(*) OVER (PARTITION BY k.email) END AS email_shared_count, k.date_of_birth AS date_of_birth, DATEDIFF(YEAR, CAST(k.date_of_birth AS TIMESTAMP), CAST(k.customer_since AS TIMESTAMP)) AS age_at_join, k.address_line1 AS address_line1, k.town AS town, k.county AS county, CASE WHEN k.county IN ('Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford') THEN 'EAST' WHEN k.county IN ('Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow') THEN 'SOUTH' WHEN k.county IN ('Galway', 'Mayo', 'Clare', 'Roscommon') THEN 'WEST' WHEN k.county IN ('Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan') THEN 'NORTH-WEST' WHEN k.county IN ('Westmeath', 'Longford', 'Offaly', 'Laois') THEN 'MIDLANDS' ELSE 'UNKNOWN' END AS region, k.eircode AS eircode, CASE WHEN LENGTH((k.eircode)) = 7 THEN 'Y' WHEN LENGTH((k.eircode)) = 8 AND SUBSTRING(k.eircode, 4, 1) = ' ' THEN 'Y' ELSE 'N' END AS eircode_valid, k.segment_code AS segment_code, CASE WHEN k.segment_code = 'STD' THEN 'Y' ELSE 'N' END AS is_standard_segment, COALESCE(k.marketing_opt_in, 'N') AS marketing_opt_in, k.customer_since AS customer_since, UPPER(RTRIM(k.source_system)) AS source_system, k.version_count AS version_count, k.updated_at AS record_updated_at, :AsOfDate AS as_of_date FROM customer AS k", args))}
