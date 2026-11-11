/******************************************************************************
  Program  : risk_scoring.sas
  Purpose  : Customer risk score and referral tier by line of business for
             underwriting. Claims experience (claim count, recoveries and
             severity against the line's average) plus the line's loss ratio,
             loaded for the policyholder's age and county.
  Inputs   : dw.claims_enriched, rpt.premium_band_summary, dw.dim_customer
  Output   : rpt.risk_scores (rebuilt on every run)
  Params   : as_of - reporting date (SAS date), set by the scheduler
  Author   : TF

  Change log
    2015-06-02  TF    Initial version (motor only)
    2016-11-21  TF    Home and travel added; scoring per line in a macro
                      (CR-0998)
    2018-04-09  GH    Age and county loadings from the pricing review (CR-1302)
    2020-01-27  GH    Line loss ratio from premium_bands.sas (CR-1544)
    2022-09-12  TF    Referral tiers for the underwriting queue (CR-2011)
******************************************************************************/

/* policyholder loadings: age at the reporting date and county */
data work.cust(keep=customer_id age age_load county_load);
  set dw.dim_customer(keep=customer_id date_of_birth county);
  age = int((&as_of - date_of_birth) / 365.25);
  if missing(age) then age_load = 1.00;
  else if age < 25 then age_load = 1.40;
  else if age >= 70 then age_load = 1.25;
  else age_load = 1.00;
  select (upcase(strip(county)));
    when ('DUBLIN') county_load = 1.15;
    when ('CORK', 'LIMERICK', 'GALWAY') county_load = 1.05;
    otherwise county_load = 1.00;
  end;
run;

/* claims experience per customer and line of business */
proc sql;
  create table work.experience as
  select customer_id, lob_code,
         count(*)          as n_claims,
         sum(total_paid)   as paid,
         sum(n_recoveries) as n_recoveries
  from   dw.claims_enriched
  group  by customer_id, lob_code;
quit;

/* loss ratio per line: paid on the claims book over earned premium */
proc sql;
  create table work.lob_ratio as
  select e.lob_code, sum(e.paid) / p.earned as loss_ratio
  from   work.experience e,
         (select lob_code, sum(earned_eur) as earned
          from   rpt.premium_band_summary
          group  by lob_code) p
  where  e.lob_code = p.lob_code
  group  by e.lob_code, p.earned;
quit;

/* each customer against the average for the line */
%macro score_lines(lobs);
  %local i lob;
  %do i = 1 %to %sysfunc(countw(&lobs));
    %let lob = %scan(&lobs, &i);
    proc sql;
      create table work.score_&lob as
      select x.customer_id, x.lob_code, x.n_claims, x.paid, x.n_recoveries,
             x.paid / mean(x.paid) as severity
      from   work.experience x
      where  x.lob_code = "&lob";
    quit;
  %end;
%mend score_lines;

%score_lines(MOT HOM TRV);

proc sql;
  create table work.scoring as
  select s.*, c.age, c.age_load, c.county_load, r.loss_ratio
  from   (select * from work.score_mot
          union all
          select * from work.score_hom
          union all
          select * from work.score_trv) s
         left join work.cust c on c.customer_id = s.customer_id
         left join work.lob_ratio r on r.lob_code = s.lob_code
  order  by s.customer_id, s.lob_code;
quit;

/* points, loadings and the referral tier */
data rpt.risk_scores(keep=customer_id lob_code n_claims paid n_recoveries severity age
                          age_load county_load loss_ratio points score tier as_of_date);
  set work.scoring;
  sev_points = 0;
  if severity >= 2 then sev_points = 10;
  else if severity >= 1 then sev_points = 5;
  lob_points = round(2.5 * loss_ratio, 0.5);
  points = 12.5 * min(n_claims, 4) + 7.5 * n_recoveries + sev_points + lob_points;
  score  = round(points * age_load * county_load, 0.01);
  if score >= 35 then tier = 'HIGH';
  else if score >= 22 then tier = 'MEDIUM';
  else tier = 'LOW';
  format as_of_date yymmdd10.;
  as_of_date = &as_of;
run;
