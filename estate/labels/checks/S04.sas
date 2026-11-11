/* Answer-key checks for S04 risk_scoring.sas (evaluation only).
   Run after the job: uv run lansh estate checks --job S04
   Creates work._lansh_checks: check_id, affected, detail. */

/* each line's mean paid, grouped: what the job's PROC SQL remerges onto every row */
proc sql;
  create table work._c_means as
  select lob_code, mean(paid) as line_mean
  from   rpt.risk_scores
  group  by lob_code;
quit;

proc sort data=rpt.risk_scores out=work._c_rs;
  by lob_code;
run;

data work._c_scores;
  merge work._c_rs work._c_means;
  by lob_code;
  length meant_tier $6;
  /* BUG-10 / SAS-11: the tier the rules give, with room for 'MEDIUM' */
  if score >= 35 then meant_tier = 'HIGH';
  else if score >= 22 then meant_tier = 'MEDIUM';
  else meant_tier = 'LOW';
  /* SAS-10: severity is paid over the remerged line mean... */
  line_ok = (abs(severity - paid / line_mean) <= 1e-12 * max(1, abs(severity)));
  /* ...whereas a per-customer mean makes severity 1 (or 0/0 when nothing is paid) */
  sev_points = 0;
  if severity >= 2 then sev_points = 10;
  else if severity >= 1 then sev_points = 5;
  own_points = ifn(paid ne 0, 5, 0);
  remerge_matters = (sev_points ne own_points);
  /* SAS-15 at line 98: SAS ROUND fuzzes a value just below a .xx5 tie upwards; Spark's
     round() rounds half up on the shortest decimal form of the double, so it rounds down */
  x = points * age_load * county_load;
  k = round(x * 200);
  spark_differs = (mod(k, 2) = 1 and x < k / 200 and abs(x - k / 200) < 1e-9);
  /* SAS-15 at line 96: round(v, 0.5) rounds to a half-point unit; Spark SQL's
     round(v, 0.5) silently uses scale 0 */
  v = 2.5 * loss_ratio;
  unit_matters = (round(v, 0.5) ne round(v));
run;

proc sql noprint;
  select count(*) into :n_rows trimmed from work._c_scores;
  select count(*) into :n_medi trimmed from work._c_scores where tier ne meant_tier;
  select count(*) into :n_line_ok trimmed from work._c_scores where line_ok;
  select count(*) into :n_remerge trimmed from work._c_scores where remerge_matters;
  select count(*) into :n_fuzz trimmed from work._c_scores where spark_differs;
  select count(*) into :n_unit trimmed from work._c_scores where unit_matters;
  select length into :tier_len trimmed from dictionary.columns
    where libname = 'RPT' and memname = 'RISK_SCORES' and upcase(name) = 'TIER';
  select count(*) into :n_low trimmed from work._c_scores where tier = 'LOW';
  select count(*) into :n_high trimmed from work._c_scores where tier = 'HIGH';
quit;

data work._lansh_checks;
  length check_id $60 detail $200;
  check_id = 'S04_BUG10_medium_stored_as_medi';
  affected = &n_medi;
  detail   = "&n_medi of &n_rows rows hold tier 'MEDI' where the rules give 'MEDIUM' (HIGH &n_high, LOW &n_low)";
  output;
  check_id = 'S04_SAS11_tier_length_from_first_assignment';
  affected = &n_medi;
  detail   = "tier was first assigned 'HIGH', so its length is &tier_len and 'MEDIUM' is cut to 'MEDI' on &n_medi rows";
  output;
  check_id = 'S04_SAS10_remerged_line_mean';
  affected = &n_remerge;
  detail   = "severity = paid / remerged line mean on &n_line_ok of &n_rows rows; a per-customer mean changes sev_points on &n_remerge rows";
  output;
  check_id = 'S04_SAS15_round_fuzz';
  affected = &n_fuzz;
  detail   = "&n_fuzz of &n_rows scores sit just below a .xx5 tie: SAS ROUND fuzzes them up, Spark round() rounds them down";
  output;
  check_id = 'S04_SAS15_round_unit';
  affected = &n_unit;
  detail   = "lob_points = round(2.5 * loss_ratio, 0.5) differs from rounding to scale 0, as Spark SQL round(v, 0.5) does, on &n_unit of &n_rows rows";
  output;
run;
