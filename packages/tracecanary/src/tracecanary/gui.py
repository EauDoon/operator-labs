"""Tkinter desktop interface for TraceCanary.

Tkinter is imported only when an interactive window is requested, so normal
library and CLI imports remain usable in headless environments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from tracecanary import batch_pairs
from tracecanary.gui_controller import EXIT_PASS, EXIT_UNRESOLVED, GuiResult, TraceCanaryController
from tracecanary.report import UnsafeReportError


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
        root = tk.Tk()
        window = TraceCanaryWindow(tk, ttk, filedialog, messagebox, root=root)
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


class TraceCanaryWindow:
    """Small local UI that delegates all analysis to TraceCanaryController."""

    def __init__(self, tk: object, ttk: object, filedialog: object, messagebox: object, root: object | None = None) -> None:
        self._tk = tk
        self._ttk = ttk
        self._filedialog = filedialog
        self._messagebox = messagebox
        self._controller = TraceCanaryController()
        self._result: GuiResult | None = None
        self._view = "human"
        self._root = root if root is not None else tk.Tk()
        self._root.title("TraceCanary")
        self._root.minsize(880, 760)
        self._contract = tk.StringVar()
        self._input = tk.StringVar()
        self._baseline = tk.StringVar()
        self._candidate = tk.StringVar()
        self._baseline_dir = tk.StringVar()
        self._candidate_dir = tk.StringVar()
        self._contract_before = tk.StringVar()
        self._contract_after = tk.StringVar()
        self._pairing = tk.StringVar(value=batch_pairs.DEFAULT_PAIRING)
        self._group = tk.StringVar()
        self._status = tk.StringVar(value="Status: awaiting input")
        self._build()
        self._refresh_history()

    def run(self) -> None:
        self._root.mainloop()

    def _build(self) -> None:
        frame = self._ttk.Frame(self._root, padding=14)
        frame.grid(sticky="nsew")
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)

        title = self._ttk.Label(frame, text="TraceCanary", font=("TkDefaultFont", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w")
        self._ttk.Label(frame, text="Offline OTLP trace privacy-regression checks. Results never print matched canary values.").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self._add_selector(frame, 2, "Contract", self._contract)
        self._add_selector(frame, 3, "Input", self._input)
        self._add_selector(frame, 4, "Baseline", self._baseline)
        self._add_selector(frame, 5, "Candidate", self._candidate)

        controls = self._ttk.Frame(frame)
        controls.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 8))
        self._ttk.Button(controls, text="Validate", command=self._validate).grid(row=0, column=0, padx=(0, 6))
        self._ttk.Button(controls, text="Check", command=self._check).grid(row=0, column=1, padx=(0, 6))
        self._ttk.Button(controls, text="Diff", command=self._diff).grid(row=0, column=2, padx=(0, 6))
        self._ttk.Button(controls, text="Run Built-in Demo", command=self._demo).grid(row=0, column=3)
        self._ttk.Button(controls, text="Create Synthetic Starter Files", command=self._create_starter).grid(row=0, column=4, padx=(6, 0))

        self._build_review(frame)

        report_frame = self._ttk.LabelFrame(frame, text="Report", padding=6)
        report_frame.grid(row=8, column=0, columnspan=3, sticky="nsew")
        report_frame.columnconfigure(0, weight=1)
        report_frame.rowconfigure(1, weight=1)
        report_controls = self._ttk.Frame(report_frame)
        report_controls.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._status_label = self._tk.Label(report_controls, textvariable=self._status, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="w")
        self._ttk.Button(report_controls, text="Show Human", command=lambda: self._show("human")).grid(row=0, column=1, padx=(12, 4))
        self._ttk.Button(report_controls, text="Show JSON", command=lambda: self._show("json")).grid(row=0, column=2, padx=4)
        self._ttk.Button(report_controls, text="Show Summary", command=self._show_summary).grid(row=0, column=3, padx=4)
        self._ttk.Button(report_controls, text="Explain", command=self._show_explanation).grid(row=0, column=4, padx=4)
        self._ttk.Button(report_controls, text="Save Report", command=self._save).grid(row=0, column=5, padx=(4, 0))
        self._report = self._tk.Text(report_frame, wrap="word", height=18, state="disabled")
        self._report.grid(row=1, column=0, sticky="nsew")
        scroll = self._ttk.Scrollbar(report_frame, orient="vertical", command=self._report.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self._report.configure(yscrollcommand=scroll.set)

        self._build_history(frame)

    def _build_review(self, frame: object) -> None:
        """Add the batch-diff and contract-review selectors and actions."""
        review = self._ttk.LabelFrame(frame, text="Batch diff and contract review", padding=6)
        review.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        review.columnconfigure(1, weight=1)
        self._add_directory_selector(review, 0, "Baseline dir", self._baseline_dir)
        self._add_directory_selector(review, 1, "Candidate dir", self._candidate_dir)
        self._ttk.Label(review, text="Pairing").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self._ttk.Combobox(
            review,
            textvariable=self._pairing,
            values=list(batch_pairs.PAIRING_MODES),
            state="readonly",
            width=12,
        ).grid(row=2, column=1, sticky="w", pady=2)
        self._add_selector(review, 3, "Contract before", self._contract_before)
        self._add_selector(review, 4, "Contract after", self._contract_after)
        actions = self._ttk.Frame(review)
        actions.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._ttk.Button(actions, text="Batch Diff", command=self._batch_diff).grid(row=0, column=0, padx=(0, 6))
        self._ttk.Button(actions, text="Contract Diff", command=self._contract_diff).grid(row=0, column=1)

    def _build_history(self, frame: object) -> None:
        """Add the read-only run history panel and its two explicit actions."""
        history = self._ttk.LabelFrame(frame, text="Run history (in memory only)", padding=6)
        history.grid(row=9, column=0, columnspan=3, sticky="ew")
        history.columnconfigure(1, weight=1)
        self._ttk.Label(history, text="Group").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._ttk.Entry(history, textvariable=self._group).grid(row=0, column=1, sticky="ew", pady=(0, 4))
        self._ttk.Label(history, text="sequence, mode, status, findings").grid(row=0, column=2, sticky="w", padx=(8, 0))
        self._history_list = self._tk.Listbox(history, height=6, state="disabled")
        self._history_list.grid(row=1, column=0, columnspan=3, sticky="ew")
        scroll = self._ttk.Scrollbar(history, orient="vertical", command=self._history_list.yview)
        scroll.grid(row=1, column=3, sticky="ns")
        self._history_list.configure(yscrollcommand=scroll.set)
        actions = self._ttk.Frame(history)
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._ttk.Button(actions, text="Clear history", command=self._clear_history).grid(row=0, column=0, padx=(0, 6))
        self._ttk.Button(actions, text="Export history...", command=self._export_history).grid(row=0, column=1)

    def _add_selector(self, frame: object, row: int, label: str, variable: object) -> None:
        self._ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        self._ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
        self._ttk.Button(frame, text="Browse", command=lambda: self._browse(variable)).grid(row=row, column=2, sticky="e", pady=2)

    def _add_directory_selector(self, frame: object, row: int, label: str, variable: object) -> None:
        self._ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        self._ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
        self._ttk.Button(frame, text="Browse", command=lambda: self._browse_directory(variable)).grid(row=row, column=2, sticky="e", pady=2)

    def _browse(self, variable: object) -> None:
        selected = self._filedialog.askopenfilename(title="Select JSON file", filetypes=[("JSON files", "*.json"), ("All files", "*")])
        if selected:
            variable.set(selected)

    def _browse_directory(self, variable: object) -> None:
        selected = self._filedialog.askdirectory(title="Select a directory of JSON trace exports", mustexist=True)
        if selected:
            variable.set(selected)

    def _group_label(self) -> str | None:
        """Return the optional declared group label, or None when it is blank."""
        return self._group.get().strip() or None

    def _validate(self) -> None:
        self._apply(self._controller.validate(self._contract.get(), group=self._group_label()))

    def _check(self) -> None:
        self._apply(self._controller.check(self._contract.get(), self._input.get(), group=self._group_label()))

    def _diff(self) -> None:
        self._apply(self._controller.diff(self._contract.get(), self._baseline.get(), self._candidate.get(), group=self._group_label()))

    def _batch_diff(self) -> None:
        self._apply(
            self._controller.batch_diff(
                self._contract.get(),
                self._baseline_dir.get(),
                self._candidate_dir.get(),
                pairing=self._pairing.get() or batch_pairs.DEFAULT_PAIRING,
                include_paths=False,
                group=self._group_label(),
            )
        )

    def _contract_diff(self) -> None:
        self._apply(self._controller.contract_review(self._contract_before.get(), self._contract_after.get()))

    def _demo(self) -> None:
        self._apply(self._controller.built_in_demo())

    def _create_starter(self) -> None:
        destination = self._filedialog.askdirectory(title="Select an empty directory for synthetic starter files", mustexist=True)
        if not destination:
            return
        result = self._controller.create_starter_files(destination)
        if result.starter_paths is not None:
            self._contract.set(str(result.starter_paths.contract))
            self._input.set(str(result.starter_paths.input))
            self._baseline.set(str(result.starter_paths.baseline))
            self._candidate.set(str(result.starter_paths.candidate))
        self._apply(result)
        if result.starter_paths is not None:
            self._status.set("Status: synthetic starter files created. Check and Diff are ready.")

    def _apply(self, result: GuiResult) -> None:
        self._result = result
        self._view = "human"
        color = {"pass": "#176b2c", "regression": "#9b2500", "unresolved": "#6b4300"}.get(result.status, "#333333")
        self._status.set(f"Status: {result.status.upper()} (exit {result.exit_code})")
        self._status_label.configure(foreground=color)
        self._refresh_history()
        self._show("human")

    def _show(self, view: str) -> None:
        if self._result is None:
            return
        self._view = view
        text = self._result.human if view == "human" else self._result.json
        self._write_report(text)

    def _show_summary(self) -> None:
        """Show the deterministic summary panel of the most recent run."""
        summary = self._controller.last_summary()
        if not summary:
            self._status.set("Status: run an action before showing a summary")
            return
        self._view = "human"
        self._write_report(summary)

    def _show_explanation(self) -> None:
        """Show the deterministic explanation of the most recent run."""
        explanation = self._controller.last_explanation()
        if not explanation:
            self._status.set("Status: run an action before explaining a report")
            return
        self._view = "human"
        self._write_report(explanation)

    def _write_report(self, text: str) -> None:
        self._report.configure(state="normal")
        self._report.delete("1.0", "end")
        self._report.insert("1.0", text)
        self._report.configure(state="disabled")

    def _refresh_history(self) -> None:
        """Redraw the read-only history list from the controller's records."""
        self._history_list.configure(state="normal")
        self._history_list.delete(0, "end")
        for record in self._controller.history_records():
            findings = int(record.summary.get("total", 0))
            line = f"#{record.sequence} {record.mode} {record.status.upper()} {findings} finding(s)"
            if record.group:
                line += f" [group={record.group}]"
            self._history_list.insert("end", line)
        self._history_list.configure(state="disabled")

    def _clear_history(self) -> None:
        """Discard the in-memory run history. This cannot be undone."""
        self._controller.clear_history()
        self._refresh_history()
        self._status.set("Status: run history cleared")

    def _export_history(self) -> None:
        """Export the run history only after the user chooses a destination."""
        if not self._controller.history_records():
            self._status.set("Status: run history is empty")
            return
        selected = self._filedialog.asksaveasfilename(
            title="Export TraceCanary run history",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
        )
        if not selected:
            return
        try:
            content = self._controller.export_history()
        except UnsafeReportError:
            self._messagebox.showerror("TraceCanary", "The run history could not be exported because it would expose a protected value.")
            self._status.set("Status: run history could not be exported")
            return
        try:
            Path(selected).write_text(content, encoding="utf-8", newline="\n")
        except OSError:
            self._messagebox.showerror("TraceCanary", "The run history could not be saved.")
            return
        self._status.set("Status: run history exported")

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
        content = self._result.json if is_json else self._result.human
        try:
            Path(selected).write_text(content, encoding="utf-8", newline="\n")
        except OSError:
            self._messagebox.showerror("TraceCanary", "The report could not be saved.")
            return
        self._status.set("Status: report saved")


if __name__ == "__main__":
    raise SystemExit(main())
