# Corridor Lab funding and liquidity report

Synthetic scenario: `fictional-funding-schedule`

| Route | Recovery delay (periods) | Required prefunding | Declared opening balance | Shortfall | Shortfall periods | Average tied-up capital | Carrying cost | Expected loss |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| cheap-capital | 0 | 2000.00 | 1000.00 | 1000.00 | 2,3 | 333.33 | 4.93 | 1.50 |
| cheap-capital | 1 | 3000.00 | 1000.00 | 2000.00 | 2,3 | 333.33 | 4.93 | 1.50 |
| expensive-capital | 0 | 2000.00 | 1000.00 | 1000.00 | 2,3 | 333.33 | 8.22 | 3.00 |
| expensive-capital | 1 | 3000.00 | 1000.00 | 2000.00 | 2,3 | 333.33 | 8.22 | 3.00 |

## How to read this funding report

Every figure is in `AMR` and is driven only by the declared schedule. No arrival distribution, financing availability, or forecast is modelled.
`Required prefunding` is the peak funding that must be available so that no declared period falls below zero. It does not depend on the declared opening balance.
`Average tied-up capital` is a holding statistic given the declared opening balance. It is not a loss.
`Expected loss` applies the route's declared per-transaction unrecovered-principal rate to the declared total disbursements. Loss is not capital tied up, and capital tied up is not loss.
`Shortfall` is the gap between the required prefunding and the declared opening balance; `Shortfall periods` names the periods that fall below zero.
`Recoveries after horizon` counts declared recoveries whose arrival period falls beyond the last declared period. It is reported rather than dropped, so the end of a schedule is not a claim of full recovery.
In the period detail, `Recoveries declared` is what the schedule says that period recovers and `Recoveries arriving` is what actually arrives after the declared recovery delay, available for disbursement from the following period.
Declared schedule: `30`-day periods, settlement delay `1` periods, declared recovery delay `0` periods, opening balance `1000`.

### Declared period detail

`cheap-capital` with a recovery delay of `0` periods:

| Period | Balance start | Disbursements | Recoveries declared | Recoveries arriving | Trough | Unsettled exposure |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1000.00 | 1000.00 | 0.00 | 0.00 | 0.00 | 1000.00 |
| 2 | 0.00 | 1000.00 | 1000.00 | 1000.00 | -1000.00 | 1000.00 |
| 3 | 0.00 | 1000.00 | 1000.00 | 1000.00 | -1000.00 | 1000.00 |

`cheap-capital` with a recovery delay of `1` periods:

| Period | Balance start | Disbursements | Recoveries declared | Recoveries arriving | Trough | Unsettled exposure |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1000.00 | 1000.00 | 0.00 | 0.00 | 0.00 | 1000.00 |
| 2 | 0.00 | 1000.00 | 1000.00 | 0.00 | -1000.00 | 1000.00 |
| 3 | -1000.00 | 1000.00 | 1000.00 | 1000.00 | -2000.00 | 1000.00 |

`expensive-capital` with a recovery delay of `0` periods:

| Period | Balance start | Disbursements | Recoveries declared | Recoveries arriving | Trough | Unsettled exposure |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1000.00 | 1000.00 | 0.00 | 0.00 | 0.00 | 1000.00 |
| 2 | 0.00 | 1000.00 | 1000.00 | 1000.00 | -1000.00 | 1000.00 |
| 3 | 0.00 | 1000.00 | 1000.00 | 1000.00 | -1000.00 | 1000.00 |

`expensive-capital` with a recovery delay of `1` periods:

| Period | Balance start | Disbursements | Recoveries declared | Recoveries arriving | Trough | Unsettled exposure |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1000.00 | 1000.00 | 0.00 | 0.00 | 0.00 | 1000.00 |
| 2 | 0.00 | 1000.00 | 1000.00 | 0.00 | -1000.00 | 1000.00 |
| 3 | -1000.00 | 1000.00 | 1000.00 | 1000.00 | -2000.00 | 1000.00 |

