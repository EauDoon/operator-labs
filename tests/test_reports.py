from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import load_json
from tracecanary.checker import check_trace
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.contract import load_contract
from tracecanary.fixture import bundle
from tracecanary.otlp import validate_trace
from tracecanary.report import UnsafeReportError, ensure_object_values_absent, render_human, render_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class ReportTests(unittest.TestCase):
    def _assert_cli_fails_silently(self, command: list[str]) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(command)
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output.getvalue() + error.getvalue(), "")

    def test_three_reports_are_byte_identical(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        payload = load_json(FIXTURES / "safe-export.json", max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
        validate_trace(payload)
        outputs = [render_json(check_trace(contract, payload)) for _ in range(3)]
        self.assertEqual(len(set(outputs)), 1)

    def test_cli_exit_codes_and_no_canary_echo(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["check", "--contract", str(FIXTURES / "contract.json"), "--input", str(FIXTURES / "safe-export.json"), "--format", "json"])
        self.assertEqual(status, EXIT_PASS)
        self.assertNotIn("TCANARY_", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["check", "--contract", str(FIXTURES / "contract.json"), "--input", str(FIXTURES / "leaked-prompt.json"), "--format", "json"])
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertNotIn("TCANARY_PROMPT_71f0e04f", output.getvalue())

    def test_cli_structural_collision_fails_silently(self) -> None:
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
            output = io.StringIO()
            error = io.StringIO()
            commands = (
                ["validate", str(contract_path), "--format", "json"],
                ["check", "--contract", str(contract_path), "--input", str(input_path)],
            )
            for command in commands:
                with self.subTest(command=command[0]):
                    self._assert_cli_fails_silently(command)

    def test_batch_structural_collisions_fail_silently(self) -> None:
        cases = (
            ("tracecanary/v1", "json"),
            ("tracecanary.batch/v1", "json"),
            ("TraceCanary", "human"),
            ("TraceCanary", "sarif"),
            ("TraceCanary", "junit"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "input.json").write_text('{"resourceSpans":[]}', encoding="utf-8")
            contract_path = root / "contract.json"
            for marker, output_format in cases:
                contract = {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "safe", "category": "test", "value": marker}],
                    "required_retained_fields": [],
                }
                contract_path.write_text(json.dumps(contract), encoding="utf-8")
                command = [
                    "batch",
                    "--contract",
                    str(contract_path),
                    "--input-dir",
                    str(inputs),
                    "--format",
                    output_format,
                ]
                with self.subTest(marker=marker, output_format=output_format):
                    self._assert_cli_fails_silently(command)

    def test_batch_report_visible_filename_collision_fails_silently(self) -> None:
        contract = json.loads((FIXTURES / "contract.json").read_text(encoding="utf-8"))
        marker = contract["canaries"][0]["value"]
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            inputs.mkdir()
            (inputs / f"{marker}.json").write_bytes((FIXTURES / "safe-export.json").read_bytes())
            for output_format in ("human", "json", "sarif", "junit"):
                command = [
                    "batch",
                    "--contract",
                    str(FIXTURES / "contract.json"),
                    "--input-dir",
                    str(inputs),
                    "--include-paths",
                    "--format",
                    output_format,
                ]
                with self.subTest(output_format=output_format):
                    self._assert_cli_fails_silently(command)

    def test_batch_escaped_filename_collisions_fail_silently(self) -> None:
        markers = ('canary"quote', "canary\\backslash", "canary\x1fcontrol")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            input_path = inputs / "input.json"
            input_path.write_text(
                '{"resourceSpans":[{"resource":{"attributes":[{"key":"blocked.key","value":{"stringValue":"safe"}}]},"scopeSpans":[]}]}',
                encoding="utf-8",
            )
            contract_path = root / "contract.json"
            for marker in markers:
                contract = {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "safe", "category": "test", "value": marker}],
                    "forbidden_attribute_keys": ["blocked.key"],
                    "required_retained_fields": [],
                }
                contract_path.write_text(json.dumps(contract), encoding="utf-8")
                relative = Mock()
                relative.as_posix.return_value = f"{marker}.json"
                for output_format in ("json", "sarif"):
                    command = [
                        "batch",
                        "--contract",
                        str(contract_path),
                        "--input-dir",
                        str(inputs),
                        "--include-paths",
                        "--format",
                        output_format,
                    ]
                    with self.subTest(marker=repr(marker), output_format=output_format):
                        with patch.object(Path, "glob", return_value=[input_path]), patch.object(Path, "relative_to", return_value=relative):
                            self._assert_cli_fails_silently(command)

    def test_batch_object_guard_checks_nested_keys_and_values_before_serialization(self) -> None:
        markers = ('canary"quote', "canary\\backslash", "canary\x1fcontrol")
        for marker in markers:
            unsafe_objects = (
                {"items": [{"path": f"before-{marker}-after"}]},
                {"items": [{f"before-{marker}-after": "safe"}]},
            )
            for value in unsafe_objects:
                with self.subTest(marker=repr(marker), value=value):
                    with self.assertRaises(UnsafeReportError):
                        ensure_object_values_absent(value, (marker,))

    def test_batch_converts_an_ordinary_value_error_to_an_unresolved_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            inputs.mkdir()
            (inputs / "input.json").write_bytes((FIXTURES / "safe-export.json").read_bytes())
            output = io.StringIO()
            error = io.StringIO()
            command = [
                "batch",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--input-dir",
                str(inputs),
                "--format",
                "json",
            ]
            with patch("tracecanary.cli.check_trace", side_effect=ValueError("sensitive per-item detail")):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    status = main(command)
            self.assertEqual(status, EXIT_UNRESOLVED)
            self.assertEqual(error.getvalue(), "")
            self.assertNotIn("sensitive per-item detail", output.getvalue())
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "unresolved")
            self.assertEqual(report["items"][0]["report"]["violations"][0]["code"], "TC006")

    def test_empty_batch_is_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            error = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                status = main([
                    "batch",
                    "--contract",
                    str(FIXTURES / "contract.json"),
                    "--input-dir",
                    directory,
                ])

            self.assertEqual(status, EXIT_UNRESOLVED)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("no JSON files", error.getvalue())

    def test_fixture_command_writes_the_synthetic_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["fixture", "create", "--output", directory])
            self.assertEqual(status, EXIT_PASS)
            self.assertEqual(set(path.name for path in Path(directory).iterdir()), set(bundle()))

    def test_human_report_omits_location_suffix_for_empty_paths(self) -> None:
        report = {
            "status": "regression",
            "summary": {"total": 1},
            "violations": [{"code": "TC004", "message": "required operational field is absent", "path": ""}],
        }
        self.assertEqual(render_human(report), "TraceCanary: REGRESSION (1 finding(s))\n- TC004 required operational field is absent\n")

    def test_batch_formats_are_deterministic_and_path_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            safe = FIXTURES / "safe-export.json"
            (inputs / "b.json").write_bytes(safe.read_bytes())
            (inputs / "a.json").write_bytes(safe.read_bytes())
            for output_format in ("human", "json", "sarif", "junit"):
                rendered: list[str] = []
                for _ in range(2):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        status = main(["batch", "--contract", str(FIXTURES / "contract.json"), "--input-dir", str(inputs), "--format", output_format])
                    self.assertEqual(status, EXIT_PASS)
                    rendered.append(output.getvalue())
                self.assertEqual(rendered[0], rendered[1])
                self.assertNotIn(str(inputs), rendered[0])
