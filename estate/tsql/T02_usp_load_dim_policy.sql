/*==============================================================================
  Job      : dw.usp_load_dim_policy
  Purpose  : Policy dimension for finance, actuarial and broker reporting. One
             row per version of a policy term, with its product, broker and
             customer segment. A new version starts whenever the status,
             broker, annual premium or vehicle registration changes from one
             policy snapshot to the next (type 2 history).
  Run by   : POL_SNAPSHOT_LOAD, once per policy snapshot, oldest first:
             EXEC dw.usp_load_dim_policy @SnapshotDate = '<snapshot date>'
  Output   : dw.dim_policy. Keeps history, so the procedure never truncates
             it. Deploying this script recreates the table empty: reload every
             snapshot in date order afterwards.
  Author   : MOB

  Change log
    2014-02-10  MOB   Initial version, one row per policy (CR-0655)
    2015-06-22  MOB   Broker name from the broker register (CR-0790)
    2016-09-05  TF    Direct business reported as broker DIRECT-SALES (CR-0961)
    2017-03-13  TF    Type 2 history with MERGE, surrogate key policy_sk
                      (CR-1077)
    2018-10-01  PH    Vehicle registration tracked for motor (CR-1388)
    2019-07-15  PH    Customer segment from dw.dim_customer (CR-1610)
    2020-02-03  TF    Refuse a snapshot older than the last one loaded
                      (INC-2105)
    2021-06-14  KB    Logging through etl.usp_log_step (CR-2003)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.dim_policy', N'U') IS NOT NULL
    DROP TABLE dw.dim_policy;

CREATE TABLE dw.dim_policy (
    policy_sk             INT IDENTITY(1,1) NOT NULL,
    policy_id             INT            NOT NULL,
    policy_number         VARCHAR(20)    NOT NULL,
    customer_id           INT            NOT NULL,
    customer_segment      CHAR(4)        NULL,
    product_code          VARCHAR(10)    NOT NULL,
    product_name          NVARCHAR(60)   NOT NULL,
    lob_code              VARCHAR(5)     NOT NULL,
    broker_code           VARCHAR(12)    NOT NULL,
    broker_name           NVARCHAR(80)   NULL,
    status                VARCHAR(12)    NOT NULL,
    inception_date        DATE           NOT NULL,
    expiry_date           DATE           NOT NULL,
    cancellation_date     DATE           NULL,
    annual_premium        DECIMAL(12,2)  NOT NULL,
    currency              CHAR(3)        NOT NULL,
    vehicle_reg           VARCHAR(12)    NULL,
    ncd_years             INT            NULL,
    valid_from            DATE           NOT NULL,
    valid_to              DATE           NOT NULL,   -- 9999-12-31 while current
    is_current            CHAR(1)        NOT NULL,   -- Y / N
    source_snapshot_date  DATE           NOT NULL,
    load_ts               DATETIME2(3)   NOT NULL,
    CONSTRAINT pk_dim_policy PRIMARY KEY CLUSTERED (policy_sk)
);

CREATE NONCLUSTERED INDEX ix_dim_policy_policy_id ON dw.dim_policy (policy_id, is_current);
GO
CREATE OR ALTER PROCEDURE dw.usp_load_dim_policy
    @SnapshotDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name     VARCHAR(128) = 'dw.usp_load_dim_policy',
            @rows         INT,
            @closed       INT,
            @last_loaded  DATE,
            @err_msg      NVARCHAR(4000),
            @err_no       INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        /* Oldest snapshot first: loading an older snapshot after a newer one
           would reopen versions that are already closed (INC-2105) */
        SELECT  @last_loaded = MAX(d.source_snapshot_date)
        FROM    dw.dim_policy d;

        IF @SnapshotDate < @last_loaded
            THROW 50001, 'dw.dim_policy already holds a later policy snapshot', 1;

        IF OBJECT_ID('tempdb..#src') IS NOT NULL DROP TABLE #src;

        /* 1. This snapshot's policies with product, broker and customer segment */
        SELECT  p.policy_id,
                p.policy_number,
                p.customer_id,
                c.segment_code                          AS customer_segment,
                pr.product_code,
                pr.product_name,
                pr.lob_code,
                ISNULL(p.broker_code, 'DIRECT-SALES')   AS broker_code,
                b.broker_name,
                p.status,
                p.inception_date,
                p.expiry_date,
                p.cancellation_date,
                p.annual_premium,
                p.currency,
                p.vehicle_reg,
                p.ncd_years
        INTO    #src
        FROM    stg.policy_snapshots p WITH (NOLOCK)
        JOIN    stg.products pr WITH (NOLOCK)
                ON pr.product_code = p.product_code
        LEFT JOIN stg.brokers b WITH (NOLOCK)
               ON b.broker_code = p.broker_code
        LEFT JOIN dw.dim_customer c WITH (NOLOCK)
               ON c.customer_id = p.customer_id
        WHERE   p.snapshot_date = @SnapshotDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'policy snapshot', @status = 'INFO', @rows_affected = @rows;

        IF @rows = 0
            THROW 50002, 'No policies found for this snapshot date', 1;

        CREATE CLUSTERED INDEX ix_src_policy_id ON #src (policy_id);

        BEGIN TRANSACTION;

        /* 2. Close the current version of policies whose status, broker, premium
              or vehicle registration has changed since the last snapshot */
        MERGE dw.dim_policy AS tgt
        USING #src AS src
           ON tgt.policy_id = src.policy_id
          AND tgt.is_current = 'Y'
        WHEN MATCHED AND (   ISNULL(src.status, '')        <> ISNULL(tgt.status, '')
                          OR ISNULL(src.broker_code, '')   <> ISNULL(tgt.broker_code, '')
                          OR ISNULL(src.annual_premium, 0) <> ISNULL(tgt.annual_premium, 0)
                          OR ISNULL(src.vehicle_reg, '')   <> ISNULL(tgt.vehicle_reg, ''))
        THEN UPDATE
             SET    tgt.valid_to   = DATEADD(DAY, -1, @SnapshotDate),
                    tgt.is_current = 'N';

        SET @closed = @@ROWCOUNT;

        /* 3. Open a current version for new policies and for those closed above */
        INSERT INTO dw.dim_policy
               (policy_id, policy_number, customer_id, customer_segment, product_code,
                product_name, lob_code, broker_code, broker_name, status, inception_date,
                expiry_date, cancellation_date, annual_premium, currency, vehicle_reg,
                ncd_years, valid_from, valid_to, is_current, source_snapshot_date, load_ts)
        SELECT  s.policy_id, s.policy_number, s.customer_id, s.customer_segment, s.product_code,
                s.product_name, s.lob_code, s.broker_code, s.broker_name, s.status,
                s.inception_date, s.expiry_date, s.cancellation_date, s.annual_premium,
                s.currency, s.vehicle_reg, s.ncd_years,
                @SnapshotDate,
                '9999-12-31',
                'Y',
                @SnapshotDate,
                SYSDATETIME()
        FROM    #src s
        WHERE   NOT EXISTS (SELECT 1
                            FROM   dw.dim_policy d
                            WHERE  d.policy_id = s.policy_id
                              AND  d.is_current = 'Y')
        ORDER BY s.policy_id;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'versions closed', @status = 'INFO', @rows_affected = @closed;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'versions opened', @status = 'INFO', @rows_affected = @rows;
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
