### rpt.risk_scores: MATCH

MATCH: all 2,645 rows agree record for record, compared on the keys ['customer_id', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 2,645 | 2,645 | ok |
| Total of `customer_id` | 291480785.0 | 291480785.0 | ok |
| Total of `n_claims` | 2911.0 | 2911.0 | ok |
| Total of `paid` | 12027486.519999988 | 12027486.519999987 | ok |
| Total of `n_recoveries` | 218.0 | 218.0 | ok |
| Total of `severity` | 2644.999999999999 | 2645.000000000001 | ok |
| Total of `age` | 140368.0 | 140368.0 | ok |
| Total of `age_load` | 2881.2000000000103 | 2881.20000000001 | ok |
| Total of `county_load` | 2780.0500000000507 | 2780.0500000000475 | ok |
| Total of `loss_ratio` | 1706.2735739276122 | 1706.273573927684 | ok |
| Total of `points` | 48141.5 | 48141.5 | ok |
| Total of `score` | 55003.30999999925 | 55003.30999999939 | ok |
| Records matched | | | 2,645 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `71253df91213` | `8e6b9e55ce0d` | - |

Keys: ['customer_id', 'lob_code'].
