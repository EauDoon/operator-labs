# Corridor Lab report

Synthetic scenario: `fictional-multi-leg-corridor`

| Route | Recipient (BRC) | Expected recipient (BRC) | Expected sender cost (AMR) | Successful by deadline probability | Tail hours |
| --- | ---: | ---: | ---: | ---: | ---: |
| single-leg-direct | 1732.38 | 1645.76 | 5.48 | 0.95 | 4 |
| two-leg-chain | 1732.38 | 1645.76 | 5.48 | 0.95 | 4 |

## Explicit objective ranking

Metric: `maximize_expected_recipient_amount`

| Rank | Route | Objective value |
| ---: | --- | ---: |
| 1 | single-leg-direct | 1645.7610678775 |
| 2 | two-leg-chain | 1645.760726429925 |

## How to read this report

Recipient figures are in `BRC` and sender-cost figures are in `AMR`.
`Recipient` is conditional on success; `Expected recipient` assigns zero recipient value to failure outcomes.
`Expected sender cost` combines declared explicit fees, liquidity carrying cost, and expected unreturned principal after failure and recovery.
`Successful by deadline probability` counts success states only when their declared delay is no greater than the stated deadline.
Completion-time metrics are discrete outcome percentiles: median is the 50th percentile and tail time is the 95th percentile of time to a final state.
The explicit objective is to maximize expected recipient amount, with guardrails: minimum successful-by-deadline probability `0.9`. The displayed ranking is an ordering under those declared conditions, not a recommendation.

### Break-even volume

- `single-leg-direct` and `two-leg-chain` have no positive break-even volume under the declared sender-cost model.
