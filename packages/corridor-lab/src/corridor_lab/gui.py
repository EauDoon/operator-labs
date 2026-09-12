"""Optional Tkinter desktop interface for Corridor Lab.

Tkinter imports are intentionally delayed so the CLI and calculation library
remain usable in headless environments.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .gui_controller import ActionResult, CorridorGuiController

STARTUP_FAILURE_MESSAGE = "Corridor Lab could not open its desktop interface. Install or enable Tcl/Tk, then try again."

TAB_TITLES = ("1. Scenario", "2. Compare Routes", "3. Investigate", "4. Report")


def _show_windows_message(message: str) -> None:
    """Best-effort visible fallback when pythonw provides no console streams."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Corridor Lab", 0x10)
    except Exception:
        pass


def _startup_failure() -> int:
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream.write(f"error: {STARTUP_FAILURE_MESSAGE}\n")
            return 2
        except Exception:
            pass
    _show_windows_message(STARTUP_FAILURE_MESSAGE)
    return 2


def _write_smoke_status() -> None:
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            stream.write("corridorlab-gui smoke test passed\n")
        except Exception:
            pass


def _load_tk_modules():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

    return tk, filedialog, messagebox, scrolledtext, simpledialog, ttk


def run_smoke_test() -> int:
    """Exercise built-in controller actions without importing or opening Tk."""
    controller = CorridorGuiController()
    if controller.load_builtin_demo().error is not None:
        return 1
    comparison = controller.compare()
    if comparison.error is not None:
        return 1
    first_json = controller.render_last_report("json")
    second_json = controller.render_last_report("json")
    if first_json is None or first_json != second_json or '"declared_inputs"' not in first_json:
        return 1
    evaluation = controller.evaluate()
    if evaluation.error is not None or controller.render_last_report("markdown") is None:
        return 1
    sensitivity = controller.sensitivity("fx_spread_bps", "10,25,50")
    if sensitivity.error is not None:
        return 1
    csv_text = controller.render_last_report("csv")
    if csv_text is None or "probability_by_deadline_definition" not in csv_text:
        return 1
    stress_grid = controller.stress_grid("fx_rate", "1.7,1.8", "fx_spread_bps", "25,50")
    if stress_grid.error is not None:
        return 1
    if controller.transaction_sweep("deadline_hours", "1,2,8").error is not None:
        return 1
    if controller.transaction_grid("deadline_hours", "1,2", "volume_per_period", "10,100").error is not None:
        return 1
    pareto = controller.pareto()
    if pareto.error is not None or controller.render_last_report("markdown") is None:
        return 1
    for action in (controller.cost_ledger, controller.deadline_profile, controller.outcome_ledger,
                   controller.guardrail_headroom, controller.loss_profile, controller.feasible_amount,
                   controller.break_even_check):
        if action().error is not None:
            return 1
    if controller.deadline_target("0.95").error is not None:
        return 1
    if controller.resolution_quantiles("0.5,0.95").error is not None:
        return 1
    rejected = controller.apply_transaction_edits(deadline_hours="-1")
    if rejected.error is None or controller.transaction_fields()["deadline_hours"] != "8":
        return 1
    applied = controller.apply_transaction_edits(send_amount="1000.00", deadline_hours="9", volume_per_period="100")
    if applied.error is not None or controller.transaction_fields()["deadline_hours"] != "9":
        return 1
    _write_smoke_status()
    return 0


class CorridorLabApp:
    """Tabbed desktop workbench around the headless controller."""

    def __init__(self, root: object, tk_module: object, ttk_module: object, filedialog: object, messagebox: object, scrolledtext_module: object, simpledialog_module: object) -> None:
        self.root = root
        self.tk = tk_module
        self.ttk = ttk_module
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext_module
        self.simpledialog = simpledialog_module
        self.controller = CorridorGuiController()
        self.experiments_var = tk_module.StringVar(value="No saved experiments")
        self.selected_experiment_var = tk_module.StringVar()
        self.variants_var = tk_module.StringVar(value="No derived variants")
        self.selected_variant_var = tk_module.StringVar()
        self.format_var = tk_module.StringVar(value="markdown")
        self.scenario_var = tk_module.StringVar(value=self.controller.scenario_source)
        self.routes_var = tk_module.StringVar(value=self.controller.routes_source)
        self.parameter_var = tk_module.StringVar(value="fx_spread_bps")
        self.values_var = tk_module.StringVar(value="10,25,50,100")
        self.transaction_parameter_var = tk_module.StringVar(value="deadline_hours")
        self.transaction_values_var = tk_module.StringVar(value="1,2,8")
        self.parameter_b_var = tk_module.StringVar(value="fx_rate")
        self.values_b_var = tk_module.StringVar(value="1.7,1.8")
        self.grid_parameter_b_var = tk_module.StringVar(value="volume_per_period")
        self.grid_values_b_var = tk_module.StringVar(value="10,100")
        self.deadline_target_var = tk_module.StringVar(value="0.95")
        self.quantiles_var = tk_module.StringVar(value="0.5,0.95,1")
        self.baseline_var = tk_module.StringVar()
        self.send_amount_var = tk_module.StringVar()
        self.deadline_var = tk_module.StringVar()
        self.volume_var = tk_module.StringVar()
        self.status_var = tk_module.StringVar(value="Load the built-in fictional demo or select your own fictional inputs.")
        self.editor_window = None
        self.editor_text = None
        self.editor_status_var = None
        root.title("Corridor Lab")
        root.minsize(880, 600)
        root.bind_all("<Control-e>", self._open_editor_shortcut)
        root.bind_all("<Control-h>", self._explain_report_shortcut)
        self._build()

    def _build(self) -> None:
        frame = self.ttk.Frame(self.root, padding=10)
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=0)

        notebook = self.ttk.Notebook(frame)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook = notebook
        self._build_scenario_tab(notebook)
        self._build_compare_tab(notebook)
        self._build_investigate_tab(notebook)
        self._build_report_tab(notebook)

        status = self.ttk.Label(frame, textvariable=self.status_var, wraplength=820, anchor="w")
        status.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def _build_scenario_tab(self, notebook: object) -> None:
        tab = self.ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=TAB_TITLES[0])
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        self.ttk.Label(tab, text="Load a fictional scenario, then edit its transaction.", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        actions = self.ttk.Frame(tab)
        actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
        self.ttk.Button(actions, text="Load Built-in Fictional Demo", command=self._load_demo).grid(row=0, column=0, sticky="w", pady=2)
        self.ttk.Button(actions, text="Open Scenario File...", command=self._choose_scenario).grid(row=0, column=1, sticky="w", padx=6)
        self.ttk.Button(actions, text="Edit Scenario JSON...", command=self._open_editor, underline=0).grid(row=0, column=2, sticky="w", padx=6)

        self.ttk.Label(tab, text="Scenario").grid(row=2, column=0, sticky="w", pady=2)
        self.ttk.Label(tab, textvariable=self.scenario_var, wraplength=760, anchor="w", relief="sunken", padding=4).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=2)

        self.ttk.Label(tab, text="Structured transaction edit", font=("TkDefaultFont", 12, "bold")).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(14, 4))
        self.ttk.Label(
            tab,
            text="Leave a field empty to keep the declared value. Amounts keep their exact declared decimal digits; nothing is converted through floats.",
            wraplength=760,
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        fields = self.ttk.Frame(tab)
        fields.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 4))
        self.ttk.Label(fields, text="Send amount").grid(row=0, column=0, sticky="w")
        self.ttk.Entry(fields, textvariable=self.send_amount_var, width=16).grid(row=0, column=1, padx=(4, 12))
        self.ttk.Label(fields, text="Deadline hours").grid(row=0, column=2, sticky="w")
        self.ttk.Entry(fields, textvariable=self.deadline_var, width=10).grid(row=0, column=3, padx=(4, 12))
        self.ttk.Label(fields, text="Volume per period").grid(row=0, column=4, sticky="w")
        self.ttk.Entry(fields, textvariable=self.volume_var, width=12).grid(row=0, column=5, padx=(4, 12))
        self.ttk.Button(fields, text="Refresh Fields", command=self._refresh_transaction_fields).grid(row=0, column=6, padx=(0, 6))
        self.ttk.Button(fields, text="Apply Edits", command=self._apply_transaction_edits).grid(row=0, column=7)

        projects = self.ttk.LabelFrame(tab, text="Saved local projects", padding=8)
        projects.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.ttk.Label(
            projects,
            text="A project bundles the scenario file, route selection, baseline, and saved experiments into one portable directory. Opening a project reports missing or modified inputs; reports stay separate from project settings.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.ttk.Button(projects, text="Open Project...", command=self._open_project).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.ttk.Button(projects, text="Save Project As...", command=self._save_project).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

    def _build_compare_tab(self, notebook: object) -> None:
        tab = self.ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=TAB_TITLES[1])
        tab.columnconfigure(0, weight=1)

        self.ttk.Label(tab, text="Compare declared routes", font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.ttk.Label(tab, text="Route JSON or folder (empty uses the routes embedded in the scenario)", wraplength=760).grid(row=1, column=0, sticky="w", pady=(6, 2))
        route_row = self.ttk.Frame(tab)
        route_row.grid(row=2, column=0, sticky="ew")
        route_row.columnconfigure(0, weight=1)
        self.ttk.Entry(route_row, textvariable=self.routes_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.ttk.Button(route_row, text="File...", command=self._choose_route_file).grid(row=0, column=1)
        self.ttk.Button(route_row, text="Folder...", command=self._choose_route_folder).grid(row=0, column=2, padx=(4, 0))
        self.ttk.Button(route_row, text="Use Embedded", command=self._clear_routes).grid(row=0, column=3, padx=(4, 0))

        buttons = self.ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="w", pady=(14, 0))
        self.ttk.Button(buttons, text="Compare Selected Routes", command=self._compare).grid(row=0, column=0, sticky="w")
        self.ttk.Button(buttons, text="Evaluate Embedded Routes", command=self._evaluate).grid(row=0, column=1, padx=6)
        self.ttk.Button(buttons, text="Pareto Frontier", command=self._pareto).grid(row=0, column=2)
        self.ttk.Label(
            tab,
            text="Compare and Pareto use the selected routes; other tabs use embedded routes. Reports show separate metrics per route and never mix currencies into a score.",
            wraplength=760,
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _build_investigate_tab(self, notebook: object) -> None:
        tab = self.ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=TAB_TITLES[2])
        for column in (0, 1):
            tab.columnconfigure(column, weight=1, uniform="investigate")

        sweeps = self.ttk.LabelFrame(tab, text="Vary one or two declared parameters", padding=8)
        sweeps.grid(row=0, column=0, sticky="new", padx=(0, 6))
        self.ttk.Label(sweeps, text="Sensitivity (route parameter)").grid(row=0, column=0, sticky="w")
        sensitivity_row = self.ttk.Frame(sweeps)
        sensitivity_row.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        self.ttk.Entry(sensitivity_row, textvariable=self.parameter_var, width=16).grid(row=0, column=0)
        self.ttk.Entry(sensitivity_row, textvariable=self.values_var, width=16).grid(row=0, column=1, padx=4)
        self.ttk.Button(sensitivity_row, text="Run", command=self._sensitivity).grid(row=0, column=2)
        self.ttk.Label(sweeps, text="Transaction sweep (send_amount, deadline_hours, volume_per_period)").grid(row=2, column=0, sticky="w")
        sweep_row = self.ttk.Frame(sweeps)
        sweep_row.grid(row=3, column=0, sticky="ew", pady=(2, 8))
        self.ttk.Combobox(sweep_row, textvariable=self.transaction_parameter_var, values=("send_amount", "deadline_hours", "volume_per_period"), state="readonly", width=18).grid(row=0, column=0)
        self.ttk.Entry(sweep_row, textvariable=self.transaction_values_var, width=16).grid(row=0, column=1, padx=4)
        self.ttk.Button(sweep_row, text="Sweep", command=self._transaction_sweep).grid(row=0, column=2)
        self.ttk.Label(sweeps, text="Transaction grid (two distinct transaction fields)").grid(row=4, column=0, sticky="w")
        grid_row = self.ttk.Frame(sweeps)
        grid_row.grid(row=5, column=0, sticky="ew", pady=(2, 4))
        self.ttk.Entry(grid_row, textvariable=self.transaction_parameter_var, state="readonly", width=18).grid(row=0, column=0)
        self.ttk.Entry(grid_row, textvariable=self.transaction_values_var, width=16).grid(row=0, column=1, padx=4)
        self.ttk.Label(grid_row, text="with").grid(row=0, column=2)
        self.ttk.Combobox(grid_row, textvariable=self.grid_parameter_b_var, values=("send_amount", "deadline_hours", "volume_per_period"), state="readonly", width=18).grid(row=0, column=3, padx=4)
        self.ttk.Entry(grid_row, textvariable=self.grid_values_b_var, width=16).grid(row=0, column=4)
        self.ttk.Button(grid_row, text="Grid", command=self._transaction_grid).grid(row=0, column=5, padx=4)
        stress_row = self.ttk.Frame(sweeps)
        stress_row.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.ttk.Label(stress_row, text="Stress grid").grid(row=0, column=0)
        self.ttk.Entry(stress_row, textvariable=self.parameter_var, width=16).grid(row=0, column=1, padx=4)
        self.ttk.Entry(stress_row, textvariable=self.values_var, width=16).grid(row=0, column=2)
        self.ttk.Label(stress_row, text="by").grid(row=0, column=3)
        self.ttk.Entry(stress_row, textvariable=self.parameter_b_var, width=16).grid(row=0, column=4, padx=4)
        self.ttk.Entry(stress_row, textvariable=self.values_b_var, width=16).grid(row=0, column=5)
        self.ttk.Button(stress_row, text="Grid", command=self._stress_grid).grid(row=0, column=6, padx=4)

        analyses = self.ttk.LabelFrame(tab, text="Declared assumption analyses (embedded routes)", padding=8)
        analyses.grid(row=0, column=1, sticky="new", padx=(6, 0))
        rows = (
            ("Cost Ledger", self._cost_ledger, 0, 0),
            ("Deadline Profile", self._deadline_profile, 0, 1),
            ("Outcome Ledger", self._outcome_ledger, 1, 0),
            ("Guardrail Headroom", self._guardrail_headroom, 1, 1),
            ("Loss Profile", self._loss_profile, 2, 0),
            ("Feasible Amount", self._feasible_amount, 2, 1),
            ("Break-even Check", self._break_even_check, 3, 0),
        )
        for text, command, row, column in rows:
            self.ttk.Button(analyses, text=text, command=command, width=18).grid(row=row, column=column, sticky="w", padx=4, pady=3)
        target_row = self.ttk.Frame(analyses)
        target_row.grid(row=3, column=1, sticky="w", pady=3)
        self.ttk.Label(target_row, text="Deadline target").grid(row=0, column=0)
        self.ttk.Entry(target_row, textvariable=self.deadline_target_var, width=8).grid(row=0, column=1, padx=3)
        self.ttk.Button(target_row, text="Find", command=self._deadline_target).grid(row=0, column=2)
        quantile_row = self.ttk.Frame(analyses)
        quantile_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        self.ttk.Label(quantile_row, text="Resolution quantiles").grid(row=0, column=0)
        self.ttk.Entry(quantile_row, textvariable=self.quantiles_var, width=14).grid(row=0, column=1, padx=3)
        self.ttk.Button(quantile_row, text="Show", command=self._resolution_quantiles).grid(row=0, column=2)

        diff = self.ttk.LabelFrame(tab, text="Scenario diff (baseline before, active scenario after)", padding=8)
        diff.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.ttk.Label(diff, text="Baseline scenario JSON (must match currencies, precisions, and rounding)").grid(row=0, column=0, sticky="w")
        diff_row = self.ttk.Frame(diff)
        diff_row.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        diff_row.columnconfigure(0, weight=1)
        self.ttk.Entry(diff_row, textvariable=self.baseline_var).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.ttk.Button(diff_row, text="Browse...", command=self._choose_baseline).grid(row=0, column=1)
        self.ttk.Button(diff_row, text="Run Diff", command=self._scenario_diff).grid(row=0, column=2, padx=(6, 0))

        saved = self.ttk.LabelFrame(tab, text="Saved experiments (rerunnable configurations from a project)", padding=8)
        saved.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        saved_row = self.ttk.Frame(saved)
        saved_row.grid(row=0, column=0, sticky="ew", pady=(2, 0))
        self.experiment_choice = self.ttk.Combobox(saved_row, textvariable=self.selected_experiment_var, state="readonly", width=28)
        self.experiment_choice.grid(row=0, column=0, sticky="w")
        self.ttk.Button(saved_row, text="Run Saved", command=self._run_saved_experiment).grid(row=0, column=1, padx=(6, 0))
        self.ttk.Button(saved_row, text="Save Current Settings...", command=self._save_experiment_dialog).grid(row=0, column=2, padx=(6, 0))
        self.ttk.Label(saved, textvariable=self.experiments_var, wraplength=760, anchor="w").grid(row=1, column=0, sticky="ew", pady=(6, 0))

        variants = self.ttk.LabelFrame(tab, text="Named scenario variants (declared changes over the project scenario)", padding=8)
        variants.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        variant_row = self.ttk.Frame(variants)
        variant_row.grid(row=0, column=0, sticky="ew", pady=(2, 0))
        self.variant_choice = self.ttk.Combobox(variant_row, textvariable=self.selected_variant_var, state="readonly", width=28)
        self.variant_choice.grid(row=0, column=0, sticky="w")
        self.ttk.Button(variant_row, text="Show Assumption Diff", command=self._show_variant_diff).grid(row=0, column=1, padx=(6, 0))
        self.ttk.Button(variant_row, text="Apply Variant", command=self._apply_variant).grid(row=0, column=2, padx=(6, 0))
        self.ttk.Button(variant_row, text="Compare Variants", command=self._compare_variants).grid(row=0, column=3, padx=(6, 0))
        self.ttk.Label(variants, textvariable=self.variants_var, wraplength=760, anchor="w").grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _build_report_tab(self, notebook: object) -> None:
        tab = self.ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=TAB_TITLES[3])
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        report_controls = self.ttk.Frame(tab)
        report_controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.ttk.Label(report_controls, text="Preview format").grid(row=0, column=0)
        format_box = self.ttk.Combobox(report_controls, textvariable=self.format_var, values=("markdown", "json", "csv"), state="readonly", width=10)
        format_box.grid(row=0, column=1, padx=6)
        format_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_preview())
        self.ttk.Button(report_controls, text="Refresh Preview", command=self._refresh_preview).grid(row=0, column=2)
        self.ttk.Button(report_controls, text="Explain Report", command=self._explain_report, underline=7).grid(row=0, column=3, padx=6)
        self.ttk.Button(report_controls, text="Save Report...", command=self._save_report).grid(row=0, column=4, padx=(6, 0))

        self.ttk.Label(tab, text="The preview shows the formats the selected analysis supports; unsupported formats explain themselves instead of exporting.").grid(row=1, column=0, sticky="w")
        self.preview = self.scrolledtext.ScrolledText(tab, wrap="word", font=("TkFixedFont", 10))
        self.preview.grid(row=2, column=0, sticky="nsew")
        self.preview.insert("1.0", "No report yet. Built-in demo values are entirely fictional.\n")
        self.preview.configure(state="disabled")

    def _set_preview(self, text: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def _show_error(self, error: str | None) -> None:
        message = error or "The requested action could not be completed."
        self.status_var.set(f"Validation error: {message}")
        self.messagebox.showerror("Corridor Lab", message, parent=self.root)

    def _refresh_preview(self) -> None:
        text = self.controller.render_last_report(self.format_var.get())
        if text is None:
            if self.controller.last_report is not None:
                self._show_error(self.controller.last_error)
            return
        self._set_preview(text)
        self.status_var.set(f"Showing {self.format_var.get()} report. Save Report writes only after you choose a path.")

    def _explain_report(self) -> None:
        if self.controller.last_report is None:
            self._show_error("Run an analysis before opening the report explanation.")
            return
        self.format_var.set("markdown")
        self._refresh_preview()
        self.status_var.set("Showing the Markdown report and its text-first explanation.")

    def _complete(self, result: ActionResult, success_message: str) -> None:
        if result.error is not None:
            self._show_error(result.error)
            return
        self._refresh_preview()
        self.status_var.set(success_message)
        self.notebook.select(3)

    def _load_demo(self) -> None:
        result = self.controller.load_builtin_demo()
        if result.error is not None:
            self._show_error(result.error)
            return
        self._refresh_transaction_fields()
        self.scenario_var.set(self.controller.scenario_source)
        self.routes_var.set(self.controller.routes_source)
        self._complete(self.controller.compare(), "Built-in fictional demo loaded and compared.")

    def _open_editor_shortcut(self, _event: object) -> str:
        self._open_editor()
        return "break"

    def _explain_report_shortcut(self, _event: object) -> str:
        self._explain_report()
        return "break"

    def _open_editor(self) -> None:
        if self.editor_window is not None and self.editor_window.winfo_exists():
            self.editor_window.deiconify()
            self.editor_window.lift()
            self.editor_text.focus_set()
            return
        editor = self.tk.Toplevel(self.root)
        editor.title("Edit Fictional Scenario JSON")
        editor.minsize(760, 560)
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(2, weight=1)
        self.editor_window = editor
        self.editor_status_var = self.tk.StringVar(
            value="Validate and Use replaces the active scenario only after strict validation succeeds."
        )
        self.ttk.Label(
            editor,
            text="Edit only fictional values. Load Fictional Template affects this draft only until Validate and Use.",
            wraplength=700,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        controls = self.ttk.Frame(editor, padding=(12, 0, 12, 6))
        controls.grid(row=1, column=0, sticky="ew")
        self.ttk.Button(controls, text="Load Fictional Template", command=self._load_editor_template).grid(row=0, column=0, padx=(0, 6))
        self.ttk.Button(controls, text="Validate and Use", command=self._validate_editor).grid(row=0, column=1, padx=6)
        self.ttk.Button(controls, text="Save Scenario As...", command=self._save_editor_scenario).grid(row=0, column=2, padx=6)
        self.ttk.Label(controls, textvariable=self.editor_status_var, wraplength=350).grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.editor_text = self.scrolledtext.ScrolledText(editor, wrap="none", undo=True, font=("TkFixedFont", 10))
        self.editor_text.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.editor_text.insert("1.0", self.controller.scenario_draft_text)
        self.editor_text.bind("<Control-Return>", self._validate_editor_shortcut)
        self.editor_text.bind("<Control-s>", self._save_editor_shortcut)
        editor.protocol("WM_DELETE_WINDOW", self._close_editor)
        self.editor_text.focus_set()

    def _close_editor(self) -> None:
        if self.editor_window is not None:
            self.editor_window.destroy()
        self.editor_window = None
        self.editor_text = None
        self.editor_status_var = None

    def _editor_contents(self) -> str:
        return self.editor_text.get("1.0", "end-1c")

    def _replace_editor_contents(self, text: str) -> None:
        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", text)

    def _load_editor_template(self) -> None:
        self._replace_editor_contents(self.controller.load_fictional_template())
        self.editor_status_var.set("Fictional template loaded into the draft. It is not active until validated.")

    def _validate_editor_shortcut(self, _event: object) -> str:
        self._validate_editor()
        return "break"

    def _validate_editor(self) -> None:
        result = self.controller.validate_and_use_scenario_text(self._editor_contents())
        if result.error is not None:
            self.editor_status_var.set(f"Validation error: {result.error}")
            self._show_error(result.error)
            return
        self.scenario_var.set(self.controller.scenario_source)
        self.routes_var.set(self.controller.routes_source)
        self._refresh_transaction_fields()
        self._set_preview("Scenario validated and active. Choose Compare, Evaluate Embedded, or open the Investigate tab.\n")
        self.editor_status_var.set("Scenario validated and active. No scenario file was written.")
        self.status_var.set("Validated in-memory fictional scenario is active (unsaved draft). External route selection was cleared.")

    def _save_editor_shortcut(self, _event: object) -> str:
        self._save_editor_scenario()
        return "break"

    def _save_editor_scenario(self) -> None:
        path = self.filedialog.asksaveasfilename(
            parent=self.editor_window,
            title="Save fictional scenario",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        result = self.controller.save_scenario_text(path, self._editor_contents())
        if result.error is not None:
            self.editor_status_var.set(f"Validation error: {result.error}")
            self._show_error(result.error)
            return
        self.editor_status_var.set("Validated fictional draft saved. Active scenario was not changed.")
        self.status_var.set(f"Scenario saved to {path}")

    def _choose_scenario(self) -> None:
        path = self.filedialog.askopenfilename(parent=self.root, title="Select fictional scenario JSON", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            return
        result = self.controller.load_scenario_file(path)
        if result.error is not None:
            self._show_error(result.error)
            return
        self._refresh_transaction_fields()
        self.scenario_var.set(self.controller.scenario_source)
        self.routes_var.set(self.controller.routes_source)
        self.status_var.set("Scenario loaded. Compare and Pareto use embedded routes unless a route file or folder is selected.")

    def _refresh_transaction_fields(self) -> None:
        if self.controller.scenario is None:
            self.send_amount_var.set("")
            self.deadline_var.set("")
            self.volume_var.set("")
            return
        fields = self.controller.transaction_fields()
        self.send_amount_var.set(fields["send_amount"])
        self.deadline_var.set(fields["deadline_hours"])
        self.volume_var.set(fields["volume_per_period"])
        self.scenario_var.set(self.controller.scenario_source)

    def _apply_transaction_edits(self) -> None:
        if self.controller.scenario is None:
            self._show_error("Load a fictional scenario or the built-in demo before editing the transaction.")
            return
        result = self.controller.apply_transaction_edits(
            self.send_amount_var.get() or None,
            self.deadline_var.get() or None,
            self.volume_var.get() or None,
        )
        if result.error is not None:
            self.status_var.set(f"Rejected draft: the active scenario and report are unchanged. {result.error}")
            self._show_error(result.error)
            return
        self._refresh_transaction_fields()
        self.scenario_var.set(self.controller.scenario_source)
        self.status_var.set("Transaction edits applied in memory (unsaved draft). The previous report was cleared.")

    def _select_routes(self, path: str) -> None:
        result = self.controller.load_routes_path(path)
        if result.error is not None:
            self._show_error(result.error)
            return
        self.routes_var.set(self.controller.routes_source)
        self.status_var.set("Route selection loaded. Compare and Pareto use this selection; other actions use embedded routes.")

    def _choose_route_file(self) -> None:
        path = self.filedialog.askopenfilename(parent=self.root, title="Select fictional route JSON", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if path:
            self._select_routes(path)

    def _choose_route_folder(self) -> None:
        path = self.filedialog.askdirectory(parent=self.root, title="Select folder of fictional route JSON files")
        if path:
            self._select_routes(path)

    def _clear_routes(self) -> None:
        self.controller.clear_route_selection()
        self.routes_var.set(self.controller.routes_source)
        self.status_var.set("Compare and Pareto now use embedded routes.")

    def _compare(self) -> None:
        self._complete(self.controller.compare(), "Comparison complete.")

    def _evaluate(self) -> None:
        self._complete(self.controller.evaluate(), "Embedded-route evaluation complete.")

    def _pareto(self) -> None:
        self._complete(self.controller.pareto(), "Pareto frontier calculated with explicit metrics.")

    def _sensitivity(self) -> None:
        self._complete(self.controller.sensitivity(self.parameter_var.get(), self.values_var.get()), "Sensitivity analysis complete.")

    def _transaction_sweep(self) -> None:
        self._complete(self.controller.transaction_sweep(self.transaction_parameter_var.get(), self.transaction_values_var.get()), "Transaction sweep complete using embedded routes.")

    def _transaction_grid(self) -> None:
        self._complete(
            self.controller.transaction_grid(self.transaction_parameter_var.get(), self.transaction_values_var.get(), self.grid_parameter_b_var.get(), self.grid_values_b_var.get()),
            "Two-parameter transaction grid calculated without a composite score.",
        )

    def _stress_grid(self) -> None:
        self._complete(
            self.controller.stress_grid(self.parameter_var.get(), self.values_var.get(), self.parameter_b_var.get(), self.values_b_var.get()),
            "Two-parameter stress grid calculated without a composite score.",
        )

    def _cost_ledger(self) -> None:
        self._complete(self.controller.cost_ledger(), "Cost ledger complete: unrounded sender-cost components with currencies.")

    def _deadline_profile(self) -> None:
        self._complete(self.controller.deadline_profile(), "Deadline profile complete: exact success and resolution probabilities over time.")

    def _outcome_ledger(self) -> None:
        self._complete(self.controller.outcome_ledger(), "Outcome ledger complete: probability-weighted contributions per declared outcome.")

    def _guardrail_headroom(self) -> None:
        self._complete(self.controller.guardrail_headroom(), "Guardrail headroom complete: signed margins against declared guardrails.")

    def _loss_profile(self) -> None:
        self._complete(self.controller.loss_profile(), "Loss profile complete: principal-loss exceedance above declared breakpoints.")

    def _feasible_amount(self) -> None:
        self._complete(self.controller.feasible_amount(), "Feasible amount complete: minimum amounts on the declared precision grid.")

    def _break_even_check(self) -> None:
        self._complete(self.controller.break_even_check(), "Break-even check complete: whole-volume costs around declared crossovers.")

    def _deadline_target(self) -> None:
        self._complete(self.controller.deadline_target(self.deadline_target_var.get()), "Deadline target complete: earliest declared times meeting the requested probability.")

    def _resolution_quantiles(self) -> None:
        self._complete(self.controller.resolution_quantiles(self.quantiles_var.get()), "Resolution quantiles complete: exact discrete final-state times.")

    def _choose_baseline(self) -> None:
        path = self.filedialog.askopenfilename(parent=self.root, title="Select baseline scenario JSON", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if path:
            self.baseline_var.set(path)

    def _open_project(self) -> None:
        path = self.filedialog.askopenfilename(
            parent=self.root,
            title="Open corridor-lab project manifest",
            filetypes=(("Corridor Lab project", "corridor-lab.project.json"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        result = self.controller.open_project(path)
        if result.error is not None:
            self._show_error(result.error)
            return
        self._refresh_transaction_fields()
        self.scenario_var.set(self.controller.scenario_source)
        self.routes_var.set(self.controller.routes_source)
        if self.controller.baseline_file is not None:
            self.baseline_var.set(str(self.controller.baseline_file))
        self._refresh_saved_experiments()
        experiments = result.report["experiments"]
        self.status_var.set(
            f"Project {result.report['project_id']} opened with {len(experiments)} saved experiment(s). "
            "The previous report was cleared; project inputs were validated as present and unchanged."
        )

    def _save_project(self) -> None:
        if self.controller.scenario_file is None:
            self._show_error("Load a scenario from a file (not only the in-memory demo) before saving a project.")
            return
        destination = self.filedialog.askdirectory(parent=self.root, title="Choose an existing empty project directory")
        if not destination:
            return
        project_id = self.simpledialog.askstring(
            "Save project", "Project identifier (letters, numbers, dot, underscore, colon, slash, hyphen):", parent=self.root
        )
        if not project_id or not project_id.strip():
            return
        description = self.simpledialog.askstring("Save project", "Optional description:", parent=self.root) or ""
        result = self.controller.save_project(destination, project_id.strip(), description.strip())
        if result.error is not None:
            self._show_error(result.error)
            return
        self.status_var.set(f"Project saved to {self.controller.project_source}. Settings and inputs were copied explicitly.")

    def _refresh_saved_experiments(self) -> None:
        names = self.controller.saved_experiment_names()
        self.experiment_choice.configure(values=names)
        self.experiments_var.set(
            ", ".join(names) if names else "No saved experiments yet. Open a project or save current settings."
        )
        if names and self.selected_experiment_var.get() not in names:
            self.selected_experiment_var.set(names[0])
        variant_names = self.controller.variant_names()
        self.variant_choice.configure(values=variant_names)
        self.variants_var.set(
            ", ".join(variant_names) if variant_names else "No derived variants yet. Add one with explicit changes."
        )
        if variant_names and self.selected_variant_var.get() not in variant_names:
            self.selected_variant_var.set(variant_names[0])

    def _show_variant_diff(self) -> None:
        name = self.selected_variant_var.get()
        if not name:
            self._show_error("Choose a derived variant to inspect its assumption diff.")
            return
        self._complete(self.controller.show_variant_diff(name), f"Assumption diff for {name}: exactly these declared fields change.")

    def _apply_variant(self) -> None:
        name = self.selected_variant_var.get()
        if not name:
            self._show_error("Choose a derived variant to apply.")
            return
        result = self.controller.apply_variant(name)
        if result.error is not None:
            self._show_error(result.error)
            return
        self._refresh_transaction_fields()
        self.scenario_var.set(self.controller.scenario_source)
        self.status_var.set(f"Variant {name} applied in memory (unsaved). The previous report was cleared; rerun analyses against it.")

    def _compare_variants(self) -> None:
        self._complete(self.controller.compare_variants(), "Variant comparison complete: one declared case per variant, no composite score.")

    def _run_saved_experiment(self) -> None:
        name = self.selected_experiment_var.get()
        if not name:
            self._show_error("Choose a saved experiment to run, or save current settings first.")
            return
        self._complete(self.controller.run_saved_experiment(name), f"Saved experiment {name} complete using the shared library executor.")

    def _save_experiment_dialog(self) -> None:
        if self.controller.scenario is None:
            self._show_error("Load a fictional scenario before saving an experiment configuration.")
            return
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Save experiment configuration")
        dialog.minsize(560, 260)
        dialog.columnconfigure(1, weight=1)
        analysis_var = self.tk.StringVar(value="transaction-sweep")
        name_var = self.tk.StringVar()
        field_a_var = self.tk.StringVar()
        field_b_var = self.tk.StringVar()
        field_c_var = self.tk.StringVar()
        field_d_var = self.tk.StringVar()
        labels = {
            "sensitivity": ("Parameter", "Values"),
            "transaction-sweep": ("Parameter", "Values"),
            "transaction-grid": ("Parameter A", "Values A", "Parameter B", "Values B"),
            "stress-grid": ("Parameter A", "Values A", "Parameter B", "Values B"),
            "deadline-target": ("Probability", ""),
            "resolution-quantiles": ("", "Probabilities"),
        }
        row = 0
        name_label = self.ttk.Label(dialog, text="Name")
        name_label.grid(row=row, column=0, sticky="w")
        self.ttk.Entry(dialog, textvariable=name_var, width=30).grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        self.ttk.Label(dialog, text="Analysis").grid(row=row, column=0, sticky="w")
        analysis_box = self.ttk.Combobox(dialog, textvariable=analysis_var, values=tuple(labels), state="readonly", width=28)
        analysis_box.grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        label_a = self.ttk.Label(dialog, text="Parameter")
        label_a.grid(row=row, column=0, sticky="w")
        entry_a = self.ttk.Entry(dialog, textvariable=field_a_var, width=28)
        entry_a.grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        label_b = self.ttk.Label(dialog, text="Values")
        label_b.grid(row=row, column=0, sticky="w")
        entry_b = self.ttk.Entry(dialog, textvariable=field_b_var, width=28)
        entry_b.grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        label_c = self.ttk.Label(dialog, text="Parameter B")
        label_c.grid(row=row, column=0, sticky="w")
        entry_c = self.ttk.Entry(dialog, textvariable=field_c_var, width=28)
        entry_c.grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        label_d = self.ttk.Label(dialog, text="Values B")
        label_d.grid(row=row, column=0, sticky="w")
        entry_d = self.ttk.Entry(dialog, textvariable=field_d_var, width=28)
        entry_d.grid(row=row, column=1, sticky="w", padx=6)
        status_var = self.tk.StringVar(value="Save Current Settings stages the experiment in memory; Save Project writes it.")

        def refresh_labels(*_args: object) -> None:
            layout = labels[analysis_var.get()]
            label_a.configure(text=layout[0])
            label_b.configure(text=layout[1] if len(layout) > 1 else "")
            label_c.configure(text=layout[2] if len(layout) > 2 else "Parameter B")
            label_d.configure(text=layout[3] if len(layout) > 3 else "Values B")

        analysis_box.bind("<<ComboboxSelected>>", refresh_labels)
        self.ttk.Label(dialog, textvariable=status_var, wraplength=520).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def save() -> None:
            analysis = analysis_var.get()
            layout = labels[analysis]
            fields: dict[str, str] = {}
            if analysis in ("transaction-grid", "stress-grid"):
                fields = {"parameter_a": field_a_var.get(), "values_a": field_b_var.get(),
                          "parameter_b": field_c_var.get(), "values_b": field_d_var.get()}
            elif analysis == "deadline-target":
                fields = {"probability": field_a_var.get()}
            elif analysis == "resolution-quantiles":
                fields = {"probabilities": field_b_var.get()}
            else:
                fields = {"parameter": field_a_var.get(), "values": field_b_var.get()}
            result = self.controller.add_saved_experiment(name_var.get(), analysis, fields)
            if result.error is not None:
                status_var.set(f"Not saved: {result.error}")
                self._show_error(result.error)
                return
            self._refresh_saved_experiments()
            dialog.destroy()
            self.status_var.set(f"Experiment {name_var.get().strip()} staged in memory. Save Project As... persists it.")

        buttons = self.ttk.Frame(dialog)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.ttk.Button(buttons, text="Save Current Settings", command=save).grid(row=0, column=0)
        self.ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=1, padx=6)

    def _scenario_diff(self) -> None:
        if not self.baseline_var.get().strip():
            self._show_error("Select a baseline scenario file before diffing.")
            return
        self._complete(
            self.controller.diff_against_baseline(self.baseline_var.get()),
            "Scenario diff complete: candidate minus baseline for matched routes.",
        )

    def _save_report(self) -> None:
        if self.controller.last_report is None:
            self._show_error("Run an analysis before saving a report.")
            return
        output_format = self.format_var.get()
        extension = {"json": ".json", "csv": ".csv", "markdown": ".md"}[output_format]
        path = self.filedialog.asksaveasfilename(
            parent=self.root,
            title="Save report",
            defaultextension=extension,
            filetypes=((f"{output_format.upper()} report", f"*{extension}"), ("All files", "*.*")),
        )
        if not path:
            return
        result = self.controller.save_last_report(path, output_format)
        if result.error is not None:
            self._show_error(result.error)
            return
        self.status_var.set(f"Report saved to {path}")


def launch_gui() -> int:
    """Open the Tk desktop interface only when a graphical session is requested."""
    try:
        tk, filedialog, messagebox, scrolledtext, simpledialog, ttk = _load_tk_modules()
    except ImportError:
        return _startup_failure()

    try:
        root = tk.Tk()
    except tk.TclError:
        return _startup_failure()
    CorridorLabApp(root, tk, ttk, filedialog, messagebox, scrolledtext, simpledialog)
    root.mainloop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corridorlab-gui", description="Open the Corridor Lab desktop interface.")
    parser.add_argument("--smoke-test", action="store_true", help="exercise controller and built-in demo without opening a window")
    args = parser.parse_args(argv)
    if args.smoke_test:
        return run_smoke_test()
    return launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
