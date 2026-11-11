/******************************************************************************
  S01 claims_enrich.sas -> dw.claims_enriched: answer-key checks
  (evaluation only: factory code never reads this file).

  Runs after the job, in a new session, with librefs stg, dw and rpt and the
  macro variable &as_of. Reads only stg and dw data sets. Writes
  work._lansh_checks (check_id $60, affected 8, detail $200), one row per
  check: each armed semantic trap and the bug. A check counts the rows where
  the legacy SAS behaviour and the naive (Spark) or intended behaviour give
  different results on our data; a positive count passes.
******************************************************************************/

/* Each claim's payments up to the as-of date, counted NULL-aware. */
proc sql;
  create table work._k_pay as
  select claim_id,
         count(*) as n_rows,
         sum(case when amount is not missing and amount < 0 then 1 else 0 end)
           as n_negative,
         sum(case when upcase(strip(payment_type)) = 'INDEMNITY' then amount
                  else . end) as ind_sum,
         sum(case when upcase(strip(payment_type)) = 'EXPENSE' then amount
                  else . end) as exp_sum,
         sum(amount) as sql_sum,
         min(payment_date) as min_date format=yymmdd10.,
         max(payment_date) as max_date format=yymmdd10.
  from stg.claim_payments
  where payment_date <= &as_of
  group by claim_id;
quit;

/* check: S01_BUG08_missing_amount_counted_as_recovery
   proves: n_recoveries and recovery_flag in dw.claims_enriched also count payments
   with no amount (if amount < 0 is true for a missing amount); counting negative
   amounts only, as intended, gives different values on these claims. */
proc sql noprint;
  create table work._k_bug08 as
  select e.claim_id, e.n_recoveries, e.recovery_flag,
         coalesce(k.n_negative, 0) as n_negative
  from dw.claims_enriched as e
       left join work._k_pay as k
       on k.claim_id = e.claim_id;

  select count(*),
         sum(n_recoveries - n_negative),
         sum(case when recovery_flag = 1 and n_negative = 0 then 1 else 0 end)
    into :bug08_n trimmed, :bug08_extra trimmed, :bug08_flag trimmed
  from work._k_bug08
  where n_recoveries ne n_negative
     or recovery_flag ne (n_negative > 0);
quit;

/* check: S01_SAS01_missing_lt_zero
   proves: SAS evaluates amount < 0 as true when amount is missing (a missing value
   is smaller than any number); in Spark NULL < 0 is NULL, never true, so a direct
   translation of the test does not count these payments. Counts the payments, on
   claims in the output, where the two semantics disagree. */
data work._k_sas01;
  set stg.claim_payments(keep=claim_id payment_date amount
                         where=(payment_date <= &as_of));
  sas_lt  = (amount < 0);
  null_lt = (not missing(amount) and amount < 0);
  if sas_lt ne null_lt;
run;

proc sql noprint;
  select count(*), count(distinct claim_id)
    into :sas01_n trimmed, :sas01_claims trimmed
  from work._k_sas01
  where claim_id in (select claim_id from dw.claims_enriched);

  select sum(n_recoveries) into :sas01_rec trimmed from dw.claims_enriched;

  select sum(n_negative) into :sas01_neg trimmed
  from work._k_pay
  where claim_id in (select claim_id from dw.claims_enriched);
quit;

/* check: S01_SAS02_plus_vs_sum
   proves: the + operator propagates a missing value and sum() ignores it. The job
   adds indemnity_amt and expense_amt up with +, so one unkeyed amount leaves the
   component missing; gross_paid (+) is then missing where sum() of the same values
   is not, and net_paid (sum()) has a value where + would be missing. Counts the
   output rows where + and sum() over the same values disagree. */
data work._k_sas02;
  set dw.claims_enriched(keep=claim_id indemnity_amt expense_amt recovery_amt
                              gross_paid net_paid);
  sum_gross = sum(indemnity_amt, expense_amt);
  plus_net  = indemnity_amt + expense_amt + recovery_amt;
  gross_differs = (missing(gross_paid) ne missing(sum_gross));
  net_differs   = (missing(net_paid) ne missing(plus_net));
  if gross_differs or net_differs;
run;

proc sql noprint;
  select count(*), sum(gross_differs), sum(net_differs), sum(sum_gross) format=16.2
    into :sas02_n trimmed, :sas02_gross trimmed, :sas02_net trimmed,
         :sas02_eur trimmed
  from work._k_sas02;

  /* the components themselves: + leaves them missing where SQL sum() has a value */
  select count(*) into :sas02_comp trimmed
  from dw.claims_enriched as e
       inner join work._k_pay as k
       on k.claim_id = e.claim_id
  where (e.indemnity_amt is missing and k.ind_sum is not missing)
     or (e.expense_amt is missing and k.exp_sum is not missing);
quit;

/* check: S01_SAS05_merge_in_keeps_register_claims
   proves: merge claims(in=c) pay_summary(in=p); if c; keeps every register claim,
   paid or not, and drops payments on claims missing from the register. An inner
   join would drop the unpaid claims; a merge without the subsetting IF (a full
   outer join) would add the orphan claim ids. Counts both kinds of row. */
proc sql noprint;
  select count(*), sum(case when has_payment = 0 then 1 else 0 end)
    into :sas05_unpaid trimmed, :sas05_flag0 trimmed
  from dw.claims_enriched
  where claim_id not in (select claim_id from work._k_pay);

  select count(*), sum(n_rows), sum(sql_sum) format=16.2
    into :sas05_orphan trimmed, :sas05_orphan_pay trimmed, :sas05_orphan_eur trimmed
  from work._k_pay
  where claim_id not in (select claim_id from stg.claims)
    and claim_id not in (select claim_id from dw.claims_enriched);
quit;

/* check: S01_SAS06_first_last_by_extract_order
   proves: first_payment_date and last_payment_date come from the first and last
   payment in extract order (_row_seq: the job sorts by claim_id _row_seq and keeps
   the dates with RETAIN at first.claim_id and last.claim_id). The earliest and
   latest payment_date (min/max, the naive translation) differ on these claims. */
proc sql noprint;
  create table work._k_sas06 as
  select e.claim_id,
         (e.first_payment_date ne k.min_date) as first_differs,
         (e.last_payment_date ne k.max_date) as last_differs
  from dw.claims_enriched as e
       inner join work._k_pay as k
       on k.claim_id = e.claim_id
  where e.first_payment_date ne k.min_date
     or e.last_payment_date ne k.max_date;

  select count(*), sum(first_differs), sum(last_differs)
    into :sas06_n trimmed, :sas06_first trimmed, :sas06_last trimmed
  from work._k_sas06;

  /* the sum statement starts at 0 and skips missing amounts: SQL sum() is missing */
  select count(*) into :sas06_zero trimmed
  from dw.claims_enriched as e
       inner join work._k_pay as k
       on k.claim_id = e.claim_id
  where e.total_paid = 0 and k.sql_sum is missing;
quit;

data work._lansh_checks;
  length check_id $60 affected 8 detail $200;

  check_id = 'S01_BUG08_missing_amount_counted_as_recovery';
  affected = &bug08_n;
  detail   = "&bug08_n claims over-count recoveries by &bug08_extra payments with no "
             || "amount; &bug08_flag have recovery_flag=1 without any negative payment";
  output;

  check_id = 'S01_SAS01_missing_lt_zero';
  affected = &sas01_n;
  detail   = "&sas01_n payments with a missing amount pass amount < 0 (on &sas01_claims "
             || "output claims): n_recoveries totals &sas01_rec, negative amounts "
             || "&sas01_neg";
  output;

  check_id = 'S01_SAS02_plus_vs_sum';
  affected = &sas02_n;
  detail   = "&sas02_n rows: gross_paid (+) missing where sum() gives a value on "
             || "&sas02_gross (EUR &sas02_eur), net_paid set where + is missing on "
             || "&sas02_net; &sas02_comp claims lose a component to +";
  output;

  check_id = 'S01_SAS05_merge_in_keeps_register_claims';
  affected = &sas05_unpaid + &sas05_orphan;
  detail   = "&sas05_unpaid unpaid register claims kept (has_payment=0 on &sas05_flag0; "
             || "an inner join drops them); &sas05_orphan orphan claim ids with "
             || "&sas05_orphan_pay payments (EUR &sas05_orphan_eur) dropped";
  output;

  check_id = 'S01_SAS06_first_last_by_extract_order';
  affected = &sas06_n;
  detail   = "&sas06_n claims: first_payment_date not the earliest (&sas06_first) or "
             || "last_payment_date not the latest (&sas06_last); total_paid 0 where "
             || "SQL sum() is missing on &sas06_zero";
  output;
run;

proc datasets lib=work nolist;
  delete _k_pay _k_bug08 _k_sas01 _k_sas02 _k_sas06;
quit;
