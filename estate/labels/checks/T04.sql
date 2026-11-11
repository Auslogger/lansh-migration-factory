/* T04 rpt.usp_build_claims_summary: answer-key checks (evaluation only). Run after the job.
   Each check compares what the legacy code does on our data with the naive or intended
   logic. The as-of date comes from the output table, so the checks follow the job's own run. */
-- check: T04_TSQL01_status_filter_ignores_case
-- proves: WHERE c.status IN ('OPEN', 'REOPENED') under the CI collation also keeps claims keyed 'Open', 'open' or 'Reopened'; the same IN compared case-sensitively (Spark's default) drops them, so they would be missing from rpt.claims_summary
WITH kept AS (      -- claims whose filter outcome depends on case
    SELECT c.claim_id,
           c.status,
           CASE WHEN s.claim_id IS NULL THEN 0 ELSE 1 END AS in_output
    FROM   stg.claims AS c
    LEFT JOIN rpt.claims_summary AS s ON s.claim_id = c.claim_id
    WHERE  c.reported_date <= (SELECT MAX(as_of_date) FROM rpt.claims_summary)
      AND  c.status IN ('OPEN', 'REOPENED')                                   -- legacy: case-insensitive
      AND  c.status COLLATE Latin1_General_CS_AS NOT IN ('OPEN', 'REOPENED')  -- naive: case-sensitive
)
SELECT 'T04_TSQL01_status_filter_ignores_case' AS check_id,
       (SELECT SUM(in_output) FROM kept) AS affected,
       CAST(CONCAT((SELECT COUNT(*) FROM kept), ' claims pass only case-insensitively, ',
                   (SELECT SUM(in_output) FROM kept), ' of them in the ',
                   (SELECT COUNT(*) FROM rpt.claims_summary), ' summary rows: ',
                   (SELECT STRING_AGG(CONCAT('''', v.status, ''' ', v.n), ', ')
                           WITHIN GROUP (ORDER BY v.status)
                    FROM  (SELECT status COLLATE Latin1_General_BIN2 AS status, COUNT(*) AS n
                           FROM   kept
                           GROUP BY status COLLATE Latin1_General_BIN2) AS v))
            AS NVARCHAR(200)) AS detail;
GO
-- check: T04_TSQL02_status_filter_ignores_trailing_spaces
-- proves: the same IN keeps claims whose status is stored with a trailing space ('OPEN '), because = ignores trailing spaces; a comparison in which trailing spaces count (Spark's =, even case-insensitive) drops them from rpt.claims_summary
WITH kept AS (      -- claims whose filter outcome depends on trailing spaces
    SELECT c.claim_id,
           c.status,
           CASE WHEN s.claim_id IS NULL THEN 0 ELSE 1 END AS in_output
    FROM   stg.claims AS c
    LEFT JOIN rpt.claims_summary AS s ON s.claim_id = c.claim_id
    WHERE  c.reported_date <= (SELECT MAX(as_of_date) FROM rpt.claims_summary)
      AND  c.status IN ('OPEN', 'REOPENED')                 -- legacy: trailing spaces ignored
      AND  c.status + '|' NOT IN ('OPEN|', 'REOPENED|')     -- naive: trailing spaces significant (case still ignored)
)
SELECT 'T04_TSQL02_status_filter_ignores_trailing_spaces' AS check_id,
       (SELECT SUM(in_output) FROM kept) AS affected,
       CAST(CONCAT((SELECT COUNT(*) FROM kept), ' claims pass only because trailing spaces are ignored, ',
                   (SELECT SUM(in_output) FROM kept), ' of them in the summary: ',
                   (SELECT STRING_AGG(CONCAT('''', v.status, ''' (', v.bytes, ' bytes) ', v.n), ', ')
                           WITHIN GROUP (ORDER BY v.status, v.bytes)
                    FROM  (SELECT status COLLATE Latin1_General_BIN2 AS status,
                                  DATALENGTH(status) AS bytes, COUNT(*) AS n
                           FROM   kept
                           GROUP BY status COLLATE Latin1_General_BIN2, DATALENGTH(status)) AS v))
            AS NVARCHAR(200)) AS detail;
GO
-- check: T04_TSQL05_claim_ref_null_without_handler
-- proves: claim_ref is built with +, so it is NULL for every open claim without a handler; CONCAT() (NULL as empty text, like Spark's concat_ws) would give 'LOB/claim_number/' instead
WITH cmp AS (
    SELECT s.claim_id,
           s.handler_code,
           s.claim_ref AS legacy_ref,
           CONCAT(s.lob_code, '/', s.claim_number, '/', s.handler_code) AS naive_ref
    FROM   rpt.claims_summary AS s
)
SELECT 'T04_TSQL05_claim_ref_null_without_handler' AS check_id,
       SUM(CASE WHEN legacy_ref IS NULL OR legacy_ref <> naive_ref THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT(SUM(CASE WHEN legacy_ref IS NULL THEN 1 ELSE 0 END), ' of ', COUNT(*),
                   ' rows have claim_ref NULL (', SUM(CASE WHEN legacy_ref IS NULL AND handler_code IS NULL THEN 1 ELSE 0 END),
                   ' with no handler); CONCAT would give e.g. ''',
                   MIN(CASE WHEN legacy_ref IS NULL THEN naive_ref END), '''')
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T04_TSQL16_convert_style_codes
-- proves: CONVERT style 103 renders dd/mm/yyyy and CHAR(6) cuts style 112 (yyyymmdd) to yyyymm; reading 103 as US mm/dd/yyyy, casting the date to text (yyyy-mm-dd) or keeping all 8 characters of style 112 gives different text
WITH cmp AS (
    SELECT CASE WHEN s.loss_date_text = CONVERT(VARCHAR(10), s.loss_date, 103)
                 AND s.loss_date_text <> CONVERT(VARCHAR(10), s.loss_date, 101) THEN 1 ELSE 0 END AS us_differs,
           CASE WHEN s.loss_date_text = CONVERT(VARCHAR(10), s.loss_date, 103)
                 AND s.loss_date_text <> CONVERT(VARCHAR(10), s.loss_date, 23)  THEN 1 ELSE 0 END AS iso_differs,
           CASE WHEN s.reported_period = CONVERT(CHAR(6), s.reported_date, 112)
                 AND s.reported_period <> CONVERT(VARCHAR(8), s.reported_date, 112) THEN 1 ELSE 0 END AS period_differs,
           CASE WHEN DAY(s.loss_date) <= 12 AND DAY(s.loss_date) <> MONTH(s.loss_date)
                THEN 1 ELSE 0 END AS valid_both_ways
    FROM   rpt.claims_summary AS s
)
SELECT 'T04_TSQL16_convert_style_codes' AS check_id,
       SUM(CASE WHEN us_differs = 1 OR iso_differs = 1 OR period_differs = 1 THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('loss_date_text differs from mm/dd/yyyy on ', SUM(us_differs), ' rows (',
                   SUM(us_differs * valid_both_ways), ' still valid dates) and from yyyy-mm-dd on ',
                   SUM(iso_differs), '; reported_period differs from yyyymmdd on ', SUM(period_differs),
                   ' of ', COUNT(*))
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T04_BUG03_paid_counted_per_reserve_row
-- proves: payments are joined to the current reserve rows (one per reserve type) before aggregating, so total_paid (and incurred) in rpt.claims_summary count each payment once per reserve type; payments summed on their own, as intended, give a different total, while n_payments (COUNT DISTINCT) still looks right
WITH pay AS (       -- intended: payments to date aggregated on their own
    SELECT p.claim_id, SUM(p.amount) AS paid, COUNT(*) AS n_payments
    FROM   stg.claim_payments AS p
    JOIN   rpt.claims_summary AS s ON s.claim_id = p.claim_id
    WHERE  p.payment_date <= s.as_of_date
    GROUP BY p.claim_id
),
res AS (            -- reserve types with an entry to date: the fan-out factor
    SELECT r.claim_id, COUNT(DISTINCT r.reserve_type) AS reserve_types
    FROM   stg.claim_reserves AS r
    JOIN   rpt.claims_summary AS s ON s.claim_id = r.claim_id
    WHERE  r.reserve_date <= s.as_of_date
    GROUP BY r.claim_id
),
cmp AS (
    SELECT s.total_paid,
           s.n_payments,
           s.incurred - s.current_reserve  AS paid_in_incurred,
           ISNULL(pay.paid, 0)             AS intended_paid,
           ISNULL(pay.n_payments, 0)       AS intended_n,
           ISNULL(res.reserve_types, 0)    AS reserve_types
    FROM   rpt.claims_summary AS s
    LEFT JOIN pay ON pay.claim_id = s.claim_id
    LEFT JOIN res ON res.claim_id = s.claim_id
)
SELECT 'T04_BUG03_paid_counted_per_reserve_row' AS check_id,
       SUM(CASE WHEN total_paid <> intended_paid THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('total_paid over-stated on ', SUM(CASE WHEN total_paid <> intended_paid THEN 1 ELSE 0 END),
                   ' of ', COUNT(*), ' claims by EUR ', SUM(total_paid - intended_paid),
                   ', incurred on ', SUM(CASE WHEN paid_in_incurred <> intended_paid THEN 1 ELSE 0 END),
                   '; paid x reserve types on ',
                   SUM(CASE WHEN total_paid <> intended_paid AND total_paid = intended_paid * reserve_types THEN 1 ELSE 0 END),
                   '; n_payments right on ', SUM(CASE WHEN n_payments = intended_n THEN 1 ELSE 0 END))
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
