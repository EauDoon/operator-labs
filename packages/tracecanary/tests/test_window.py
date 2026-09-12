"""Real-window tests for the TraceCanary desktop interface.

These construct an actual Tk root and build the real widget tree, so they show
that the window is constructible, that the run-history panel is wired to the
controller, and that a failing action still records something. When no graphical
display is available the tests skip with an explicit reason rather than
pretending the window was built.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tracecanary import gui  # noqa: E402


def _tk_modules() -> tuple[Any, Any, Any, Any] | None:
    """Return the Tkinter modules, or None when no graphical session exists."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:  # pragma: no cover - environment dependent
        return None
    return tk, ttk, filedialog, messagebox


try:
    import tkinter as _tk  # noqa: E402

    _probe = _tk.Tk()
    _probe.withdraw()
    _probe.destroy()
    DISPLAY_AVAILABLE = _tk_modules() is not None
except Exception:  # pragma: no cover - environment dependent
    DISPLAY_AVAILABLE = False

SKIP_REASON = "no graphical display available for a real-window test"

FIXTURES = ROOT / "fixtures" / "v1"


@unittest.skipUnless(DISPLAY_AVAILABLE, SKIP_REASON)
class RealWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        modules = _tk_modules()
        assert modules is not None
        self.tk, self.ttk, self.filedialog, self.messagebox = modules
        self.root = self.tk.Tk()
        self.root.withdraw()
        self.app = gui.TraceCanaryWindow(self.tk, self.ttk, self.filedialog, self.messagebox, root=self.root)

    def tearDown(self) -> None:
        self.root.destroy()

    def _history_lines(self) -> list[str]:
        return [self.app._history_list.get(index) for index in range(self.app._history_list.size())]

    def _run_a_passing_check(self) -> None:
        self.app._contract.set(str(FIXTURES / "contract.json"))
        self.app._input.set(str(FIXTURES / "safe-export.json"))
        self.app._check()

    def test_window_builds_with_a_title_and_the_expected_controls(self) -> None:
        self.assertEqual(self.root.title(), "TraceCanary")
        self.root.update_idletasks()
        labels = sorted(_walk_labels(self.root))
        for expected in (
            "Validate",
            "Check",
            "Diff",
            "Batch Diff",
            "Contract Diff",
            "Clear history",
            "Export history...",
            "Run history (in memory only)",
            "Show Summary",
            "Explain",
        ):
            self.assertIn(expected, labels)

    def test_history_panel_starts_empty_and_gains_a_record_after_a_run(self) -> None:
        self.assertEqual(self._history_lines(), [])
        self.assertEqual(self.app._controller.history_records(), ())
        self._run_a_passing_check()
        lines = self._history_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("#1", lines[0])
        self.assertIn("check", lines[0])
        self.assertIn("PASS", lines[0])
        self.assertIn("0 finding(s)", lines[0])
        self.assertEqual(len(self.app._controller.history_records()), 1)

    def test_history_records_every_run_in_insertion_order(self) -> None:
        self.app._contract.set(str(FIXTURES / "contract.json"))
        self._run_a_passing_check()
        self.app._input.set(str(FIXTURES / "leaked-prompt.json"))
        self.app._check()
        lines = self._history_lines()
        self.assertEqual([line.split()[0] for line in lines], ["#1", "#2"])
        self.assertIn("REGRESSION", lines[1])

    def test_clear_history_empties_the_panel(self) -> None:
        self._run_a_passing_check()
        self.assertEqual(len(self._history_lines()), 1)
        self.app._clear_history()
        self.assertEqual(self._history_lines(), [])
        self.assertEqual(self.app._controller.history_records(), ())

    def test_a_failing_action_records_an_unresolved_entry(self) -> None:
        self.app._contract.set("")
        self.app._input.set(str(FIXTURES / "safe-export.json"))
        self.app._check()
        lines = self._history_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("UNRESOLVED", lines[0])
        self.assertEqual(self.app._controller.history_records()[0].status, "unresolved")

    def test_export_history_writes_nothing_until_a_path_is_chosen(self) -> None:
        self._run_a_passing_check()
        chosen: list[str] = []
        self.app._filedialog = SimpleNamespace(
            askopenfilename=lambda *args, **kwargs: "",
            askdirectory=lambda *args, **kwargs: "",
            asksaveasfilename=lambda *args, **kwargs: chosen.append(kwargs.get("title", "")) or "",
        )
        self.app._export_history()
        self.assertEqual(chosen, ["Export TraceCanary run history"])
        self.assertEqual(self.app._controller.history_records()[0].sequence, 1)

    def test_export_history_writes_the_chosen_path(self) -> None:
        self._run_a_passing_check()
        with _temporary_directory() as directory:
            destination = directory / "history.json"
            self.app._filedialog = SimpleNamespace(
                askopenfilename=lambda *args, **kwargs: "",
                askdirectory=lambda *args, **kwargs: "",
                asksaveasfilename=lambda *args, **kwargs: str(destination),
            )
            self.app._export_history()
            written = destination.read_text(encoding="utf-8")
        self.assertIn('"history_version":"tracecanary.history/v1"', written)
        self.assertNotIn("TCANARY_", written)

    def test_summary_and_explanation_views_render_for_a_run(self) -> None:
        self._run_a_passing_check()
        self.app._show_summary()
        self.assertIn("TraceCanary summary", self._report_text())
        self.app._show_explanation()
        self.assertIn("what remains unknown", self._report_text())

    def _report_text(self) -> str:
        return self.app._report.get("1.0", "end-1c")


class _temporary_directory:
    """Minimal temporary-directory context manager for the export test."""

    def __init__(self) -> None:
        self._path: Path | None = None

    def __enter__(self) -> Path:
        import tempfile

        self._context = tempfile.TemporaryDirectory()
        self._path = Path(self._context.__enter__())
        return self._path

    def __exit__(self, *args: object) -> None:
        self._context.__exit__(*args)


def _walk_labels(root: object) -> list[str]:
    """Return the text of every descendant widget that has one."""
    found: list[str] = []
    pending = [child for child in root.winfo_children()]  # type: ignore[attr-defined]
    while pending:
        widget = pending.pop()
        try:
            text = widget.cget("text")
        except Exception:
            text = ""
        if isinstance(text, str) and text:
            found.append(text)
        pending.extend(widget.winfo_children())
    return found


if __name__ == "__main__":
    unittest.main()
