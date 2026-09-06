# Fictional multi-period funding schedule

Everything here is invented: the currency code, the disbursement and recovery
schedule, the opening balance, the delays, and every route assumption. This
example demonstrates the `funding` block of `corridor-lab.scenario/v2`. It is
not a treasury model, a cash-flow forecast, or a statement about financing
availability.

## Declared schedule

```text
opening balance   1000.00 AMR
days per period   30
settlement delay  1 period
recovery delay    0 periods

period 1: disburse 1000.00, recover    0.00
period 2: disburse 1000.00, recover 1000.00
period 3: disburse 1000.00, recover 1000.00
```

## Hand-worked result at a zero recovery delay

Recoveries arriving strictly before a period are available for its
disbursement:

| Period | Balance start | Disbursement | Trough |
|---|---:|---:|---:|
| 1 | `1000.00` | `1000.00` | `0.00` |
| 2 | `0.00` | `1000.00` | `-1000.00` |
| 3 | `0.00` | `1000.00` | `-1000.00` |

```text
required prefunding  = max(1000 - 0, 1000 - (-1000), 1000 - (-1000)) = 2000.00
shortfall            = 2000.00 - 1000.00                             = 1000.00
shortfall periods    = 2 and 3 (period 1 ends exactly at zero, not below)
average tied-up      = mean(max(0, 1000), max(0, 0), max(0, 0))      = 333.33
carrying cost (1000 bps) = 1000 * 0.10 * 30 / 365                    = 8.22
carrying cost (600 bps)  = 1000 * 0.06 * 30 / 365                    = 4.93
expected loss (0.02 * 50 / 1000 rate) = 0.001 * 3000                 = 3.00
expected loss (0.01 * 50 / 1000 rate) = 0.0005 * 3000                = 1.50
```

Three quantities are kept deliberately apart. `Required prefunding` is the peak
funding that must be available; it does not depend on the declared opening
balance. `Average tied-up capital` is a holding statistic given that balance; it
is not a loss. `Expected loss` applies the route's declared per-transaction
unrecovered-principal rate to the declared total disbursements.

## Hand-worked result at a one-period recovery delay

With `recovery_delay_periods: 1`, each declared recovery arrives one period
later, so period 3 has seen no recovery at all:

| Period | Balance start | Disbursement | Trough |
|---|---:|---:|---:|
| 1 | `1000.00` | `1000.00` | `0.00` |
| 2 | `0.00` | `1000.00` | `-1000.00` |
| 3 | `-1000.00` | `1000.00` | `-2000.00` |

```text
required prefunding = 3000.00   (was 2000.00)
shortfall           = 2000.00   (was 1000.00)
recoveries after horizon = 1000.00   (period 3's recovery falls beyond the schedule)
```

The 1000.00 declared for period 3 would arrive in period 4. Because period 4 is
not declared, Corridor Lab reports it as `recoveries after horizon` rather than
dropping it: the end of a schedule is not evidence of full recovery.

## Reproduce

From `packages/corridor-lab`:

```text
python -m corridor_lab validate examples/fictional-funding/scenario.json
python -m corridor_lab funding examples/fictional-funding/scenario.json --delays 0,1 --format markdown
python -m corridor_lab funding examples/fictional-funding/scenario.json --delays 0,1 --format csv
python -m corridor_lab funding examples/fictional-funding/scenario.json
```

`expected/funding.md` and `expected/funding.csv` record the byte-exact output of
the second and third commands. Omitting `--delays` uses the schedule's own
declared `recovery_delay_periods`.

## What is not modelled

No arrival distribution, seasonality, financing availability, credit line,
intraday position, or forecast is involved. A period exists only because the
schedule declares it, and every delay is a whole number of declared periods.
