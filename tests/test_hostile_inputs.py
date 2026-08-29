from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError, load_json
from tracecanary.cli import EXIT_PASS, EXIT_UNRESOLVED, main


class HostileInputTests(unittest.TestCase):
    def test_duplicate_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"resourceSpans":[],"resourceSpans":[]}', encoding="utf-8")
            with self.assertRaisesRegex(InputError, "duplicate"):
                load_json(path, max_bytes=1_024, max_depth=10)

    def test_excessive_nesting_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.json"
            path.write_text("[" * 11 + "0" + "]" * 11, encoding="utf-8")
            with self.assertRaisesRegex(InputError, "nesting"):
                load_json(path, max_bytes=1_024, max_depth=10)

    def test_oversized_input_fails_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.json"
            path.write_bytes(b"x" * 1_025)
            with self.assertRaisesRegex(InputError, "exceeds"):
                load_json(path, max_bytes=1_024, max_depth=10)

    def test_input_that_grows_after_stat_still_obeys_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growing.json"
            path.write_text("{}", encoding="utf-8")
            read_sizes: list[int] = []

            class GrowingInput(io.BytesIO):
                def read(self, size: int = -1) -> bytes:
                    read_sizes.append(size)
                    return super().read(size)

            with patch.object(Path, "open", return_value=GrowingInput(b"x" * 2_048)):
                with self.assertRaisesRegex(InputError, "exceeds"):
                    load_json(path, max_bytes=1_024, max_depth=10)
            self.assertEqual(read_sizes, [1_025])

    def test_unknown_version_returns_unresolved_exit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.json"
            contract.write_text('{"contract_version":"tracecanary/v999","semantic_conventions_version":"opentelemetry/semconv/1.43.0","canaries":[{"label":"a","category":"test","value":"synthetic"}],"required_retained_fields":[]}', encoding="utf-8")
            self.assertEqual(main(["validate", str(contract)]), EXIT_UNRESOLVED)

    def test_parser_recursion_error_is_a_controlled_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser-deep.json"
            path.write_text("[]", encoding="utf-8")
            with patch("tracecanary.canonical.json.loads", side_effect=RecursionError):
                with self.assertRaisesRegex(InputError, "nesting"):
                    load_json(path, max_bytes=4_096, max_depth=2_000)

    def test_configured_nesting_limit_returns_exit_two(self) -> None:
        contract_data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "safe", "category": "test", "value": "TCANARY_LIMIT_7c3a"}],
            "required_retained_fields": [],
            "limits": {"max_input_bytes": 1024, "max_nesting": 2},
        }
        trace = {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": []}]}
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.json"
            candidate = Path(directory) / "candidate.json"
            contract.write_text(json.dumps(contract_data), encoding="utf-8")
            candidate.write_text(json.dumps(trace), encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(["check", "--contract", str(contract), "--input", str(candidate)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertIn("nesting", error.getvalue())

    def test_arbitrary_nested_anyvalue_key_fails_closed_without_echoing_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        marker = "TCANARY_PROMPT_71f0e04f"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            payload = {
                "resourceSpans": [
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "synthetic"}}]},
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "name": "synthetic",
                                        "attributes": [
                                            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                                            {"key": "invalid", "value": {marker: "hidden"}},
                                        ],
                                        "events": [{"name": "event", "attributes": [{"key": "telemetry.event.class", "value": {"stringValue": "synthetic"}}]}],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(["check", "--contract", str(root / "fixtures" / "v1" / "contract.json"), "--input", str(candidate)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertNotIn(marker, error.getvalue())

    def test_deep_supported_anyvalue_reaches_cli_check_without_recursion_error(self) -> None:
        marker = "TCANARY_DEEP_6a4e"
        contract_data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "deep", "category": "test", "value": marker}],
            "required_retained_fields": [
                {"scope": "resource", "key": "service.name"},
                {"scope": "span", "key": "gen_ai.operation.name"},
                {"scope": "event", "key": "telemetry.event.class"},
            ],
            "limits": {"max_input_bytes": 5_000_000, "max_nesting": 1_000},
        }
        deep_value = '{"stringValue":"benign"}'
        # Stay below CPython 3.11's JSON parser ceiling while exceeding the default nesting limit.
        for _ in range(250):
            deep_value = '{"arrayValue":{"values":[' + deep_value + ']}}'
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "synthetic"}}]},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "name": "synthetic",
                                    "attributes": [
                                        {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                                        {"key": "deep", "value": "__DEEP_VALUE__"},
                                    ],
                                    "events": [{"name": "event", "attributes": [{"key": "telemetry.event.class", "value": {"stringValue": "synthetic"}}]}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.json"
            candidate = Path(directory) / "candidate.json"
            contract.write_text(json.dumps(contract_data), encoding="utf-8")
            candidate.write_text(json.dumps(payload).replace('"__DEEP_VALUE__"', deep_value), encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                status = main(["check", "--contract", str(contract), "--input", str(candidate), "--format", "json"])
        self.assertEqual(status, EXIT_PASS)
        self.assertIn('"status":"pass"', output.getvalue())
        self.assertNotIn(marker, output.getvalue() + error.getvalue())
