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

For a source checkout on Windows, double-click `CorridorLab.pyw`. The first
screen provides a built-in fictional Amber to Birch demo, so it works without
example files after installation.

Select a fictional scenario JSON first, or choose **Edit Scenario JSON...**.
The editor opens an in-memory draft: **Load Fictional Template** changes only
that draft, **Validate and Use** replaces the active scenario only after strict
validation succeeds, and **Save Scenario As...** is the only way it writes a
scenario file. An invalid draft leaves the active scenario unchanged.

Compare and Pareto Frontier use selected route files or a selected route folder
when provided; otherwise they use routes embedded in the scenario. Evaluate
Embedded, Sensitivity, and 2D Grid intentionally use only embedded routes. Use
the preview-format selector to view Markdown, JSON, or CSV. **Explain Report**,
or `Ctrl+H`, opens the text-first Markdown explanation. Choose **Save Report...**
to write the current report. `Ctrl+E` opens the scenario editor. Any of those
actions produces a report that can then be previewed, explained, or saved.

The GUI calls Corridor Lab library functions directly. It does not start a
subprocess, fetch live data, send telemetry, or persist state. For a headless
controller check that opens no window:

```text
corridorlab-gui --smoke-test
```
