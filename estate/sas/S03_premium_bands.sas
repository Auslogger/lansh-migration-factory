/******************************************************************************
  Program  : premium_bands.sas
  Purpose  : Written and earned premium by line of business and premium band
             for the pricing committee. Each policy is banded once, on the
             premium of its first transaction as loaded, and all of its
             transactions are reported in that band.
  Inputs   : dw.fact_premium_earned
  Output   : rpt.premium_band_summary (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : RN

  Change log
    2016-02-22  RN    Initial version
    2017-05-08  RN    Top band split: 1000 and over (CR-1077)
    2019-10-14  CB    Transactions reported in their policy's band, not their
                      own (CR-1520)
    2022-03-07  CB    Policy count per band (CR-1951)
******************************************************************************/

/* premium bands used by pricing since 2017 */
proc format;
  value premband
    low  -< 0    = 'NEGATIVE'
    0    -< 250  = '0-249'
    250  -< 500  = '250-499'
    500  -< 1000 = '500-999'
    1000 - high  = '1000+'
    other        = 'UNKNOWN';
run;

/* one row per policy: its opening transaction, as loaded */
proc sort data=dw.fact_premium_earned(keep=policy_id lob_code written_eur)
          out=work.opening nodupkey;
  by policy_id;
run;

data work.policy_band(keep=policy_id lob_code prem_band);
  set work.opening;
  length prem_band $8;
  prem_band = put(written_eur, premband.);
run;

/* every transaction, in its policy's band */
proc sort data=dw.fact_premium_earned(keep=policy_id written_eur earned_eur)
          out=work.txn;
  by policy_id;
run;

data work.txn_band;
  merge work.txn(in=t) work.policy_band;
  by policy_id;
  if t;
run;

proc means data=work.txn_band noprint nway;
  class lob_code prem_band;
  var written_eur earned_eur;
  output out=work.premium_sums(drop=_type_ _freq_)
         n(written_eur)=n_transactions sum(written_eur)=written_eur
         sum(earned_eur)=earned_eur;
run;

proc means data=work.policy_band noprint nway;
  class lob_code prem_band;
  var policy_id;
  output out=work.policy_counts(drop=_type_ _freq_) n(policy_id)=n_policies;
run;

data rpt.premium_band_summary(keep=lob_code prem_band n_policies n_transactions
                                   written_eur earned_eur as_of_date);
  merge work.policy_counts work.premium_sums;
  by lob_code prem_band;
  format as_of_date yymmdd10.;
  as_of_date = &as_of;
run;
