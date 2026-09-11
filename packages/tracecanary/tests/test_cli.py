from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.cli import EXIT_PASS, EXIT_UNRESOLVED, main
from tracecanary.gui import main as gui_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class CliUsageTests(unittest.TestCase):
    def test_explicit_quality_gates_emit_reports_with_expected_exit_status(self):
        for command, extra, expected in (
            ("control-check", [], 2),
            ("population-gate", ["--scope", "span", "--minimum", "1"], 0),
            ("population-gate", ["--scope", "span", "--minimum", "2"], 1),
            ("dropped-telemetry", ["--require-zero"], 0),
        ):
            for fmt in ("human", "json"):
                with self.subTest(command=command, format=fmt, extra=extra):
                    status, output, error = self._run([command, "--contract", str(FIXTURES / "contract.json"),
                                                     "--input", str(FIXTURES / "safe-export.json"), *extra, "--format", fmt])
                    self.assertEqual(status, expected)
                    self.assertTrue(output)
                    self.assertEqual(error, "")

    def _run(self, command: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(command)
        return status, output.getvalue(), error.getvalue()

    def test_help_documents_exit_status_and_arguments(self) -> None:
        status, output, error = self._run(["--help"])
        self.assertEqual(status, EXIT_PASS)
        self.assertEqual(error, "")
        self.assertIn("Exit status:", output)
        self.assertIn("control-check: 0 means all canaries were exercised", output)
        self.assertIn("invalid input, unsupported version, or unresolved comparison", output)
        self.assertIn("validate", output)
        status, output, error = self._run(["check", "--help"])
        self.assertEqual(status, EXIT_PASS)
        self.assertIn("OTLP/HTTP JSON trace export", output)
        self.assertIn("--contract", output)

    def test_empty_path_is_unresolved_and_is_not_the_working_directory(self) -> None:
        status, output, error = self._run(
            ["check", "--contract", str(FIXTURES / "contract.json"), "--input", ""]
        )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("path must not be empty", error)
        self.assertNotIn("directory", error)

    def test_whitespace_path_is_unresolved(self) -> None:
        status, output, error = self._run(["validate", "   "])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("path must not be empty", error)

    def test_empty_fixture_output_does_not_write_into_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            previous = Path.cwd()
            output = io.StringIO()
            error = io.StringIO()
            try:
                os.chdir(cwd)
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    status = main(["fixture", "create", "--output", ""])
            finally:
                os.chdir(previous)
            self.assertEqual(status, EXIT_UNRESOLVED)
            self.assertEqual(list(cwd.iterdir()), [])
            self.assertEqual(output.getvalue(), "")
            self.assertIn("path must not be empty", error.getvalue())

    def test_unknown_flag_is_unresolved(self) -> None:
        status, output, error = self._run(
            [
                "check",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--input",
                str(FIXTURES / "safe-export.json"),
                "--bogus",
            ]
        )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("unrecognized arguments", error)
        self.assertIn("UNRESOLVED", error)

    def test_abbreviated_flags_are_rejected(self) -> None:
        status, output, error = self._run(
            [
                "check",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--input",
                str(FIXTURES / "safe-export.json"),
                "--form",
                "json",
            ]
        )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("unrecognized arguments", error)
        self.assertIn("--form", error)

    def test_unknown_command_is_unresolved(self) -> None:
        status, output, error = self._run(["nope"])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("invalid choice", error)

    def test_batch_help_documents_the_file_limit_default(self) -> None:
        status, output, error = self._run(["batch", "--help"])
        self.assertEqual(status, EXIT_PASS)
        self.assertEqual(error, "")
        self.assertIn("limits.max_batch_files", output)
        self.assertIn("default 256", output)

    def test_directory_with_no_json_files_is_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "notes.txt").write_text("not a trace\n", encoding="utf-8")
            status, output, error = self._run(
                ["batch", "--contract", str(FIXTURES / "contract.json"), "--input-dir", directory]
            )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("no JSON files", error)

    def test_gui_help_and_unknown_flag(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = gui_main(["--help"])
        self.assertEqual(status, EXIT_PASS)
        self.assertIn("Save Report", output.getvalue())
        self.assertIn("--smoke-test", output.getvalue())
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = gui_main(["--bogus"])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("unrecognized arguments", error.getvalue())
