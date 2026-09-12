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
corridorlab cost-ledger examples/fictional-corridor/embedded-scenario.json --format markdown
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
accept JSON or Markdown but not CSV. Use `--output FILE` to write a report.
If `--format` is omitted, it is inferred from `--output` (`.json`, `.md` /
`.markdown`, `.csv`) or from `CORRIDOR_LAB_FORMAT`; otherwise JSON is the
default. An explicit `--format` always wins.

## Inspect declared cost, timing, and loss

These commands require embedded routes. Use `corridorlab init --output scenario.json`
to create a self-contained fictional input, or use the bundled `embedded-scenario.json`.
All five support JSON, CSV, Markdown, and protected atomic `--output` files.

`corridorlab feasible-amount scenario.json` finds the smallest positive amount on
the declared send-currency precision grid that covers fees and every stated
recovery. It can explain scenarios whose current amount cannot be evaluated.
A 100% proportional fee plus a positive fixed fee is infeasible at every amount.
The result permits zero recipient value and addresses model bounds only, not
commercial availability or profitability. Other transaction assumptions stay fixed.
The current amount is checked against exact fee and recovery bounds before the
reported minimum is rounded up to the currency grid; existing inputs may contain
more decimal places than the display precision.

`corridorlab loss-profile scenario.json --format csv` shows the unconditional
probability of unreturned principal **strictly above** zero and each declared
failure-loss breakpoint, plus expected excess loss above that breakpoint. At zero,
expected excess reconciles to model failure cost. Fees and liquidity carry are
excluded; full recovery has no principal loss. This is a synthetic distribution.

`corridorlab resolution-quantiles scenario.json --probabilities 0.5,0.9,0.99,1`
reports exact discrete final-state times, including failure recovery. Probabilities
must be distinct and greater than zero through one; zero is undefined for this
inverse CDF. Up to 64 values and 512 route/value rows are allowed. JSON, CSV, and
Markdown expose the chosen probability beside each time without interpolation.

`corridorlab deadline-target scenario.json --probability 0.95` finds the earliest
declared success time reaching that unconditional probability. If total success
probability is too low, the row is `unreachable` with a null time. Target zero
returns time zero. Failure recovery is not delivery, and times are not interpolated.

`corridorlab cost-ledger scenario.json --format markdown` explains unrounded
per-transaction sender cost as fixed fee, percentage fee, liquidity carry, and
expected failure loss. Components reconcile to the existing model; receive-currency
FX spread is separate. A zero total has null component shares. These are declared
fictional assumptions, not observed costs or route recommendations.

## First screen

`corridorlab-gui` opens a standard-library Tkinter desktop interface in four
tabs sized for ordinary laptops. Start with **Load Built-in Fictional Demo**
in the Scenario tab for an immediate, installed-package demo that has no
repository file dependency. The tabs are:

- **Scenario:** scenario selector, the built-in demo, a structured transaction
  editor for send amount, deadline hours, and volume per period (empty fields
  keep declared values; exact decimal digits are preserved and never pass
  through binary floats), and the raw JSON editor with strict **Validate and
  Use** plus explicit **Save Scenario As...**. Applied edits are in-memory and
  clearly marked unsaved; rejected drafts leave the active scenario and
  current report untouched.
- **Compare Routes:** compare selected route files or folders against the
  transaction, evaluate embedded routes, and show the Pareto frontier as
  separate metrics with no composite score.
- **Investigate:** sensitivity, transaction sweep and grid, two-parameter
  stress grid, cost ledger, deadline profile, outcome ledger, guardrail
  headroom, loss profile, feasible amount, break-even check, deadline target,
  resolution quantiles, and a baseline scenario diff with explicit before and
  after direction.
- **Report:** Markdown, JSON, and CSV previews for the current report, the
  text-first **Explain Report** view (`Ctrl+H`), and **Save Report...**, one
  of only two GUI actions that write files (the other is **Save Scenario
  As...**); both require a path chosen in a save dialog. Report destinations
  that would replace a tracked input are rejected, including symlinks, hard
  links, and paths inside a selected route folder.

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

`corridorlab transaction-grid scenario.json --parameter-a deadline_hours --values-a
1,2 --parameter-b volume_per_period --values-b 10,100 --format markdown` evaluates
the explicit cross-product of two distinct transaction fields. It supports amount,
deadline and volume, at most 64 values per axis and 512 route/cell rows. Every
combination passes the existing transaction and route preconditions. Guardrail
state is null without a declared objective. Routes and fixed recovery amounts do
not scale implicitly when the send amount changes.

`corridorlab break-even-check scenario.json --format markdown` re-evaluates
sender costs at the floor and ceiling whole volumes around each positive
continuous break-even point, clamped to at least one transaction. The cost delta
is left route minus right route in sender currency. Equal sample volumes are
reported honestly; parallel/nonpositive intersections keep their existing status.
Derived samples must satisfy transaction bounds. This is a comparison, not a route selection.

`corridorlab deadline-profile scenario.json --format markdown` shows exact
successful-delivery and final-resolution cumulative probabilities at declared
event times, zero, and the current deadline. Failure recovery contributes to
resolution only. Values between event times are constant; no interpolation or
forecast is implied. Reports are bounded to 512 rows.

`corridorlab outcome-ledger scenario.json --format csv` breaks down each declared
outcome's weighted recipient amount, failure loss, recovery, and resolution time.
Contributions are unrounded Decimal values in explicitly labeled currencies and
hours. Their totals reconcile to the existing model; fees and liquidity costs
remain separate, so they are not counted twice in outcome losses.

`corridorlab guardrail-headroom scenario.json --format markdown` reports the
signed margin against each declared minimum probability or maximum tail-time
guardrail. Zero meets the threshold; positive is headroom and negative is a
shortfall. It requires an explicit objective and never infers missing guardrails.

`corridorlab transaction-sweep scenario.json --parameter deadline_hours --values 1,2,8 --format markdown` varies `send_amount`, `deadline_hours`, or `volume_per_period` against embedded routes. Values use the same strict transaction validator and bounded row budget as other analyses. All route assumptions, including fixed recovery amounts, remain unchanged. Invalid combinations return exit 2.

`corridorlab diff candidate.json --baseline baseline.json --format markdown` compares matching route IDs and lists added or removed routes. Deltas are candidate minus baseline. Currencies, precisions, and rounding must match. This is a descriptive comparison of all changed assumptions, with no inferred causal attribution or route recommendation. CSV contains matched-route metric deltas; JSON and Markdown also list route membership changes.

Stress grids now evaluate declared objective guardrails at every cell. JSON and CSV expose pass/failure details; Markdown summarizes passing cells per route. These counts apply only to sampled assumptions and are not probabilities or implicit rankings. Scenarios without objectives retain unranked metric-only grids.

## Start outside a checkout

After installation, `corridorlab init --output fictional.json` creates a complete, deterministic synthetic scenario with two embedded routes. It refuses an existing file and requires an existing parent directory. Then run `corridorlab evaluate fictional.json`, `corridorlab transaction-sweep fictional.json --parameter volume_per_period --values 10,100,1000`, or open the file in the GUI. This starter does not fetch data or require repository fixtures.

Report output paths cannot replace a scenario, baseline, or route input, including aliases. Reports from route-folder comparison or batch evaluation must be written outside the corresponding input directory so subsequent runs cannot ingest their own outputs.
