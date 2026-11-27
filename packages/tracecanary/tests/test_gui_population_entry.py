"""The window's population minimum entry, exercised without a Tk display.

The window methods under test read a few variables and call the controller,
so an instance built without __init__ and given stub variables runs them as
the real window does.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.gui import TraceCanaryWindow
from tracecanary.gui_controller import TraceCanaryController


class _Var:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _Dialogs:
    """Record dialog calls; a save that reaches them was not refused first."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return ""
        return call


def _window(entry, *, ticked=True):
    window = object.__new__(TraceCanaryWindow)
    window._controller = TraceCanaryController()
    window._contract = _Var("contract.json")
    window._input = _Var("")
    window._batch_dir = _Var("exports")
    window._baseline = _Var("")
    window._use_baseline = _Var(False)
    window._recursive = _Var(False)
    window._include_paths = _Var(False)
    window._batch_ratio = _Var("")
    window._batch_population = _Var(ticked)
    window._population_scope = _Var("span")
    window._population_minimum = _Var(entry)
    window._status = _Var("")
    window._messagebox = window._filedialog = window._simpledialog = _Dialogs()
    window.applied = []
    window.started = []
    window._apply = window.applied.append
    window._run_background = lambda work, status, **kwargs: window.started.append(work)
    window._batch_button = window._coverage_batch_button = None
    return window


REJECTED = ("0_1", "９９９", "٩٩٩", "²", "two", "1.0", "9" * 5000)


class PopulationEntryTests(unittest.TestCase):
    def assert_gui007(self, window, mode):
        self.assertEqual(window.started, [])
        self.assertEqual(len(window.applied), 1)
        report = json.loads(window.applied[0].json)
        self.assertEqual(report["mode"], mode)
        self.assertEqual(report["violations"][0]["code"], "GUI007")

    def test_a_ticked_batch_gate_never_runs_without_its_minimum(self):
        # The entry used to be dropped with a status line that the run then
        # replaced, so a batch passed without the gate the user had ticked.
        for action, mode in (("_batch", "batch"), ("_coverage_batch", "coverage-batch")):
            for entry in REJECTED + ("", "   "):
                with self.subTest(action=action, entry=entry[:8]):
                    window = _window(entry)
                    getattr(window, action)()
                    self.assert_gui007(window, mode)

    def test_a_batch_gate_with_an_ascii_minimum_starts_with_that_gate(self):
        for entry, expected in (("999", 999), (" 7 ", 7)):
            with self.subTest(entry=entry):
                window = _window(entry)
                self.assertEqual(window._batch_population_config("batch"), ("span", expected, None))
                window._batch()
                self.assertEqual(window.applied, [])
                self.assertEqual(len(window.started), 1)

    def test_an_unticked_batch_gate_ignores_the_entry(self):
        window = _window("two", ticked=False)
        self.assertEqual(window._batch_population_config("batch"), (None, None, None))
        window._batch()
        self.assertEqual(window.applied, [])
        self.assertEqual(len(window.started), 1)

    def test_project_save_refuses_a_bad_minimum_before_any_dialog(self):
        for entry in REJECTED:
            with self.subTest(entry=entry[:8]):
                window = _window(entry)
                window._save_project()
                self.assert_gui007(window, "project-save")
                self.assertEqual(window._filedialog.calls, [])


if __name__ == "__main__":
    unittest.main()
