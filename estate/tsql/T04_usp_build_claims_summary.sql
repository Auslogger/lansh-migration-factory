/*==============================================================================
  Job       rpt.usp_build_claims_summary
  Purpose   Open claims summary for the claims MI pack: one row per claim that
            is open or reopened at the reporting date, with paid, case reserve
            and incurred to date.
  Author    JMcK
  Run by    CLM_MI_NIGHTLY, after the claims extracts have loaded
  Output    rpt.claims_summary (full refresh)

  Change log
    2014-09-03  JMcK  Initial version (CR-0871)
    2015-02-17  JMcK  Policy number from the policy extract (CR-0933)
    2017-06-26  AOS   Claim reference for the handler worklist (CR-1188)
    2018-11-05  RD    Case reserves by type, current reserve and incurred (CR-1402)
    2020-03-30  AOS   Reopened claims reported with the open book (INC-2207)
    2021-08-12  RD    Days open and reported period for the ageing tabs (CR-1655)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claims_summary', N'U') IS NULL
CREATE TABLE rpt.claims_summary (
    claim_id           INT            NOT NULL,
    claim_number       VARCHAR(20)    NOT NULL,
    claim_ref          VARCHAR(40)    NULL,      -- LOB/claim number/handler
    policy_id          INT            NOT NULL,
    policy_number      VARCHAR(20)    NULL,
    lob_code           VARCHAR(5)     NOT NULL,
    status             VARCHAR(12)    NOT NULL,
    handler_code       VARCHAR(8)     NULL,
    loss_date          DATE           NOT NULL,
    loss_date_text     VARCHAR(10)    NOT NULL,  -- dd/mm/yyyy for the MI pack
    reported_date      DATE           NOT NULL,
    reported_period    CHAR(6)        NOT NULL,  -- yyyymm
    days_open          INT            NOT NULL,
    n_payments         INT            NOT NULL,
    total_paid         DECIMAL(14,2)  NOT NULL,
    indemnity_reserve  DECIMAL(14,2)  NOT NULL,
    expense_reserve    DECIMAL(14,2)  NOT NULL,
    current_reserve    DECIMAL(14,2)  NOT NULL,
    incurred           DECIMAL(14,2)  NOT NULL,
    as_of_date         DATE           NOT NULL,
    CONSTRAINT pk_rpt_claims_summary PRIMARY KEY (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_build_claims_summary
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name       VARCHAR(128) = 'rpt.usp_build_claims_summary',
            @rows           INT,
            @snapshot_date  DATE,
            @err_msg        NVARCHAR(4000),
            @err_no         INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Open book: claims open or reopened and notified by the reporting date */
        IF OBJECT_ID('tempdb..#open_claims') IS NOT NULL DROP TABLE #open_claims;

        SELECT  c.claim_id,
                c.claim_number,
                c.policy_id,
                UPPER(RTRIM(c.lob_code))    AS lob_code,
                c.status,
                c.handler_code,
                c.loss_date,
                c.reported_date
        INTO    #open_claims
        FROM    stg.claims c WITH (NOLOCK)
        WHERE   c.status IN ('OPEN', 'REOPENED')
          AND   c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'open claims', @status = 'INFO', @rows_affected = @rows;

        /* Case reserve per claim and reserve type: the latest entry on or before
           the reporting date (a second entry on the same day is a correction) */
        IF OBJECT_ID('tempdb..#reserve') IS NOT NULL DROP TABLE #reserve;

        SELECT  x.claim_id,
                x.reserve_type,
                x.reserve_amount
        INTO    #reserve
        FROM   (SELECT  r.claim_id,
                        r.reserve_type,
                        r.reserve_amount,
                        ROW_NUMBER() OVER (PARTITION BY r.claim_id, r.reserve_type
                                           ORDER BY r.reserve_date DESC, r.reserve_id DESC) AS rn
                FROM    stg.claim_reserves r WITH (NOLOCK)
                JOIN    #open_claims oc ON oc.claim_id = r.claim_id
                WHERE   r.reserve_date <= @AsOfDate) x
        WHERE   x.rn = 1;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'case reserves', @status = 'INFO', @rows_affected = @rows;

        /* Paid to date and case reserves per claim */
        IF OBJECT_ID('tempdb..#money') IS NOT NULL DROP TABLE #money;

        SELECT  oc.claim_id,
                COUNT(DISTINCT p.payment_id)    AS n_payments,
                ISNULL(SUM(p.amount), 0)        AS total_paid,
                ISNULL(MAX(CASE WHEN r.reserve_type = 'INDEMNITY' THEN r.reserve_amount END), 0) AS indemnity_reserve,
                ISNULL(MAX(CASE WHEN r.reserve_type = 'EXPENSE'   THEN r.reserve_amount END), 0) AS expense_reserve
        INTO    #money
        FROM    #open_claims oc
        LEFT JOIN stg.claim_payments p WITH (NOLOCK)
               ON p.claim_id = oc.claim_id
              AND p.payment_date <= @AsOfDate
        LEFT JOIN #reserve r
               ON r.claim_id = oc.claim_id
        GROUP BY oc.claim_id;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'paid and reserves', @status = 'INFO', @rows_affected = @rows;

        /* Policy number from the latest policy extract on or before the reporting date */
        SELECT  @snapshot_date = MAX(ps.snapshot_date)
        FROM    stg.policy_snapshots ps WITH (NOLOCK)
        WHERE   ps.snapshot_date <= @AsOfDate;

        BEGIN TRANSACTION;

        TRUNCATE TABLE rpt.claims_summary;

        INSERT INTO rpt.claims_summary
               (claim_id, claim_number, claim_ref, policy_id, policy_number, lob_code,
                status, handler_code, loss_date, loss_date_text, reported_date,
                reported_period, days_open, n_payments, total_paid, indemnity_reserve,
                expense_reserve, current_reserve, incurred, as_of_date)
        SELECT  oc.claim_id,
                oc.claim_number,
                oc.lob_code + '/' + oc.claim_number + '/' + oc.handler_code,
                oc.policy_id,
                ps.policy_number,
                oc.lob_code,
                oc.status,
                oc.handler_code,
                oc.loss_date,
                CONVERT(VARCHAR(10), oc.loss_date, 103),
                oc.reported_date,
                CONVERT(CHAR(6), oc.reported_date, 112),
                DATEDIFF(DAY, oc.reported_date, @AsOfDate),
                m.n_payments,
                m.total_paid,
                m.indemnity_reserve,
                m.expense_reserve,
                m.indemnity_reserve + m.expense_reserve,
                m.total_paid + m.indemnity_reserve + m.expense_reserve,
                @AsOfDate
        FROM    #open_claims oc
        JOIN    #money m
                ON m.claim_id = oc.claim_id
        LEFT JOIN stg.policy_snapshots ps WITH (NOLOCK)
               ON ps.policy_id = oc.policy_id
              AND ps.snapshot_date = @snapshot_date;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'rpt.claims_summary', @status = 'INFO', @rows_affected = @rows;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;

        SELECT  @err_msg = ERROR_MESSAGE(),
                @err_no  = ERROR_NUMBER();

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'end', @status = 'FAILED',
             @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH
END;
GO
