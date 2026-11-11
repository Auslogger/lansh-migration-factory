/*==============================================================================
  Job      : rpt.usp_claim_aging
  Purpose  : Ageing of the open claims book for claims operations: each open or
             re-opened claim is aged on the days since its last activity (its
             last payment up to the reporting date, or the date it was notified
             when nothing has been paid yet). Feeds the weekly diary review.
  Output   : rpt.claim_aging (truncated and reloaded on every run)
  Author   : BMcG

  Change log
    2013-10-07  BMcG  Initial version
    2014-05-19  BMcG  weeks_open added for the handler workload report (CR-0317)
    2016-02-08  RF    Re-opened claims aged as well (CR-0852)
    2017-09-25  RF    Payments staged in #pay first; nightly run down from
                      40 min to 2 min (INC-1904)
    2019-04-01  NK    Payments dated after the reporting date ignored (CR-1488)
    2020-11-16  NK    Ageing bands added for the claims MI pack (CR-1951)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claim_aging', N'U') IS NULL
CREATE TABLE rpt.claim_aging (
    claim_id             INT            NOT NULL,
    claim_number         VARCHAR(20)    NOT NULL,
    lob_code             VARCHAR(5)     NOT NULL,
    reported_date        DATE           NOT NULL,
    n_payments           INT            NOT NULL,
    total_paid           DECIMAL(14,2)  NULL,
    last_payment_date    DATE           NULL,
    last_activity_date   DATE           NOT NULL,
    days_since_activity  INT            NOT NULL,
    weeks_open           INT            NOT NULL,
    aging_band           VARCHAR(10)    NOT NULL,
    as_of_date           DATE           NOT NULL,
    CONSTRAINT pk_claim_aging PRIMARY KEY CLUSTERED (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_claim_aging
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'rpt.usp_claim_aging',
            @rows      INT,
            @claim_id  INT,
            @reported  DATE,
            @pay_date  DATE,
            @amount    DECIMAL(12,2),
            @n_pay     INT,
            @total     DECIMAL(14,2),
            @last_pay  DATE,
            @last_act  DATE,
            @days      INT,
            @weeks     INT,
            @band      VARCHAR(10),
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        IF OBJECT_ID('tempdb..#open_claims') IS NOT NULL DROP TABLE #open_claims;
        IF OBJECT_ID('tempdb..#pay') IS NOT NULL DROP TABLE #pay;

        -- 1. open book: open and re-opened claims notified by the reporting date
        SELECT c.claim_id,
               c.claim_number,
               UPPER(RTRIM(c.lob_code)) AS lob_code,
               c.reported_date
        INTO   #open_claims
        FROM   stg.claims AS c WITH (NOLOCK)
        WHERE  c.status IN ('OPEN', 'REOPENED')
          AND  c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'open claims',
             @status = 'INFO', @rows_affected = @rows;

        -- 2. payments on those claims up to the reporting date
        SELECT p.claim_id, p.payment_id, p.payment_date, p.amount
        INTO   #pay
        FROM   stg.claim_payments AS p WITH (NOLOCK)
        INNER JOIN #open_claims AS o ON o.claim_id = p.claim_id
        WHERE  p.payment_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        CREATE CLUSTERED INDEX ix_pay ON #pay (claim_id, payment_date, payment_id);
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'payments',
             @status = 'INFO', @rows_affected = @rows;

        CREATE TABLE #aging (
            claim_id             INT            NOT NULL PRIMARY KEY,
            n_payments           INT            NOT NULL,
            total_paid           DECIMAL(14,2)  NULL,
            last_payment_date    DATE           NULL,
            last_activity_date   DATE           NOT NULL,
            days_since_activity  INT            NOT NULL,
            weeks_open           INT            NOT NULL,
            aging_band           VARCHAR(10)    NOT NULL
        );

        -- 3. age each claim on its payment history
        DECLARE claim_cur CURSOR LOCAL FAST_FORWARD FOR
            SELECT claim_id, reported_date
            FROM   #open_claims
            ORDER  BY claim_id;

        OPEN claim_cur;
        FETCH NEXT FROM claim_cur INTO @claim_id, @reported;

        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @n_pay    = 0;
            SET @total    = 0;
            SET @last_pay = NULL;

            DECLARE pay_cur CURSOR LOCAL FAST_FORWARD FOR
                SELECT payment_date, amount
                FROM   #pay
                WHERE  claim_id = @claim_id
                ORDER  BY payment_date, payment_id;

            OPEN pay_cur;
            FETCH NEXT FROM pay_cur INTO @pay_date, @amount;

            WHILE @@FETCH_STATUS = 0
            BEGIN
                SET @n_pay    = @n_pay + 1;
                SET @total    = @total + @amount;
                SET @last_pay = @pay_date;

                FETCH NEXT FROM pay_cur INTO @pay_date, @amount;
            END

            CLOSE pay_cur;
            DEALLOCATE pay_cur;

            -- last activity: the last payment, or notification if nothing paid yet
            SET @last_act = ISNULL(@last_pay, @reported);
            SET @days     = DATEDIFF(DAY, @last_act, @AsOfDate);
            SET @weeks    = DATEDIFF(WEEK, @reported, @AsOfDate);

            -- ageing band for the MI pack
            SET @band = CASE WHEN @days < 30 THEN '0-29'
                             WHEN @days BETWEEN 31 AND 60 THEN '31-60'
                             WHEN @days > 60 THEN '61+'
                             ELSE 'UNKNOWN'
                        END;

            INSERT INTO #aging (claim_id, n_payments, total_paid, last_payment_date,
                                last_activity_date, days_since_activity, weeks_open, aging_band)
            VALUES (@claim_id, @n_pay, @total, @last_pay, @last_act, @days, @weeks, @band);

            FETCH NEXT FROM claim_cur INTO @claim_id, @reported;
        END

        CLOSE claim_cur;
        DEALLOCATE claim_cur;

        SELECT @rows = COUNT(*) FROM #aging;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claim loop',
             @status = 'INFO', @rows_affected = @rows;

        -- 4. reload the report table
        TRUNCATE TABLE rpt.claim_aging;

        INSERT INTO rpt.claim_aging (claim_id, claim_number, lob_code, reported_date,
               n_payments, total_paid, last_payment_date, last_activity_date,
               days_since_activity, weeks_open, aging_band, as_of_date)
        SELECT o.claim_id, o.claim_number, o.lob_code, o.reported_date,
               a.n_payments, a.total_paid, a.last_payment_date, a.last_activity_date,
               a.days_since_activity, a.weeks_open, a.aging_band, @AsOfDate
        FROM   #aging AS a
        INNER JOIN #open_claims AS o ON o.claim_id = a.claim_id;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'load rpt.claim_aging',
             @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        SELECT @err_msg = ERROR_MESSAGE(), @err_no = ERROR_NUMBER();
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claim aging',
             @status = 'FAILED', @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH
END;
GO
