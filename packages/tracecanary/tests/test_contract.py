from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.cli import EXIT_UNRESOLVED, main
from tracecanary.contract import (
    DEFAULT_MAX_BATCH_FILES,
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_NESTING,
    ContractError,
    load_contract,
    parse_contract,
)

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_non_string_retained_scopes_fail_without_tracebacks(self) -> None:
        fixture = ROOT / "fixtures" / "v1" / "contract.json"
        for scope in ({}, [], None, True, 1):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                data = json.loads(fixture.read_text(encoding="utf-8"))
                data["required_retained_fields"][0]["scope"] = scope
                with self.assertRaisesRegex(ContractError, "scope or key is invalid"):
                    parse_contract(data)
                contract = Path(directory) / "contract.json"
                contract.write_text(json.dumps(data), encoding="utf-8")
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    code = main(["population-gate", "--contract", str(contract), "--input",
                                 str(ROOT / "fixtures" / "v1" / "safe-export.json"),
                                 "--scope", "span", "--minimum", "1", "--format", "json"])
                self.assertEqual(code, EXIT_UNRESOLVED)
                self.assertNotIn("Traceback", output.getvalue() + errors.getvalue())

    def test_fixture_contract_is_valid(self) -> None:
        contract = load_contract(ROOT / "fixtures" / "v1" / "contract.json")
        self.assertEqual(contract.contract_version, "tracecanary/v1")
        self.assertEqual(len(contract.canaries), 4)

    def test_unknown_versions_are_rejected(self) -> None:
        data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/999.0.0",
            "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
            "required_retained_fields": [],
        }
        with self.assertRaisesRegex(ContractError, "semantic-conventions"):
            parse_contract(data)

    def test_unknown_contract_fields_fail_closed(self) -> None:
        data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
            "required_retained_fields": [],
            "unrecognized": True,
        }
        with self.assertRaisesRegex(ContractError, "unsupported"):
            parse_contract(data)

    def test_duplicate_canary_values_are_rejected(self) -> None:
        data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [
                {"label": "a", "category": "test", "value": "synthetic"},
                {"label": "b", "category": "test", "value": "synthetic"},
            ],
            "required_retained_fields": [],
        }
        with self.assertRaisesRegex(ContractError, "unique"):
            parse_contract(data)

    def test_labels_and_categories_cannot_contain_any_canary_value(self) -> None:
        for field in ("label", "category"):
            with self.subTest(field=field):
                data = {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "safe", "category": "test", "value": "synthetic canary sample value"}],
                    "required_retained_fields": [],
                }
                data["canaries"][0][field] = "prefix synthetic canary sample value suffix"
                with self.assertRaisesRegex(ContractError, "must not contain"):
                    parse_contract(data)

    def test_malicious_category_is_rejected_without_echoing_canary_value(self) -> None:
        marker = "synthetic canary sample value"
        data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "safe", "category": marker, "value": marker}],
            "required_retained_fields": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(["validate", str(path)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertNotIn(marker, error.getvalue())

    def test_omitted_limits_use_documented_defaults(self) -> None:
        data = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
            "required_retained_fields": [],
        }
        contract = parse_contract(data)
        self.assertEqual(contract.max_input_bytes, DEFAULT_MAX_INPUT_BYTES)
        self.assertEqual(contract.max_nesting, DEFAULT_MAX_NESTING)
        self.assertEqual(contract.max_batch_files, DEFAULT_MAX_BATCH_FILES)
        self.assertEqual(DEFAULT_MAX_BATCH_FILES, 256)

    def test_invalid_max_batch_files_is_rejected(self) -> None:
        for value in (0, 10_001, True, "256"):
            with self.subTest(value=value):
                data = {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
                    "required_retained_fields": [],
                    "limits": {"max_batch_files": value},
                }
                with self.assertRaisesRegex(ContractError, "max_batch_files"):
                    parse_contract(data)

    def test_report_visible_contract_fields_cannot_contain_canary_values(self) -> None:
        marker = "synthetic canary sample value"
        cases = {
            "forbidden_attribute_keys": [marker],
            "forbidden_attribute_key_prefixes": [f"prefix.{marker}"],
            "forbidden_path_prefixes": [f"/resourceSpans/{marker}"],
            "required_retained_fields": [{"scope": "span", "key": f"prefix.{marker}"}],
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                data = {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "safe", "category": "test", "value": marker}],
                    "required_retained_fields": [],
                    field: value,
                }
                with self.assertRaises(ContractError) as raised:
                    parse_contract(data)
                self.assertNotIn(marker, str(raised.exception))
