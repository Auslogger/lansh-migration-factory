/******************************************************************************
  Program  : claims_enrich.sas
  Purpose  : Claim-level payment history for the risk team. One row per claim
             on the claims register with its payments up to the reporting
             date: payment and recovery counts, paid to date, the paid split
             by payment type (gross, and net of recoveries), the first and
             last payment dates and a recovery marker. Read by the customer
             risk scoring (risk_scoring.sas).
  Inputs   : stg.claims, stg.claim_payments
  Output   : dw.claims_enriched (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : DOS

  Change log
    2014-03-10  DOS   Initial version
    2015-08-24  DOS   Recoveries counted and flagged for the subrogation desk
                      (CR-0611)
    2017-01-16  AK    Paid split by payment type; gross and net paid (CR-1042)
    2018-11-05  AK    Payments dated after the reporting date left out
                      (INC-1677)
    2019-09-30  AK    Line of business and status tidied for the MI pack
                      (CR-1502)
    2021-06-14  SMcC  Claims with nothing paid yet kept, with has_payment, for
                      risk_scoring.sas (CR-1873)
******************************************************************************/

/* claims register */
proc sort data=stg.claims(keep=claim_id claim_number policy_id customer_id lob_code
                               loss_date reported_date status)
          out=work.claims;
  by claim_id;
run;

/* payments to the reporting date, claim by claim in the order they were keyed */
proc sort data=stg.claim_payments(keep=claim_id payment_date amount payment_type _row_seq
                                  where=(payment_date <= &as_of))
          out=work.payments;
  by claim_id _row_seq;
run;

/* roll the payments up to one row per claim */
data work.pay_summary(keep=claim_id n_payments n_recoveries total_paid indemnity_amt
                           expense_amt recovery_amt first_payment_date last_payment_date
                           recovery_flag);
  set work.payments;
  by claim_id;
  length ptype $12;
  retain n_payments n_recoveries total_paid indemnity_amt expense_amt recovery_amt
         first_payment_date last_payment_date recovery_flag;
  format first_payment_date last_payment_date date9.;

  if first.claim_id then do;
    n_payments    = 0;
    n_recoveries  = 0;
    total_paid    = 0;
    indemnity_amt = 0;
    expense_amt   = 0;
    recovery_amt  = 0;
    recovery_flag = 0;
    first_payment_date = payment_date;
  end;

  n_payments + 1;
  total_paid + amount;

  /* paid split by payment type (keyed in mixed case) */
  ptype = upcase(strip(payment_type));
  if ptype = 'INDEMNITY' then indemnity_amt = indemnity_amt + amount;
  else if ptype = 'EXPENSE' then expense_amt = expense_amt + amount;
  else if ptype = 'RECOVERY' then recovery_amt = recovery_amt + amount;

  /* recoveries (salvage, third-party) come through as negative amounts */
  if amount < 0 then do;
    recovery_flag = 1;
    n_recoveries + 1;
  end;

  last_payment_date = payment_date;
  if last.claim_id then output;
run;

/* enrich the register: every claim is reported, paid or not */
data dw.claims_enriched(keep=claim_id claim_number policy_id customer_id lob_code
                             loss_date reported_date status n_payments n_recoveries
                             total_paid indemnity_amt expense_amt recovery_amt gross_paid
                             net_paid first_payment_date last_payment_date recovery_flag
                             has_payment);
  merge work.claims(in=c) work.pay_summary(in=p);
  by claim_id;
  if c;

  lob_code = upcase(strip(lob_code));
  status   = upcase(strip(status));

  has_payment = p;
  if not p then do;
    n_payments    = 0;
    n_recoveries  = 0;
    total_paid    = 0;
    recovery_flag = 0;
  end;

  gross_paid = indemnity_amt + expense_amt;
  net_paid   = sum(indemnity_amt, expense_amt, recovery_amt);
run;

proc datasets lib=work nolist;
  delete claims payments pay_summary;
quit;
