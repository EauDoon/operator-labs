"""Optional Tkinter desktop interface for Corridor Lab.

Tkinter imports are intentionally delayed so the CLI and calculation library
remain usable in headless environments.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .gui_controller import CorridorGuiController


STARTUP_FAILURE_MESSAGE = "Corridor Lab could not open its desktop interface. Install or enable Tcl/Tk, then try again."


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
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    return tk, filedialog, messagebox, scrolledtext, ttk


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
    _write_smoke_status()
    return 0


def launch_gui() -> int:
    """Open the Tk desktop interface only when a graphical session is requested."""
    try:
        tk, filedialog, messagebox, scrolledtext, ttk = _load_tk_modules()
    except ImportError:
        return _startup_failure()

    class CorridorLabApp:
        def __init__(self, root: object) -> None:
            self.root = root
            self.controller = CorridorGuiController()
            self.format_var = tk.StringVar(value="markdown")
            self.scenario_var = tk.StringVar(value=self.controller.scenario_source)
            self.routes_var = tk.StringVar(value=self.controller.routes_source)
            self.parameter_var = tk.StringVar(value="fx_spread_bps")
            self.values_var = tk.StringVar(value="10,25,50,100")
            self.status_var = tk.StringVar(value="Load the built-in fictional demo or select your own fictional inputs.")
            self.editor_window = None
            self.editor_text = None
            self.editor_status_var = None
            root.title("Corridor Lab")
            root.minsize(900, 620)
            root.bind_all("<Control-e>", self._open_editor_shortcut)
            root.bind_all("<Control-h>", self._explain_report_shortcut)
            self._build(ttk, scrolledtext)

        def _build(self, ttk_module: object, scrolledtext_module: object) -> None:
            frame = ttk_module.Frame(self.root, padding=12)
            frame.grid(sticky="nsew")
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(6, weight=1)

            ttk_module.Label(frame, text="Corridor Lab", font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
            ttk_module.Label(
                frame,
                text="Offline comparison of declared fictional payment-route scenarios. No live rates or provider data.",
            ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 10))

            ttk_module.Button(frame, text="Load Built-in Fictional Demo", command=self._load_demo).grid(row=2, column=0, sticky="w", pady=2)
            ttk_module.Button(frame, text="Edit Scenario JSON...", command=self._open_editor, underline=0).grid(row=2, column=1, sticky="w", padx=6)
            ttk_module.Label(frame, textvariable=self.status_var, wraplength=360).grid(row=2, column=2, sticky="w", padx=(10, 0))

            ttk_module.Label(frame, text="Scenario JSON").grid(row=3, column=0, sticky="w", pady=2)
            ttk_module.Entry(frame, textvariable=self.scenario_var, state="readonly").grid(row=3, column=1, sticky="ew", padx=6)
            ttk_module.Button(frame, text="Browse...", command=self._choose_scenario).grid(row=3, column=2, sticky="e")

            ttk_module.Label(frame, text="Route JSON or folder").grid(row=4, column=0, sticky="w", pady=2)
            ttk_module.Entry(frame, textvariable=self.routes_var, state="readonly").grid(row=4, column=1, sticky="ew", padx=6)
            route_actions = ttk_module.Frame(frame)
            route_actions.grid(row=4, column=2, sticky="e")
            ttk_module.Button(route_actions, text="File...", command=self._choose_route_file).grid(row=0, column=0)
            ttk_module.Button(route_actions, text="Folder...", command=self._choose_route_folder).grid(row=0, column=1, padx=(4, 0))
            ttk_module.Button(route_actions, text="Use Embedded", command=self._clear_routes).grid(row=0, column=2, padx=(4, 0))

            actions = ttk_module.LabelFrame(frame, text="Actions", padding=8)
            actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 8))
            actions.columnconfigure(7, weight=1)
            ttk_module.Button(actions, text="Compare", command=self._compare).grid(row=0, column=0, padx=(0, 5))
            ttk_module.Button(actions, text="Evaluate Embedded", command=self._evaluate).grid(row=0, column=1, padx=5)
            ttk_module.Label(actions, text="Sensitivity").grid(row=0, column=2, padx=(15, 3))
            ttk_module.Entry(actions, textvariable=self.parameter_var, width=18).grid(row=0, column=3, padx=3)
            ttk_module.Entry(actions, textvariable=self.values_var, width=18).grid(row=0, column=4, padx=3)
            ttk_module.Button(actions, text="Run", command=self._sensitivity).grid(row=0, column=5, padx=(3, 15))
            ttk_module.Label(actions, text="Preview format").grid(row=0, column=6, padx=(0, 3))
            format_box = ttk_module.Combobox(actions, textvariable=self.format_var, values=("markdown", "json", "csv"), state="readonly", width=10)
            format_box.grid(row=0, column=7, sticky="w")
            format_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_preview())
            ttk_module.Button(actions, text="Save Report...", command=self._save_report).grid(row=0, column=8, padx=(12, 0))
            ttk_module.Button(actions, text="Explain Report", command=self._explain_report).grid(row=0, column=9, padx=(6, 0))

            self.preview = scrolledtext_module.ScrolledText(frame, wrap="word", height=24, font=("TkFixedFont", 10))
            self.preview.grid(row=6, column=0, columnspan=3, sticky="nsew")
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
            messagebox.showerror("Corridor Lab", message, parent=self.root)

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
                self._show_error("Run Compare, Evaluate, or Sensitivity before opening the report explanation.")
                return
            self.format_var.set("markdown")
            self._refresh_preview()
            self.status_var.set("Showing the Markdown report and its text-first explanation.")

        def _complete(self, result: object, success_message: str) -> None:
            if result.error is not None:
                self._show_error(result.error)
                return
            self._refresh_preview()
            self.status_var.set(success_message)

        def _load_demo(self) -> None:
            result = self.controller.load_builtin_demo()
            if result.error is not None:
                self._show_error(result.error)
                return
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
            editor = tk.Toplevel(self.root)
            editor.title("Edit Fictional Scenario JSON")
            editor.minsize(760, 560)
            editor.columnconfigure(0, weight=1)
            editor.rowconfigure(2, weight=1)
            self.editor_window = editor
            self.editor_status_var = tk.StringVar(
                value="Validate and Use replaces the active scenario only after strict validation succeeds."
            )
            ttk.Label(
                editor,
                text="Edit only fictional values. Load Fictional Template affects this draft only until Validate and Use.",
                wraplength=700,
            ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
            controls = ttk.Frame(editor, padding=(12, 0, 12, 6))
            controls.grid(row=1, column=0, sticky="ew")
            ttk.Button(controls, text="Load Fictional Template", command=self._load_editor_template).grid(row=0, column=0, padx=(0, 6))
            ttk.Button(controls, text="Validate and Use", command=self._validate_editor).grid(row=0, column=1, padx=6)
            ttk.Button(controls, text="Save Scenario As...", command=self._save_editor_scenario).grid(row=0, column=2, padx=6)
            ttk.Label(controls, textvariable=self.editor_status_var, wraplength=350).grid(row=0, column=3, sticky="w", padx=(12, 0))
            self.editor_text = scrolledtext.ScrolledText(editor, wrap="none", undo=True, font=("TkFixedFont", 10))
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
            self._set_preview("Scenario validated and active. Choose Compare, Evaluate Embedded, or Sensitivity.\n")
            self.editor_status_var.set("Scenario validated and active. No scenario file was written.")
            self.status_var.set("Validated in-memory fictional scenario is active. External route selection was cleared.")

        def _save_editor_shortcut(self, _event: object) -> str:
            self._save_editor_scenario()
            return "break"

        def _save_editor_scenario(self) -> None:
            path = filedialog.asksaveasfilename(
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
            path = filedialog.askopenfilename(parent=self.root, title="Select fictional scenario JSON", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
            if not path:
                return
            result = self.controller.load_scenario_file(path)
            if result.error is not None:
                self._show_error(result.error)
                return
            self.scenario_var.set(self.controller.scenario_source)
            self.routes_var.set(self.controller.routes_source)
            self.status_var.set("Scenario loaded. Compare uses embedded routes unless a route file or folder is selected.")

        def _select_routes(self, path: str) -> None:
            result = self.controller.load_routes_path(path)
            if result.error is not None:
                self._show_error(result.error)
                return
            self.routes_var.set(self.controller.routes_source)
            self.status_var.set("Route selection loaded. Compare uses this selection; Evaluate and Sensitivity use embedded routes.")

        def _choose_route_file(self) -> None:
            path = filedialog.askopenfilename(parent=self.root, title="Select fictional route JSON", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
            if path:
                self._select_routes(path)

        def _choose_route_folder(self) -> None:
            path = filedialog.askdirectory(parent=self.root, title="Select folder of fictional route JSON files")
            if path:
                self._select_routes(path)

        def _clear_routes(self) -> None:
            self.controller.clear_route_selection()
            self.routes_var.set(self.controller.routes_source)
            self.status_var.set("Compare now uses embedded routes.")

        def _compare(self) -> None:
            self._complete(self.controller.compare(), "Comparison complete.")

        def _evaluate(self) -> None:
            self._complete(self.controller.evaluate(), "Embedded-route evaluation complete.")

        def _sensitivity(self) -> None:
            self._complete(
                self.controller.sensitivity(self.parameter_var.get(), self.values_var.get()),
                "Sensitivity analysis complete.",
            )

        def _save_report(self) -> None:
            if self.controller.last_report is None:
                self._show_error("Run Compare, Evaluate, or Sensitivity before saving a report.")
                return
            output_format = self.format_var.get()
            extension = {"json": ".json", "csv": ".csv", "markdown": ".md"}[output_format]
            path = filedialog.asksaveasfilename(
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

    try:
        root = tk.Tk()
    except tk.TclError:
        return _startup_failure()
    CorridorLabApp(root)
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
