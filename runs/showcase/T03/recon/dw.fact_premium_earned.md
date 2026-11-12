### dw.fact_premium_earned: MATCH

MATCH: all 67,879 rows agree record for record, compared on the keys ['txn_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 67,879 | 67,879 | ok |
| Total of `txn_id` | 477457288333 | 477457288333 | ok |
| Total of `policy_id` | 36027338916 | 36027338916 | ok |
| Total of `policy_sk` | 2451710359 | 2451710359 | ok |
| Total of `amount` | 23878512.88 | 23878512.88 | ok |
| Total of `fx_rate` | 68243.18983386 | 68243.18983386 | ok |
| Total of `written_eur` | 24033402.72 | 24033402.72 | ok |
| Total of `term_days` | 22352049 | 22352049 | ok |
| Total of `earned_days` | 17376000 | 17376000 | ok |
| Total of `earned_pct` | 5370266 | 5370266 | ok |
| Total of `earned_eur` | 18768844.41 | 18768844.41 | ok |
| Total of `unearned_eur` | 5264558.31 | 5264558.31 | ok |
| Total of `daily_rate_eur` | 79181.1928 | 79181.1928 | ok |
| Total of `monthly_instalment_eur` | 2121880.48 | 2121880.48 | ok |
| Records matched | | | 67,879 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8877a71b1cda` | `8877a71b1cda` | identical |

Keys: ['txn_id'].
