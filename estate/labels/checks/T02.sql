/* T02 dw.usp_load_dim_policy: answer-key checks (evaluation only). Run after the job, once
   both snapshot batches are loaded. dw.dim_policy keeps status, broker_code and vehicle_reg
   as keyed in the snapshot each version came from (source_snapshot_date), so each check
   recomputes, from the output and the snapshot rows behind it, what a case-sensitive,
   space-sensitive or NULL-safe engine would do, and counts the output rows that differ. The
   change-detection checks compare the current versions with the latest snapshot loaded. */
-- check: T02_TSQL06_direct_sales_truncated
-- proves: ISNULL(p.broker_code, 'DIRECT-SALES') takes the type of broker_code, VARCHAR(10), so direct business is stored as 'DIRECT-SAL' although dw.dim_policy.broker_code is VARCHAR(12); COALESCE, like Spark's coalesce, returns the full 'DIRECT-SALES'
WITH cmp AS (
    SELECT d.policy_id,
           d.broker_code                            AS legacy_code,
           COALESCE(s.broker_code, 'DIRECT-SALES')  AS coalesce_code
    FROM   dw.dim_policy AS d
    JOIN   stg.policy_snapshots AS s
           ON s.policy_id = d.policy_id
          AND s.snapshot_date = d.source_snapshot_date
    WHERE  s.broker_code IS NULL
)
SELECT 'T02_TSQL06_direct_sales_truncated' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' versions of ', COUNT(DISTINCT policy_id), ' direct policies hold broker_code ''',
                   MAX(legacy_code), ''' (', MAX(DATALENGTH(legacy_code)), ' characters); COALESCE gives ''',
                   MAX(coalesce_code), ''', which the VARCHAR(', COL_LENGTH('dw.dim_policy', 'broker_code'),
                   ') column holds')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  CAST(legacy_code AS VARBINARY(12)) <> CAST(coalesce_code AS VARBINARY(12));
GO
-- check: T02_TSQL06_vehicle_reg_null_equals_empty
-- proves: change detection compares ISNULL(vehicle_reg, ''), so a registration that went from NULL to '' (or '' to NULL) between snapshots is no change and the current version keeps the old value; a NULL-safe comparison (Spark's <=>) closes these versions and opens new ones
DECLARE @latest DATE = (SELECT MAX(source_snapshot_date) FROM dw.dim_policy);

WITH cmp AS (
    SELECT d.policy_id,
           d.vehicle_reg AS kept_reg,
           s.vehicle_reg AS latest_reg,
           CASE WHEN ISNULL(s.vehicle_reg, '') <> ISNULL(d.vehicle_reg, '') THEN 1 ELSE 0 END AS legacy_change,
           CASE WHEN (s.vehicle_reg IS NULL AND d.vehicle_reg IS NOT NULL)
                  OR (s.vehicle_reg IS NOT NULL AND d.vehicle_reg IS NULL)
                  OR CAST(s.vehicle_reg AS VARBINARY(12)) <> CAST(d.vehicle_reg AS VARBINARY(12))
                THEN 1 ELSE 0 END AS null_safe_change
    FROM   dw.dim_policy AS d
    JOIN   stg.policy_snapshots AS s
           ON s.policy_id = d.policy_id
          AND s.snapshot_date = @latest
    WHERE  d.is_current = 'Y'
)
SELECT 'T02_TSQL06_vehicle_reg_null_equals_empty' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' current versions keep a vehicle_reg the ', @latest, ' snapshot changed between NULL and empty: ',
                   SUM(CASE WHEN kept_reg IS NULL THEN 1 ELSE 0 END), ' NULL now empty, ',
                   SUM(CASE WHEN latest_reg IS NULL THEN 1 ELSE 0 END), ' empty now NULL; ',
                   'a NULL-safe comparison would open a new version for each')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  legacy_change = 0
  AND  null_safe_change = 1
  AND  ISNULL(DATALENGTH(kept_reg), 0) = 0
  AND  ISNULL(DATALENGTH(latest_reg), 0) = 0;
GO
-- check: T02_TSQL01_status_case_change_ignored
-- proves: change detection compares status case-insensitively, so a status re-keyed only in case between snapshots ('EXPIRED' -> 'Expired') is no change and the current version keeps the old text; compared case-sensitively, as Spark compares strings, each of these policies gets a new version
DECLARE @latest DATE = (SELECT MAX(source_snapshot_date) FROM dw.dim_policy);

WITH cmp AS (
    SELECT d.policy_id,
           d.status AS kept_status,
           s.status AS latest_status
    FROM   dw.dim_policy AS d
    JOIN   stg.policy_snapshots AS s
           ON s.policy_id = d.policy_id
          AND s.snapshot_date = @latest
    WHERE  d.is_current = 'Y'
      AND  ISNULL(s.status, '') = ISNULL(d.status, '')                                  -- the job's test: no change
      AND  s.status COLLATE Latin1_General_CS_AS <> d.status COLLATE Latin1_General_CS_AS  -- case-sensitive: changed
)
SELECT 'T02_TSQL01_status_case_change_ignored' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' current versions keep a status the ', @latest, ' snapshot re-keyed in another case (',
                   SUM(CASE WHEN UPPER(kept_status) = 'EXPIRED' THEN 1 ELSE 0 END), ' EXPIRED, ',
                   SUM(CASE WHEN UPPER(kept_status) = 'ACTIVE' THEN 1 ELSE 0 END), ' ACTIVE, ',
                   SUM(CASE WHEN UPPER(kept_status) = 'LAPSED' THEN 1 ELSE 0 END), ' LAPSED, ',
                   SUM(CASE WHEN UPPER(kept_status) = 'CANCELLED' THEN 1 ELSE 0 END), ' CANCELLED), e.g. policy ',
                   (SELECT TOP 1 CONCAT(x.policy_id, ' kept ', x.kept_status, ', now ', x.latest_status)
                    FROM cmp AS x ORDER BY x.policy_id))
            AS NVARCHAR(200)) AS detail
FROM   cmp;
GO
-- check: T02_TSQL01_product_join_case
-- proves: the product join matches product codes keyed in lower case ('mot-comp') to the catalogue's 'MOT-COMP'; joined case-sensitively, as Spark joins strings, these versions find no product and the inner join drops them
WITH cmp AS (
    SELECT d.policy_sk,
           d.policy_id,
           d.product_code,
           s.product_code AS keyed_code,
           (SELECT pr.product_name FROM stg.products AS pr
            WHERE  pr.product_code COLLATE Latin1_General_CS_AS = s.product_code COLLATE Latin1_General_CS_AS) AS case_sensitive_name
    FROM   dw.dim_policy AS d
    JOIN   stg.policy_snapshots AS s
           ON s.policy_id = d.policy_id
          AND s.snapshot_date = d.source_snapshot_date
)
SELECT 'T02_TSQL01_product_join_case' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' versions of ', COUNT(DISTINCT policy_id), ' policies were joined to the catalogue from a ',
                   'product code keyed in another case (', COUNT(DISTINCT CAST(keyed_code AS VARBINARY(10))),
                   ' spellings, e.g. ',
                   (SELECT TOP 1 CONCAT(x.keyed_code, ' for ', x.product_code) FROM cmp AS x
                    WHERE x.case_sensitive_name IS NULL ORDER BY x.policy_sk),
                   '); a case-sensitive inner join drops them')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  case_sensitive_name IS NULL;
GO
-- check: T02_TSQL02_product_join_padding
-- proves: the product join ignores trailing spaces, so a product code keyed as 'HOM-BC ' matches the catalogue's 'HOM-BC'; compared exactly, as Spark compares strings, these versions find no product and the inner join drops them
WITH cmp AS (
    SELECT d.policy_sk,
           d.policy_id,
           s.product_code AS keyed_code,
           (SELECT pr.product_name FROM stg.products AS pr
            WHERE  pr.product_code = s.product_code
              AND  DATALENGTH(pr.product_code) = DATALENGTH(s.product_code)) AS space_sensitive_name
    FROM   dw.dim_policy AS d
    JOIN   stg.policy_snapshots AS s
           ON s.policy_id = d.policy_id
          AND s.snapshot_date = d.source_snapshot_date
)
SELECT 'T02_TSQL02_product_join_padding' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' versions of ', COUNT(DISTINCT policy_id), ' policies were joined to the catalogue from a ',
                   'product code keyed with a trailing space (', COUNT(DISTINCT CAST(keyed_code AS VARBINARY(10))),
                   ' spellings, e.g. ''',
                   (SELECT TOP 1 x.keyed_code FROM cmp AS x
                    WHERE x.space_sensitive_name IS NULL ORDER BY x.policy_sk),
                   '''); an exact inner join drops them')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  space_sensitive_name IS NULL;
GO
-- check: T02_TSQL01_broker_join_case
-- proves: the broker join matches broker codes keyed in another case ('brk001', 'Brk001', 'bk102') to the register; joined case-sensitively, as Spark joins strings, these versions get no broker_name
WITH cmp AS (
    SELECT d.policy_sk,
           d.policy_id,
           d.broker_code,
           d.broker_name AS legacy_name,
           (SELECT b.broker_name FROM stg.brokers AS b
            WHERE  b.broker_code COLLATE Latin1_General_CS_AS = d.broker_code COLLATE Latin1_General_CS_AS) AS case_sensitive_name
    FROM   dw.dim_policy AS d
    WHERE  d.broker_name IS NOT NULL
)
SELECT 'T02_TSQL01_broker_join_case' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' versions of ', COUNT(DISTINCT policy_id), ' policies have a broker_name from a broker code ',
                   'keyed in another case (', SUM(CASE WHEN broker_code COLLATE Latin1_General_BIN2 = LOWER(broker_code) THEN 1 ELSE 0 END),
                   ' versions all lower case; first example ',
                   (SELECT TOP 1 x.broker_code FROM cmp AS x
                    WHERE x.case_sensitive_name IS NULL ORDER BY x.policy_sk),
                   '); joined case-sensitively broker_name is NULL')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  case_sensitive_name IS NULL;
GO
-- check: T02_TSQL02_broker_join_padding
-- proves: the broker join ignores trailing spaces, so 'BK102' (VARCHAR) matches the register's CHAR(6) 'BK102 ' and 'BRK001  ' matches 'BRK001'; compared exactly, as Spark compares strings, these versions get no broker_name
WITH cmp AS (
    SELECT d.policy_id,
           d.broker_code,
           d.broker_name AS legacy_name,
           (SELECT b.broker_name FROM stg.brokers AS b
            WHERE  b.broker_code = d.broker_code
              AND  DATALENGTH(b.broker_code) = DATALENGTH(d.broker_code)) AS space_sensitive_name
    FROM   dw.dim_policy AS d
    WHERE  d.broker_name IS NOT NULL
)
SELECT 'T02_TSQL02_broker_join_padding' AS check_id,
       COUNT(*) AS affected,
       CAST(CONCAT(COUNT(*), ' versions of ', COUNT(DISTINCT policy_id), ' policies have a broker_name only because ',
                   'trailing spaces are ignored: ', SUM(CASE WHEN DATALENGTH(broker_code) < 6 THEN 1 ELSE 0 END),
                   ' keyed as 5 characters against the CHAR(6) register, ',
                   SUM(CASE WHEN DATALENGTH(broker_code) > 6 THEN 1 ELSE 0 END), ' keyed with extra trailing spaces')
            AS NVARCHAR(200)) AS detail
FROM   cmp
WHERE  space_sensitive_name IS NULL;
GO
