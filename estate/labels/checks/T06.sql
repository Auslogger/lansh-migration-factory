/* T06 rpt.usp_loss_triangle: answer-key checks (evaluation only). Run after the job.
   The as-of date comes from the output table, so the checks follow the job's own run. */
-- check: T06_BUG05_loss_date_payments_dropped
-- proves: dev_0 and the paid to date (latest cumulative_n) are short by exactly the payments made on the loss date, because the job keeps payment_date > loss_date; the intended >= would include them
DECLARE @AsOfDate DATE = (SELECT MAX(as_of_date) FROM rpt.loss_triangle_paid);

WITH pay AS (   -- payments as intended: from the loss date itself
    SELECT YEAR(c.loss_date)        AS accident_year,
           UPPER(RTRIM(c.lob_code)) AS lob_code,
           DATEDIFF(YEAR, c.loss_date, p.payment_date) AS dev_year,
           p.amount,
           CASE WHEN p.payment_date = c.loss_date THEN 1 ELSE 0 END AS on_loss_date
    FROM   stg.claims AS c
    JOIN   stg.claim_payments AS p ON p.claim_id = c.claim_id
    WHERE  p.payment_date >= c.loss_date
      AND  p.payment_date <= @AsOfDate
      AND  p.amount IS NOT NULL
      AND  YEAR(c.loss_date) BETWEEN YEAR(@AsOfDate) - 6 AND YEAR(@AsOfDate)
),
cell AS (
    SELECT accident_year, lob_code,
           SUM(CASE WHEN dev_year = 0 THEN amount ELSE 0 END)     AS intended_dev_0,
           SUM(amount)                                            AS intended_to_date,
           SUM(CASE WHEN on_loss_date = 1 THEN amount ELSE 0 END) AS day0_paid,
           SUM(on_loss_date)                                      AS day0_payments
    FROM   pay
    GROUP BY accident_year, lob_code
),
hit AS (        -- output rows that miss exactly their loss-date payments
    SELECT i.day0_payments, i.day0_paid
    FROM   rpt.loss_triangle_paid AS t
    JOIN   cell AS i ON i.accident_year = t.accident_year AND i.lob_code = t.lob_code
    WHERE  i.day0_paid <> 0
      AND  t.dev_0 = i.intended_dev_0 - i.day0_paid
      AND  COALESCE(t.cumulative_6, t.cumulative_5, t.cumulative_4, t.cumulative_3,
                    t.cumulative_2, t.cumulative_1, t.cumulative_0)
             = i.intended_to_date - i.day0_paid
)
SELECT 'T06_BUG05_loss_date_payments_dropped' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM rpt.loss_triangle_paid),
                   ' rows short in dev_0 and paid to date: ', ISNULL(SUM(day0_payments), 0),
                   ' payments made on the loss date left out, EUR ', ISNULL(SUM(day0_paid), 0))
            AS NVARCHAR(200)) AS detail
FROM   hit;
GO
-- check: T06_TSQL04_dev_year_counts_calendar_years
-- proves: the output follows DATEDIFF(YEAR) (calendar-year boundaries); counting whole years since the loss instead moves payments made within a year of the loss but in the next calendar year back one development year, and the triangle differs
DECLARE @AsOfDate DATE = (SELECT MAX(as_of_date) FROM rpt.loss_triangle_paid);

WITH pay AS (   -- the job's own payment filter, so only the year count differs
    SELECT YEAR(c.loss_date)        AS accident_year,
           UPPER(RTRIM(c.lob_code)) AS lob_code,
           DATEDIFF(YEAR, c.loss_date, p.payment_date) AS dev_boundaries,
           DATEDIFF(YEAR, c.loss_date, p.payment_date)
             - CASE WHEN DATEADD(YEAR, DATEDIFF(YEAR, c.loss_date, p.payment_date), c.loss_date)
                         > p.payment_date THEN 1 ELSE 0 END AS dev_whole_years,
           p.amount
    FROM   stg.claims AS c
    JOIN   stg.claim_payments AS p ON p.claim_id = c.claim_id
    WHERE  p.payment_date > c.loss_date
      AND  p.payment_date <= @AsOfDate
      AND  p.amount IS NOT NULL
      AND  YEAR(c.loss_date) BETWEEN YEAR(@AsOfDate) - 6 AND YEAR(@AsOfDate)
),
cal AS (
    SELECT accident_year, lob_code, dev_boundaries AS dev_year, SUM(amount) AS paid
    FROM   pay GROUP BY accident_year, lob_code, dev_boundaries
),
whole AS (
    SELECT accident_year, lob_code, dev_whole_years AS dev_year, SUM(amount) AS paid
    FROM   pay GROUP BY accident_year, lob_code, dev_whole_years
),
cells AS (      -- every output cell up to the as-at date, against both counts
    SELECT t.accident_year, t.lob_code, v.dev_year, v.paid,
           ISNULL(c.paid, 0) AS paid_calendar,
           ISNULL(w.paid, 0) AS paid_whole
    FROM   rpt.loss_triangle_paid AS t
    CROSS APPLY (VALUES (0, t.dev_0), (1, t.dev_1), (2, t.dev_2), (3, t.dev_3),
                        (4, t.dev_4), (5, t.dev_5), (6, t.dev_6)) AS v (dev_year, paid)
    LEFT JOIN cal AS c
           ON c.accident_year = t.accident_year AND c.lob_code = t.lob_code AND c.dev_year = v.dev_year
    LEFT JOIN whole AS w
           ON w.accident_year = t.accident_year AND w.lob_code = t.lob_code AND w.dev_year = v.dev_year
    WHERE  v.paid IS NOT NULL
),
row_cmp AS (
    SELECT accident_year, lob_code,
           SUM(CASE WHEN paid <> paid_calendar THEN 1 ELSE 0 END) AS off_calendar,
           SUM(CASE WHEN paid <> paid_whole THEN 1 ELSE 0 END)    AS off_whole
    FROM   cells
    GROUP BY accident_year, lob_code
)
SELECT 'T06_TSQL04_dev_year_counts_calendar_years' AS check_id,
       SUM(CASE WHEN off_calendar = 0 AND off_whole > 0 THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT(SUM(CASE WHEN off_calendar = 0 AND off_whole > 0 THEN 1 ELSE 0 END), ' of ',
                   COUNT(*), ' rows (', SUM(off_whole), ' cells) differ from whole years; ',
                   (SELECT COUNT(*) FROM pay WHERE dev_boundaries <> dev_whole_years), ' of ',
                   (SELECT COUNT(*) FROM pay), ' payments sit a development year later')
            AS NVARCHAR(200)) AS detail
FROM   row_cmp;
GO
