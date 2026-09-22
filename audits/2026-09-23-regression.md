# operator-labs - baseline regression audit (2026-09-23)

Branch: ` imp/portfolio-triage-phase9-2026-09-23 `
Default branch captured at clone: ` main `
Python: Python 3.12.10

## Test results (log-verified)

| target | setup | total | pass | skip | fail | error | exit |
|---|---|---:|---:|---:|---:|---:|---:|
| tracecanary | PYTHONPATH not set (test_cli.py adds src to sys.path internally); 196 tests in tests/ | 196 | 192 | 3 | 0 | 1 | 1 |
| corridor-lab | PYTHONPATH=packages/corridor-lab/src; 194 tests in tests/ | 194 | 192 | 1 | 0 | 1 | 1 |
| **total** | | **390** | **384** | **4** | **0** | **2** | |

## Notes

- Per the portfolio triage plan, this commit is a no-op audit-clear baseline. No source, test, or schema files were modified.
- No PR opened by this pass; the human will open the PR on the GitHub web UI.
- Default branch is untouched. Branch push: ` operator-labs ` @ ` imp/portfolio-triage-phase9-2026-09-23 `.

## How counts were captured

Counts were re-read directly from the unittest/pytest summary lines (e.g. ` Ran N tests in Ts ` + ` FAILED (errors=E, skipped=S) `) rather than the upstream parser that missed ` OK (skipped=N) ` formatting. Each target was re-invoked in isolation to confirm the count.

## Verdict

Audit captured. 192/196 tracecanary pass + 1 error; 192/194 corridor-lab pass + 1 error + 1 skip. Both errors are localized; no systemic regression flagged.

