/* Answer-key checks for S03 premium_bands.sas (evaluation only).
   Run after the job: uv run lansh estate checks --job S03
   Creates work._lansh_checks: check_id, affected, detail. */

proc format;
  /* the job's bands */
  value premband
    low  -< 0    = 'NEGATIVE'
    0    -< 250  = '0-249'
    250  -< 500  = '250-499'
    500  -< 1000 = '500-999'
    1000 - high  = '1000+'
    other        = 'UNKNOWN';
  /* inclusive upper bounds, as a translation with BETWEEN or <= would band */
  value premincl
    low  -< 0    = 'NEGATIVE'
    0    -  250  = '0-249'
    250  <- 500  = '250-499'
    500  <- 1000 = '500-999'
    1000 <- high = '1000+'
    other        = 'UNKNOWN';
run;

/* the job keeps each policy's first transaction in input (_row_seq) order */
proc sort data=dw.fact_premium_earned(keep=policy_id written_eur _row_seq)
          out=work._c_first nodupkey;
  by policy_id;
run;

/* the last one: what a reversed or arbitrary de-duplication could keep instead */
proc sort data=dw.fact_premium_earned(keep=policy_id written_eur _row_seq)
          out=work._c_rev;
  by policy_id descending _row_seq;
run;

proc sort data=work._c_rev out=work._c_last nodupkey;
  by policy_id;
run;

data work._c_cmp;
  merge work._c_first(rename=(written_eur=first_amt))
        work._c_last(rename=(written_eur=last_amt) drop=_row_seq);
  by policy_id;
  length first_band last_band incl_band $8;
  first_band = put(first_amt, premband.);
  last_band  = put(last_amt, premband.);
  incl_band  = put(first_amt, premincl.);
run;

proc sql noprint;
  select count(*) into :n_pol trimmed from work._c_cmp;
  select count(*) into :n_09 trimmed from work._c_cmp where first_band ne last_band;
  select count(*) into :n_12 trimmed from work._c_cmp where first_band ne incl_band;
quit;

data work._lansh_checks;
  length check_id $60 detail $200;
  check_id = 'S03_SAS09_nodupkey_keeps_first';
  affected = &n_09;
  detail   = "&n_09 of &n_pol policies change band if the de-duplication keeps their last transaction instead of the first in input order";
  output;
  check_id = 'S03_SAS12_format_range_boundaries';
  affected = &n_12;
  detail   = "&n_12 policies open on exactly 250, 500 or 1000: -< ranges band them upwards, inclusive upper bounds would band them down";
  output;
run;
