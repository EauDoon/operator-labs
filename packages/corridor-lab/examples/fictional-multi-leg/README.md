# Fictional multi-leg route composition

Everything here is invented: currency codes, leg rates, spreads, fees, delays,
probabilities, and recoveries. This example demonstrates the `legs` block of
`corridor-lab.route/v2`. It is not a description of any payment network.

## Declared chain

| Leg | From | To | Rate | Spread | Fixed fee | Percentage fee | Delay |
|---|---|---|---:|---:|---:|---:|---:|
| `onshore` | `AMR` | `USD` | `1.25` | `20` bps | `1.00` | `10` bps | `1` h |
| `offshore` | `USD` | `BRC` | `1.40` | `30` bps | `2.00` | `15` bps | `3` h |

## Hand-worked leg-by-leg walk

Leg fees are charged in each leg's `from_currency` and deducted before that leg
converts:

```text
leg 1: amount 1000.00 AMR
       fee      = 1.00 + 1000.00 * 10/10000        = 2.00 AMR
       convert  = (1000.00 - 2.00) * 1.25          = 1247.50 USD
       spread   = 1247.50 * 20/10000               = 2.495 USD
       amount   = 1245.005 USD
       effective rate e1 = 1.25 * (1 - 20/10000)   = 1.2475

leg 2: amount 1245.005 USD
       fee      = 2.00 + 1245.005 * 15/10000       = 3.8675075 USD
       convert  = (1245.005 - 3.8675075) * 1.40    = 1737.5924895 BRC
       spread   = 1737.5924895 * 30/10000          = 0.52127774... BRC
       amount   = 1737.0712117353... BRC
       effective rate e2 = 1.40 * (1 - 30/10000)   = 1.3958
```

To express one send-currency sender cost, each leg fee is converted back using
the declared effective rates of the preceding legs:

```text
fee in send = 2.00 + 3.8675075 / 1.2475            = 5.10020641... AMR
recipient   = (1000 - 5.10020641...) * (1.2475 * 1.3958)
            = 1732.3797120315 BRC
```

That identity is exact for the declared chain: the step-by-step walk and the
aggregated form agree to the last digit. The conversion is a declared valuation
convention, not a market quote. Both leg fees are also reported partitioned in
their own currencies (`2.00 AMR` and `3.8675075 USD`), so nothing is hidden by
the conversion.

## Declared joint outcomes

Failures across legs are not assumed independent and success probabilities are
never multiplied. Each outcome names the leg at which the payment terminates:

| Outcome | Probability | Terminal leg | Resolution time |
|---|---:|---|---:|
| `completed` | `0.95` | `offshore` | `1 + 3 = 4` h |
| `failed-on-leg-1` | `0.03` | `onshore` | `1 + 12 = 13` h |
| `failed-on-leg-2` | `0.02` | `offshore` | `4 + 24 = 28` h |

```text
success probability          = 0.95 (declared, not a product of leg rates)
expected completion time     = 0.95*4 + 0.03*13 + 0.02*28 = 4.75 h
expected failure cost        = 0.03*(1000-995) + 0.02*(1000-990) = 0.35 AMR
```

A success outcome must terminate at the final leg, because a composed route only
completes when every leg completes. A failure may terminate at any leg.

## Reproduce

From `packages/corridor-lab`:

```text
python -m corridor_lab validate examples/fictional-multi-leg/scenario.json
python -m corridor_lab evaluate examples/fictional-multi-leg/scenario.json --format markdown
python -m corridor_lab evaluate examples/fictional-multi-leg/scenario.json --format json
```

`expected/evaluate.md` and `expected/evaluate.json` record the byte-exact output
of the second and third commands.

The bundled `single-leg-direct` route declares the same end-to-end effective
rate (`1.7412605`) and a flat `5.10` fee, so the comparison isolates the effect
of the declared joint outcomes: identical recipient amount, and a small
difference in expected recipient amount driven only by the declared recoveries.

## What is rejected

- Fewer than two legs, or more than eight.
- A chain whose `from_currency` does not continue the previous leg's
  `to_currency`.
- A chain that revisits a currency, which by construction rejects cycles.
- A chain whose endpoints do not match the transaction's declared send and
  receive currencies.
- Mixing scalar `fx_rate`, `fx_spread_bps`, `fixed_fee_send`,
  `percent_fee_bps`, or `fee_schedule` with `legs`; each leg carries its own.
- A success outcome whose `terminal_leg` is not the final leg.
