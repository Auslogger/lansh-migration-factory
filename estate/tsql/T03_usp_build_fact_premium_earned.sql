/*==============================================================================
  Job       dw.usp_build_fact_premium_earned
  Purpose   Premium fact for finance: one row per premium transaction, converted
            to EUR at the rate published on or before the booking date, with
            the premium earned as at the reporting date.
  Author    MOD
  Run by    FIN_MONTH_END, after dw.usp_load_dim_policy
  Output    dw.fact_premium_earned (full refresh)

  Change log
    2016-01-11  MOD  Initial version (CR-0904)
    2016-07-04  MOD  Sterling and dollar business converted to EUR (CR-0977)
    2018-03-19  PK   Policy surrogate key and line of business from dim_policy (CR-1290)
    2019-09-30  PK   Daily rate and monthly instalment for the cash-flow model (CR-1510)
    2021-02-15  MOD  First instalment due date for the direct debit file (CR-1618)
    2023-05-08  JMcK Earned percentage for the finance dashboard (INC-2301)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.fact_premium_earned', N'U') IS NULL
CREATE TABLE dw.fact_premium_earned (
    txn_id                  INT            NOT NULL,
    policy_id               INT            NOT NULL,
    policy_sk               INT            NOT NULL,
    lob_code                VARCHAR(5)     NOT NULL,
    txn_type                VARCHAR(4)     NOT NULL,
    txn_date                DATE           NOT NULL,
    effective_from          DATE           NOT NULL,
    effective_to            DATE           NOT NULL,
    currency                CHAR(3)        NOT NULL,
    amount                  DECIMAL(12,2)  NOT NULL,
    fx_rate                 DECIMAL(18,8)  NOT NULL,
    written_eur             DECIMAL(14,2)  NOT NULL,
    term_days               INT            NOT NULL,
    earned_days             INT            NOT NULL,
    earned_pct              DECIMAL(5,2)   NOT NULL,
    earned_eur              DECIMAL(14,2)  NOT NULL,
    unearned_eur            DECIMAL(14,2)  NOT NULL,
    daily_rate_eur          DECIMAL(12,4)  NOT NULL,
    monthly_instalment_eur  DECIMAL(14,2)  NOT NULL,
    first_due_date          DATE           NOT NULL,
    as_of_date              DATE           NOT NULL,
    CONSTRAINT pk_dw_fact_premium_earned PRIMARY KEY (txn_id)
);
GO
CREATE OR ALTER PROCEDURE dw.usp_build_fact_premium_earned
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'dw.usp_build_fact_premium_earned',
            @rows      INT,
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Transactions with their EUR rate: EUR as is, other currencies at the
           latest rate on or before the booking date (later row wins on revisions) */
        IF OBJECT_ID('tempdb..#txn') IS NOT NULL DROP TABLE #txn;

        SELECT  t.txn_id, t.policy_id, UPPER(RTRIM(t.txn_type)) AS txn_type, t.txn_date,
                t.effective_from, t.effective_to, t.currency, t.amount,
                CAST(1 AS DECIMAL(18,8)) AS fx_rate
        INTO    #txn
        FROM    stg.premium_transactions t WITH (NOLOCK)
        WHERE   t.currency = 'EUR'
          AND   t.txn_date <= @AsOfDate;

        INSERT INTO #txn (txn_id, policy_id, txn_type, txn_date, effective_from, effective_to,
                          currency, amount, fx_rate)
        SELECT  t.txn_id, t.policy_id, UPPER(RTRIM(t.txn_type)), t.txn_date,
                t.effective_from, t.effective_to, t.currency, t.amount, fx.rate_to_eur
        FROM    stg.premium_transactions t WITH (NOLOCK)
        CROSS APPLY (SELECT TOP 1 r.rate_to_eur
                     FROM   stg.fx_rates r WITH (NOLOCK)
                     WHERE  r.currency = t.currency
                       AND  r.rate_date <= t.txn_date
                     ORDER BY r.rate_date DESC, r._row_seq DESC) fx
        WHERE   t.currency <> 'EUR'
          AND   t.txn_date <= @AsOfDate;

        SELECT @rows = COUNT(*) FROM #txn;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'transactions', @status = 'INFO', @rows_affected = @rows;

        /* Days of cover and days earned by the reporting date */
        IF OBJECT_ID('tempdb..#earn') IS NOT NULL DROP TABLE #earn;

        SELECT  x.*,
                CAST(ROUND(x.amount * x.fx_rate, 2) AS DECIMAL(14,2)) AS written_eur,
                DATEDIFF(DAY, x.effective_from, x.effective_to) + 1  AS term_days,
                CASE WHEN @AsOfDate < x.effective_from THEN 0
                     WHEN @AsOfDate >= x.effective_to  THEN DATEDIFF(DAY, x.effective_from, x.effective_to) + 1
                     ELSE DATEDIFF(DAY, x.effective_from, @AsOfDate) + 1
                END AS earned_days
        INTO    #earn
        FROM    #txn x;

        BEGIN TRANSACTION;

        TRUNCATE TABLE dw.fact_premium_earned;

        INSERT INTO dw.fact_premium_earned
               (txn_id, policy_id, policy_sk, lob_code, txn_type, txn_date, effective_from,
                effective_to, currency, amount, fx_rate, written_eur, term_days, earned_days,
                earned_pct, earned_eur, unearned_eur, daily_rate_eur, monthly_instalment_eur,
                first_due_date, as_of_date)
        SELECT  e.txn_id,
                e.policy_id,
                p.policy_sk,
                p.lob_code,
                e.txn_type,
                e.txn_date,
                e.effective_from,
                e.effective_to,
                e.currency,
                e.amount,
                e.fx_rate,
                e.written_eur,
                e.term_days,
                e.earned_days,
                e.earned_days * 100 / e.term_days,
                ROUND(e.written_eur * e.earned_days / 365, 2),
                e.written_eur - ROUND(e.written_eur * e.earned_days / 365, 2),
                ROUND(e.written_eur / e.term_days, 4, 1),
                ROUND(e.written_eur / ISNULL(NULLIF(e.term_days / 30, 0), 1), 2),
                DATEADD(MONTH, 1, EOMONTH(e.effective_from)),
                @AsOfDate
        FROM    #earn e
        JOIN    dw.dim_policy p WITH (NOLOCK)
                ON p.policy_id = e.policy_id
               AND p.is_current = 'Y';

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'dw.fact_premium_earned', @status = 'INFO', @rows_affected = @rows;
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
