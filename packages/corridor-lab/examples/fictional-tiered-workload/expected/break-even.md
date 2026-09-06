# Corridor Lab break-even workload exploration

Synthetic scenario: `fictional-tiered-workload`

Routes: `tiered-marginal` versus `flat-fee`.
Outcome: `crossing_between_declared_workloads`.

| Workload | Transactions per period | Left expected sender cost | Right expected sender cost | Difference |
| --- | ---: | ---: | ---: | ---: |
| low | 50 | 14.85 | 8.45 | 6.40 |
| base | 100 | 10.75 | 8.43 | 2.32 |
| peak | 400 | 7.68 | 8.41 | -0.73 |

The ordering reverses between `base` and `peak`. Corridor Lab does not interpolate between declared workloads, so no volume between them is claimed.

This is an ordering comparison under declared assumptions, not a recommendation.
