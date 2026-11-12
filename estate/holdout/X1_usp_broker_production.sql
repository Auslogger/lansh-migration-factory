/*==============================================================================
  Job      : rpt.usp_broker_production
  Purpose  : Broker production report for distribution MI. One row per broker
             and line of business as at @AsOfDate: policies in force, gross
             written premium in EUR booked in the calendar year, claims notified
             and claims paid in the year, and a review flag for brokers whose
             paid-to-written ratio for the year is above 0.75.
  Author   : PdeB
  Change log
    2014-02-10  PdeB  Initial version (CR-0412)
    2015-09-03  PdeB  GBP/USD premium converted to EUR at the ECB rate (CR-0688)
    2017-11-20  SOK   Direct business reported under broker code DIRECT (CR-1047)
    2019-05-14  AMcG  Inactive brokers kept when they still have business (INC-2231)
    2021-03-08  SOK   Paid-to-written review flag for distribution (CR-1590)
    2022-06-27  AMcG  Broker codes trimmed and upper-cased (INC-3118)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.broker_production', N'U') IS NULL
CREATE TABLE rpt.broker_production (
    as_of_date         DATE           NOT NULL,
    broker_code        VARCHAR(10)    NOT NULL,
    broker_name        NVARCHAR(80)   NULL,
    broker_status      VARCHAR(10)    NULL,
    lob_code           VARCHAR(5)     NOT NULL,
    policies_in_force  INT            NOT NULL,
    gwp_eur            DECIMAL(14,2)  NOT NULL,
    claims_notified    INT            NOT NULL,
    claims_paid_eur    DECIMAL(14,2)  NOT NULL,
    paid_to_written    DECIMAL(12,4)  NULL,
    review_flag        CHAR(1)        NOT NULL
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_broker_production
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job       VARCHAR(128) = 'rpt.usp_broker_production';
    DECLARE @YearStart DATE         = DATEFROMPARTS(YEAR(@AsOfDate), 1, 1);
    DECLARE @rows      INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'start', @status = 'STARTED';

        -- policy attributes from the latest snapshot on or before the as-of date
        SELECT x.policy_id, x.broker_code, x.lob_code, x.inception_date, x.expiry_date, x.cancellation_date
        INTO #pol
        FROM (
            SELECT s.policy_id,
                   ISNULL(UPPER(LTRIM(RTRIM(s.broker_code))), 'DIRECT') AS broker_code,
                   UPPER(RTRIM(p.lob_code)) AS lob_code,
                   s.inception_date, s.expiry_date, s.cancellation_date,
                   ROW_NUMBER() OVER (PARTITION BY s.policy_id
                                      ORDER BY s.snapshot_date DESC, s._row_seq DESC) AS rn
            FROM stg.policy_snapshots s WITH (NOLOCK)
            INNER JOIN stg.products p WITH (NOLOCK) ON p.product_code = s.product_code
            WHERE s.snapshot_date <= @AsOfDate
        ) x
        WHERE x.rn = 1;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'policies', @status = 'INFO', @rows_affected = @rows;

        -- policies in force on the as-of date
        SELECT p.broker_code, p.lob_code, COUNT(*) AS policies_in_force
        INTO #inforce
        FROM #pol p
        WHERE p.inception_date <= @AsOfDate
          AND p.expiry_date >= @AsOfDate
          AND (p.cancellation_date IS NULL OR p.cancellation_date > @AsOfDate)
        GROUP BY p.broker_code, p.lob_code;

        -- premium booked in the year, at the latest rate published on or before the booking date
        SELECT p.broker_code, p.lob_code,
               SUM(t.amount * CASE WHEN t.currency = 'EUR' THEN 1 ELSE fx.rate_to_eur END) AS gwp_eur
        INTO #gwp
        FROM stg.premium_transactions t WITH (NOLOCK)
        INNER JOIN #pol p ON p.policy_id = t.policy_id
        OUTER APPLY (
            SELECT TOP 1 f.rate_to_eur
            FROM stg.fx_rates f WITH (NOLOCK)
            WHERE f.currency = t.currency
              AND f.rate_date <= t.txn_date
            ORDER BY f.rate_date DESC, f._row_seq DESC
        ) fx
        WHERE t.txn_date >= @YearStart
          AND t.txn_date <= @AsOfDate
        GROUP BY p.broker_code, p.lob_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'premium', @status = 'INFO', @rows_affected = @rows;

        -- claims notified in the year
        SELECT c.claim_id, p.broker_code, p.lob_code
        INTO #clm
        FROM stg.claims c WITH (NOLOCK)
        INNER JOIN #pol p ON p.policy_id = c.policy_id
        WHERE c.reported_date >= @YearStart
          AND c.reported_date <= @AsOfDate;

        SELECT c.broker_code, c.lob_code, COUNT(*) AS claims_notified
        INTO #notified
        FROM #clm c
        GROUP BY c.broker_code, c.lob_code;

        -- claims paid in the year, recoveries netted off, unkeyed amounts ignored
        SELECT c.broker_code, c.lob_code, SUM(ISNULL(cp.amount, 0)) AS claims_paid_eur
        INTO #paid
        FROM stg.claim_payments cp WITH (NOLOCK)
        INNER JOIN #clm c ON c.claim_id = cp.claim_id
        WHERE cp.payment_date >= @YearStart
          AND cp.payment_date <= @AsOfDate
        GROUP BY c.broker_code, c.lob_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'claims', @status = 'INFO', @rows_affected = @rows;

        SELECT broker_code, lob_code INTO #keys FROM #inforce
        UNION SELECT broker_code, lob_code FROM #gwp
        UNION SELECT broker_code, lob_code FROM #notified
        UNION SELECT broker_code, lob_code FROM #paid;

        -- paid-to-written ratio over all lines of the broker
        SELECT k.broker_code,
               CAST(SUM(ISNULL(pd.claims_paid_eur, 0)) / NULLIF(SUM(ISNULL(g.gwp_eur, 0)), 0) AS DECIMAL(12,4)) AS paid_to_written
        INTO #ratio
        FROM #keys k
        LEFT JOIN #gwp g   ON g.broker_code = k.broker_code AND g.lob_code = k.lob_code
        LEFT JOIN #paid pd ON pd.broker_code = k.broker_code AND pd.lob_code = k.lob_code
        GROUP BY k.broker_code;

        TRUNCATE TABLE rpt.broker_production;

        INSERT INTO rpt.broker_production
            (as_of_date, broker_code, broker_name, broker_status, lob_code, policies_in_force,
             gwp_eur, claims_notified, claims_paid_eur, paid_to_written, review_flag)
        SELECT @AsOfDate,
               k.broker_code,
               b.broker_name,
               UPPER(RTRIM(b.status)),
               k.lob_code,
               ISNULL(i.policies_in_force, 0),
               CAST(ISNULL(g.gwp_eur, 0) AS DECIMAL(14,2)),
               ISNULL(n.claims_notified, 0),
               CAST(ISNULL(pd.claims_paid_eur, 0) AS DECIMAL(14,2)),
               r.paid_to_written,
               CASE WHEN r.paid_to_written > 0.75 THEN 'Y' ELSE 'N' END
        FROM #keys k
        LEFT JOIN stg.brokers b WITH (NOLOCK) ON b.broker_code = k.broker_code
        LEFT JOIN #inforce i  ON i.broker_code = k.broker_code AND i.lob_code = k.lob_code
        LEFT JOIN #gwp g      ON g.broker_code = k.broker_code AND g.lob_code = k.lob_code
        LEFT JOIN #notified n ON n.broker_code = k.broker_code AND n.lob_code = k.lob_code
        LEFT JOIN #paid pd    ON pd.broker_code = k.broker_code AND pd.lob_code = k.lob_code
        LEFT JOIN #ratio r    ON r.broker_code = k.broker_code;
        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job, @step_name = 'load rpt.broker_production', @status = 'INFO', @rows_affected = @rows;

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
