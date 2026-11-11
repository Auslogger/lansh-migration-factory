/*==============================================================================
  Job      : dw.usp_load_dim_customer
  Purpose  : Customer dimension for the marketing and pricing teams. One row
             per CRM customer with the customer's current details from the
             CRM extract, plus sales region, Eircode check, initials and
             segment flags for campaigns and the pricing models.
  Output   : dw.dim_customer (truncated and reloaded on every run)
  Author   : DOC

  Change log
    2013-05-20  DOC   Initial version
    2014-11-03  DOC   Sales region from county for the regional reports (CR-0412)
    2015-01-26  DOC   full_name and initials for the mail merge (CR-0538)
    2016-02-18  AMcG  Eircode added, with a format check (CR-0877)
    2017-09-07  AMcG  email_shared_count for the marketing duplicate review
                      (CR-1190)
    2018-05-21  AMcG  Opt-in defaults to N when the customer was never asked
                      (GDPR, CR-1342)
    2019-03-25  SR    age_at_join for the pricing models (CR-1564)
    2019-11-04  KB    CRM extract is now change data capture: one row per
                      saved version, keep the current one (CR-1702)
    2020-10-12  SR    is_standard_segment for the renewal campaign (CR-1841)
    2021-06-14  KB    Logging through etl.usp_log_step (CR-2003)
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'dw.dim_customer', N'U') IS NULL
CREATE TABLE dw.dim_customer (
    customer_id          INT            NOT NULL,
    first_name           NVARCHAR(40)   NOT NULL,
    last_name            NVARCHAR(60)   NOT NULL,
    full_name            NVARCHAR(101)  NOT NULL,
    initials             NVARCHAR(2)    NOT NULL,
    email                VARCHAR(120)   NULL,
    email_shared_count   INT            NOT NULL,
    date_of_birth        DATE           NULL,
    age_at_join          INT            NULL,
    address_line1        NVARCHAR(100)  NULL,
    town                 NVARCHAR(50)   NULL,
    county               VARCHAR(30)    NULL,
    region               VARCHAR(12)    NOT NULL,
    eircode              VARCHAR(10)    NULL,
    eircode_valid        CHAR(1)        NOT NULL,
    segment_code         CHAR(4)        NULL,
    is_standard_segment  CHAR(1)        NOT NULL,
    marketing_opt_in     CHAR(1)        NOT NULL,
    customer_since       DATE           NOT NULL,
    source_system        VARCHAR(10)    NOT NULL,
    version_count        INT            NOT NULL,
    record_updated_at    DATETIME2(0)   NOT NULL,
    as_of_date           DATE           NOT NULL,
    CONSTRAINT pk_dim_customer PRIMARY KEY CLUSTERED (customer_id)
);
GO
CREATE OR ALTER PROCEDURE dw.usp_load_dim_customer
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @job_name  VARCHAR(128) = 'dw.usp_load_dim_customer',
            @rows      INT,
            @err_msg   NVARCHAR(4000),
            @err_no    INT;

    BEGIN TRY
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'start', @status = 'STARTED';

        IF OBJECT_ID('tempdb..#customer_versions') IS NOT NULL DROP TABLE #customer_versions;
        IF OBJECT_ID('tempdb..#customer') IS NOT NULL DROP TABLE #customer;

        /* 1. Customer versions saved up to the reporting date. The CRM extract
              writes a new row every time a record is saved. */
        SELECT  c.customer_id,
                c.first_name,
                c.last_name,
                c.email,
                c.date_of_birth,
                c.address_line1,
                c.town,
                c.county,
                c.eircode,
                c.segment_code,
                c.marketing_opt_in,
                c.customer_since,
                c.source_system,
                c.updated_at,
                c._row_seq,
                COUNT(*) OVER (PARTITION BY c.customer_id) AS version_count
        INTO    #customer_versions
        FROM    stg.customers c WITH (NOLOCK)
        WHERE   CAST(c.updated_at AS DATE) <= @AsOfDate;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'customer versions', @status = 'INFO', @rows_affected = @rows;

        /* 2. Keep the current version of each customer */
        SELECT  v.*
        INTO    #customer
        FROM   (SELECT  cv.*,
                        ROW_NUMBER() OVER (PARTITION BY cv.customer_id
                                           ORDER BY cv.updated_at, cv._row_seq) AS version_no
                FROM    #customer_versions cv) v
        WHERE   v.version_no = 1;

        SET @rows = @@ROWCOUNT;
        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'current versions', @status = 'INFO', @rows_affected = @rows;

        /* 3. Reload the dimension */
        BEGIN TRANSACTION;

        TRUNCATE TABLE dw.dim_customer;

        INSERT INTO dw.dim_customer
               (customer_id, first_name, last_name, full_name, initials, email,
                email_shared_count, date_of_birth, age_at_join, address_line1, town,
                county, region, eircode, eircode_valid, segment_code, is_standard_segment,
                marketing_opt_in, customer_since, source_system, version_count,
                record_updated_at, as_of_date)
        SELECT  k.customer_id,
                RTRIM(k.first_name),
                k.last_name,
                RTRIM(k.first_name) + N' ' + RTRIM(k.last_name),
                UPPER(SUBSTRING(k.first_name, 0, 2) + SUBSTRING(k.last_name, 0, 2)),
                k.email,
                CASE WHEN k.email IS NULL THEN 0
                     ELSE COUNT(*) OVER (PARTITION BY k.email) END,
                k.date_of_birth,
                DATEDIFF(YEAR, k.date_of_birth, k.customer_since),
                k.address_line1,
                k.town,
                k.county,
                -- sales regions as agreed with distribution (CR-0412)
                CASE WHEN k.county IN ('Dublin', 'Kildare', 'Meath', 'Wicklow', 'Louth', 'Wexford') THEN 'EAST'
                     WHEN k.county IN ('Cork', 'Kerry', 'Limerick', 'Tipperary', 'Waterford', 'Kilkenny', 'Carlow') THEN 'SOUTH'
                     WHEN k.county IN ('Galway', 'Mayo', 'Clare', 'Roscommon') THEN 'WEST'
                     WHEN k.county IN ('Donegal', 'Sligo', 'Leitrim', 'Cavan', 'Monaghan') THEN 'NORTH-WEST'
                     WHEN k.county IN ('Westmeath', 'Longford', 'Offaly', 'Laois') THEN 'MIDLANDS'
                     ELSE 'UNKNOWN'
                END,
                k.eircode,
                -- routing key (3) and unique identifier (4), keyed with or without the space
                CASE WHEN LEN(k.eircode) = 7 THEN 'Y'
                     WHEN LEN(k.eircode) = 8 AND SUBSTRING(k.eircode, 4, 1) = ' ' THEN 'Y'
                     ELSE 'N'
                END,
                k.segment_code,
                CASE WHEN k.segment_code = 'STD' THEN 'Y' ELSE 'N' END,
                ISNULL(k.marketing_opt_in, 'N'),
                k.customer_since,
                UPPER(RTRIM(k.source_system)),
                k.version_count,
                k.updated_at,
                @AsOfDate
        FROM    #customer k;

        SET @rows = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC etl.usp_log_step @job_name = @job_name, @step_name = 'dw.dim_customer', @status = 'INFO', @rows_affected = @rows;
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
