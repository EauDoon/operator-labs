# Assumptions

Every scenario must declare:

- Send amount, send and receive currency labels, both precisions, a rounding
  mode, deadline, and volume per period.
- Each route's rate, fixed fee, percentage fee, FX spread, prefunding amount,
  annual cost of capital, and holding period.
- A non-empty set of named outcome states whose probabilities sum exactly to
  one. Each state is either a success or failure and has an explicit delay.
- Recovery amount and recovery delay for failure states.

Supported rounding modes are `ROUND_HALF_UP`, `ROUND_HALF_EVEN`, `ROUND_DOWN`,
and `ROUND_UP`. Currency values are retained as `Decimal` calculations and
rounded only for a displayed amount at the declared currency precision.

Sensitivity changes exactly one of `fx_rate`, `fixed_fee_send`,
`percent_fee_bps`, or `fx_spread_bps` across the unchanged scenario. A stress
grid changes two of those same parameters. Both are what-if calculations, not
forecasts.

## Declared fee structures (`corridor-lab.route/v2`)

A v2 route declares exactly one fee basis:

- A flat `fixed_fee_send` plus `percent_fee_bps`, as in v1; or
- A `fee_schedule` with a `basis` of `marginal` or `whole_band`, an ordered
  `tiers` array, and optional `period_charges`.

Declaring both is rejected. Tiers are contiguous and ordered; only the final
tier may have a null `upper_bound_send`; tier bounds are half-open
`(lower, upper]`, so an amount equal to a bound belongs to that tier.

Each period charge declares how it is amortized: over its own
`period_transactions` (`declared_transactions`) or over the volume in force
(`scenario_volume`). The default path never guesses a denominator.

## Declared multi-leg composition (`corridor-lab.route/v2`)

A v2 route may declare `legs` instead of scalar rate and fee fields: an ordered
array of two to eight legs, each with a unique `leg_id`, distinct
`from_currency` and `to_currency`, a positive `fx_rate`, non-negative
`fx_spread_bps`, `fixed_fee_send`, `percent_fee_bps`, and `delay_hours`.

The chain must be contiguous: each leg's `from_currency` must equal the previous
leg's `to_currency`. No currency may appear twice, which rejects cycles and
revisits. The chain's endpoints must match the transaction's declared send and
receive currencies.

Every outcome of a composed route must declare a `terminal_leg`. Corridor Lab
does not assume leg failures are independent and does not multiply success
probabilities: the declared joint outcomes are taken exactly as declared.

## Declared workload scenarios (`corridor-lab.scenario/v2`)

A v2 scenario may declare `workload_scenarios`, each with a unique
`workload_id`, a `label`, and a positive `transactions_per_period`. Corridor Lab
never derives a volume: without a declared workload there is no workload
analysis.

## Declared funding schedules (`corridor-lab.scenario/v2`)

A v2 scenario may declare `funding` with `opening_balance_send`,
`days_per_period`, optionally `settlement_delay_periods` and
`recovery_delay_periods`, and an ordered non-empty `periods` array. Each period
declares `period_index` (strictly increasing from 1), `disbursements_send`, and
`recoveries_send`, all non-negative.

Every delay is a whole number of declared periods. Corridor Lab does not model
arrival distributions, intraday timing, financing availability, or credit
facilities, and does not forecast a period that the schedule does not declare.
Period figures are reported separately from per-transaction sender cost and are
never added to it.

An optional objective can rank routes only after every stated guardrail passes.
The v1 objectives are maximum expected recipient amount and minimum expected
sender cost. The available guardrails are minimum probability of successful
completion by the declared deadline and maximum tail time.
