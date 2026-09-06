"""Real-window tests for the Corridor Lab desktop interface.

These construct an actual Tk root and build the real widget tree. They are not a
substitute for looking at the window, but they do establish that the layout is
constructible, that the controls are wired to the controller, and that the
template and revision actions behave. When no graphical display is available the
tests skip with an explicit reason rather than pretending the window was built.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from corridor_lab import gui  # noqa: E402


def _tk_modules():
    """Return the Tkinter modules, or None when no graphical session exists."""
    try:
        return gui._load_tk_modules()
    except ImportError:
        return None


_MODULES = _tk_modules()

try:
    import tkinter as tk  # noqa: E402

    _probe = tk.Tk()
    _probe.withdraw()
    _probe.destroy()
    DISPLAY_AVAILABLE = _MODULES is not None
except Exception:  # pragma: no cover - environment dependent
    DISPLAY_AVAILABLE = False

SKIP_REASON = "no graphical display available for a real-window test"


@unittest.skipUnless(DISPLAY_AVAILABLE, SKIP_REASON)
class RealWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tk, self.filedialog, self.messagebox, self.scrolledtext, self.ttk = _MODULES
        self.root = self.tk.Tk()
        self.root.withdraw()
        self.app = gui.CorridorLabApp(
            self.root, self.ttk, self.scrolledtext, self.filedialog, self.messagebox, self.tk
        )

    def tearDown(self) -> None:
        if self.app.editor_window is not None:
            self.app.editor_window.destroy()
        self.root.destroy()

    def _preview_text(self) -> str:
        return self.app.preview.get("1.0", "end-1c")

    def test_window_builds_with_a_title_and_minimum_size(self):
        self.assertEqual(self.root.title(), "Corridor Lab")
        self.root.update_idletasks()
        self.assertGreaterEqual(self.root.winfo_reqwidth(), 900)

    def test_every_main_action_button_is_present(self):
        self.root.update_idletasks()
        labels = sorted(_walk_labels(self.app))
        for expected in ("Compare", "Evaluate Embedded", "Pareto Frontier", "Run", "Grid", "Save Report...", "Explain Report"):
            self.assertIn(expected, labels)

    def test_template_selector_is_populated_with_synthetic_templates(self):
        values = self.app.template_box.cget("values")
        self.assertIn("flat-fee-low-volume", values)
        self.assertIn("funding-shortfall", values)
        self.assertIn(self.app.template_var.get(), values)

    def test_load_template_fills_the_editor_without_writing_or_activating(self):
        self.app.template_var.set("funding-shortfall")
        self.app._load_template()
        self.assertIsNotNone(self.app.editor_text)
        draft = self.app.editor_text.get("1.0", "end-1c")
        self.assertIn("corridor-lab.scenario/v2", draft)
        self.assertIn("funding", draft)
        # The active scenario is untouched until the draft is validated.
        self.assertIsNone(self.app.controller.scenario)

    def test_validate_and_use_activates_the_template(self):
        self.app.template_var.set("funding-shortfall")
        self.app._load_template()
        self.app._validate_editor()
        self.assertIsNone(self.app.controller.last_error)
        self.assertIsNotNone(self.app.controller.scenario)
        self.assertEqual(self.app.controller.scenario.scenario_id, "fictional-funding-shortfall")

    def test_invalid_draft_keeps_the_previous_valid_scenario(self):
        self.app.template_var.set("funding-shortfall")
        self.app._load_template()
        self.app._validate_editor()
        active = self.app.controller.scenario
        current = self.app.editor_text.get("1.0", "end-1c")
        self.app._replace_editor_contents(current.replace('"fictional":true', '"fictional":false'))
        with _suppress_error_dialog(self.app):
            self.app._validate_editor()
        self.assertIs(self.app.controller.scenario, active)
        self.assertIn("fictional", self.app.controller.last_error)

    def test_compare_populates_the_preview(self):
        self.app._load_demo()
        text = self._preview_text()
        self.assertIn("How to read this report", text)
        self.assertIn("fictional-gui-linked-instant", text)

    def test_funding_action_runs_on_a_template_that_declares_a_schedule(self):
        self.app.template_var.set("funding-shortfall")
        self.app._load_template()
        self.app._validate_editor()
        result = self.app.controller.funding("0,1")
        self.assertIsNone(result.error)
        self.assertEqual(len(result.report["rows"]), 4)

    def test_scenario_diff_action_renders_an_explanation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = folder / "a.json"
            second = folder / "b.json"
            from corridor_lab.templates import template

            before = template("flat-fee-low-volume")
            after = template("flat-fee-low-volume")
            after["routes"][1]["fixed_fee_send"] = "4.00"
            import json

            first.write_text(json.dumps(before), encoding="utf-8")
            second.write_text(json.dumps(after), encoding="utf-8")
            result = self.app.controller.scenario_diff(first, second)
            self.assertIsNone(result.error)
            self.assertEqual(result.report["attribution"]["status"], "single_declared_change")
            self.app.format_var.set("markdown")
            self.app._refresh_preview()
            self.assertIn("## Attribution", self._preview_text())

    def test_save_revision_refuses_a_missing_folder(self):
        self.app.template_var.set("flat-fee-low-volume")
        self.app._load_template()
        result = self.app.controller.save_revision(Path("/definitely/not/a/folder"))
        self.assertIsNotNone(result.error)


class _SuppressDialog:
    def __init__(self, app: object) -> None:
        self.app = app
        self.original = None

    def __enter__(self):
        self.original = self.app._show_error
        self.app._show_error = lambda error: None
        return self

    def __exit__(self, *_args: object) -> None:
        self.app._show_error = self.original


def _suppress_error_dialog(app: object) -> _SuppressDialog:
    return _SuppressDialog(app)


def _walk_labels(app: object) -> list[str]:
    """Return the text of every descendant widget that has one."""
    found: list[str] = []
    pending = [child for child in app.root.winfo_children()]
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
