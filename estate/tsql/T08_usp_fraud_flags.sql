/*==============================================================================
  Job       rpt.usp_fraud_flags
  Purpose   Fraud indicators for the Special Investigations Unit (SIU): one row
            per claim notified in the twelve months to the reporting date, with
            the indicator flags, a score and a referral band for the SIU
            worklist and case tool.
  Author    MOB
  Run by    SIU_WEEKLY, after the claims and policy extracts and dw.dim_customer
            have loaded
  Output    rpt.claim_fraud_flags (full refresh)

  Change log
    2016-05-09  MOB   Initial version: early notification and new customer
                      indicators (CR-0954)
    2016-11-21  MOB   Motor claims: registration not in the Irish format
                      (CR-1012)
    2017-04-03  SB    Claim keyed against a policy from another line of
                      business (INC-1530)
    2018-08-27  SB    fraud_score and referral bands agreed with SIU (CR-1377)
    2019-02-11  NF    Policy dates from the latest policy extract on or before
                      the reporting date, not the old policy master (CR-1529)
    2020-06-15  NF    loss_day_key and reason text for the SIU case tool
                      (CR-1810)
    2021-10-04  SB    lob_code upper-cased for the SIU dashboard (INC-2389)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.claim_fraud_flags', N'U') IS NULL
CREATE TABLE rpt.claim_fraud_flags (
    claim_id                 INT            NOT NULL,
    claim_number             VARCHAR(20)    NOT NULL,
    policy_id                INT            NOT NULL,
    policy_number            VARCHAR(20)    NULL,
    customer_id              INT            NOT NULL,
    lob_code                 VARCHAR(5)     NOT NULL,
    loss_date                DATE           NOT NULL,
    reported_date            DATE           NOT NULL,
    early_notification_flag  INT            NOT NULL,
    invalid_reg_flag         INT            NOT NULL,
    new_customer_flag        INT            NOT NULL,
    lob_mismatch_flag        INT            NOT NULL,
    fraud_score              INT            NOT NULL,
    fraud_band               VARCHAR(6)     NOT NULL,  -- HIGH / MEDIUM / LOW
    loss_day_key             CHAR(8)        NOT NULL,  -- yyyymmdd, day key in the case tool
    reason_text              VARCHAR(100)   NOT NULL,
    as_of_date               DATE           NOT NULL,
    CONSTRAINT pk_rpt_claim_fraud_flags PRIMARY KEY (claim_id)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_fraud_flags
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name       VARCHAR(128) = 'rpt.usp_fraud_flags',
            @rows           INT,
            @snapshot_date  DATE,
            @err_msg        NVARCHAR(4000),
            @err_no         INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Policy details from the latest policy extract on or before the reporting date */
        SELECT  @snapshot_date = MAX(ps.snapshot_date)
        FROM    stg.policy_snapshots ps WITH (NOLOCK)
        WHERE   ps.snapshot_date <= @AsOfDate;

        /* 1. Claims notified in the twelve months to the reporting date, with the
              policy they were made under and when the policyholder became a customer */
        IF OBJECT_ID('tempdb..#claims') IS NOT NULL DROP TABLE #claims;

        SELECT  c.claim_id,
                c.claim_number,
                c.policy_id,
                c.customer_id,
                c.lob_code,
                c.loss_date,
                c.reported_date,
                p.policy_number,
                p.inception_date,
                p.expiry_date,
                p.vehicle_reg,
                dc.customer_since
        INTO    #claims
        FROM    stg.claims c WITH (NOLOCK)
        LEFT JOIN stg.policy_snapshots p WITH (NOLOCK)
               ON p.policy_id = c.policy_id
              AND p.snapshot_date = @snapshot_date
        LEFT JOIN dw.dim_customer dc WITH (NOLOCK)
               ON dc.customer_id = c.customer_id
        WHERE   c.reported_date >  DATEADD(MONTH, -12, @AsOfDate)
          AND   c.reported_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'claims notified', @status = 'INFO', @rows_affected = @rows;

        /* 2. SIU indicators, one point each (CR-0954, CR-1012, INC-1530) */
        IF OBJECT_ID('tempdb..#flags') IS NOT NULL DROP TABLE #flags;

        SELECT  f.*,
                f.early_notification_flag + f.invalid_reg_flag
                  + f.new_customer_flag + f.lob_mismatch_flag     AS fraud_score
        INTO    #flags
        FROM   (SELECT  cl.claim_id,
                        -- claim notified within 30 days of the cover starting
                        CASE WHEN DATEDIFF(DAY, cl.expiry_date, cl.reported_date) BETWEEN 0 AND 30
                             THEN 1 ELSE 0 END                    AS early_notification_flag,
                        -- motor: registration not in the Irish format, e.g. 191-D-12345
                        CASE WHEN cl.lob_code = 'MOT'
                              AND cl.vehicle_reg NOT LIKE '[0-9][0-9]%-[A-Z]%-[0-9]%'
                             THEN 1 ELSE 0 END                    AS invalid_reg_flag,
                        -- customer for less than six months at the date of loss
                        CASE WHEN DATEDIFF(DAY, cl.customer_since, cl.loss_date) < 180
                             THEN 1 ELSE 0 END                    AS new_customer_flag,
                        -- policy number starts with its line of business (MOT/2024/500001)
                        CASE WHEN SUBSTRING(cl.policy_number, 0, 4) <> cl.lob_code
                             THEN 1 ELSE 0 END                    AS lob_mismatch_flag
                FROM    #claims cl) f;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'indicators', @status = 'INFO', @rows_affected = @rows;

        /* 3. Reload the SIU table: bands agreed with SIU (CR-1377) */
        BEGIN TRANSACTION;

        TRUNCATE TABLE rpt.claim_fraud_flags;

        INSERT INTO rpt.claim_fraud_flags
               (claim_id, claim_number, policy_id, policy_number, customer_id, lob_code,
                loss_date, reported_date, early_notification_flag, invalid_reg_flag,
                new_customer_flag, lob_mismatch_flag, fraud_score, fraud_band,
                loss_day_key, reason_text, as_of_date)
        SELECT  cl.claim_id,
                cl.claim_number,
                cl.policy_id,
                cl.policy_number,
                cl.customer_id,
                UPPER(RTRIM(cl.lob_code)),
                cl.loss_date,
                cl.reported_date,
                f.early_notification_flag,
                f.invalid_reg_flag,
                f.new_customer_flag,
                f.lob_mismatch_flag,
                f.fraud_score,
                CASE WHEN f.fraud_score >= 2 THEN 'HIGH'
                     WHEN f.fraud_score = 1  THEN 'MEDIUM'
                     ELSE 'LOW'
                END,
                CONVERT(CHAR(8), cl.loss_date, 112),
                'Notified ' + CONVERT(VARCHAR(10), cl.reported_date, 103)
                    + CASE WHEN f.fraud_score = 0 THEN ' - no indicators' ELSE ' -' END
                    + CASE WHEN f.early_notification_flag = 1 THEN ' EARLY'   ELSE '' END
                    + CASE WHEN f.invalid_reg_flag        = 1 THEN ' REG'     ELSE '' END
                    + CASE WHEN f.new_customer_flag       = 1 THEN ' NEWCUST' ELSE '' END
                    + CASE WHEN f.lob_mismatch_flag       = 1 THEN ' LOB'     ELSE '' END,
                @AsOfDate
        FROM    #claims cl
        JOIN    #flags f
                ON f.claim_id = cl.claim_id;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'rpt.claim_fraud_flags', @status = 'INFO', @rows_affected = @rows;
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
