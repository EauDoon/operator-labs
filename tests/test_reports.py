from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import load_json
from tracecanary.checker import check_trace
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.contract import load_contract
from tracecanary.fixture import bundle
from tracecanary.otlp import validate_trace
from tracecanary.report import render_json
from tracecanary.report import render_human


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class ReportTests(unittest.TestCase):
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
                    output = io.StringIO()
                    error = io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        status = main(command)
                    self.assertEqual(status, EXIT_UNRESOLVED)
                    self.assertEqual(output.getvalue() + error.getvalue(), "")

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
