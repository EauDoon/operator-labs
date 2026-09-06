# Limitations

- All input is synthetic and user-declared. The engine does not validate it
  against a market, institution, network, regulator, or dataset.
- A route template is an abstract scenario pattern. It does not represent or
  describe a production network, product, provider, or corridor.
- The model treats supplied outcome states as mutually exclusive and complete.
  Correlations, seasonality, operational queues, and feedback effects are out
  of scope.
- The liquidity model uses a simple annualized capital-cost allocation. It does
  not model balance-sheet constraints, intraday liquidity, or accounting.
- Tiered fee schedules are interpreted only under the two declared bases. A
  real-world tariff with rebates, minimums, caps, blended bands, or
  retroactive repricing is not represented and must not be inferred.
- Period charges are amortized linearly over a declared denominator. No
  seasonality, tier interaction, credit terms, or minimum-commitment behaviour
  is modelled.
- A workload is a declared transaction count, not an arrival process. Corridor
  Lab does not model queuing, concurrency, peaks within a period, or the
  variability of a declared volume.
- `break-even` over workloads reports a reversal between adjacent declared
  volumes. It does not interpolate, extrapolate, or solve for the crossing
  volume, and it does not imply a route is preferable at untested volumes.
- Funding schedules are discrete and declared. There is no arrival
  distribution, seasonality, queue, credit facility, intraday position, or
  foreign-exchange revaluation inside a period. Every delay is a whole number of
  declared periods, so a delay shorter than one period cannot be expressed.
- Funding figures are reported separately from per-transaction sender cost and
  are deliberately not summed into it. `Required prefunding`,
  `average tied-up capital`, and `expected loss` are different quantities and
  must not be added together.
- A declared schedule that ends does not imply full recovery. Recoveries whose
  arrival period falls beyond the last declared period are surfaced as
  `recoveries after horizon` instead of being dropped.
- Composed routes use declared joint outcomes. Corridor Lab does not assume leg
  failures are independent, does not multiply success probabilities, and does
  not derive a per-leg success rate. A dependency model the author does not
  declare cannot be evaluated.
- The send-currency aggregation of leg fees is a declared valuation convention
  based on the route's own declared rates. It is not a market conversion, a
  hedged rate, or a quote. Partitioned per-leg fees in each leg's own currency
  are always reported alongside the aggregate.
- A composed route models one payment travelling one declared chain. It does not
  model netting, batching, parallel settlement paths, or inventory rebalancing
  between legs.
- Currency labels and precision are formatting inputs, not ISO validation.
- Ranking only orders assumptions under an explicit objective and guardrails.
  It is not advice or an automated route selection decision.
- The optional desktop interface requires a local Tcl/Tk graphical environment.
  Its smoke test exercises controller logic only and deliberately creates no
  window.
- The scenario editor intentionally edits raw JSON rather than inferring missing
  assumptions. It accepts only a strictly validated fictional scenario and does
  not edit separately selected external route files.
