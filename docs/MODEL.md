# Model

Corridor Lab evaluates finite, mutually exclusive outcome states with `Decimal`
arithmetic. It neither estimates an outcome distribution nor fetches one. The
scenario author supplies every probability, price, fee, delay, and liquidity
assumption.

For a send amount `S`, fixed fee `F`, percentage fee `p` basis points, reference
FX rate `r`, and FX spread `s` basis points:

```text
percentage fee = S * p / 10000
amount converted = S - F - percentage fee
gross recipient = amount converted * r
FX spread cost = gross recipient * s / 10000
conditional recipient amount = gross recipient - FX spread cost
```

The conditional recipient amount applies when the route completes successfully.
Expected recipient amount multiplies it by the sum of success-state
probabilities. Failure states have zero recipient value.

For declared prefunding `P`, annual capital cost `c` basis points, holding days
`d`, and transaction volume `V` per period:

```text
liquidity carry per transaction = P * c / 10000 * d / 365 / V
```

Expected failure and recovery cost is the probability-weighted principal not
recovered in failure states. Explicit fees remain separately visible, so that
metric does not double count them.

`probability_by_deadline` is the sum of success-state probabilities whose
`delay_hours` is no greater than the declared deadline. It excludes failure and
recovery outcomes, even when they resolve by the deadline.

Time metrics use time to a final outcome. A successful outcome resolves after
its `delay_hours`; a failure resolves after `delay_hours + recovery_delay_hours`.
The median and tail metrics are discrete 50th and 95th percentiles respectively.

Pairwise break-even volume solves:

```text
fixed cost left + liquidity numerator left / V
= fixed cost right + liquidity numerator right / V
```

Only positive, finite solutions are reported. All outputs expose their route and
transaction assumptions so a reader can reconstruct the calculation.
