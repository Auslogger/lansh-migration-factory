"""
T04: sqlglot's translation alone, made runnable (a LANSH comparison run, plan §9.5).
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
    spark.sql(_bind("SELECT c.claim_id AS claim_id, c.claim_number AS claim_number, c.policy_id AS policy_id, UPPER(RTRIM(c.lob_code)) AS lob_code, c.status AS status, c.handler_code AS handler_code, c.loss_date AS loss_date, c.reported_date AS reported_date FROM stg_claims AS c WHERE c.status IN ('OPEN', 'REOPENED') AND c.reported_date <= :AsOfDate", args)).createOrReplaceTempView('open_claims')
    spark.sql(_bind('SELECT x.claim_id AS claim_id, x.reserve_type AS reserve_type, x.reserve_amount AS reserve_amount FROM (SELECT r.claim_id AS claim_id, r.reserve_type AS reserve_type, r.reserve_amount AS reserve_amount, ROW_NUMBER() OVER (PARTITION BY r.claim_id, r.reserve_type ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn FROM stg_claim_reserves AS r JOIN open_claims AS oc ON oc.claim_id = r.claim_id WHERE r.reserve_date <= :AsOfDate) AS x WHERE x.rn = 1', args)).createOrReplaceTempView('reserve')
    spark.sql(_bind("SELECT oc.claim_id AS claim_id, COUNT(DISTINCT p.payment_id) AS n_payments, COALESCE(SUM(p.amount), 0) AS total_paid, COALESCE(MAX(CASE WHEN r.reserve_type = 'INDEMNITY' THEN r.reserve_amount END), 0) AS indemnity_reserve, COALESCE(MAX(CASE WHEN r.reserve_type = 'EXPENSE' THEN r.reserve_amount END), 0) AS expense_reserve FROM open_claims AS oc LEFT JOIN stg_claim_payments AS p ON p.claim_id = oc.claim_id AND p.payment_date <= :AsOfDate LEFT JOIN reserve AS r ON r.claim_id = oc.claim_id GROUP BY oc.claim_id", args)).createOrReplaceTempView('money')
    args['snapshot_date'] = spark.sql(_bind('SELECT MAX(ps.snapshot_date) AS v FROM stg_policy_snapshots AS ps WHERE ps.snapshot_date <= :AsOfDate', args)).first()[0]
    return {'rpt.claims_summary': spark.sql(_bind("SELECT oc.claim_id AS claim_id, oc.claim_number AS claim_number, CONCAT(CONCAT(CONCAT(CONCAT(oc.lob_code, '/'), oc.claim_number), '/'), oc.handler_code) AS claim_ref, oc.policy_id AS policy_id, ps.policy_number AS policy_number, oc.lob_code AS lob_code, oc.status AS status, oc.handler_code AS handler_code, oc.loss_date AS loss_date, CAST(DATE_FORMAT(oc.loss_date, 'dd/MM/yyyy') AS VARCHAR(10)) AS loss_date_text, oc.reported_date AS reported_date, CAST(DATE_FORMAT(oc.reported_date, 'yyyyMMdd') AS CHAR(6)) AS reported_period, DATEDIFF(DAY, CAST(oc.reported_date AS TIMESTAMP), CAST(:AsOfDate AS TIMESTAMP)) AS days_open, m.n_payments AS n_payments, m.total_paid AS total_paid, m.indemnity_reserve AS indemnity_reserve, m.expense_reserve AS expense_reserve, m.indemnity_reserve + m.expense_reserve AS current_reserve, m.total_paid + m.indemnity_reserve + m.expense_reserve AS incurred, :AsOfDate AS as_of_date FROM open_claims AS oc JOIN money AS m ON m.claim_id = oc.claim_id LEFT JOIN stg_policy_snapshots AS ps ON ps.policy_id = oc.policy_id AND ps.snapshot_date = :snapshot_date", args))}
