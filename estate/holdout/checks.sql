-- check: X1_bug
-- Output rows of rpt.broker_production whose claims_paid_eur or paid_to_written changes
-- when payments in the year are taken for all claims, not only claims notified in the year.
DECLARE @AsOfDate DATE = '2025-12-31';
DECLARE @YearStart DATE = DATEFROMPARTS(YEAR(@AsOfDate), 1, 1);
WITH pol AS (
    SELECT x.policy_id, x.broker_code, x.lob_code, x.inception_date, x.expiry_date, x.cancellation_date
    FROM (
        SELECT s.policy_id,
               ISNULL(UPPER(LTRIM(RTRIM(s.broker_code))), 'DIRECT') AS broker_code,
               UPPER(RTRIM(p.lob_code)) AS lob_code,
               s.inception_date, s.expiry_date, s.cancellation_date,
               ROW_NUMBER() OVER (PARTITION BY s.policy_id ORDER BY s.snapshot_date DESC, s._row_seq DESC) AS rn
        FROM stg.policy_snapshots s
        INNER JOIN stg.products p ON p.product_code = s.product_code
        WHERE s.snapshot_date <= @AsOfDate
    ) x
    WHERE x.rn = 1
),
gwp AS (
    SELECT p.broker_code, p.lob_code,
           SUM(t.amount * CASE WHEN t.currency = 'EUR' THEN 1 ELSE fx.rate_to_eur END) AS gwp_eur
    FROM stg.premium_transactions t
    INNER JOIN pol p ON p.policy_id = t.policy_id
    OUTER APPLY (
        SELECT TOP 1 f.rate_to_eur FROM stg.fx_rates f
        WHERE f.currency = t.currency AND f.rate_date <= t.txn_date
        ORDER BY f.rate_date DESC, f._row_seq DESC
    ) fx
    WHERE t.txn_date >= @YearStart AND t.txn_date <= @AsOfDate
    GROUP BY p.broker_code, p.lob_code
),
pay AS (
    SELECT p.broker_code, p.lob_code, c.reported_date, ISNULL(cp.amount, 0) AS amount
    FROM stg.claim_payments cp
    INNER JOIN stg.claims c ON c.claim_id = cp.claim_id
    INNER JOIN pol p ON p.policy_id = c.policy_id
    WHERE cp.payment_date >= @YearStart AND cp.payment_date <= @AsOfDate
),
paid_fixed AS (
    SELECT broker_code, lob_code, SUM(amount) AS amt FROM pay GROUP BY broker_code, lob_code
),
paid_bug AS (
    SELECT broker_code, lob_code, SUM(amount) AS amt FROM pay
    WHERE reported_date >= @YearStart AND reported_date <= @AsOfDate
    GROUP BY broker_code, lob_code
),
keys AS (
    SELECT broker_code, lob_code FROM pol
    WHERE inception_date <= @AsOfDate AND expiry_date >= @AsOfDate
      AND (cancellation_date IS NULL OR cancellation_date > @AsOfDate)
    UNION SELECT broker_code, lob_code FROM gwp
    UNION SELECT p.broker_code, p.lob_code FROM stg.claims c INNER JOIN pol p ON p.policy_id = c.policy_id
          WHERE c.reported_date >= @YearStart AND c.reported_date <= @AsOfDate
    UNION SELECT broker_code, lob_code FROM paid_fixed
),
cmp AS (
    SELECT k.broker_code, k.lob_code,
           ISNULL(f.amt, 0) AS paid_fixed,
           ISNULL(b.amt, 0) AS paid_bug,
           CAST(SUM(ISNULL(f.amt, 0)) OVER (PARTITION BY k.broker_code)
                / NULLIF(SUM(ISNULL(g.gwp_eur, 0)) OVER (PARTITION BY k.broker_code), 0) AS DECIMAL(12,4)) AS ratio_fixed,
           CAST(SUM(ISNULL(b.amt, 0)) OVER (PARTITION BY k.broker_code)
                / NULLIF(SUM(ISNULL(g.gwp_eur, 0)) OVER (PARTITION BY k.broker_code), 0) AS DECIMAL(12,4)) AS ratio_bug
    FROM keys k
    LEFT JOIN paid_fixed f ON f.broker_code = k.broker_code AND f.lob_code = k.lob_code
    LEFT JOIN paid_bug b   ON b.broker_code = k.broker_code AND b.lob_code = k.lob_code
    LEFT JOIN gwp g        ON g.broker_code = k.broker_code AND g.lob_code = k.lob_code
)
SELECT 'X1_bug' AS check_id, COUNT(*) AS affected
FROM cmp
WHERE paid_fixed <> paid_bug
   OR ISNULL(ratio_fixed, -1) <> ISNULL(ratio_bug, -1);
GO
-- check: X2_bug
-- Watchlist rows that appear, disappear or change incurred amounts / category when the
-- outstanding reserve sums the latest row of each reserve type instead of the latest row overall.
DECLARE @AsOfDate DATE = '2025-12-31';
DECLARE @PriorDate DATE = DATEADD(DAY, -90, @AsOfDate);
WITH clm AS (
    SELECT c.claim_id FROM stg.claims c
    WHERE c.reported_date <= @AsOfDate AND (c.status <> 'CLOSED' OR c.closed_date > @PriorDate)
),
paid AS (
    SELECT p.claim_id,
           SUM(ISNULL(p.amount, 0)) AS paid_now,
           SUM(CASE WHEN p.payment_date <= @PriorDate THEN ISNULL(p.amount, 0) ELSE 0 END) AS paid_prior
    FROM stg.claim_payments p
    WHERE p.payment_date <= @AsOfDate
    GROUP BY p.claim_id
),
res AS (
    SELECT r.claim_id, d.period, r.reserve_amount,
           ROW_NUMBER() OVER (PARTITION BY d.period, r.claim_id, r.reserve_type
                              ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn_fixed,
           ROW_NUMBER() OVER (PARTITION BY d.period, r.claim_id
                              ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn_bug
    FROM stg.claim_reserves r
    CROSS APPLY (VALUES ('NOW', @AsOfDate), ('PRIOR', @PriorDate)) d (period, as_at)
    WHERE r.reserve_date <= d.as_at
),
os AS (
    SELECT claim_id,
           SUM(CASE WHEN period = 'NOW'   AND rn_fixed = 1 THEN reserve_amount ELSE 0 END) AS now_fixed,
           SUM(CASE WHEN period = 'PRIOR' AND rn_fixed = 1 THEN reserve_amount ELSE 0 END) AS prior_fixed,
           SUM(CASE WHEN period = 'NOW'   AND rn_bug = 1   THEN reserve_amount ELSE 0 END) AS now_bug,
           SUM(CASE WHEN period = 'PRIOR' AND rn_bug = 1   THEN reserve_amount ELSE 0 END) AS prior_bug
    FROM res
    GROUP BY claim_id
),
inc AS (
    SELECT c.claim_id,
           ISNULL(p.paid_now, 0) + ISNULL(o.now_fixed, 0)     AS now_fixed,
           ISNULL(p.paid_prior, 0) + ISNULL(o.prior_fixed, 0) AS prior_fixed,
           ISNULL(p.paid_now, 0) + ISNULL(o.now_bug, 0)       AS now_bug,
           ISNULL(p.paid_prior, 0) + ISNULL(o.prior_bug, 0)   AS prior_bug
    FROM clm c
    LEFT JOIN paid p ON p.claim_id = c.claim_id
    LEFT JOIN os o   ON o.claim_id = c.claim_id
)
SELECT 'X2_bug' AS check_id, COUNT(*) AS affected
FROM inc
WHERE (now_fixed >= 25000 OR now_bug >= 25000)
  AND (now_fixed <> now_bug OR prior_fixed <> prior_bug);
GO
