"""Tkinter desktop interface for TraceCanary.

Tkinter is imported only when an interactive window is requested, so normal
library and CLI imports remain usable in headless environments.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tracecanary.canonical import InputError
from tracecanary.gui_controller import (
    EXIT_PASS,
    EXIT_UNRESOLVED,
    GuiResult,
    TraceCanaryController,
)
from tracecanary.output import protect_inputs, write_report

TAB_TITLES = (
    "1. Files and Starters",
    "2. Is the Contract Usable?",
    "3. Were Canaries Exercised?",
    "4. Did the Candidate Leak?",
    "5. Did Telemetry Survive?",
    "6. Batch Directories",
)

SCOPES = ("resource", "scope", "span", "event", "link")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tracecanary-gui",
        description=(
            "Offline desktop interface for TraceCanary privacy-regression checks. "
            "Reports are written only through Save Report; starter files are written "
            "only into an empty directory chosen by the user."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="exercise the controller and built-in demo without opening a window",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_PASS if exc.code in (0, None) else EXIT_UNRESOLVED
    if args.smoke_test:
        return smoke_test()
    return launch_window()


def smoke_test() -> int:
    """Exercise deterministic built-in demo logic without importing Tkinter."""
    controller = TraceCanaryController()
    reports = [controller.built_in_demo() for _ in range(3)]
    if all(report.status == "pass" and report.exit_code == EXIT_PASS for report in reports) and len({report.json for report in reports}) == 1:
        _write_stream(sys.stdout, "TraceCanary GUI smoke test: pass")
        return EXIT_PASS
    _write_stream(sys.stderr, "TraceCanary GUI smoke test: unresolved")
    return EXIT_UNRESOLVED


def launch_window() -> int:
    """Import Tkinter lazily and start the interactive desktop window."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        _startup_error("TraceCanary GUI is unavailable because Tkinter is not installed.")
        return EXIT_UNRESOLVED
    try:
        window = TraceCanaryWindow(tk, ttk, filedialog, messagebox)
    except tk.TclError:
        _startup_error("TraceCanary GUI could not open a window in this environment.")
        return EXIT_UNRESOLVED
    window.run()
    return EXIT_PASS


def _startup_error(message: str) -> None:
    """Report startup failure without assuming pythonw provides stderr."""
    if not _write_stream(sys.stderr, message):
        _show_windows_error(message)


def _write_stream(stream: object, message: str) -> bool:
    if stream is None:
        return False
    try:
        stream.write(message + "\n")
        stream.flush()
    except (AttributeError, OSError):
        return False
    return True


def _show_windows_error(message: str) -> None:
    """Use a minimal Windows dialog only when pythonw provides no stderr."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "TraceCanary", 0x10)
    except (AttributeError, OSError):
        return


def save_gui_report(target: Path, result: GuiResult, view: str) -> None:
    """Write a rendered GUI report under the same protection as CLI output.

    The destination must not replace any input the result depends on and must
    stay outside a scanned batch directory. The write itself is the bounded
    atomic replacement used by the CLI, so a failed write preserves the
    previous file and removes temporary files.
    """
    protect_inputs(target, list(result.inputs), result.input_dir)
    write_report(target, result.json if view == "json" else result.human)


class TraceCanaryWindow:
    """Guided local UI that delegates all analysis to TraceCanaryController."""

    def __init__(self, tk: object, ttk: object, filedialog: object, messagebox: object) -> None:
        self._tk = tk
        self._ttk = ttk
        self._filedialog = filedialog
        self._messagebox = messagebox
        self._controller = TraceCanaryController()
        self._result: GuiResult | None = None
        self._view = "human"
        self._root = tk.Tk()
        self._root.title("TraceCanary")
        self._root.minsize(880, 640)
        self._contract = tk.StringVar()
        self._input = tk.StringVar()
        self._baseline = tk.StringVar()
        self._candidate = tk.StringVar()
        self._batch_dir = tk.StringVar()
        self._minimum_ratio = tk.StringVar(value="0.95")
        self._batch_ratio = tk.StringVar(value="0.95")
        self._population_scope = tk.StringVar(value="span")
        self._population_minimum = tk.StringVar(value="1")
        self._recursive = tk.BooleanVar(value=False)
        self._include_paths = tk.BooleanVar(value=False)
        self._require_zero = tk.BooleanVar(value=False)
        self._use_baseline = tk.BooleanVar(value=False)
        self._status = tk.StringVar(value="Status: awaiting input")
        for index in range(len(TAB_TITLES)):
            self._root.bind_all(f"<Control-Key-{index + 1}>", self._make_tab_shortcut(index), add="+")
        self._build()

    def run(self) -> None:
        self._root.mainloop()

    def _build(self) -> None:
        frame = self._ttk.Frame(self._root, padding=14)
        frame.grid(sticky="nsew")
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=0)

        self._ttk.Label(frame, text="TraceCanary", font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, sticky="w")
        self._ttk.Label(
            frame,
            text="Offline OTLP trace privacy-regression checks. Results never print matched canary values. Ctrl+1..6 switch tabs.",
        ).grid(row=0, column=0, sticky="e")

        self._notebook = self._ttk.Notebook(frame)
        self._notebook.grid(row=0, column=0, sticky="nsew", pady=(8, 0))
        self._build_files_tab()
        self._build_contract_tab()
        self._build_control_tab()
        self._build_leak_tab()
        self._build_survival_tab()
        self._build_batch_tab()

        report_frame = self._ttk.LabelFrame(frame, text="Result report", padding=6)
        report_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        report_frame.columnconfigure(0, weight=1)
        report_controls = self._ttk.Frame(report_frame)
        report_controls.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._status_label = self._tk.Label(report_controls, textvariable=self._status, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="w")
        self._ttk.Button(report_controls, text="Show Human", command=lambda: self._show("human")).grid(row=0, column=1, padx=(12, 4))
        self._ttk.Button(report_controls, text="Show JSON", command=lambda: self._show("json")).grid(row=0, column=2, padx=4)
        self._ttk.Button(report_controls, text="Save Report", command=self._save).grid(row=0, column=3, padx=(4, 0))
        self._report = self._tk.Text(report_frame, wrap="word", height=14, state="disabled")
        self._report.grid(row=1, column=0, sticky="ew")
        scroll = self._ttk.Scrollbar(report_frame, orient="vertical", command=self._report.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self._report.configure(yscrollcommand=scroll.set)

    def _add_selector(self, frame: object, row: int, label: str, variable: object) -> None:
        self._ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        self._ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
        self._ttk.Button(frame, text="Browse", command=lambda: self._browse(variable)).grid(row=row, column=2, sticky="e", pady=2)

    def _build_files_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[0])
        tab.columnconfigure(1, weight=1)
        self._ttk.Label(tab, text="Select the synthetic files this investigation uses. All values stay fictional and offline.", wraplength=760).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self._add_selector(tab, 1, "Contract", self._contract)
        self._add_selector(tab, 2, "Input (trace)", self._input)
        self._add_selector(tab, 3, "Baseline (before)", self._baseline)
        self._add_selector(tab, 4, "Candidate (after)", self._candidate)
        self._add_selector(tab, 5, "Batch directory", self._batch_dir)

        starters = self._ttk.LabelFrame(tab, text="Reproducible synthetic starters", padding=8)
        starters.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self._ttk.Label(
            starters,
            text="Writes the fictional bundle into an empty directory you choose, then prepares the selectors: a safe export, four detected leaks, a retained-field regression, a partial-coverage export for threshold failures, an invalid export for unresolved results, and the contract.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self._ttk.Button(starters, text="Run Built-in Demo", command=self._demo).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._ttk.Button(starters, text="Create Synthetic Starter Files...", command=self._create_starter).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

    def _build_contract_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[1])
        tab.columnconfigure(0, weight=1)
        self._ttk.Label(tab, text="Is the contract usable?", font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        self._ttk.Label(
            tab,
            text="Validate confirms the contract parses under its strict version pinning. Inspect Contract inventories the effective value-free checks, limits, and direct retention conflicts without exposing canary values.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))
        buttons = self._ttk.Frame(tab)
        buttons.grid(row=2, column=0, sticky="w")
        self._ttk.Button(buttons, text="Validate", command=self._validate).grid(row=0, column=0, padx=(0, 6))
        self._ttk.Button(buttons, text="Inspect Contract", command=self._inspect).grid(row=0, column=1)

    def _build_control_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[2])
        tab.columnconfigure(0, weight=1)
        self._ttk.Label(tab, text="Were the synthetic canaries exercised?", font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        self._ttk.Label(
            tab,
            text="Control Check verifies that the unsanitized synthetic positive control contains every declared canary. A control pass only confirms canary exercise; it is not a privacy pass. Use Check on the separately sanitized export next.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))
        self._ttk.Button(tab, text="Check Positive Control", command=self._control_check).grid(row=2, column=0, sticky="w")

    def _build_leak_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[3])
        tab.columnconfigure(0, weight=1)
        self._ttk.Label(tab, text="Did the sanitized candidate leak the canaries?", font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        self._ttk.Label(
            tab,
            text="Check scans one sanitized export for exact canary values, forbidden attribute keys, and forbidden path prefixes. Diff compares a passing baseline with a candidate and reports what changed.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))
        buttons = self._ttk.Frame(tab)
        buttons.grid(row=2, column=0, sticky="w")
        self._ttk.Button(buttons, text="Check Sanitized Export", command=self._check).grid(row=0, column=0, padx=(0, 6))
        self._ttk.Button(buttons, text="Diff Baseline vs Candidate", command=self._diff).grid(row=0, column=1)

    def _build_survival_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[4])
        for column in (0, 1):
            tab.columnconfigure(column, weight=1, uniform="survival")
        self._ttk.Label(tab, text="Did required telemetry survive?", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        descriptive = self._ttk.LabelFrame(tab, text="Descriptive inspection", padding=8)
        descriptive.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        self._ttk.Label(
            descriptive,
            text="Coverage shows entity and required-field counts with population denominators. Retention Matrix locates missing fields by structural pointer. Dropped Telemetry reports declared dropped counters.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self._ttk.Button(descriptive, text="Coverage", command=self._coverage).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._ttk.Button(descriptive, text="Retention Matrix", command=self._retention_matrix).grid(row=1, column=1, sticky="w", pady=(6, 0))
        drop_row = self._ttk.Frame(descriptive)
        drop_row.grid(row=1, column=2, sticky="w", pady=(6, 0))
        self._ttk.Checkbutton(drop_row, text="Require zero", variable=self._require_zero).grid(row=0, column=0)
        self._ttk.Button(drop_row, text="Dropped Telemetry", command=self._dropped).grid(row=0, column=1, padx=(4, 0))

        gates = self._ttk.LabelFrame(tab, text="Explicit gates (regressions fail closed)", padding=8)
        gates.grid(row=2, column=0, sticky="new", padx=(0, 6))
        self._ttk.Label(gates, text="Minimum retained-field ratio (0 to 1, at most six places). Empty or invalid required populations stay unresolved.", wraplength=360).grid(row=0, column=0, columnspan=2, sticky="w")
        ratio_row = self._ttk.Frame(gates)
        ratio_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._ttk.Entry(ratio_row, textvariable=self._minimum_ratio, width=10).grid(row=0, column=0)
        self._ttk.Button(ratio_row, text="Coverage Gate", command=self._coverage_gate).grid(row=0, column=1, padx=(6, 0))

        population = self._ttk.LabelFrame(tab, text="Population gate", padding=8)
        population.grid(row=2, column=1, sticky="new", padx=(6, 0))
        self._ttk.Label(population, text="Require an explicit entity population while keeping every privacy check.", wraplength=360).grid(row=0, column=0, columnspan=2, sticky="w")
        pop_row = self._ttk.Frame(population)
        pop_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._ttk.Combobox(pop_row, textvariable=self._population_scope, values=SCOPES, state="readonly", width=10).grid(row=0, column=0)
        self._ttk.Entry(pop_row, textvariable=self._population_minimum, width=8).grid(row=0, column=1, padx=(6, 0))
        self._ttk.Button(pop_row, text="Gate", command=self._population_gate).grid(row=0, column=2, padx=(6, 0))

        diff = self._ttk.LabelFrame(tab, text="Coverage comparison", padding=8)
        diff.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._ttk.Label(diff, text="Compare exact retained-field rates between the baseline (before) and candidate (after) with both denominators visible.", wraplength=760).grid(row=0, column=0, sticky="w")
        self._ttk.Button(diff, text="Coverage Diff", command=self._coverage_diff).grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_batch_tab(self) -> None:
        tab = self._ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text=TAB_TITLES[5])
        tab.columnconfigure(0, weight=1)
        self._ttk.Label(tab, text="Check a bounded directory of exports", font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        self._ttk.Label(
            tab,
            text="The directory selected on the Files tab is scanned with the same bounded enumeration as the CLI: no symlinked files, a per-contract file limit, deterministic ordering, per-file results, and unresolved precedence.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))
        options = self._ttk.Frame(tab)
        options.grid(row=2, column=0, sticky="w")
        self._ttk.Checkbutton(options, text="Recursive", variable=self._recursive).grid(row=0, column=0, sticky="w")
        self._ttk.Checkbutton(options, text="Include paths (opt-in)", variable=self._include_paths).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._ttk.Checkbutton(options, text="Compare candidates against the passing Baseline from the Files tab", variable=self._use_baseline).grid(row=1, column=0, columnspan=2, sticky="w")
        self._ttk.Button(tab, text="Run Batch Check", command=self._batch).grid(row=3, column=0, sticky="w", pady=(8, 0))

        coverage = self._ttk.LabelFrame(tab, text="Aggregate coverage batch", padding=8)
        coverage.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self._ttk.Label(
            coverage,
            text="Sums presence counts and entity denominators across valid exports without averaging percentages. An optional exact per-file ratio gate applies independently to every file.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ratio_row = self._ttk.Frame(coverage)
        ratio_row.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._ttk.Label(ratio_row, text="Per-file minimum ratio (optional)").grid(row=0, column=0)
        self._ttk.Entry(ratio_row, textvariable=self._batch_ratio, width=10).grid(row=0, column=1, padx=(6, 0))
        self._ttk.Button(ratio_row, text="Run Coverage Batch", command=self._coverage_batch).grid(row=0, column=2, padx=(6, 0))

    def _make_tab_shortcut(self, index: int):
        def handler(_event: object) -> str:
            try:
                self._notebook.select(index)
            except Exception:
                pass
            return "break"

        return handler

    def _browse(self, variable: object) -> None:
        selected = self._filedialog.askopenfilename(title="Select JSON file", filetypes=[("JSON files", "*.json"), ("All files", "*")])
        if selected:
            variable.set(selected)

    def _validate(self) -> None:
        self._apply(self._controller.validate(self._contract.get()))

    def _inspect(self) -> None:
        self._apply(self._controller.inspect(self._contract.get()))

    def _check(self) -> None:
        self._apply(self._controller.check(self._contract.get(), self._input.get()))

    def _diff(self) -> None:
        self._apply(self._controller.diff(self._contract.get(), self._baseline.get(), self._candidate.get()))

    def _control_check(self) -> None:
        self._apply(self._controller.control_check(self._contract.get(), self._input.get()))

    def _coverage(self) -> None:
        self._apply(self._controller.coverage(self._contract.get(), self._input.get()))

    def _retention_matrix(self) -> None:
        self._apply(self._controller.retention_matrix(self._contract.get(), self._input.get()))

    def _dropped(self) -> None:
        self._apply(self._controller.dropped_telemetry(self._contract.get(), self._input.get(), bool(self._require_zero.get())))

    def _coverage_gate(self) -> None:
        self._apply(self._controller.coverage_gate(self._contract.get(), self._input.get(), self._minimum_ratio.get()))

    def _coverage_diff(self) -> None:
        self._apply(self._controller.coverage_diff(self._contract.get(), self._baseline.get(), self._candidate.get()))

    def _population_gate(self) -> None:
        self._apply(self._controller.population_gate(self._contract.get(), self._input.get(), self._population_scope.get(), self._population_minimum.get()))

    def _batch(self) -> None:
        self._apply(
            self._controller.batch(
                self._contract.get(),
                self._batch_dir.get() or self._input.get(),
                recursive=bool(self._recursive.get()),
                include_paths=bool(self._include_paths.get()),
                baseline_path=self._baseline.get() if self._use_baseline.get() else None,
            )
        )

    def _coverage_batch(self) -> None:
        self._apply(
            self._controller.coverage_batch(
                self._contract.get(),
                self._batch_dir.get() or self._input.get(),
                recursive=bool(self._recursive.get()),
                include_paths=bool(self._include_paths.get()),
                minimum_ratio=self._batch_ratio.get() or None,
            )
        )

    def _demo(self) -> None:
        self._apply(self._controller.built_in_demo())

    def _create_starter(self) -> None:
        destination = self._filedialog.askdirectory(title="Select an empty directory for synthetic starter files", mustexist=True)
        if not destination:
            return
        result = self._controller.create_starter_files(destination)
        if result.starter_paths is not None:
            paths = result.starter_paths
            self._contract.set(str(paths.contract))
            self._input.set(str(paths.input))
            self._baseline.set(str(paths.baseline))
            self._candidate.set(str(paths.candidate))
            self._batch_dir.set(str(paths.batch_dir))
        self._apply(result)
        if result.starter_paths is not None:
            self._status.set("Status: synthetic starter files created. Validate, Control Check, Check, Coverage Gate, and Batch are ready.")

    def _apply(self, result: GuiResult) -> None:
        self._result = result
        self._view = "human"
        color = {"pass": "#176b2c", "regression": "#9b2500", "unresolved": "#6b4300"}.get(result.status, "#333333")
        if result.mode == "control-check" and result.status == "pass":
            label = "CONTROL PASS (all canaries exercised; not a privacy pass)"
        else:
            label = f"{result.status.upper()} (exit {result.exit_code})"
        self._status.set(f"Status: {label}")
        self._status_label.configure(foreground=color)
        self._show("human")

    def _show(self, view: str) -> None:
        if self._result is None:
            return
        self._view = view
        text = self._result.human if view == "human" else self._result.json
        self._report.configure(state="normal")
        self._report.delete("1.0", "end")
        self._report.insert("1.0", text)
        self._report.configure(state="disabled")

    def _save(self) -> None:
        if self._result is None:
            self._status.set("Status: run an action before saving")
            return
        is_json = self._view == "json"
        selected = self._filedialog.asksaveasfilename(
            title="Save TraceCanary report",
            defaultextension=".json" if is_json else ".txt",
            filetypes=[("JSON report", "*.json"), ("Text report", "*.txt")],
        )
        if not selected:
            return
        target = Path(selected)
        try:
            save_gui_report(target, self._result, self._view)
        except InputError as exc:
            self._messagebox.showerror("TraceCanary", f"The report could not be saved: {exc}")
            return
        except OSError:
            self._messagebox.showerror("TraceCanary", "The report could not be saved.")
            return
        self._status.set(f"Status: report saved to {selected}")


if __name__ == "__main__":
    raise SystemExit(main())
