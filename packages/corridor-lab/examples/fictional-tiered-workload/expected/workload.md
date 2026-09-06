# Corridor Lab workload report

Synthetic scenario: `fictional-tiered-workload`

| Workload | Route | Transactions per period | Fee basis | Transaction fee | Amortized period charge | Explicit fee | Liquidity carry | Expected sender cost | Period sender cost |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low | flat-fee | 50 | flat | 8.00 | 0.00 | 8.00 | 0.05 | 8.45 | 422.74 |
| low | tiered-marginal | 50 | marginal | 6.25 | 8.00 | 14.25 | 0.20 | 14.85 | 742.50 |
| base | flat-fee | 100 | flat | 8.00 | 0.00 | 8.00 | 0.03 | 8.43 | 842.74 |
| base | tiered-marginal | 100 | marginal | 6.25 | 4.00 | 10.25 | 0.10 | 10.75 | 1075.00 |
| peak | flat-fee | 400 | flat | 8.00 | 0.00 | 8.00 | 0.01 | 8.41 | 3362.74 |
| peak | tiered-marginal | 400 | marginal | 6.25 | 1.00 | 7.25 | 0.03 | 7.68 | 3070.00 |

## How to read this workload report

Sender-cost and fee figures are in `AMR`; recipient figures are in `BRC`.
Each row pairs one declared workload with one route. A workload is an author-declared number of transactions per period; it is not measured or forecast.
`Transaction fee` is the per-transaction tiered or flat fee. `Amortized period charge` spreads declared period charges across the workload's transactions.
`Period sender cost` is the per-transaction expected sender cost multiplied by the declared transactions per period.
Recipient amount changes across workloads only when a period charge is amortized over the scenario volume, because that charge reduces the per-transaction deduction. It is otherwise constant for the same route.
Successful-by-deadline probability does not depend on volume.
The scenario's own reference volume is `100` transactions per period.
