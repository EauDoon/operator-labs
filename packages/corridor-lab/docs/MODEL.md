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

## Declared tiered fee schedules (`corridor-lab.route/v2`)

A v2 route declares *either* a flat `fixed_fee_send` and `percent_fee_bps` pair
*or* a `fee_schedule`, never both. Mixing them is rejected because it would
double count the same charge.

A `fee_schedule` declares a `basis`, an ordered non-empty `tiers` array, and an
optional `period_charges` array. Tier `i` covers the half-open interval
`(lower_i, upper_i]` where `lower_0` is zero and `lower_i` is the previous tier's
`upper_bound_send`. An amount exactly equal to a bound belongs to that tier. The
final tier carries a null upper bound.

For `basis: whole_band`, with `k` the band containing the send amount `S`:

```text
percentage fee = S * p_k / 10000
transaction fee = F_k + percentage fee
```

For `basis: marginal`, each band's percentage applies only to the part of `S`
inside that band, and the fixed fee is charged once using the band containing
`S`:

```text
portion_i = max(0, min(S, upper_i) - lower_i)
percentage fee = sum_i portion_i * p_i / 10000
transaction fee = F_k + percentage fee
```

Fixed fees are never summed across bands, so a marginal schedule cannot charge
more than one fixed fee per transaction, and its percentage fee is continuous
across a band boundary.

A period charge is not incurred per transaction. Its per-transaction share is
always computed against an explicitly declared denominator:

```text
amortization_over: declared_transactions -> amount_send / period_transactions
amortization_over: scenario_volume      -> amount_send / V
```

where `V` is the transaction volume in force: the scenario's
`volume_per_period`, or the active declared workload's
`transactions_per_period`. The reported
`explicit_fee_send` is `transaction fee + amortized period charges`, and both
components are also reported separately, so neither is hidden or counted twice.

Because a `scenario_volume` period charge reduces the per-transaction deduction,
it also raises the recipient amount as volume rises. That is a direct
consequence of the declared amortization and is reported as such.

## Declared workload scenarios (`corridor-lab.scenario/v2`)

A workload is an author-declared number of transactions per period. For each
declared workload and route:

```text
liquidity carry per transaction = P * c / 10000 * d / 365 / V_workload
period sender cost = expected sender cost * V_workload
```

Pairwise break-even volume solves:

```text
fixed cost left + liquidity numerator left / V
= fixed cost right + liquidity numerator right / V
```

Only positive, finite solutions are reported. All outputs expose their route and
transaction assumptions so a reader can reconstruct the calculation.

Break-even volume therefore uses only the volume-independent part of the explicit
fee: a period charge amortized over `scenario_volume` moves with `V` by
declaration and is excluded, which keeps the documented equation valid.

`break-even` over declared workloads does not solve for a volume. It reports the
ordered per-workload costs of two routes and flags a reversal of their ordering
between two *adjacent declared* workloads. No volume between them is
interpolated or claimed.
