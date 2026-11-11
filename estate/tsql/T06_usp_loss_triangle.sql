/*==============================================================================
  Job      : rpt.usp_loss_triangle
  Purpose  : Paid loss development triangle for the actuarial reserving team.
             One row per accident year and line of business, with the amount
             paid in each development year (dev_0 .. dev_6) and the cumulative
             paid to date (cumulative_0 .. cumulative_6) as at @AsOfDate. Feeds
             the chain-ladder workbook for the quarterly reserving review.
  Author   : CNM

  Change log
    2019-04-08  CNM   Initial version (CR-0862)
    2019-10-21  CNM   Travel added to the triangle (CR-0947)
    2020-09-14  PD    Payments keyed with a date before the loss left out
                      (INC-2318)
    2021-02-01  PD    Unkeyed payments (NULL amount) left out
    2022-01-17  EOS   Seven accident years. Cells after the as-at date now NULL
                      instead of 0, as the workbook expects (CR-1405)
    2023-06-26  EOS   lob_code trimmed and upper-cased before grouping
                      (INC-2851)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'rpt.loss_triangle_paid', N'U') IS NULL
CREATE TABLE rpt.loss_triangle_paid (
    accident_year  INT            NOT NULL,
    lob_code       VARCHAR(5)     NOT NULL,
    dev_0          DECIMAL(14,2)  NULL,
    dev_1          DECIMAL(14,2)  NULL,
    dev_2          DECIMAL(14,2)  NULL,
    dev_3          DECIMAL(14,2)  NULL,
    dev_4          DECIMAL(14,2)  NULL,
    dev_5          DECIMAL(14,2)  NULL,
    dev_6          DECIMAL(14,2)  NULL,
    cumulative_0   DECIMAL(14,2)  NULL,
    cumulative_1   DECIMAL(14,2)  NULL,
    cumulative_2   DECIMAL(14,2)  NULL,
    cumulative_3   DECIMAL(14,2)  NULL,
    cumulative_4   DECIMAL(14,2)  NULL,
    cumulative_5   DECIMAL(14,2)  NULL,
    cumulative_6   DECIMAL(14,2)  NULL,
    as_of_date     DATE           NOT NULL,
    CONSTRAINT pk_loss_triangle_paid PRIMARY KEY (accident_year, lob_code)
);
GO
CREATE OR ALTER PROCEDURE rpt.usp_loss_triangle
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name VARCHAR(128) = 'rpt.usp_loss_triangle',
            @as_at_yr INT          = YEAR(@AsOfDate),
            @rows     INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Start',
             @status = 'STARTED';

        ------------------------------------------------------------------
        -- 1. Claims with a loss in the last seven accident years
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#claims') IS NOT NULL DROP TABLE #claims;

        SELECT c.claim_id,
               c.loss_date,
               YEAR(c.loss_date)        AS accident_year,
               UPPER(RTRIM(c.lob_code)) AS lob_code
        INTO   #claims
        FROM   stg.claims AS c WITH (NOLOCK)
        WHERE  YEAR(c.loss_date) BETWEEN @as_at_yr - 6 AND @as_at_yr
          AND  c.loss_date <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Load #claims',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 2. Payments to the as-at date, with their development year
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#paid') IS NOT NULL DROP TABLE #paid;

        SELECT cl.claim_id,
               p.payment_id,
               cl.accident_year,
               cl.lob_code,
               DATEDIFF(YEAR, cl.loss_date, p.payment_date) AS dev_year,
               p.amount
        INTO   #paid
        FROM   #claims AS cl
        INNER JOIN stg.claim_payments AS p WITH (NOLOCK)
                ON p.claim_id = cl.claim_id
        WHERE  p.payment_date <= @AsOfDate
          AND  p.payment_date >  cl.loss_date   -- dated before the loss = keying error
          AND  p.amount IS NOT NULL;            -- not keyed yet

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Load #paid',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 3. One column per development year
        ------------------------------------------------------------------
        IF OBJECT_ID('tempdb..#tri') IS NOT NULL DROP TABLE #tri;

        SELECT pv.accident_year,
               pv.lob_code,
               pv.[0] AS d0, pv.[1] AS d1, pv.[2] AS d2, pv.[3] AS d3,
               pv.[4] AS d4, pv.[5] AS d5, pv.[6] AS d6
        INTO   #tri
        FROM  (SELECT accident_year, lob_code, dev_year, amount
               FROM   #paid) AS src
        PIVOT (SUM(amount) FOR dev_year IN ([0], [1], [2], [3], [4], [5], [6])) AS pv;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Pivot #tri',
             @status = 'INFO', @rows_affected = @rows;

        ------------------------------------------------------------------
        -- 4. Reload the triangle. Nothing paid yet = 0; a cell after the
        --    as-at date stays NULL.
        ------------------------------------------------------------------
        TRUNCATE TABLE rpt.loss_triangle_paid;

        INSERT INTO rpt.loss_triangle_paid
               (accident_year, lob_code, dev_0, dev_1, dev_2, dev_3, dev_4, dev_5, dev_6,
                as_of_date)
        SELECT t.accident_year,
               t.lob_code,
               ISNULL(t.d0, 0),
               CASE WHEN t.accident_year + 1 <= @as_at_yr THEN ISNULL(t.d1, 0) END,
               CASE WHEN t.accident_year + 2 <= @as_at_yr THEN ISNULL(t.d2, 0) END,
               CASE WHEN t.accident_year + 3 <= @as_at_yr THEN ISNULL(t.d3, 0) END,
               CASE WHEN t.accident_year + 4 <= @as_at_yr THEN ISNULL(t.d4, 0) END,
               CASE WHEN t.accident_year + 5 <= @as_at_yr THEN ISNULL(t.d5, 0) END,
               CASE WHEN t.accident_year + 6 <= @as_at_yr THEN ISNULL(t.d6, 0) END,
               @AsOfDate
        FROM   #tri AS t;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Insert rpt.loss_triangle_paid',
             @status = 'INFO', @rows_affected = @rows;

        -- cumulative paid (NULL after the as-at date, same as dev_n)
        UPDATE rpt.loss_triangle_paid
           SET cumulative_0 = dev_0,
               cumulative_1 = dev_0 + dev_1,
               cumulative_2 = dev_0 + dev_1 + dev_2,
               cumulative_3 = dev_0 + dev_1 + dev_2 + dev_3,
               cumulative_4 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4,
               cumulative_5 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4 + dev_5,
               cumulative_6 = dev_0 + dev_1 + dev_2 + dev_3 + dev_4 + dev_5 + dev_6;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Cumulative paid',
             @status = 'INFO', @rows_affected = @rows;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'End',
             @status = 'SUCCESS';
    END TRY
    BEGIN CATCH
        DECLARE @err_msg NVARCHAR(4000) = ERROR_MESSAGE(),
                @err_no  INT            = ERROR_NUMBER();

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'Error',
             @status = 'FAILED', @message = @err_msg, @error_number = @err_no;
        THROW;
    END CATCH;
END;
GO
