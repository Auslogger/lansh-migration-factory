### dw.dim_customer: MATCH

MATCH: all 20,000 rows agree record for record, compared on the keys ['customer_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 20,000 | 20,000 | ok |
| Total of `customer_id` | 2200010000 | 2200010000 | ok |
| Total of `email_shared_count` | 19336 | 19336 | ok |
| Total of `age_at_join` | 961043 | 961043 | ok |
| Total of `version_count` | 23799 | 23799 | ok |
| Records matched | | | 20,000 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `a0897c3f9194` | `a0897c3f9194` | identical |

Keys: ['customer_id'].
