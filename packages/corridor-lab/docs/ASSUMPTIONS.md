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

An optional objective can rank routes only after every stated guardrail passes.
The v1 objectives are maximum expected recipient amount and minimum expected
sender cost. The available guardrails are minimum probability of successful
completion by the declared deadline and maximum tail time.
