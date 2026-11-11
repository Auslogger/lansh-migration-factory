/*==============================================================================
  SynthInsure Data Warehouse (SynthInsureDW) - base objects

  Schemas
    stg  source extracts, loaded nightly from the policy, claims, CRM and
         finance systems
    dw   warehouse tables (dimensions and facts)
    rpt  reporting tables read by finance, actuarial and claims MI
    etl  job control and logging

  Change log
    2016-03-02  DBA  Initial version
    2017-08-21  DBA  etl.usp_log_step added so every job logs the same way
    2019-01-14  DBA  etl_log.message widened to NVARCHAR(4000)
==============================================================================*/
SET NOCOUNT ON;
GO
IF SCHEMA_ID(N'stg') IS NULL EXEC (N'CREATE SCHEMA stg AUTHORIZATION dbo');
GO
IF SCHEMA_ID(N'dw') IS NULL EXEC (N'CREATE SCHEMA dw AUTHORIZATION dbo');
GO
IF SCHEMA_ID(N'rpt') IS NULL EXEC (N'CREATE SCHEMA rpt AUTHORIZATION dbo');
GO
IF SCHEMA_ID(N'etl') IS NULL EXEC (N'CREATE SCHEMA etl AUTHORIZATION dbo');
GO
IF OBJECT_ID(N'etl.etl_log', N'U') IS NULL
CREATE TABLE etl.etl_log (
    log_id         INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_etl_log PRIMARY KEY,
    job_name       VARCHAR(128)      NOT NULL,
    step_name      VARCHAR(128)      NULL,
    status         VARCHAR(20)       NOT NULL,   -- STARTED / INFO / SUCCESS / FAILED
    rows_affected  INT               NULL,
    message        NVARCHAR(4000)    NULL,
    error_number   INT               NULL,
    logged_at      DATETIME2(3)      NOT NULL
        CONSTRAINT df_etl_log_logged_at DEFAULT (SYSDATETIME())
);
GO
CREATE OR ALTER PROCEDURE etl.usp_log_step
    @job_name      VARCHAR(128),
    @step_name     VARCHAR(128)   = NULL,
    @status        VARCHAR(20),
    @rows_affected INT            = NULL,
    @message       NVARCHAR(4000) = NULL,
    @error_number  INT            = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO etl.etl_log (job_name, step_name, status, rows_affected, message, error_number)
    VALUES (@job_name, @step_name, @status, @rows_affected, @message, @error_number);
END;
GO
