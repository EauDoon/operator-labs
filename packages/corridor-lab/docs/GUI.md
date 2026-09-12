# GUI usage

Launch the installed desktop interface with:

```text
corridorlab-gui
```

The GUI requires Python 3.11 or newer with Tcl/Tk available. From a Windows
checkout, install the local package first:

```text
py -3.11 -m pip install --user .
```

If `corridorlab-gui` is not available on `PATH`, use the module fallback:

```text
py -3.11 -m corridor_lab.gui
```

For a source checkout on Windows, double-click `CorridorLab.pyw`. The window
uses four keyboard-reachable tabs so ordinary laptop sizes stay readable, and
the status line at the bottom always names the latest outcome. The built-in
fictional Amber to Birch demo works without example files after installation.

## 1. Scenario

Load the built-in demo or **Open Scenario File...**, then edit the transaction
either structurally or as JSON:

- The structured editor shows the declared send amount, deadline hours, and
  volume per period. Leave a field empty to keep the declared value. Amounts
  keep their exact decimal digits; nothing passes through binary floats.
- **Apply Edits** validates the edited scenario as a whole before it replaces
  the active scenario. A rejected draft leaves the active scenario, the JSON
  draft, and the current report untouched, and the status line says so.
- Applied edits are in-memory and unsaved: the scenario label says
  "edited in memory, unsaved" until **Save Scenario As...** writes a file.
- **Edit Scenario JSON...** (or `Ctrl+E`) opens the raw JSON editor. **Load
  Fictional Template** changes only that draft, **Validate and Use** replaces
  the active scenario only after strict validation succeeds, and **Save
  Scenario As...** is the only way it writes a scenario file.

## 2. Compare Routes

**Compare Selected Routes** and **Pareto Frontier** use the selected route
file or folder; otherwise they use routes embedded in the scenario. **Evaluate
Embedded Routes** always uses embedded routes. Reports show separate metrics
per declared route and never merge currencies into a composite score; a
ranking appears only when the scenario declares an objective with guardrails.

## 3. Investigate

This tab groups the assumption analyses on the declared data:

- **Vary declared inputs:** Sensitivity, Transaction Sweep, Transaction Grid
  (two distinct transaction fields), and the two-parameter Stress Grid.
- **Declared assumption analyses:** Cost Ledger (unrounded sender-cost
  components with currencies), Deadline Profile (exact success and resolution
  probabilities over time), Outcome Ledger (probability-weighted
  contributions), Guardrail Headroom (signed margins), Loss Profile
  (principal-loss exceedance), Feasible Amount (minimum amounts on the
  declared precision grid), and Break-even Check (whole-volume costs around
  declared crossovers).
- **Targets and quantiles:** Deadline Target finds the earliest declared time
  meeting a requested delivery probability and marks unreachable rows instead
  of inventing times; Resolution Quantiles reports exact discrete final-state
  times.
- **Baseline comparison:** select a baseline scenario JSON and **Run Diff**
  compares the active scenario (candidate, after) against it (before).
  Currencies, precisions, and rounding must match; deltas are candidate minus
  baseline.

Infeasible or unreachable outcomes are explained in the report rather than
hidden. Every analysis runs against embedded routes.

## 4. Report

The preview shows Markdown, JSON, or CSV for the current report; a format an
analysis does not support (CSV for Pareto, for example) explains itself
instead of exporting. **Explain Report** (or `Ctrl+H`) opens the text-first
Markdown explanation that defines currencies, units, and metrics. **Save
Report...** is the only action that writes a report file, after you choose a
path in the save dialog. Report destinations that would replace a tracked
scenario or route input, including symlinks, hard links, and paths inside a
selected route folder, are rejected before anything is written, and a failed
save preserves any previous report file.

The GUI calls Corridor Lab library functions directly. It does not start a
subprocess, fetch live data, send telemetry, or persist state. For a headless
controller check that opens no window:

```text
corridorlab-gui --smoke-test
```

## Transaction sweeps

Choose a transaction field from the read-only selector, enter comma-separated decimal values, and select **Sweep**. It uses embedded routes and previews a bounded what-if report in all three formats. The active scenario stays unchanged, including after an invalid sweep. Save Report explicitly exports the current result.
