/*==============================================================================
  Job      : rpt.usp_large_loss_watchlist
  Purpose  : Large-loss watchlist for the claims committee. Every claim with an
             incurred amount (paid to date plus outstanding case reserve) of at
             least EUR 25,000 as at @AsOfDate, compared with 90 days earlier and
             given a watch category (NEW, DETERIORATING, IMPROVING, STABLE).
  Author   : RBy
  Change log
    2013-05-22  RBy   Initial version (CR-0301)
    2015-01-19  RBy   Expense reserves included in incurred (CR-0577)
    2016-10-04  DMcC  Claims closed more than 90 days ago dropped (CR-0912)
    2018-07-30  DMcC  Reserve changes and days since last activity added (CR-1188)
    2020-02-11  NOF   Threshold raised from EUR 20,000 to EUR 25,000 (CR-1402)
    2022-09-05  NOF   Status and LOB codes trimmed and upper-cased (INC-3204)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.large_loss_watchlist', N'U') IS NULL
CREATE TABLE rpt.large_loss_watchlist (
    as_of_date                DATE           NOT NULL,
    claim_id                  INT            NOT NULL,
    claim_number              VARCHAR(20)    NOT NULL,
    policy_id                 INT            NOT NULL,
    lob_code                  VARCHAR(5)     NOT NULL,
    claim_status              VARCHAR(12)    NOT NULL,
    reported_date             DATE           NOT NULL,
    closed_date               DATE           NULL,
    paid_to_date              DECIMAL(14,2)  NOT NULL,
    outstanding_reserve       DECIMAL(14,2)  NOT NULL,
    incurred_amount           DECIMAL(14,2)  NOT NULL,
    incurred_90d_ago          DECIMAL(14,2)  NOT NULL,
    movement_90d              DECIMAL(14,2)  NOT NULL,
    reserve_changes_90d       INT            NOT NULL,
    days_since_last_activity  INT            NULL,
    watch_category            VARCHAR(15)    NOT NULL
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_large_loss_watchlist
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job       VARCHAR(128) = 'rpt.usp_large_loss_watchlist';
    DECLARE @PriorDate DATE         = DATEADD(DAY, -90, @AsOfDate);
    DECLARE @rows      INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'start', @status = 'STARTED';

        -- open and reopened claims, plus claims closed in the last 90 days
        SELECT c.claim_id, c.claim_number, c.policy_id,
               UPPER(LTRIM(RTRIM(c.lob_code))) AS lob_code,
               UPPER(LTRIM(RTRIM(c.status)))   AS claim_status,
               c.reported_date, c.closed_date
        INTO #clm
        FROM stg.claims c WITH (NOLOCK)
        WHERE c.reported_date <= @AsOfDate
          AND (c.status <> 'CLOSED' OR c.closed_date > @PriorDate);
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'claims', @status = 'INFO', @rows_affected = @rows;

        -- payments to date and 90 days ago; unkeyed amounts count as nil
        SELECT p.claim_id,
               SUM(ISNULL(p.amount, 0)) AS paid_now,
               SUM(CASE WHEN p.payment_date <= @PriorDate THEN ISNULL(p.amount, 0) ELSE 0 END) AS paid_prior,
               MAX(CASE WHEN p.amount IS NOT NULL THEN p.payment_date END) AS last_payment_date
        INTO #paid
        FROM stg.claim_payments p WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = p.claim_id
        WHERE p.payment_date <= @AsOfDate
        GROUP BY p.claim_id;

        -- outstanding reserve as at today and 90 days ago
        SELECT r.claim_id, d.period, r.reserve_amount,
               ROW_NUMBER() OVER (PARTITION BY d.period, r.claim_id
                                  ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn
        INTO #res
        FROM stg.claim_reserves r WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = r.claim_id
        CROSS APPLY (VALUES ('NOW', @AsOfDate), ('PRIOR', @PriorDate)) d (period, as_at)
        WHERE r.reserve_date <= d.as_at;

        SELECT claim_id,
               SUM(CASE WHEN period = 'NOW'   THEN reserve_amount ELSE 0 END) AS os_now,
               SUM(CASE WHEN period = 'PRIOR' THEN reserve_amount ELSE 0 END) AS os_prior
        INTO #os
        FROM #res
        WHERE rn = 1
        GROUP BY claim_id;

        -- reserve activity
        SELECT r.claim_id,
               SUM(CASE WHEN r.reserve_date > @PriorDate THEN 1 ELSE 0 END) AS reserve_changes_90d,
               MAX(r.reserve_date) AS last_reserve_date
        INTO #ract
        FROM stg.claim_reserves r WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = r.claim_id
        WHERE r.reserve_date <= @AsOfDate
        GROUP BY r.claim_id;

        SELECT c.claim_id,
               ISNULL(p.paid_now, 0) AS paid_to_date,
               ISNULL(o.os_now, 0) AS outstanding_reserve,
               ISNULL(p.paid_now, 0) + ISNULL(o.os_now, 0) AS incurred_amount,
               ISNULL(p.paid_prior, 0) + ISNULL(o.os_prior, 0) AS incurred_90d_ago,
               ISNULL(a.reserve_changes_90d, 0) AS reserve_changes_90d,
               CASE WHEN ISNULL(p.last_payment_date, '19000101') > ISNULL(a.last_reserve_date, '19000101')
                    THEN p.last_payment_date ELSE a.last_reserve_date END AS last_activity_date
        INTO #inc
        FROM #clm c
        LEFT JOIN #paid p ON p.claim_id = c.claim_id
        LEFT JOIN #os o   ON o.claim_id = c.claim_id
        LEFT JOIN #ract a ON a.claim_id = c.claim_id;

        TRUNCATE TABLE rpt.large_loss_watchlist;

        INSERT INTO rpt.large_loss_watchlist
            (as_of_date, claim_id, claim_number, policy_id, lob_code, claim_status, reported_date,
             closed_date, paid_to_date, outstanding_reserve, incurred_amount, incurred_90d_ago,
             movement_90d, reserve_changes_90d, days_since_last_activity, watch_category)
        SELECT @AsOfDate, c.claim_id, c.claim_number, c.policy_id, c.lob_code, c.claim_status,
               c.reported_date, c.closed_date,
               i.paid_to_date, i.outstanding_reserve, i.incurred_amount, i.incurred_90d_ago,
               i.incurred_amount - i.incurred_90d_ago,
               i.reserve_changes_90d,
               DATEDIFF(DAY, i.last_activity_date, @AsOfDate),
               CASE WHEN i.incurred_90d_ago < 25000 THEN 'NEW'
                    WHEN i.incurred_amount > i.incurred_90d_ago * 1.10 THEN 'DETERIORATING'
                    WHEN i.incurred_amount < i.incurred_90d_ago * 0.90 THEN 'IMPROVING'
                    ELSE 'STABLE' END
        FROM #inc i
        INNER JOIN #clm c ON c.claim_id = i.claim_id
        WHERE i.incurred_amount >= 25000;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'load rpt.large_loss_watchlist', @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(4000) = ERROR_MESSAGE(), @err INT = ERROR_NUMBER();
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'end', @status = 'FAILED',
             @message = @msg, @error_number = @err;
        THROW;
    END CATCH
END;
GO
