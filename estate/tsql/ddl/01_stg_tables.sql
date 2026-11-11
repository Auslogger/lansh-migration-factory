/*==============================================================================
  SynthInsure Data Warehouse - source extract tables (schema stg)

  GENERATED from estate/data/dictionary.yaml by `lansh estate ddl`.
  Do not edit by hand: change the dictionary and regenerate.
==============================================================================*/
SET NOCOUNT ON;
GO
IF OBJECT_ID(N'stg.customers', N'U') IS NOT NULL DROP TABLE stg.customers;
GO
-- CRM customer extract. Change-data-capture style: each customer appears once per version of their record, so customer_id repeats and updated_at tells the versions apart.
CREATE TABLE stg.customers (
    customer_id       INT            NOT NULL,
    first_name        NVARCHAR(40)   NOT NULL,
    last_name         NVARCHAR(60)   NOT NULL,
    email             VARCHAR(120)   NULL,
    date_of_birth     DATE           NULL,
    address_line1     NVARCHAR(100)  NULL,
    town              NVARCHAR(50)   NULL,
    county            VARCHAR(30)    NULL,
    eircode           VARCHAR(10)    NULL,
    segment_code      CHAR(4)        NULL,
    marketing_opt_in  CHAR(1)        NULL,
    customer_since    DATE           NOT NULL,
    source_system     VARCHAR(10)    NOT NULL,
    updated_at        DATETIME2(0)   NOT NULL,
    _row_seq          INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.brokers', N'U') IS NOT NULL DROP TABLE stg.brokers;
GO
-- Broker register from the distribution system.
CREATE TABLE stg.brokers (
    broker_code      CHAR(6)        NOT NULL,
    broker_name      NVARCHAR(80)   NOT NULL,
    region           VARCHAR(20)    NULL,
    commission_rate  DECIMAL(5,4)   NOT NULL,
    status           VARCHAR(10)    NOT NULL,
    appointed_date   DATE           NOT NULL,
    _row_seq         INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.products', N'U') IS NOT NULL DROP TABLE stg.products;
GO
-- Product catalogue.
CREATE TABLE stg.products (
    product_code  VARCHAR(10)    NOT NULL,
    product_name  NVARCHAR(60)   NOT NULL,
    lob_code      VARCHAR(5)     NOT NULL,
    term_months   INT            NULL,
    levy_rate     DECIMAL(5,4)   NOT NULL,
    launched_on   DATE           NOT NULL,
    withdrawn_on  DATE           NULL,
    _row_seq      INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.policy_snapshots', N'U') IS NOT NULL DROP TABLE stg.policy_snapshots;
GO
-- Policy administration extract taken on two snapshot dates (2025-06-30 and 2025-12-31). Each snapshot lists every policy term incepted on or before that date, with its attributes as they stood on that date. One row per policy term per snapshot.
CREATE TABLE stg.policy_snapshots (
    snapshot_date      DATE           NOT NULL,
    policy_id          INT            NOT NULL,
    policy_number      VARCHAR(20)    NOT NULL,
    customer_id        INT            NOT NULL,
    product_code       VARCHAR(10)    NOT NULL,
    broker_code        VARCHAR(10)    NULL,
    inception_date     DATE           NOT NULL,
    expiry_date        DATE           NOT NULL,
    status             VARCHAR(12)    NOT NULL,
    cancellation_date  DATE           NULL,
    annual_premium     DECIMAL(12,2)  NOT NULL,
    currency           CHAR(3)        NOT NULL,
    sum_insured        DECIMAL(14,2)  NULL,
    payment_frequency  VARCHAR(10)    NOT NULL,
    vehicle_reg        VARCHAR(12)    NULL,
    ncd_years          INT            NULL,
    _row_seq           INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.premium_transactions', N'U') IS NOT NULL DROP TABLE stg.premium_transactions;
GO
-- Premium ledger from the policy system. One row per premium transaction.
CREATE TABLE stg.premium_transactions (
    txn_id          INT            NOT NULL,
    policy_id       INT            NOT NULL,
    txn_type        VARCHAR(4)     NOT NULL,
    txn_date        DATE           NOT NULL,
    effective_from  DATE           NOT NULL,
    effective_to    DATE           NOT NULL,
    amount          DECIMAL(12,2)  NOT NULL,
    currency        CHAR(3)        NOT NULL,
    _row_seq        INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.claims', N'U') IS NOT NULL DROP TABLE stg.claims;
GO
-- Claims register from the claims system. One row per claim.
CREATE TABLE stg.claims (
    claim_id       INT            NOT NULL,
    claim_number   VARCHAR(20)    NOT NULL,
    policy_id      INT            NOT NULL,
    customer_id    INT            NOT NULL,
    lob_code       VARCHAR(5)     NOT NULL,
    loss_date      DATE           NOT NULL,
    reported_date  DATE           NOT NULL,
    status         VARCHAR(12)    NOT NULL,
    closed_date    DATE           NULL,
    cause_code     VARCHAR(10)    NULL,
    handler_code   VARCHAR(8)     NULL,
    description    NVARCHAR(200)  NULL,
    _row_seq       INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.claim_payments', N'U') IS NOT NULL DROP TABLE stg.claim_payments;
GO
-- Claim payments and recoveries. One row per payment.
CREATE TABLE stg.claim_payments (
    payment_id    INT            NOT NULL,
    claim_id      INT            NOT NULL,
    payment_date  DATE           NOT NULL,
    amount        DECIMAL(12,2)  NULL,
    payment_type  VARCHAR(12)    NOT NULL,
    payee_type    VARCHAR(12)    NULL,
    _row_seq      INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.claim_reserves', N'U') IS NOT NULL DROP TABLE stg.claim_reserves;
GO
-- Case reserve history. Each row sets the outstanding estimate for one reserve type of a claim from its reserve_date until the next row of the same type.
CREATE TABLE stg.claim_reserves (
    reserve_id      INT            NOT NULL,
    claim_id        INT            NOT NULL,
    reserve_date    DATE           NOT NULL,
    reserve_type    VARCHAR(12)    NOT NULL,
    reserve_amount  DECIMAL(12,2)  NOT NULL,
    _row_seq        INT            NOT NULL
);
GO
IF OBJECT_ID(N'stg.fx_rates', N'U') IS NOT NULL DROP TABLE stg.fx_rates;
GO
-- Daily reference exchange rates (EUR per unit of currency) on business days. Gaps on weekends and holidays; a later row for the same date and currency is a revision.
CREATE TABLE stg.fx_rates (
    rate_date    DATE           NOT NULL,
    currency     CHAR(3)        NOT NULL,
    rate_to_eur  DECIMAL(18,8)  NOT NULL,
    source       VARCHAR(10)    NOT NULL,
    _row_seq     INT            NOT NULL
);
GO
