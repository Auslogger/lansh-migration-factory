### rpt.claim_fraud_flags: MATCH

MATCH: all 1,042 rows agree record for record, compared on the keys ['claim_id']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 1,042 | 1,042 | ok |
| Total of `claim_id` | 315090901 | 315090901 | ok |
| Total of `policy_id` | 553100929 | 553100929 | ok |
| Total of `customer_id` | 114690369 | 114690369 | ok |
| Total of `early_notification_flag` | 72 | 72 | ok |
| Total of `invalid_reg_flag` | 11 | 11 | ok |
| Total of `new_customer_flag` | 51 | 51 | ok |
| Total of `lob_mismatch_flag` | 1 | 1 | ok |
| Total of `fraud_score` | 135 | 135 | ok |
| Records matched | | | 1,042 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `dbeb53828d46` | `dbeb53828d46` | identical |

Keys: ['claim_id'].
