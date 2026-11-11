/* T05 rpt.usp_claim_aging: answer-key checks (evaluation only). Run after the job.
   Every check reads rpt.claim_aging (and the as-of date stored in it), so the same
   checks can be run against a migrated copy of the output. */
-- check: T05_BUG04_thirty_days_unbanded
-- proves: claims exactly 30 days past their last activity fall between the '0-29' and '31-60' bands and come out as 'UNKNOWN'; gap-free bands would put every claim with a valid day count in a band
SELECT 'T05_BUG04_thirty_days_unbanded' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM rpt.claim_aging),
                   ' claims banded UNKNOWN with days_since_activity ',
                   MIN(a.days_since_activity), '-', MAX(a.days_since_activity),
                   '; gap-free bands put them in ', MIN(i.band))
            AS NVARCHAR(200)) AS detail
FROM   rpt.claim_aging AS a
CROSS APPLY (SELECT CASE WHEN a.days_since_activity BETWEEN 0 AND 30 THEN '0-30'
                         WHEN a.days_since_activity BETWEEN 31 AND 60 THEN '31-60'
                         WHEN a.days_since_activity > 60 THEN '61+'
                    END AS band) AS i            -- intended: contiguous bands
WHERE  a.aging_band = 'UNKNOWN'
  AND  i.band IS NOT NULL;
GO
-- check: T05_TSQL04_weeks_open_counts_sundays
-- proves: weeks_open follows DATEDIFF(WEEK), which counts the Sunday boundaries crossed; whole 7-day weeks since notification (days / 7) give a different value on these rows
SELECT 'T05_TSQL04_weeks_open_counts_sundays' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM rpt.claim_aging),
                   ' rows: weeks_open exceeds whole weeks by ',
                   MIN(a.weeks_open - w.whole_weeks), '-', MAX(a.weeks_open - w.whole_weeks),
                   ' (as-of date is a ', DATENAME(WEEKDAY, MAX(a.as_of_date)), ')')
            AS NVARCHAR(200)) AS detail
FROM   rpt.claim_aging AS a
CROSS APPLY (SELECT DATEDIFF(DAY, a.reported_date, a.as_of_date) / 7 AS whole_weeks) AS w
WHERE  a.weeks_open <> w.whole_weeks;
GO
-- check: T05_TSQL01_open_status_case_variants
-- proves: the open-status filter IN ('OPEN', 'REOPENED') also keeps 'Open', 'open' and 'Reopened' under the case-insensitive collation; a case-sensitive comparison drops these claims from the output
SELECT 'T05_TSQL01_open_status_case_variants' AS check_id,
       ISNULL(SUM(v.n), 0) AS affected,
       CAST(CONCAT('kept by the job, dropped by a case-sensitive match: ',
                   STRING_AGG(CONCAT('''', v.status, ''' x', v.n), ', ')
                       WITHIN GROUP (ORDER BY v.status))
            AS NVARCHAR(200)) AS detail
FROM  (SELECT c.status COLLATE Latin1_General_CS_AS AS status, COUNT(*) AS n
       FROM   rpt.claim_aging AS a
       JOIN   stg.claims AS c ON c.claim_id = a.claim_id
       WHERE  c.status IN ('OPEN', 'REOPENED')                                 -- the job's filter
         AND  c.status COLLATE Latin1_General_CS_AS NOT IN ('OPEN', 'REOPENED') -- case-sensitive
       GROUP BY c.status COLLATE Latin1_General_CS_AS) AS v;
GO
-- check: T05_TSQL02_open_status_trailing_spaces
-- proves: the open-status filter also keeps 'OPEN ' because SQL Server ignores trailing spaces when comparing; an exact comparison of the stored value (padding included) drops these claims from the output
SELECT 'T05_TSQL02_open_status_trailing_spaces' AS check_id,
       ISNULL(SUM(v.n), 0) AS affected,
       CAST(CONCAT('kept by the job, dropped by an exact match: ',
                   STRING_AGG(CONCAT('''', v.status, ''' (', v.bytes, ' bytes) x', v.n), ', ')
                       WITHIN GROUP (ORDER BY v.status))
            AS NVARCHAR(200)) AS detail
FROM  (SELECT c.status COLLATE Latin1_General_CS_AS AS status,
              DATALENGTH(c.status) AS bytes, COUNT(*) AS n
       FROM   rpt.claim_aging AS a
       JOIN   stg.claims AS c ON c.claim_id = a.claim_id
       WHERE  c.status IN ('OPEN', 'REOPENED')                     -- the job's filter
         AND  DATALENGTH(c.status) > DATALENGTH(RTRIM(c.status))  -- stored value is padded
       GROUP BY c.status COLLATE Latin1_General_CS_AS, DATALENGTH(c.status)) AS v;
GO
-- check: T05_TSQL12_null_amount_voids_total
-- proves: the cursor's running total (SET @total = @total + @amount) turns NULL at an unkeyed (NULL) payment amount and stays NULL, where a set-based SUM(amount) skips the NULL and returns a total
SELECT 'T05_TSQL12_null_amount_voids_total' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' claims with total_paid NULL that SUM(amount) would total; EUR ',
                   SUM(s.sum_paid), ' of payments not reported')
            AS NVARCHAR(200)) AS detail
FROM   rpt.claim_aging AS a
CROSS APPLY (SELECT SUM(p.amount) AS sum_paid
             FROM   stg.claim_payments AS p
             WHERE  p.claim_id = a.claim_id
               AND  p.payment_date <= a.as_of_date
               AND  p.amount IS NOT NULL) AS s
WHERE  a.total_paid IS NULL
  AND  s.sum_paid IS NOT NULL;
GO
