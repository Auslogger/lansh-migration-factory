### rpt.claim_aging: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 2904669.63 | 2904669.63 | ok |
| Total of `days_since_activity` | 118343 | 118343 | ok |
| Total of `weeks_open` | 40753 | 40753 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `52e8d5320a5c` | `52e8d5320a5c` | identical |

Keys: ['claim_id'].
