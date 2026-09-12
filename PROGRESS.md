# Operator Labs development status

Working branch: `dev/desktop-workbench` (from `origin/main` at `1952f98`).
The earlier `dev/operator-labs-release` line (based on `eac7bff`) is preserved
untouched; its parallel implementations are reference material only and were
superseded by the merged `improve/product-cycle-*` work on main.

## Baseline verification at 1952f98 (executed, green)

| Check | Command (from the package directory) | Result |
|---|---|---|
| Corridor Lab unit tests | `PYTHONPATH=src python -m unittest discover -s tests -v` | 120 passed |
| TraceCanary unit tests | `python -m unittest discover -s tests -v` | 128 passed |
| Compile checks | `python -m compileall -q src` (both) | clean |
| GUI smoke tests | `corridorlab-gui --smoke-test`, `tracecanary-gui --smoke-test` | pass |

Python 3.11.16 (macOS/arm64, uv build with tkinter). Environment note: the
homebrew `python3.13` on this machine has no `_tkinter`; the 3.11.16
interpreter is used for all GUI work. TraceCanary tests self-expose `src`;
Corridor Lab tests need `PYTHONPATH=src` (matches CI).

## Gaps confirmed by inspection (goal items)

1. Export correctness:
   - `tracecanary/gui.py` `_save` writes with `Path.write_text` directly:
     no atomic replace, no output byte budget, no input-collision guard,
     despite `output.py` providing `protect_inputs`/`write_report`.
   - `corridor_lab/gui_controller.py` `save_last_report` uses
     `atomic_write_text` but never checks report destinations against the
     scenario/route inputs the way the CLI `_protect_report_inputs` does.
   - Neither GUI tracks which input files/directories a report described at
     generation time, so a report could later overwrite one of them.
2. Corridor desktop: GUI exposes only compare/evaluate/sensitivity/stress
   grid/transaction sweep/pareto; the CLI's cost ledger, deadline profile,
   guardrail headroom, outcome ledger, deadline target, resolution quantiles,
   loss profile, feasible amount, break-even check, and scenario diff are not
   reachable from the desktop. No structured transaction editing.
3. TraceCanary desktop: GUI exposes validate/check/coverage/diff/demo/starter
   only; inspection, control check, population gate, dropped telemetry,
   retention matrix, coverage gate/diff, batch, and coverage-batch are CLI
   only. Starter bundle has no partial-coverage (threshold failure) case.
4. Docs: GUI sections lag the current command set.

## Plan (increments, in order)

| # | Increment | Status |
|---|---|---|
| 1 | Export correctness + regressions (both packages) | done (48b8039) |
| 2 | Corridor Lab desktop workbench (controller + tabbed GUI + structured transaction edits + baseline diff) | done |
| 3 | TraceCanary guided investigation workflow (controller + grouped GUI + batch directories + starter additions) | in progress |
| 4 | Documentation and quick starts around the finished workflows | pending |
| 5 | Clean-environment installed verification, real-window exercise, full suites, final diff review | pending |

## Verification commands (authoritative)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```
