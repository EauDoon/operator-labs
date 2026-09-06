# Corridor Lab

Corridor Lab compares declared, fictional cross-border payment routes using
deterministic cost, timing, liquidity, and failure assumptions. It is an
offline scenario engine, not a live pricing service or provider recommendation.

All bundled entities, currencies, rates, fees, probabilities, and timings are
synthetic. Do not use real customer, account, transaction, or provider data.

![Diagram showing alternative comparison, stress, and Pareto analyses of a synthetic payment scenario, with results available in the GUI or stable reports.](https://raw.githubusercontent.com/EauDoon/operator-labs/main/packages/corridor-lab/.github/assets/project-overview.svg)

## Quick start

Requires Python 3.11 or newer. The runtime uses only the Python standard
library.

```text
python -m pip install .
corridorlab validate examples/fictional-corridor/scenario.json
corridorlab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes
corridorlab evaluate examples/fictional-corridor/embedded-scenario.json --format markdown
corridorlab sensitivity examples/fictional-corridor/embedded-scenario.json --parameter fx_spread_bps --values 10,25,50,100
corridorlab stress-grid examples/fictional-corridor/embedded-scenario.json --parameter-a fx_rate --values-a 1.7,1.8 --parameter-b fx_spread_bps --values-b 25,50
corridorlab pareto examples/fictional-corridor/embedded-scenario.json --format markdown
corridorlab batch examples/fictional-corridor/portfolio --format json
corridorlab workload examples/fictional-tiered-workload/scenario.json --format markdown
corridorlab break-even examples/fictional-tiered-workload/scenario.json --left tiered-marginal --right flat-fee --format markdown
corridorlab funding examples/fictional-funding/scenario.json --delays 0,1 --format markdown
corridorlab-gui
corridorlab-gui --smoke-test
```

On Windows, use `py -3.11 -m pip install --user .` when `python` is not on
`PATH`. If the installed GUI launcher is not on `PATH`, use
`py -3.11 -m corridor_lab.gui` instead.

Each result is deterministic. JSON reports are canonical, UTF-8, sorted-key
documents with an LF terminator. Compare, evaluate, sensitivity, and
stress-grid also accept `--format csv` or `--format markdown`. Pareto and batch
accept `--format markdown` only, not csv. Use `--output FILE` to write a report.
If `--format` is omitted, it is inferred from `--output` (`.json`, `.md` /
`.markdown`, `.csv`) or from `CORRIDOR_LAB_FORMAT`; otherwise JSON is the
default. An explicit `--format` always wins.

## First screen

`corridorlab-gui` opens a standard-library Tkinter desktop interface. Start
with **Load Built-in Fictional Demo** for an immediate, installed-package demo
that has no repository file dependency. The screen then provides:

- A scenario JSON selector and route JSON or route-folder selectors.
- An editable in-memory scenario JSON window with a fictional template, strict
  **Validate and Use**, and explicit **Save Scenario As...** controls.
- Compare, Evaluate Embedded, and one-parameter Sensitivity actions.
- A Pareto Frontier action that shows expected recipient amount and expected sender cost as separate metrics.
- A bounded 2D Grid action for two declared parameters, with no hidden composite score.
- Markdown, JSON, and CSV previews plus a text-first **Explain Report** view
  that defines currencies, outcome metrics, timing, ranking, and break-even.
- **Save Scenario As...** and **Save Report...**, the only GUI actions that
  write files; each requires a path chosen in the save dialog.

For a checkout on Windows, double-click `CorridorLab.pyw` to launch the same
interface without installation. The GUI imports the calculation library
directly, never starts a subprocess, and has no network, telemetry, or datastore.
Its `--smoke-test` verifies the controller and built-in demo without opening a
window, including in headless CI environments.

Use `Ctrl+E` to open the scenario editor and `Ctrl+H` to open the Markdown
report explanation. The editor keeps the active scenario unchanged after an
invalid draft and writes no scenario file unless **Save Scenario As...** is
chosen.

## What it calculates

- Conditional and expected recipient amounts.
- Fixed and percentage fees, FX-spread effect, and effective FX rate.
- Per-transaction liquidity carrying cost from explicit prefunding, capital
  cost, holding-period, and volume assumptions.
- Expected loss after failure and recovery states.
- Probability of successful completion by the declared deadline plus expected, median, and 95th-percentile
  time to a final state.
- Pairwise break-even transaction volume for declared sender-currency costs.
- One-parameter sensitivity analysis.
- Declared tiered fee schedules with marginal or whole-band semantics, plus
  period charges amortized over an explicitly declared denominator.
- Declared workload (transaction-volume) scenarios and a break-even exploration
  that never interpolates between declared volumes.
- Declared multi-period funding schedules: required prefunding, funding
  shortfalls, average tied-up capital, carrying cost, and sensitivity to
  declared settlement and recovery delays. These are reported separately from
  per-transaction sender cost and are never added to it.
- Bounded scenario portfolios, explicit two-parameter stress grids, and a Pareto frontier with no composite score.

The default `compare` report has no ranking. A ranking is emitted only when a
scenario explicitly states an objective and at least one guardrail.

## Contracts and commands

`schemas/scenario.schema.json` and `schemas/route.schema.json` document v1.
`schemas/scenario.schema.v2.json` and `schemas/route.schema.v2.json` document the
v2 contracts, which add declared tiered fee schedules, period charges, workload
scenarios, and funding schedules. v1 parsing is unchanged: a v1 document is never
reinterpreted, and a v2 contract cannot loosen a v1 constraint.

The schemas provide portable structural checks. The runtime validator is
authoritative for duplicate-key rejection, bounded decimal values, exact
probability totals, field constraints, and calculation preconditions. It rejects
unknown fields, non-finite decimals, invalid probabilities, unsupported
precision, and inputs not explicitly marked fictional.

```text
corridorlab validate scenario.json
corridorlab evaluate scenario.json [--format json|csv|markdown] [--output FILE]
corridorlab compare scenario.json --routes ROUTE_FILE_OR_DIRECTORY [--format json|csv|markdown] [--output FILE]
corridorlab sensitivity scenario.json --parameter fx_spread_bps --values 10,25,50,100 [--format json|csv|markdown] [--output FILE]
corridorlab stress-grid scenario.json --parameter-a fx_rate --values-a 1.7,1.8 --parameter-b fx_spread_bps --values-b 25,50 [--format json|csv|markdown] [--output FILE]
corridorlab pareto scenario.json [--format json|markdown] [--output FILE]
corridorlab batch SCENARIO_DIRECTORY [--recursive] [--include-paths] [--format json|markdown] [--output FILE]
corridorlab workload scenario.json [--workloads ID,ID] [--format json|csv|markdown] [--output FILE]
corridorlab break-even scenario.json --left ROUTE_ID --right ROUTE_ID [--workloads ID,ID] [--format json|markdown] [--output FILE]
corridorlab funding scenario.json [--delays 0,1,2] [--format json|csv|markdown] [--output FILE]
```

`workload` and `break-even` require a `corridor-lab.scenario/v2` scenario that
declares `workload_scenarios`. They re-evaluate every embedded route under each
selected declared volume; Corridor Lab never derives a volume from data.
`funding` requires a declared `funding` schedule; `--delays` overrides the
schedule's own `recovery_delay_periods` with one row per declared delay.

`evaluate`, `sensitivity`, `stress-grid`, and `pareto` use the routes embedded
in the scenario. `compare` uses only the route file or directory supplied with
`--routes`. `batch` evaluates each JSON scenario file in the supplied
directory.

## Limits

Corridor Lab does not fetch rates, fees, or network status. It does not perform
regulatory, sanctions, compliance, legal, tax, investment, or operational-risk
determinations. It does not select a route unless the user supplies an explicit
objective and guardrails, and even then it only orders the declared assumptions.

See [the model](docs/MODEL.md), [assumptions](docs/ASSUMPTIONS.md),
[limitations](docs/LIMITATIONS.md), [GUI usage](docs/GUI.md), the
[worked example](docs/WORKED_EXAMPLE.md), and the
[tiered fee and workload example](examples/fictional-tiered-workload/README.md),
and the [funding example](examples/fictional-funding/README.md).

## Repository map

- `src/corridor_lab/` contains the calculation library, CLI, and optional GUI.
- `CorridorLab.pyw` is the checkout double-click launcher.
- `schemas/` contains the v1 and v2 structural contracts.
- `routes/templates/` and `examples/` contain only fictional inputs.
- `tests/` contains deterministic model, safety, CLI, and GUI-controller tests.

## Development

```text
python -m unittest discover -s tests -v
python -m compileall -q src
```

Licensed under [Apache-2.0](LICENSE).
