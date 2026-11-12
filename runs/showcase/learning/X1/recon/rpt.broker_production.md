### rpt.broker_production: MATCH

MATCH: all 126 rows agree record for record, compared on the keys ['broker_code', 'lob_code']; counts, totals and every compared column agree under their policies.

| Check | Legacy | Candidate | Result |
|---|---|---|---|
| Schema | | | ok |
| Rows | 126 | 126 | ok |
| Total of `policies_in_force` | 21466 | 21466 | ok |
| Total of `gwp_eur` | 9177239.83 | 9177239.83 | ok |
| Total of `claims_notified` | 1042 | 1042 | ok |
| Total of `claims_paid_eur` | 4010931.67 | 4010931.67 | ok |
| Total of `paid_to_written` | 60.0255 | 60.0255 | ok |
| Records matched | | | 126 |
| Records differing | | | 0 value, 0 missing, 0 extra |
| Content hash | `8db4e15fa848` | `8db4e15fa848` | identical |

Keys: ['broker_code', 'lob_code'].
