# Corridor Lab report

Synthetic scenario: `fictional-amber-to-birch`

| Route | Recipient (BRC) | Expected recipient (BRC) | Expected sender cost (AMR) | Successful by deadline probability | Tail hours |
| --- | ---: | ---: | ---: | ---: | ---: |
| fictional-correspondent-style | 1713.44 | 1610.63 | 12.69 | 0 | 84 |
| fictional-fiat-token-bridge | 1731.67 | 1679.72 | 6.21 | 0.97 | 4 |
| fictional-linked-instant | 1726.45 | 1691.92 | 6.42 | 0.98 | 8 |
| fictional-tokenized-deposit | 1735.16 | 1709.13 | 4.38 | 0.985 | 0.5 |

## Explicit objective ranking

Metric: `maximize_expected_recipient_amount`

| Rank | Route | Objective value |
| ---: | --- | ---: |
| 1 | fictional-tokenized-deposit | 1709.1291525 |
| 2 | fictional-linked-instant | 1691.924675 |
| 3 | fictional-fiat-token-bridge | 1679.72293125 |

### Guardrail rejections

| Route | Failed guardrails |
| --- | --- |
| fictional-correspondent-style | Minimum successful-by-deadline probability; Maximum tail time |

## How to read this report

Recipient figures are in `BRC` and sender-cost figures are in `AMR`.
`Recipient` is conditional on success; `Expected recipient` assigns zero recipient value to failure outcomes.
`Expected sender cost` combines declared explicit fees, liquidity carrying cost, and expected unreturned principal after failure and recovery.
`Successful by deadline probability` counts success states only when their declared delay is no greater than the stated deadline.
Completion-time metrics are discrete outcome percentiles: median is the 50th percentile and tail time is the 95th percentile of time to a final state.
The explicit objective is to maximize expected recipient amount, with guardrails: minimum successful-by-deadline probability `0.85`; maximum tail time `72` hours. The displayed ranking is an ordering under those declared conditions, not a recommendation.

### Break-even volume

- `fictional-correspondent-style` and `fictional-fiat-token-bridge` have no positive break-even volume under the declared sender-cost model.
- `fictional-correspondent-style` and `fictional-linked-instant` have no positive break-even volume under the declared sender-cost model.
- `fictional-correspondent-style` and `fictional-tokenized-deposit` have no positive break-even volume under the declared sender-cost model.
- `fictional-fiat-token-bridge` and `fictional-linked-instant` have no positive break-even volume under the declared sender-cost model.
- `fictional-fiat-token-bridge` and `fictional-tokenized-deposit` have no positive break-even volume under the declared sender-cost model.
- `fictional-linked-instant` and `fictional-tokenized-deposit` have no positive break-even volume under the declared sender-cost model.
