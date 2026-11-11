/* Answer-key checks for T03 dw.usp_build_fact_premium_earned (evaluation only).
   Run after the job: uv run lansh estate checks --job T03 */
-- check: T03_BUG02_earned_divides_by_365
-- proves: earned_eur divides by a hard-coded 365; dividing by the days in the cover period gives a different earned premium
SELECT 'T03_BUG02_earned_divides_by_365' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM dw.fact_premium_earned),
                   ' rows differ from earned over the cover period; ',
                   SUM(CASE WHEN f.term_days = 366 THEN 1 ELSE 0 END), ' are 366-day covers; net EUR ',
                   CAST(SUM(f.earned_eur - ROUND(f.written_eur * f.earned_days / f.term_days, 2)) AS DECIMAL(14,2)))
            AS NVARCHAR(200)) AS detail
FROM   dw.fact_premium_earned f
WHERE  f.earned_eur <> ROUND(f.written_eur * f.earned_days / f.term_days, 2);
GO
-- check: T03_TSQL03_integer_division
-- proves: INT / INT truncates before the value is stored: earned_pct keeps 27.00 where decimal division
--         stores 27.40, and the instalment count drops its fraction (and is 1 for covers under 30 days)
SELECT 'T03_TSQL03_integer_division' AS check_id,
       SUM(CASE WHEN f.earned_pct <> CAST(f.earned_days * 100.0 / f.term_days AS DECIMAL(5,2))
                  OR f.monthly_instalment_eur <> ROUND(f.written_eur / (f.term_days / 30.0), 2)
                THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('earned_pct truncated on ',
                   SUM(CASE WHEN f.earned_pct <> CAST(f.earned_days * 100.0 / f.term_days AS DECIMAL(5,2))
                            THEN 1 ELSE 0 END),
                   ' rows; monthly_instalment_eur differs on ',
                   SUM(CASE WHEN f.monthly_instalment_eur <> ROUND(f.written_eur / (f.term_days / 30.0), 2)
                            THEN 1 ELSE 0 END), ' rows')
            AS NVARCHAR(200)) AS detail
FROM   dw.fact_premium_earned f;
GO
-- check: T03_TSQL07_round_truncates
-- proves: ROUND(x, 4, 1) truncates the computed daily rate; rounding half up gives a different value
SELECT 'T03_TSQL07_round_truncates' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM dw.fact_premium_earned),
                   ' daily rates differ from ROUND(written_eur / term_days, 4)')
            AS NVARCHAR(200)) AS detail
FROM   dw.fact_premium_earned f
WHERE  f.daily_rate_eur <> ROUND(f.written_eur / f.term_days, 4);
GO
-- check: T03_TSQL18_month_end_dateadd
-- proves: DATEADD(MONTH, 1, EOMONTH(d)) is not the next month-end after a 30-day month or February
SELECT 'T03_TSQL18_month_end_dateadd' AS check_id,
       (SELECT COUNT(*) FROM dw.fact_premium_earned f
        WHERE  f.first_due_date <> EOMONTH(f.effective_from, 1)) AS affected,
       CAST(CONCAT((SELECT COUNT(*) FROM dw.fact_premium_earned f
                    WHERE  f.first_due_date <> EOMONTH(f.effective_from, 1)),
                   ' first_due_date values are not EOMONTH(effective_from, 1), e.g. cover from ',
                   CONVERT(CHAR(10), x.effective_from, 23), ' falls due ',
                   CONVERT(CHAR(10), x.first_due_date, 23), ', not ',
                   CONVERT(CHAR(10), EOMONTH(x.effective_from, 1), 23))
            AS NVARCHAR(200)) AS detail
FROM   (SELECT TOP 1 f.effective_from, f.first_due_date
        FROM   dw.fact_premium_earned f
        WHERE  f.first_due_date <> EOMONTH(f.effective_from, 1)
        ORDER  BY f.txn_id) x;
GO
-- check: T03_TSQL09_cross_apply_drops_unrated
-- proves: CROSS APPLY drops foreign-currency transactions that have no rate on or before their booking date
SELECT 'T03_TSQL09_cross_apply_drops_unrated' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' foreign-currency transactions have no earlier rate and no fact row (',
                   SUM(CASE WHEN t.currency = 'GBP' THEN 1 ELSE 0 END), ' GBP, ',
                   SUM(CASE WHEN t.currency = 'USD' THEN 1 ELSE 0 END), ' USD), booked ',
                   MIN(CONVERT(CHAR(10), t.txn_date, 23)), ' to ', MAX(CONVERT(CHAR(10), t.txn_date, 23)))
            AS NVARCHAR(200)) AS detail
FROM   stg.premium_transactions t
WHERE  t.currency <> 'EUR'
  AND  NOT EXISTS (SELECT 1 FROM stg.fx_rates r
                   WHERE  r.currency = t.currency AND r.rate_date <= t.txn_date)
  AND  NOT EXISTS (SELECT 1 FROM dw.fact_premium_earned f WHERE f.txn_id = t.txn_id);
GO
