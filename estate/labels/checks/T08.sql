/* T08 rpt.usp_fraud_flags: answer-key checks (evaluation only). Run after the job.
   Each check compares what the legacy code does on our data with the naive or intended
   logic. The as-of date comes from the output table, and policy details come from the
   latest policy snapshot on or before it, as the job takes them. The claim's lob_code is
   read as keyed from stg.claims, because the job compares it before normalising it. */
-- check: T08_BUG07_early_flag_uses_expiry_date
-- proves: early_notification_flag in rpt.claim_fraud_flags is set when the claim was notified 0-30 days after the policy's expiry date; the intended rule (notified within 30 days of the cover starting, i.e. the inception date) gives a different flag on these rows: false referrals on one side, missed early notifications on the other
WITH pol AS (       -- the policy extract the job reads
    SELECT p.policy_id, p.inception_date, p.expiry_date
    FROM   stg.policy_snapshots AS p
    WHERE  p.snapshot_date = (SELECT MAX(s.snapshot_date)
                              FROM   stg.policy_snapshots AS s
                              WHERE  s.snapshot_date <= (SELECT MAX(as_of_date) FROM rpt.claim_fraud_flags))
),
cmp AS (
    SELECT f.early_notification_flag AS legacy_flag,
           CASE WHEN DATEDIFF(DAY, pol.inception_date, f.reported_date) BETWEEN 0 AND 30
                THEN 1 ELSE 0 END AS intended_flag,                      -- intended: days since cover started
           CASE WHEN DATEDIFF(DAY, pol.expiry_date, f.reported_date) BETWEEN 0 AND 30
                THEN 1 ELSE 0 END AS after_expiry,                       -- what the legacy rule measures
           f.fraud_score,
           f.fraud_band
    FROM   rpt.claim_fraud_flags AS f
    LEFT JOIN pol ON pol.policy_id = f.policy_id
),
banded AS (
    SELECT cmp.*,
           CASE WHEN fraud_score - legacy_flag + intended_flag >= 2 THEN 'HIGH'
                WHEN fraud_score - legacy_flag + intended_flag = 1  THEN 'MEDIUM'
                ELSE 'LOW' END AS intended_band
    FROM   cmp
)
SELECT 'T08_BUG07_early_flag_uses_expiry_date' AS check_id,
       SUM(CASE WHEN legacy_flag <> intended_flag THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('early_notification_flag wrong on ', SUM(CASE WHEN legacy_flag <> intended_flag THEN 1 ELSE 0 END),
                   ' of ', COUNT(*), ' rows: set on ', SUM(CASE WHEN legacy_flag = 1 AND intended_flag = 0 THEN 1 ELSE 0 END),
                   ' (', SUM(CASE WHEN legacy_flag = 1 AND after_expiry = 1 THEN 1 ELSE 0 END), ' of ', SUM(legacy_flag),
                   ' flags 0-30 days after expiry), missed on ', SUM(CASE WHEN legacy_flag = 0 AND intended_flag = 1 THEN 1 ELSE 0 END),
                   ' notified within 30 days of inception; fraud_band differs on ',
                   SUM(CASE WHEN fraud_band <> intended_band THEN 1 ELSE 0 END))
            AS NVARCHAR(200)) AS detail
FROM   banded;
GO
-- check: T08_TSQL14_like_character_classes
-- proves: invalid_reg_flag uses NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%', where [0-9] and [A-Z] are T-SQL character classes, so only registrations outside the Irish format are flagged; Spark's LIKE has no character classes and reads the brackets as plain text (written '[[]' below), so no registration matches and every motor claim with a registration would be flagged
WITH pol AS (
    SELECT p.policy_id, p.vehicle_reg
    FROM   stg.policy_snapshots AS p
    WHERE  p.snapshot_date = (SELECT MAX(s.snapshot_date)
                              FROM   stg.policy_snapshots AS s
                              WHERE  s.snapshot_date <= (SELECT MAX(as_of_date) FROM rpt.claim_fraud_flags))
),
cmp AS (
    SELECT f.invalid_reg_flag AS legacy_flag,
           CASE WHEN c.lob_code = 'MOT'
                 AND pol.vehicle_reg NOT LIKE '[[]0-9][[]0-9]%-[[]A-Z]%-[[]0-9]%'   -- naive: brackets as plain text
                THEN 1 ELSE 0 END AS naive_flag,
           CASE WHEN c.lob_code = 'MOT' AND pol.vehicle_reg IS NOT NULL THEN 1 ELSE 0 END AS motor_with_reg,
           f.fraud_score,
           f.fraud_band
    FROM   rpt.claim_fraud_flags AS f
    JOIN   stg.claims AS c ON c.claim_id = f.claim_id
    LEFT JOIN pol ON pol.policy_id = f.policy_id
),
banded AS (
    SELECT cmp.*,
           CASE WHEN fraud_score - legacy_flag + naive_flag >= 2 THEN 'HIGH'
                WHEN fraud_score - legacy_flag + naive_flag = 1  THEN 'MEDIUM'
                ELSE 'LOW' END AS naive_band
    FROM   cmp
)
SELECT 'T08_TSQL14_like_character_classes' AS check_id,
       SUM(CASE WHEN legacy_flag <> naive_flag THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('invalid_reg_flag set on ', SUM(legacy_flag), ' of ', SUM(motor_with_reg),
                   ' motor claims with a non-NULL vehicle_reg; with the brackets as plain text it would be set on ',
                   SUM(naive_flag), ': ', SUM(CASE WHEN legacy_flag <> naive_flag THEN 1 ELSE 0 END),
                   ' rows differ, fraud_band on ', SUM(CASE WHEN fraud_band <> naive_band THEN 1 ELSE 0 END))
            AS NVARCHAR(200)) AS detail
FROM   banded;
GO
-- check: T08_TSQL15_substring_from_position_zero
-- proves: SUBSTRING(policy_number, 0, 4) returns 3 characters in T-SQL ('MOT': position 0 lies before the string), so no claim is flagged as keyed under another line of business; Spark's substring(policy_number, 0, 4) starts at position 1 and returns 4 characters ('MOT/'), which never equals a line of business, so every row would get lob_mismatch_flag = 1 and one more point of fraud_score
WITH cmp AS (
    SELECT f.lob_mismatch_flag AS legacy_flag,
           CASE WHEN SUBSTRING(f.policy_number, 1, 4) <> c.lob_code
                THEN 1 ELSE 0 END AS naive_flag,                          -- 4 characters, as Spark returns them
           LEN(SUBSTRING(f.policy_number, 0, 4)) AS legacy_len,
           f.fraud_score,
           f.fraud_band
    FROM   rpt.claim_fraud_flags AS f
    JOIN   stg.claims AS c ON c.claim_id = f.claim_id
),
banded AS (
    SELECT cmp.*,
           CASE WHEN fraud_score - legacy_flag + naive_flag >= 2 THEN 'HIGH'
                WHEN fraud_score - legacy_flag + naive_flag = 1  THEN 'MEDIUM'
                ELSE 'LOW' END AS naive_band
    FROM   cmp
)
SELECT 'T08_TSQL15_substring_from_position_zero' AS check_id,
       SUM(CASE WHEN legacy_flag <> naive_flag THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('lob_mismatch_flag differs on ', SUM(CASE WHEN legacy_flag <> naive_flag THEN 1 ELSE 0 END),
                   ' of ', COUNT(*), ' rows (legacy prefix 3 characters on ', SUM(CASE WHEN legacy_len = 3 THEN 1 ELSE 0 END),
                   ', naive 4); fraud_band changes on ', SUM(CASE WHEN fraud_band <> naive_band THEN 1 ELSE 0 END),
                   ', LOW to MEDIUM on ', SUM(CASE WHEN fraud_band = 'LOW' AND naive_band = 'MEDIUM' THEN 1 ELSE 0 END))
            AS NVARCHAR(200)) AS detail
FROM   banded;
GO
-- check: T08_TSQL16_convert_style_codes
-- proves: CONVERT style 112 makes loss_day_key yyyymmdd and style 103 writes the notification date into reason_text as dd/mm/yyyy; casting the date to text (yyyy-mm-dd) changes every loss_day_key, and reading 103 as US mm/dd/yyyy (style 101) changes reason_text wherever day and month differ
WITH cmp AS (
    SELECT CASE WHEN f.loss_day_key = CONVERT(CHAR(8), f.loss_date, 112)
                 AND f.loss_day_key <> CONVERT(VARCHAR(10), f.loss_date, 23) THEN 1 ELSE 0 END AS key_differs,
           CASE WHEN LEFT(f.reason_text, 19) = 'Notified ' + CONVERT(VARCHAR(10), f.reported_date, 103)
                 AND LEFT(f.reason_text, 19) <> 'Notified ' + CONVERT(VARCHAR(10), f.reported_date, 101) THEN 1 ELSE 0 END AS us_differs,
           CASE WHEN DAY(f.reported_date) <= 12 AND DAY(f.reported_date) <> MONTH(f.reported_date)
                THEN 1 ELSE 0 END AS valid_both_ways
    FROM   rpt.claim_fraud_flags AS f
)
SELECT 'T08_TSQL16_convert_style_codes' AS check_id,
       SUM(CASE WHEN key_differs = 1 OR us_differs = 1 THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT('loss_day_key differs from yyyy-mm-dd on ', SUM(key_differs), ' of ', COUNT(*),
                   ' rows; reason_text date differs from mm/dd/yyyy on ', SUM(us_differs),
                   ' (', SUM(us_differs * valid_both_ways), ' still valid dates)')
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T08_TSQL01_lob_code_compared_ignoring_case
-- proves: lob_mismatch_flag compares the claim's lob_code as keyed with the policy number's prefix under the CI collation, so claims keyed 'mot', 'Mot ' or 'hom' match 'MOT' or 'HOM'; compared case-sensitively (Spark's default), with the prefix length right, those claims would get lob_mismatch_flag = 1
WITH cmp AS (
    SELECT c.lob_code,
           f.lob_mismatch_flag AS legacy_flag,
           CASE WHEN SUBSTRING(f.policy_number, 0, 4) COLLATE Latin1_General_CS_AS
                     <> c.lob_code COLLATE Latin1_General_CS_AS        -- case counts; trailing spaces still ignored
                THEN 1 ELSE 0 END AS cs_flag
    FROM   rpt.claim_fraud_flags AS f
    JOIN   stg.claims AS c ON c.claim_id = f.claim_id
),
hit AS (
    SELECT * FROM cmp WHERE legacy_flag <> cs_flag
)
SELECT 'T08_TSQL01_lob_code_compared_ignoring_case' AS check_id,
       (SELECT COUNT(*) FROM hit) AS affected,
       CAST(CONCAT('lob_mismatch_flag differs on ', (SELECT COUNT(*) FROM hit), ' of ', (SELECT COUNT(*) FROM cmp),
                   ' rows (0 as legacy, 1 case-sensitively); lob_code keyed ',
                   (SELECT STRING_AGG(CONCAT('''', v.lob_code, ''' ', v.n), ', ') WITHIN GROUP (ORDER BY v.lob_code)
                    FROM  (SELECT lob_code COLLATE Latin1_General_BIN2 AS lob_code, COUNT(*) AS n
                           FROM   hit
                           GROUP BY lob_code COLLATE Latin1_General_BIN2) AS v))
            AS NVARCHAR(200)) AS detail;
GO
-- check: T08_TSQL01_motor_test_ignores_case
-- proves: the motor test cl.lob_code = 'MOT' compares lob_code as keyed under the CI collation, so a claim keyed 'mot' or 'Mot ' is treated as motor and its registration checked; with a case-sensitive = (Spark's default) such a claim whose registration is outside the pattern would lose its invalid_reg_flag
WITH pol AS (
    SELECT p.policy_id, p.vehicle_reg
    FROM   stg.policy_snapshots AS p
    WHERE  p.snapshot_date = (SELECT MAX(s.snapshot_date)
                              FROM   stg.policy_snapshots AS s
                              WHERE  s.snapshot_date <= (SELECT MAX(as_of_date) FROM rpt.claim_fraud_flags))
),
cmp AS (
    SELECT f.claim_id,
           c.lob_code,
           pol.vehicle_reg,
           f.invalid_reg_flag AS legacy_flag,
           CASE WHEN c.lob_code COLLATE Latin1_General_CS_AS = 'MOT'   -- case counts; trailing spaces still ignored
                 AND pol.vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'
                THEN 1 ELSE 0 END AS cs_flag
    FROM   rpt.claim_fraud_flags AS f
    JOIN   stg.claims AS c ON c.claim_id = f.claim_id
    LEFT JOIN pol ON pol.policy_id = f.policy_id
    WHERE  c.lob_code = 'MOT'                                          -- motor claims as the legacy test sees them
)
SELECT 'T08_TSQL01_motor_test_ignores_case' AS check_id,
       SUM(CASE WHEN legacy_flag <> cs_flag THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT(SUM(CASE WHEN lob_code COLLATE Latin1_General_CS_AS <> 'MOT' THEN 1 ELSE 0 END), ' of ', COUNT(*),
                   ' motor claims are motor only case-insensitively; invalid_reg_flag differs on ',
                   SUM(CASE WHEN legacy_flag <> cs_flag THEN 1 ELSE 0 END), ': ',
                   STRING_AGG(CASE WHEN legacy_flag <> cs_flag
                                   THEN CONCAT('claim ', claim_id, ' lob_code ''', lob_code, ''' reg ''', vehicle_reg, '''') END, ', ')
                       WITHIN GROUP (ORDER BY claim_id))
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T08_TSQL02_lob_code_compared_ignoring_trailing_spaces
-- proves: = and <> ignore trailing spaces, so a claim whose lob_code is keyed 'MOT ' or 'Hom ' equals its policy number's prefix; compared with trailing spaces significant (Spark's =, even case-insensitively) those claims would get lob_mismatch_flag = 1. The detail also shows the motor test (lob_code = 'MOT') is not affected on our data
WITH pol AS (
    SELECT p.policy_id, p.vehicle_reg
    FROM   stg.policy_snapshots AS p
    WHERE  p.snapshot_date = (SELECT MAX(s.snapshot_date)
                              FROM   stg.policy_snapshots AS s
                              WHERE  s.snapshot_date <= (SELECT MAX(as_of_date) FROM rpt.claim_fraud_flags))
),
cmp AS (
    SELECT c.lob_code,
           DATALENGTH(c.lob_code) AS bytes,
           CASE WHEN f.lob_mismatch_flag <> CASE WHEN SUBSTRING(f.policy_number, 0, 4) + '|'
                                                      <> c.lob_code + '|'      -- trailing spaces count; case still ignored
                                                 THEN 1 ELSE 0 END
                THEN 1 ELSE 0 END AS lob_differs,
           CASE WHEN f.invalid_reg_flag <> CASE WHEN c.lob_code + '|' = 'MOT|'
                                                 AND pol.vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'
                                                THEN 1 ELSE 0 END
                THEN 1 ELSE 0 END AS reg_differs
    FROM   rpt.claim_fraud_flags AS f
    JOIN   stg.claims AS c ON c.claim_id = f.claim_id
    LEFT JOIN pol ON pol.policy_id = f.policy_id
),
hit AS (
    SELECT * FROM cmp WHERE lob_differs = 1
)
SELECT 'T08_TSQL02_lob_code_compared_ignoring_trailing_spaces' AS check_id,
       (SELECT COUNT(*) FROM hit) AS affected,
       CAST(CONCAT('lob_mismatch_flag differs on ', (SELECT COUNT(*) FROM hit), ' rows, ',
                   (SELECT SUM(CASE WHEN bytes > LEN(lob_code) THEN 1 ELSE 0 END) FROM hit),
                   ' keyed with trailing spaces: ',
                   (SELECT STRING_AGG(CONCAT('''', v.lob_code, ''' ', v.n), ', ') WITHIN GROUP (ORDER BY v.lob_code)
                    FROM  (SELECT lob_code COLLATE Latin1_General_BIN2 AS lob_code, COUNT(*) AS n
                           FROM   hit
                           GROUP BY lob_code COLLATE Latin1_General_BIN2) AS v),
                   '; motor test: invalid_reg_flag differs on ', (SELECT SUM(reg_differs) FROM cmp))
            AS NVARCHAR(200)) AS detail;
GO
