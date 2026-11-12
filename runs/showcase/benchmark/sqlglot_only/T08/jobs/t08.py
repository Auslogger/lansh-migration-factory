"""
T08: sqlglot's translation alone, made runnable (a LANSH comparison run, plan §9.5).
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
    args['snapshot_date'] = spark.sql(_bind('SELECT MAX(ps.snapshot_date) AS v FROM stg_policy_snapshots AS ps WHERE ps.snapshot_date <= :AsOfDate', args)).first()[0]
    spark.sql(_bind('SELECT c.claim_id AS claim_id, c.claim_number AS claim_number, c.policy_id AS policy_id, c.customer_id AS customer_id, c.lob_code AS lob_code, c.loss_date AS loss_date, c.reported_date AS reported_date, p.policy_number AS policy_number, p.inception_date AS inception_date, p.expiry_date AS expiry_date, p.vehicle_reg AS vehicle_reg, dc.customer_since AS customer_since FROM stg_claims AS c LEFT JOIN stg_policy_snapshots AS p ON p.policy_id = c.policy_id AND p.snapshot_date = :snapshot_date LEFT JOIN dw_dim_customer AS dc ON dc.customer_id = c.customer_id WHERE c.reported_date > ADD_MONTHS(:AsOfDate, -12) AND c.reported_date <= :AsOfDate', args)).createOrReplaceTempView('claims')
    spark.sql(_bind("SELECT f.claim_id AS claim_id, f.early_notification_flag AS early_notification_flag, f.invalid_reg_flag AS invalid_reg_flag, f.new_customer_flag AS new_customer_flag, f.lob_mismatch_flag AS lob_mismatch_flag, f.early_notification_flag + f.invalid_reg_flag + f.new_customer_flag + f.lob_mismatch_flag AS fraud_score FROM (SELECT cl.claim_id AS claim_id, CASE WHEN DATEDIFF(DAY, CAST(cl.expiry_date AS TIMESTAMP), CAST(cl.reported_date AS TIMESTAMP)) BETWEEN 0 AND 30 THEN 1 ELSE 0 END AS early_notification_flag, CASE WHEN cl.lob_code = 'MOT' AND cl.vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%' THEN 1 ELSE 0 END AS invalid_reg_flag, CASE WHEN DATEDIFF(DAY, CAST(cl.customer_since AS TIMESTAMP), CAST(cl.loss_date AS TIMESTAMP)) < 180 THEN 1 ELSE 0 END AS new_customer_flag, CASE WHEN SUBSTRING(cl.policy_number, 0, 4) <> cl.lob_code THEN 1 ELSE 0 END AS lob_mismatch_flag FROM claims AS cl) AS f", args)).createOrReplaceTempView('flags')
    return {'rpt.claim_fraud_flags': spark.sql(_bind("SELECT cl.claim_id AS claim_id, cl.claim_number AS claim_number, cl.policy_id AS policy_id, cl.policy_number AS policy_number, cl.customer_id AS customer_id, UPPER(RTRIM(cl.lob_code)) AS lob_code, cl.loss_date AS loss_date, cl.reported_date AS reported_date, f.early_notification_flag AS early_notification_flag, f.invalid_reg_flag AS invalid_reg_flag, f.new_customer_flag AS new_customer_flag, f.lob_mismatch_flag AS lob_mismatch_flag, f.fraud_score AS fraud_score, CASE WHEN f.fraud_score >= 2 THEN 'HIGH' WHEN f.fraud_score = 1 THEN 'MEDIUM' ELSE 'LOW' END AS fraud_band, CAST(DATE_FORMAT(cl.loss_date, 'yyyyMMdd') AS CHAR(8)) AS loss_day_key, 'Notified ' + CAST(DATE_FORMAT(cl.reported_date, 'dd/MM/yyyy') AS VARCHAR(10)) + CASE WHEN f.fraud_score = 0 THEN ' - no indicators' ELSE ' -' END + CASE WHEN f.early_notification_flag = 1 THEN ' EARLY' ELSE '' END + CASE WHEN f.invalid_reg_flag = 1 THEN ' REG' ELSE '' END + CASE WHEN f.new_customer_flag = 1 THEN ' NEWCUST' ELSE '' END + CASE WHEN f.lob_mismatch_flag = 1 THEN ' LOB' ELSE '' END AS reason_text, :AsOfDate AS as_of_date FROM claims AS cl JOIN flags AS f ON f.claim_id = cl.claim_id", args))}
