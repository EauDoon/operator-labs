from __future__ import annotations

import builtins
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary import gui
from tracecanary.gui import launch_window
from tracecanary.gui import main as gui_main
from tracecanary.gui_controller import (
    EXIT_PASS,
    EXIT_REGRESSION,
    EXIT_UNRESOLVED,
    GUI001,
    GUI002,
    GUI003,
    GUI004,
    GUI005,
    GUI006,
    TraceCanaryController,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class GuiControllerTests(unittest.TestCase):
    @staticmethod
    def _guidance_code(report: object) -> str:
        return json.loads(report.json)["violations"][0]["code"]

    def test_built_in_demo_is_deterministic_and_does_not_echo_canaries(self) -> None:
        controller = TraceCanaryController()
        reports = [controller.built_in_demo() for _ in range(3)]
        self.assertTrue(all(report.status == "pass" and report.exit_code == EXIT_PASS for report in reports))
        self.assertEqual(len({report.json for report in reports}), 1)
        self.assertNotIn("TCANARY_", reports[0].human + reports[0].json)

    def test_controller_check_reports_regression_without_matched_value(self) -> None:
        report = TraceCanaryController().check(FIXTURES / "contract.json", FIXTURES / "leaked-prompt.json")
        self.assertEqual(report.status, "regression")
        self.assertEqual(report.exit_code, EXIT_REGRESSION)
        self.assertNotIn("TCANARY_PROMPT_71f0e04f", report.human + report.json)

    def test_controller_structural_collision_returns_no_rendered_output(self) -> None:
        marker = "tracecanary/v1"
        contract = {
            "contract_version": marker,
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "safe", "category": "test", "value": marker}],
            "required_retained_fields": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            input_path = root / "input.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            input_path.write_text('{"resourceSpans":[]}', encoding="utf-8")
            controller = TraceCanaryController()
            results = (controller.validate(contract_path), controller.check(contract_path, input_path))
        for result in results:
            self.assertEqual(result.exit_code, EXIT_UNRESOLVED)
            self.assertEqual(result.human + result.json, "")

    def test_hostile_numeric_otlp_is_unresolved_without_gui_exception(self) -> None:
        payload_text = '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"doubleValue":' + "9" * 5001 + '} } ]},"scopeSpans":[]} ]}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hostile.json"
            path.write_text(payload_text, encoding="utf-8")
            report = TraceCanaryController().check(FIXTURES / "contract.json", path)
        self.assertEqual(report.status, "unresolved")
        self.assertEqual(report.exit_code, EXIT_UNRESOLVED)

    def test_hostile_contract_error_is_unresolved_without_echoing_value(self) -> None:
        marker = "TCANARY_GUI_HOSTILE_9e12"
        contract = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "safe", "category": marker, "value": marker}],
            "required_retained_fields": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            report = TraceCanaryController().validate(path)
        self.assertEqual(report.status, "unresolved")
        self.assertEqual(report.exit_code, EXIT_UNRESOLVED)
        self.assertNotIn(marker, report.human + report.json)

    def test_action_preflight_identifies_only_the_missing_requirement(self) -> None:
        controller = TraceCanaryController()
        cases = [
            (controller.validate(""), GUI001),
            (controller.check("", "input.json"), GUI001),
            (controller.check("contract.json", ""), GUI002),
            (controller.diff("contract.json", "", "candidate.json"), GUI003),
            (controller.diff("contract.json", "baseline.json", ""), GUI004),
        ]
        for report, code in cases:
            with self.subTest(code=code):
                self.assertEqual(report.status, "unresolved")
                self.assertEqual(report.exit_code, EXIT_UNRESOLVED)
                self.assertEqual(self._guidance_code(report), code)
                self.assertNotIn("TC900", report.human + report.json)

    def test_invalid_selection_guidance_is_safe_and_does_not_echo_path(self) -> None:
        marker = "TCANARY_GUI_PATH_8b1e"
        report = TraceCanaryController().validate(marker)
        self.assertEqual(self._guidance_code(report), GUI005)
        self.assertNotIn(marker, report.human + report.json)
        self.assertNotIn("TC900", report.human + report.json)

    def test_starter_files_are_explicit_and_prepare_a_meaningful_diff(self) -> None:
        controller = TraceCanaryController()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "starter"
            destination.mkdir()
            result = controller.create_starter_files(destination)
            self.assertEqual(result.status, "pass")
            self.assertIsNotNone(result.starter_paths)
            paths = result.starter_paths
            self.assertTrue(paths.contract.is_file())
            self.assertTrue(paths.input.is_file())
            self.assertEqual(paths.input, paths.baseline)
            self.assertNotEqual(paths.baseline, paths.candidate)
            comparison = controller.diff(paths.contract, paths.baseline, paths.candidate)
        self.assertEqual(comparison.status, "regression")
        self.assertEqual(comparison.exit_code, EXIT_REGRESSION)

    def test_nonempty_starter_directory_fails_without_echoing_path_or_content(self) -> None:
        marker = "TCANARY_GUI_STARTER_19cf"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / marker
            destination.mkdir()
            (destination / "existing.txt").write_text(marker, encoding="utf-8")
            result = TraceCanaryController().create_starter_files(destination)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(self._guidance_code(result), GUI006)
        self.assertNotIn(marker, result.human + result.json)

    def test_gui_smoke_test_is_headless_and_stable(self) -> None:
        outputs = []
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = gui_main(["--smoke-test"])
            self.assertEqual(status, EXIT_PASS)
            outputs.append(output.getvalue())
        self.assertEqual(outputs, ["TraceCanary GUI smoke test: pass\n"] * 2)

    def test_tcl_error_during_window_creation_is_controlled(self) -> None:
        fake_tk = types.ModuleType("tkinter")

        class FakeTclError(Exception):
            pass

        def fail_to_create_window() -> None:
            raise FakeTclError()

        fake_tk.TclError = FakeTclError
        fake_tk.Tk = fail_to_create_window
        fake_tk.filedialog = object()
        fake_tk.messagebox = object()
        fake_tk.ttk = object()
        error = io.StringIO()
        with patch.dict(sys.modules, {"tkinter": fake_tk}), contextlib.redirect_stderr(error):
            status = launch_window()
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(error.getvalue(), "TraceCanary GUI could not open a window in this environment.\n")

    def test_missing_tk_with_absent_streams_uses_windows_fallback_without_dialog(self) -> None:
        original_import = builtins.__import__

        def deny_tkinter(name: str, *args: object, **kwargs: object) -> object:
            if name == "tkinter":
                raise ImportError("unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=deny_tkinter), patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), patch.object(gui, "_show_windows_error") as fallback:
            status = gui.launch_window()
        self.assertEqual(status, EXIT_UNRESOLVED)
        fallback.assert_called_once_with("TraceCanary GUI is unavailable because Tkinter is not installed.")

    def test_tcl_error_with_absent_streams_uses_windows_fallback_without_dialog(self) -> None:
        fake_tk = types.ModuleType("tkinter")

        class FakeTclError(Exception):
            pass

        def fail_to_create_window() -> None:
            raise FakeTclError()

        fake_tk.TclError = FakeTclError
        fake_tk.Tk = fail_to_create_window
        fake_tk.filedialog = object()
        fake_tk.messagebox = object()
        fake_tk.ttk = object()
        with patch.dict(sys.modules, {"tkinter": fake_tk}), patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), patch.object(gui, "_show_windows_error") as fallback:
            status = gui.launch_window()
        self.assertEqual(status, EXIT_UNRESOLVED)
        fallback.assert_called_once_with("TraceCanary GUI could not open a window in this environment.")
