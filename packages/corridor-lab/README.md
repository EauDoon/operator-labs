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
- Bounded scenario portfolios, explicit two-parameter stress grids, and a Pareto frontier with no composite score.

The default `compare` report has no ranking. A ranking is emitted only when a
scenario explicitly states an objective and at least one guardrail.

## Contracts and commands

`schemas/scenario.schema.json` and `schemas/route.schema.json` document v1.
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
```

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
[limitations](docs/LIMITATIONS.md), [GUI usage](docs/GUI.md), and the
[worked example](docs/WORKED_EXAMPLE.md).

## Repository map

- `src/corridor_lab/` contains the calculation library, CLI, and optional GUI.
- `CorridorLab.pyw` is the checkout double-click launcher.
- `schemas/` contains the v1 structural contracts.
- `routes/templates/` and `examples/` contain only fictional inputs.
- `tests/` contains deterministic model, safety, CLI, and GUI-controller tests.

## Development

```text
python -m unittest discover -s tests -v
python -m compileall -q src
```

Licensed under [Apache-2.0](LICENSE).

## Transaction what-if analysis

`corridorlab transaction-sweep scenario.json --parameter deadline_hours --values 1,2,8 --format markdown` varies `send_amount`, `deadline_hours`, or `volume_per_period` against embedded routes. Values use the same strict transaction validator and bounded row budget as other analyses. All route assumptions, including fixed recovery amounts, remain unchanged. Invalid combinations return exit 2.

`corridorlab diff candidate.json --baseline baseline.json --format markdown` compares matching route IDs and lists added or removed routes. Deltas are candidate minus baseline. Currencies, precisions, and rounding must match. This is a descriptive comparison of all changed assumptions, with no inferred causal attribution or route recommendation. CSV contains matched-route metric deltas; JSON and Markdown also list route membership changes.

Stress grids now evaluate declared objective guardrails at every cell. JSON and CSV expose pass/failure details; Markdown summarizes passing cells per route. These counts apply only to sampled assumptions and are not probabilities or implicit rankings. Scenarios without objectives retain unranked metric-only grids.
