# Fictional tiered fee and workload corridor

Everything here is invented: currency codes, band boundaries, fees, period
charges, volumes, probabilities, and delays. This example demonstrates the
`corridor-lab.route/v2` and `corridor-lab.scenario/v2` contracts. It is not a
quote, forecast, recommendation, or representation of any payment network.

## Declared tiered schedule (`tiered-marginal`)

Three contiguous bands on the send amount, with the half-open convention
`(lower, upper]`:

| Band | Covers | Fixed fee | Percentage fee |
|---|---|---|---|
| 1 | `0 < amount <= 500` | `5.00 AMR` | `40` bps |
| 2 | `500 < amount <= 1500` | `3.00 AMR` | `25` bps |
| 3 | `amount > 1500` | `0` | `15` bps |

`basis: marginal` applies each band's percentage to the portion of the amount
inside that band and charges the fixed fee of the band containing the whole
amount exactly once. A send amount of `1000.00 AMR` splits as:

```text
band 1 portion = min(1000, 500) - 0    = 500  ->  500 * 40/10000  = 2.00
band 2 portion = min(1000, 1500) - 500 = 500  ->  500 * 25/10000  = 1.25
band 3 portion = 1000 - 1500 = -500 (not entered) -> 0
percentage fee = 3.25
fixed fee      = 3.00   (band 2 contains 1000)
transaction fee = 6.25
```

The declared `monthly-platform-fee` of `400.00 AMR` is amortized over the active
workload's transactions per period, so it contributes `8.00`, `4.00`, or `1.00`
at 50, 100, and 400 transactions respectively.

## Declared flat schedule (`flat-fee`)

`6.00 AMR` fixed plus `20` bps on `1000.00`, giving `8.00 AMR`, with no period
charges. Its fee therefore does not move with volume; only its liquidity
carrying cost does.

## Workload assumptions

`workload_scenarios` declares three volumes (50, 100, and 400 transactions per
period). Corridor Lab never derives a volume: a workload exists only when the
scenario declares it.

## Reproduce

From `packages/corridor-lab`:

```text
python -m corridor_lab validate examples/fictional-tiered-workload/scenario.json
python -m corridor_lab workload examples/fictional-tiered-workload/scenario.json --format markdown
python -m corridor_lab workload examples/fictional-tiered-workload/scenario.json --workloads low,peak --format csv
python -m corridor_lab break-even examples/fictional-tiered-workload/scenario.json --left tiered-marginal --right flat-fee --format markdown
python -m corridor_lab evaluate examples/fictional-tiered-workload/scenario.json
```

`expected/workload.md`, `expected/workload.csv`, and `expected/break-even.md`
record the byte-exact output of the `workload --format markdown`,
`workload --format csv`, and `break-even` commands above.

## What the break-even result means

The tiered route is more expensive at the declared low and base volumes and
cheaper at the declared peak volume. Corridor Lab reports the crossing as lying
between two *declared* workloads; it does not interpolate a volume between them
or estimate where the lines meet.
