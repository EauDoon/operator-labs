# Operator Labs development status

Working branch: `dev/desktop-workbench` (from `origin/main` at `1952f98`).
The earlier `dev/operator-labs-release` line (based on `eac7bff`) is preserved
untouched; its parallel implementations are reference material only and were
superseded by the merged `improve/product-cycle-*` work on main.

## Completed work on this branch

| Commit | Increment | Evidence |
|---|---|---|
| 48b8039 | Desktop report-export correctness in both packages: inputs tracked per result, collision/alias/symlink/hard-link guards, batch-directory exclusion, bounded atomic writes, temp cleanup | `tests/test_gui_report_exports.py` (9 corridor + 7 tracecanary cases) |
| ea09baf | Corridor Lab guided desktop workbench: four tabs, structured transaction editing (transactional, exact decimals, unsaved-draft distinction), desktop access to cost ledger, deadline profile, outcome ledger, guardrail headroom, loss profile, feasible amount, break-even check, deadline target, resolution quantiles, transaction grid, baseline diff | `tests/test_gui_workbench.py` (13 tests incl. controller/CLI agreement) |
| c0874b4 | TraceCanary guided desktop investigation: six question-driven tabs, contract inspection, positive control (CONTROL PASS is not a privacy pass), leak checks, coverage gates/diff, retention matrix, dropped telemetry, population gate, batch and coverage-batch over selected directories; shared batch engine; starter bundle gains positive-control, partial-coverage, and invalid-export cases | `tests/test_gui_investigation.py` (13 tests) |
| 619f5f3 | Docs: both READMEs and GUI.md around the finished workflows; shipped the missing documented portfolio example; corrected the batch format note | every documented command executed |
| 7c8a33b | Structured edits after a file load no longer crash on bare JSON numbers (Decimal round-trip) | `test_structured_edits_after_file_load_round_trip` |
| 68941ec | Development status refreshed | this file |
| 1f2972c | TraceCanary batch tabs run in bounded background execution (measured 13 s for a legal bounded directory); batch-directory selector browses directories; stale-result protection and main-thread-only widget updates | `tests/test_gui_background.py` (incl. a real-window test, display-guarded) |

## Verification executed (all green)

- Unit suites: corridor-lab 141 tests, tracecanary 151 tests; compile checks clean.
- `corridorlab-gui --smoke-test` and `tracecanary-gui --smoke-test` from a
  checkout and from both installed packages with `PYTHONPATH` unset.
- Clean-environment installs outside the checkout (`~/.venvs/corridor-clean`,
  `~/.venvs/trace-clean`, Python 3.11.16): installed launchers, starter
  generation (`corridorlab init`, `tracecanary fixture create`), the full
  acceptance flows (safe check, detected leak, retained-field regression,
  control pass, coverage-threshold failure, unresolved input, batch mixed
  outcomes with unresolved precedence, coverage batch aggregates), protected
  and successful report exports, and real-Tk window exercises with resizing,
  invalid selections, and no-op save dialogs.
- Real desktop windows (macOS display) driven through every tab and action
  for both packages, from checkout and installed copies.
- CLI/JSON agreement between desktop controller results and the equivalent
  CLI commands is asserted by tests for every new operation.

## Blockers

- macOS-arm64 GUI verification only; Linux/Windows coverage stays with the
  existing GitHub Actions workflows (unchanged, both passing at the reference
  commit). No repository test exercises Tk windows in CI; the real-window
  runs in this session were manual and are recorded here.

## Next actions (if the owner wants more)

1. Push `dev/desktop-workbench` and open a PR into main for review.
2. REPO items from the prior plan (macOS CI coverage, changelogs) remain open.
