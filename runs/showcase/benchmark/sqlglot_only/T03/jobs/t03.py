"""
T03: sqlglot's translation alone, made runnable (a LANSH comparison run, plan §9.5).
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
    spark.sql(_bind("SELECT t.txn_id AS txn_id, t.policy_id AS policy_id, UPPER(RTRIM(t.txn_type)) AS txn_type, t.txn_date AS txn_date, t.effective_from AS effective_from, t.effective_to AS effective_to, t.currency AS currency, t.amount AS amount, CAST(1 AS DECIMAL(18, 8)) AS fx_rate FROM stg_premium_transactions AS t WHERE t.currency = 'EUR' AND t.txn_date <= :AsOfDate", args)).createOrReplaceTempView('txn')
    spark.sql(_bind("SELECT t.txn_id AS txn_id, t.policy_id AS policy_id, UPPER(RTRIM(t.txn_type)) AS txn_type, t.txn_date AS txn_date, t.effective_from AS effective_from, t.effective_to AS effective_to, t.currency AS currency, t.amount AS amount, fx.rate_to_eur AS fx_rate FROM stg_premium_transactions AS t INNER JOIN LATERAL (SELECT r.rate_to_eur AS rate_to_eur FROM stg_fx_rates AS r WHERE r.currency = t.currency AND r.rate_date <= t.txn_date ORDER BY r.rate_date DESC, r._row_seq DESC LIMIT 1) AS fx WHERE t.currency <> 'EUR' AND t.txn_date <= :AsOfDate", args)).createOrReplaceTempView('txn')
    args['rows'] = spark.sql(_bind('SELECT COUNT(*) AS v FROM txn AS txn', args)).first()[0]
    spark.sql(_bind('SELECT x.txn_id AS txn_id, x.policy_id AS policy_id, x.txn_type AS txn_type, x.txn_date AS txn_date, x.effective_from AS effective_from, x.effective_to AS effective_to, x.currency AS currency, x.amount AS amount, x.fx_rate AS fx_rate, CAST(ROUND(x.amount * x.fx_rate, 2) AS DECIMAL(14, 2)) AS written_eur, DATEDIFF(DAY, CAST(x.effective_from AS TIMESTAMP), CAST(x.effective_to AS TIMESTAMP)) + 1 AS term_days, CASE WHEN :AsOfDate < x.effective_from THEN 0 WHEN :AsOfDate >= x.effective_to THEN DATEDIFF(DAY, CAST(x.effective_from AS TIMESTAMP), CAST(x.effective_to AS TIMESTAMP)) + 1 ELSE DATEDIFF(DAY, CAST(x.effective_from AS TIMESTAMP), CAST(:AsOfDate AS TIMESTAMP)) + 1 END AS earned_days FROM txn AS x', args)).createOrReplaceTempView('earn')
    return {'dw.fact_premium_earned': spark.sql(_bind("SELECT e.txn_id AS txn_id, e.policy_id AS policy_id, p.policy_sk AS policy_sk, p.lob_code AS lob_code, e.txn_type AS txn_type, e.txn_date AS txn_date, e.effective_from AS effective_from, e.effective_to AS effective_to, e.currency AS currency, e.amount AS amount, e.fx_rate AS fx_rate, e.written_eur AS written_eur, e.term_days AS term_days, e.earned_days AS earned_days, CAST(e.earned_days * 100 / e.term_days AS BIGINT) AS earned_pct, ROUND(e.written_eur * e.earned_days / 365, 2) AS earned_eur, e.written_eur - ROUND(e.written_eur * e.earned_days / 365, 2) AS unearned_eur, ROUND(e.written_eur / e.term_days, 4, 1) AS daily_rate_eur, ROUND(e.written_eur / COALESCE(NULLIF(CAST(e.term_days / 30 AS BIGINT), 0), 1), 2) AS monthly_instalment_eur, ADD_MONTHS(LAST_DAY((e.effective_from)), 1) AS first_due_date, :AsOfDate AS as_of_date FROM earn AS e JOIN dw_dim_policy AS p ON p.policy_id = e.policy_id AND p.is_current = 'Y'", args))}
