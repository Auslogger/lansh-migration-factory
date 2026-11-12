# Labels for the holdout jobs

Line numbers refer to the deployment scripts as delivered. Row counts are for HoldoutScratch
with `@AsOfDate = '2025-12-31'`.

## X1: `X1_usp_broker_production.sql` (rpt.usp_broker_production -> rpt.broker_production)

### (a) Planted bug

- **What the code does.** Lines 94-99 build `#clm` from claims **notified in the as-of year**
  (`reported_date` between `@YearStart` and `@AsOfDate`) so that they can be counted. The
  claims-paid step at lines 107-113 then reuses that temp table: line 110
  `INNER JOIN #clm c ON c.claim_id = cp.claim_id`. So "claims paid in the year" only counts
  payments on claims that were *also notified* in the year.
- **What was intended.** The brief asks for the claims paid in the year: every payment with
  `payment_date` in the as-of year, whichever year the claim was notified in. Line 110 should
  join the payments to `stg.claims` and `#pol` (all claims), not to the year-filtered `#clm`.
  Payments in 2025 on claims notified in 2019-2024 are silently dropped.
- **Lines.** 110 (the join), with the filter it inherits at lines 98-99.
- **Rows affected.** 123 of the 127 output rows:
  - `claims_paid_eur` is understated on 96 rows;
  - `paid_to_written` (a broker-level ratio, line 124) changes on 123 rows, i.e. every row of
    41 of the 45 broker codes, including DIRECT (for example BRK031 0.8651 instead of 2.1961,
    BRK004 1.1223 instead of 2.7491);
  - `review_flag` does not change on this data (every affected broker is above 0.75 either way);
  - no output row appears or disappears (every broker/LOB with 2025 payments also has 2025
    premium or in-force policies).
- `checks.sql` batch `X1_bug` returns `affected = 123`.

### (b) SQL Server behaviours the code relies on

| Lines | Behaviour | Why another engine might differ |
|---|---|---|
| 58 | `p.product_code = s.product_code` matches `'hom-bc'`, `'HOM-BC '` and `'HOM-BC'` because the database collation `SQL_Latin1_General_CP1_CI_AS` is case-insensitive and `=` ignores trailing spaces (ANSI padding). 634 snapshot rows carry lower-case or space-padded product codes. | A case-sensitive collation, or an engine that compares VARCHAR without padding (PostgreSQL `text`/`varchar`, SQLite, Spark), would drop those policies from `#pol` and from every measure. |
| 148 | `LEFT JOIN stg.brokers b ON b.broker_code = k.broker_code` compares `CHAR(6)` `'BK102 '` (space-padded) with the trimmed `VARCHAR` `'BK102'`; trailing spaces are ignored. Also case-insensitive. | An engine that keeps CHAR padding in comparisons with VARCHAR, or is case-sensitive, would leave `broker_name` / `broker_status` NULL for the 5-character BK1xx codes. |
| 117-120 | `UNION` de-duplicates (broker_code, lob_code) keys under the case-insensitive, pad-insensitive collation. Keys are already upper-cased and trimmed at lines 52-53, so the result does not depend on it. | Same collation caveat; also `SELECT ... INTO` from a `UNION` is T-SQL syntax (`CREATE TABLE AS` elsewhere). |
| 52 | `ISNULL(x, 'DIRECT')` takes the data type of the first argument (`VARCHAR(10)`); `'DIRECT'` fits. `UPPER(LTRIM(RTRIM(...)))` for trimming (no `TRIM` needed). | `COALESCE` / `NVL` type the result differently; with a shorter first argument `ISNULL` would truncate in SQL Server only. |
| 53, 139 | `UPPER(RTRIM(...))` normalises `lob_code` and broker `status`. | Function names differ (`TRIM`, `BTRIM`); `RTRIM` on CHAR differs between engines. |
| 41 | `DATEFROMPARTS(YEAR(@AsOfDate), 1, 1)` for 1 January of the as-of year. | T-SQL-specific (`MAKE_DATE`, `DATE_TRUNC('year', ...)`, `TRUNC(d, 'YYYY')` elsewhere). |
| 55-56 | `ROW_NUMBER() OVER (PARTITION BY policy_id ORDER BY snapshot_date DESC, _row_seq DESC)` picks the latest snapshot per policy; `_row_seq` is the unique tiebreaker. | Window functions are portable, but NULL ordering for DESC (NULLs last in SQL Server) differs in other engines; not hit here (columns are NOT NULL). |
| 80-86 | `OUTER APPLY (SELECT TOP 1 ... ORDER BY f.rate_date DESC, f._row_seq DESC)` picks the latest published rate on or before the booking date, taking the later revision (`ECB-REV`, higher `_row_seq`) when a date has two rows. 182 of the 576 non-EUR 2025 transactions fall on a date with no rate and use the previous business day. | `OUTER APPLY` and `TOP` are T-SQL (`LEFT JOIN LATERAL ... LIMIT 1` elsewhere). If no rate exists, `OUTER APPLY` yields NULL and the transaction silently drops out of `SUM` (line 76). |
| 76, 83 | `t.currency = 'EUR'` and `f.currency = t.currency` on `CHAR(3)` columns (fixed width, pad-insensitive compare). | CHAR semantics vary by engine. |
| 76 | `DECIMAL(12,2) * DECIMAL(18,8)` keeps exact decimal precision; the `CASE` mixing integer `1` with `DECIMAL(18,8)` returns DECIMAL by type precedence; `SUM` of DECIMAL returns `DECIMAL(38,s)`. | Other engines apply different precision/scale rules or may promote to float. |
| 124 | `SUM(...) / NULLIF(SUM(...), 0)`: DECIMAL / DECIMAL with SQL Server's result-scale rules (minimum scale 6 when precision overflows), then `CAST(... AS DECIMAL(12,4))`, which **rounds** (not truncates). `NULLIF` turns a zero denominator into NULL (BRK032 has no premium: ratio NULL). | Result scale and rounding-on-cast differ between engines; some raise on division by zero rather than needing `NULLIF`. |
| 142, 144 | `CAST(... AS DECIMAL(14,2))` rounds half away from zero. | Rounding mode differs (e.g. banker's rounding). |
| 146 | `CASE WHEN r.paid_to_written > 0.75 ...` : a NULL ratio is UNKNOWN and falls to `'N'` (BRK032). | Three-valued logic is standard, but this relies on it. |
| 69-71 | `cancellation_date IS NULL OR cancellation_date > @AsOfDate`: NULL handling for in-force; DATE comparisons. | Standard, but relies on NULL semantics. |
| 107 | `SUM(ISNULL(cp.amount, 0))`: unkeyed (NULL) payment amounts count as nil (SUM would ignore them anyway). | `ISNULL` is T-SQL (`COALESCE`). |
| 49, 67, 77, 95, 102, 108, 117, 125 | `SELECT ... INTO #temp` creates session temp tables. | T-SQL-specific. |
| 57, 58, 78, 82, 96, 109, 148 | `WITH (NOLOCK)` table hints (read uncommitted). | T-SQL-specific; ignored or a syntax error elsewhere. |
| 62, 90, 114, 154 | `@@ROWCOUNT` after each step for logging. | T-SQL-specific. |
| 131 | `TRUNCATE TABLE` for the full refresh. | Transactional behaviour of TRUNCATE varies. |
| 159-164 | `BEGIN TRY / BEGIN CATCH`, `ERROR_MESSAGE()`, `ERROR_NUMBER()`, `THROW;`. | T-SQL error handling. |

## X2: `X2_usp_large_loss_watchlist.sql` (rpt.usp_large_loss_watchlist -> rpt.large_loss_watchlist)

### (a) Planted bug

- **What the code does.** Lines 75-82 number the reserve rows as at each date with
  `ROW_NUMBER() OVER (PARTITION BY d.period, r.claim_id ORDER BY r.reserve_date DESC, r.reserve_id DESC)`
  (line 76) and lines 84-90 keep `rn = 1`. The partition omits `reserve_type`, so only the
  single most recent reserve row of the claim (INDEMNITY *or* EXPENSE) is kept, and the
  outstanding balance of the other reserve type is dropped.
- **What was intended.** The brief defines incurred as paid to date plus "the latest outstanding
  reserve of **each reserve type**": line 76 should read
  `PARTITION BY d.period, r.claim_id, r.reserve_type`, giving one row per type, summed at
  lines 85-86.
- **Lines.** 76 (the partition), consumed at 84-90 and 104-106.
- **Rows affected.** 122 claims:
  - 44 claims that are large losses (incurred >= EUR 25,000) are missing from the output
    (the correct watchlist has 298 rows, the job writes 254);
  - 78 of the 254 output rows carry a wrong `outstanding_reserve` / `incurred_amount` and/or
    `incurred_90d_ago`, and hence a wrong `movement_90d` and possibly `watch_category`.
- `checks.sql` batch `X2_bug` returns `affected = 122`.

### (b) SQL Server behaviours the code relies on

| Lines | Behaviour | Why another engine might differ |
|---|---|---|
| 59 | `c.status <> 'CLOSED'` is false for `'Closed'` and `'CLOSED '` because the collation is case-insensitive and comparison ignores trailing spaces; status is only normalised for output (line 54). 282 claims carry a lower/mixed-case or padded CLOSED status. | On a case-sensitive or pad-sensitive engine those claims would pass the filter as "not closed" and long-closed large losses would be listed. |
| 53-54 | `UPPER(LTRIM(RTRIM(...)))` normalises `lob_code` and `status` for output. | Function names differ (`TRIM`, `BTRIM`). |
| 45 | `DATEADD(DAY, -90, @AsOfDate)` for the 90-day look-back (2025-10-02). | T-SQL-specific (`@d - INTERVAL '90 days'`, `DATE_SUB`, `date_add`). |
| 127 | `DATEDIFF(DAY, last_activity_date, @AsOfDate)` counts day boundaries; NULL when the claim has no payment or reserve activity. | T-SQL-specific argument order/semantics (`DATEDIFF(end, start)` in MySQL, date subtraction in PostgreSQL/Oracle). |
| 108-109 | `ISNULL(p.last_payment_date, '19000101')`: the string literal is implicitly converted to `DATE` (ISNULL takes the first argument's type) to find the later of two possibly-NULL dates. `CASE` without ELSE returns NULL when both are NULL. | Implicit string-to-date conversion and the `YYYYMMDD` literal format are engine-specific; `GREATEST` (which SQL Server 2022 also has) treats NULLs differently across engines. |
| 81 | `CROSS APPLY (VALUES ('NOW', @AsOfDate), ('PRIOR', @PriorDate)) d (period, as_at)` duplicates each reserve row for the two as-at dates. | `CROSS APPLY` with a table value constructor is T-SQL (`CROSS JOIN LATERAL` / `CROSS JOIN (VALUES ...)` elsewhere). |
| 76-77 | `ROW_NUMBER()` with `reserve_id DESC` as the unique tiebreaker for same-day reserve entries (1,302 rows share a claim/type/date with another row). | Portable, but without the tiebreaker the pick would be engine- and plan-dependent. |
| 85-86, 89 | `period = 'NOW'` compares literal VARCHAR(5) values produced by `VALUES`; the column type is inferred from the longest literal. | Type inference for `VALUES` literals differs (CHAR vs VARCHAR padding). |
| 65-66 | `SUM(ISNULL(p.amount, 0))`: NULL (unkeyed) payment amounts count as nil. | `ISNULL` is T-SQL. |
| 67 | `MAX(CASE WHEN p.amount IS NOT NULL THEN p.payment_date END)`: CASE without ELSE yields NULL and `MAX` ignores NULLs. | Standard, but relies on aggregate NULL handling. |
| 103-107 | `ISNULL(..., 0)` after LEFT JOINs so claims without payments or reserves still get a numeric incurred; DECIMAL + DECIMAL keeps scale 2. | `ISNULL` is T-SQL; decimal result typing differs. |
| 124-125 | Results are implicitly converted to `DECIMAL(14,2)` on insert. | Implicit narrowing rules (error vs round) differ. |
| 128-131 | `incurred_90d_ago * 1.10` / `* 0.90`: numeric literals are DECIMAL in SQL Server, so the comparison is exact decimal arithmetic. | Some engines treat `1.10` as floating point. |
| 56, 68, 78, 87, 96, 110 | `SELECT ... INTO #temp` session temp tables. | T-SQL-specific. |
| 57, 69, 79, 97 | `WITH (NOLOCK)` table hints. | T-SQL-specific. |
| 60, 135 | `@@ROWCOUNT` for logging. | T-SQL-specific. |
| 116 | `TRUNCATE TABLE` for the full refresh. | Transactional behaviour varies. |
| 140-145 | `BEGIN TRY / BEGIN CATCH`, `ERROR_MESSAGE()`, `ERROR_NUMBER()`, `THROW;`. | T-SQL error handling. |
