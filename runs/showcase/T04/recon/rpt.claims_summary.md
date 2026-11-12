### rpt.claims_summary: MATCH

MATCH: all 823 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 823 | 823 | ok |
| Total of `claim_id` | 248594498 | 248594498 | ok |
| Total of `policy_id` | 437355285 | 437355285 | ok |
| Total of `days_open` | 285214 | 285214 | ok |
| Total of `n_payments` | 1979 | 1979 | ok |
| Total of `total_paid` | 4267583.98 | 4267583.98 | ok |
| Total of `indemnity_reserve` | 5253371.37 | 5253371.37 | ok |
| Total of `expense_reserve` | 271669.04 | 271669.04 | ok |
| Total of `current_reserve` | 5525040.41 | 5525040.41 | ok |
| Total of `incurred` | 9792624.39 | 9792624.39 | ok |
| Records matched | | | 823 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `88c866643793` | `88c866643793` | identical |

Keys: ['claim_id'].
