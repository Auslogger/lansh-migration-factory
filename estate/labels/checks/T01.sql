/* T01 dw.usp_load_dim_customer: answer-key checks (evaluation only). Run after the job.
   dw.dim_customer holds the version of each customer the job kept, with email, county,
   eircode and segment_code as keyed, so most checks re-derive a column from the output's
   own values the way a case- or space-sensitive engine would, and count the rows that
   change. The as-of date comes from the output table, so the checks follow the job's run. */
-- check: T01_BUG01_oldest_version_kept
-- proves: customers with several CRM versions hold their oldest version in dw.dim_customer; the intended latest version (updated_at DESC, _row_seq DESC) is a later save and, for most, different details
DECLARE @AsOfDate DATE = (SELECT MAX(as_of_date) FROM dw.dim_customer);

WITH latest AS (    -- the version the job means to keep: the last one saved
    SELECT c.customer_id, c.updated_at, c.first_name, c.last_name, c.email, c.address_line1,
           c.town, c.county, c.eircode, c.segment_code, c.marketing_opt_in,
           ROW_NUMBER() OVER (PARTITION BY c.customer_id
                              ORDER BY c.updated_at DESC, c._row_seq DESC) AS rn
    FROM   stg.customers AS c
    WHERE  CAST(c.updated_at AS DATE) <= @AsOfDate
),
cmp AS (            -- byte-exact, NULL-safe comparison of the copied columns
    SELECT d.version_count,
           CASE WHEN d.record_updated_at < l.updated_at THEN 1 ELSE 0 END AS older_save,
           CASE WHEN EXISTS (
                    SELECT CAST(d.first_name AS VARBINARY(80)), CAST(d.last_name AS VARBINARY(120)),
                           CAST(d.email AS VARBINARY(120)), CAST(d.address_line1 AS VARBINARY(200)),
                           CAST(d.town AS VARBINARY(100)), CAST(d.county AS VARBINARY(30)),
                           CAST(d.eircode AS VARBINARY(10)), CAST(d.segment_code AS VARBINARY(4)),
                           CAST(d.marketing_opt_in AS VARBINARY(1))
                    EXCEPT
                    SELECT CAST(RTRIM(l.first_name) AS VARBINARY(80)), CAST(l.last_name AS VARBINARY(120)),
                           CAST(l.email AS VARBINARY(120)), CAST(l.address_line1 AS VARBINARY(200)),
                           CAST(l.town AS VARBINARY(100)), CAST(l.county AS VARBINARY(30)),
                           CAST(l.eircode AS VARBINARY(10)), CAST(l.segment_code AS VARBINARY(4)),
                           CAST(ISNULL(l.marketing_opt_in, 'N') AS VARBINARY(1)))
                THEN 1 ELSE 0 END AS stale_details,
           CASE WHEN d.record_updated_at = l.updated_at AND d.version_count > 1 THEN 1 ELSE 0 END AS same_second
    FROM   dw.dim_customer AS d
    JOIN   latest AS l ON l.customer_id = d.customer_id AND l.rn = 1
)
SELECT 'T01_BUG01_oldest_version_kept' AS check_id,
       SUM(CASE WHEN older_save = 1 OR stale_details = 1 THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT(SUM(CASE WHEN older_save = 1 OR stale_details = 1 THEN 1 ELSE 0 END), ' of ',
                   SUM(CASE WHEN version_count > 1 THEN 1 ELSE 0 END),
                   ' multi-version customers hold an older version: ', SUM(older_save),
                   ' an earlier save, ', SUM(stale_details), ' superseded details (',
                   SUM(same_second * stale_details), ' saved in the same second as the latest)')
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T01_TSQL01_region_county_case
-- proves: the region CASE matches county names keyed in another case (DUBLIN, dublin); looked up case-sensitively, as Spark compares strings, these customers fall to UNKNOWN
WITH region_map AS (
    SELECT m.county, m.region
    FROM  (VALUES ('Dublin', 'EAST'), ('Kildare', 'EAST'), ('Meath', 'EAST'), ('Wicklow', 'EAST'),
                  ('Louth', 'EAST'), ('Wexford', 'EAST'),
                  ('Cork', 'SOUTH'), ('Kerry', 'SOUTH'), ('Limerick', 'SOUTH'), ('Tipperary', 'SOUTH'),
                  ('Waterford', 'SOUTH'), ('Kilkenny', 'SOUTH'), ('Carlow', 'SOUTH'),
                  ('Galway', 'WEST'), ('Mayo', 'WEST'), ('Clare', 'WEST'), ('Roscommon', 'WEST'),
                  ('Donegal', 'NORTH-WEST'), ('Sligo', 'NORTH-WEST'), ('Leitrim', 'NORTH-WEST'),
                  ('Cavan', 'NORTH-WEST'), ('Monaghan', 'NORTH-WEST'),
                  ('Westmeath', 'MIDLANDS'), ('Longford', 'MIDLANDS'), ('Offaly', 'MIDLANDS'),
                  ('Laois', 'MIDLANDS')) AS m (county, region)
),
naive AS (
    SELECT d.county, d.region,
           ISNULL((SELECT m.region FROM region_map AS m
                   WHERE m.county COLLATE Latin1_General_CS_AS = d.county COLLATE Latin1_General_CS_AS),
                  'UNKNOWN') AS case_sensitive_region
    FROM   dw.dim_customer AS d
)
SELECT 'T01_TSQL01_region_county_case' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers move from a region to UNKNOWN: county keyed in upper case ',
                   SUM(CASE WHEN county COLLATE Latin1_General_BIN2 = UPPER(county) THEN 1 ELSE 0 END),
                   ', lower case ',
                   SUM(CASE WHEN county COLLATE Latin1_General_BIN2 = LOWER(county) THEN 1 ELSE 0 END))
            AS NVARCHAR(200)) AS detail
FROM   naive
WHERE  case_sensitive_region <> region;
GO
-- check: T01_TSQL02_region_county_padding
-- proves: the region CASE matches county names keyed with a trailing space ('Dublin '); compared exactly, as Spark compares strings, these customers fall to UNKNOWN
WITH region_map AS (
    SELECT m.county, m.region
    FROM  (VALUES ('Dublin', 'EAST'), ('Kildare', 'EAST'), ('Meath', 'EAST'), ('Wicklow', 'EAST'),
                  ('Louth', 'EAST'), ('Wexford', 'EAST'),
                  ('Cork', 'SOUTH'), ('Kerry', 'SOUTH'), ('Limerick', 'SOUTH'), ('Tipperary', 'SOUTH'),
                  ('Waterford', 'SOUTH'), ('Kilkenny', 'SOUTH'), ('Carlow', 'SOUTH'),
                  ('Galway', 'WEST'), ('Mayo', 'WEST'), ('Clare', 'WEST'), ('Roscommon', 'WEST'),
                  ('Donegal', 'NORTH-WEST'), ('Sligo', 'NORTH-WEST'), ('Leitrim', 'NORTH-WEST'),
                  ('Cavan', 'NORTH-WEST'), ('Monaghan', 'NORTH-WEST'),
                  ('Westmeath', 'MIDLANDS'), ('Longford', 'MIDLANDS'), ('Offaly', 'MIDLANDS'),
                  ('Laois', 'MIDLANDS')) AS m (county, region)
),
naive AS (
    SELECT d.county, d.region,
           ISNULL((SELECT m.region FROM region_map AS m
                   WHERE m.county = d.county
                     AND DATALENGTH(m.county) = DATALENGTH(d.county)),
                  'UNKNOWN') AS space_sensitive_region,
           CASE WHEN d.county COLLATE Latin1_General_CS_AS IN (SELECT m.county FROM region_map AS m)
                THEN 1 ELSE 0 END AS same_case
    FROM   dw.dim_customer AS d
)
SELECT 'T01_TSQL02_region_county_padding' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers move from a region to UNKNOWN: county keyed with a ',
                   'trailing space (', SUM(same_case),
                   ' of them otherwise in the exact case of the county list)')
            AS NVARCHAR(200)) AS detail
FROM   naive
WHERE  space_sensitive_region <> region;
GO
-- check: T01_TSQL01_email_shared_case
-- proves: email_shared_count counts emails that differ only in case (Mary.Ryan1@x / mary.ryan1@x) as one address; grouped case-sensitively, as Spark groups strings, these customers' counts drop
WITH naive AS (
    SELECT d.email_shared_count,
           COUNT(*) OVER (PARTITION BY d.email COLLATE Latin1_General_CS_AS) AS case_sensitive_count
    FROM   dw.dim_customer AS d
    WHERE  d.email IS NOT NULL
)
SELECT 'T01_TSQL01_email_shared_case' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers share an email only case-insensitively: email_shared_count ',
                   SUM(email_shared_count), ' in total, ', SUM(case_sensitive_count),
                   ' when grouped case-sensitively')
            AS NVARCHAR(200)) AS detail
FROM   naive
WHERE  case_sensitive_count <> email_shared_count;
GO
-- check: T01_TSQL02_email_shared_padding
-- proves: email_shared_count counts an email keyed with a trailing space as the same address; grouped on the exact value, as Spark groups strings, these customers' counts drop
WITH naive AS (
    SELECT d.email_shared_count,
           COUNT(*) OVER (PARTITION BY d.email, DATALENGTH(d.email)) AS space_sensitive_count
    FROM   dw.dim_customer AS d
    WHERE  d.email IS NOT NULL
)
SELECT 'T01_TSQL02_email_shared_padding' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers share an email only when trailing spaces are ignored: ',
                   'email_shared_count ', SUM(email_shared_count), ' in total, ',
                   SUM(space_sensitive_count), ' when grouped on the exact value')
            AS NVARCHAR(200)) AS detail
FROM   naive
WHERE  space_sensitive_count <> email_shared_count;
GO
-- check: T01_TSQL02_segment_char_padding
-- proves: segment_code is CHAR(4), so STD is held as 'STD ' and equals 'STD' only because the comparison ignores trailing spaces; compared exactly, as Spark compares strings, none of these customers is standard
SELECT 'T01_TSQL02_segment_char_padding' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers have is_standard_segment = Y from a ',
                   MAX(DATALENGTH(d.segment_code)), '-character segment_code; ',
                   SUM(CASE WHEN CAST(d.segment_code AS VARBINARY(4)) = CAST('STD' AS VARBINARY(4))
                            THEN 1 ELSE 0 END),
                   ' of them hold exactly STD')
            AS NVARCHAR(200)) AS detail
FROM   dw.dim_customer AS d
WHERE  d.is_standard_segment = 'Y'
  AND  CASE WHEN d.segment_code = 'STD' AND DATALENGTH(d.segment_code) = DATALENGTH('STD')
            THEN 'Y' ELSE 'N' END = 'N';
GO
-- check: T01_TSQL04_age_at_join_year_boundaries
-- proves: age_at_join is DATEDIFF(YEAR), the number of year boundaries crossed; for customers who joined before their birthday in that year it is one more than their age in whole years
WITH ages AS (
    SELECT d.age_at_join,
           (  (YEAR(d.customer_since) * 10000 + MONTH(d.customer_since) * 100 + DAY(d.customer_since))
            - (YEAR(d.date_of_birth) * 10000 + MONTH(d.date_of_birth) * 100 + DAY(d.date_of_birth))
           ) / 10000 AS whole_years
    FROM   dw.dim_customer AS d
    WHERE  d.date_of_birth IS NOT NULL
)
SELECT 'T01_TSQL04_age_at_join_year_boundaries' AS check_id,
       SUM(CASE WHEN age_at_join <> whole_years THEN 1 ELSE 0 END) AS affected,
       CAST(CONCAT(SUM(CASE WHEN age_at_join <> whole_years THEN 1 ELSE 0 END), ' of ', COUNT(*),
                   ' customers with a date of birth have age_at_join above their age in whole years (',
                   SUM(CASE WHEN age_at_join = whole_years + 1 THEN 1 ELSE 0 END),
                   ' by exactly one year)')
            AS NVARCHAR(200)) AS detail
FROM   ages;
GO
-- check: T01_TSQL15_eircode_len_trailing_space
-- proves: LEN ignores trailing spaces, so a 7-character Eircode keyed with a trailing space passes the length test; counting every character, as Spark's length does, the same rule marks it invalid
WITH naive AS (
    SELECT d.eircode, d.eircode_valid,
           CASE WHEN DATALENGTH(d.eircode) = 7 THEN 'Y'
                WHEN DATALENGTH(d.eircode) = 8 AND SUBSTRING(d.eircode, 4, 1) = ' ' THEN 'Y'
                ELSE 'N'
           END AS valid_counting_spaces
    FROM   dw.dim_customer AS d
)
SELECT 'T01_TSQL15_eircode_len_trailing_space' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' customers have eircode_valid = ', MAX(eircode_valid),
                   ' from an Eircode that LEN counts as ', MAX(LEN(eircode)),
                   ' characters but holds ', MAX(DATALENGTH(eircode)))
            AS NVARCHAR(200)) AS detail
FROM   naive
WHERE  valid_counting_spaces <> eircode_valid;
GO
-- check: T01_TSQL15_initials_substring_from_0
-- proves: SUBSTRING(name, 0, 2) returns one character in T-SQL (positions 0 and 1); read as starting at the first character, as Spark's substring does, it returns two and every customer's initials change
SELECT 'T01_TSQL15_initials_substring_from_0' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' of ', (SELECT COUNT(*) FROM dw.dim_customer),
                   ' customers, e.g. customer ', MIN(d.customer_id), ': ',
                   (SELECT TOP 1 CONCAT(x.initials, ' would be ',
                                        UPPER(SUBSTRING(x.first_name, 1, 2) + SUBSTRING(x.last_name, 1, 2)))
                    FROM   dw.dim_customer AS x
                    WHERE  x.initials <> UPPER(SUBSTRING(x.first_name, 1, 2) + SUBSTRING(x.last_name, 1, 2))
                    ORDER BY x.customer_id))
            AS NVARCHAR(200)) AS detail
FROM   dw.dim_customer AS d
WHERE  d.initials <> UPPER(SUBSTRING(d.first_name, 1, 2) + SUBSTRING(d.last_name, 1, 2));
GO
