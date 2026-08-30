from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import load_json
from tracecanary.checker import check_trace
from tracecanary.contract import Canary, Contract, load_contract
from tracecanary.otlp import validate_trace
from tracecanary.report import UnsafeReportError, render_human, render_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class CheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract(FIXTURES / "contract.json")

    def _check(self, name: str) -> dict:
        payload = load_json(FIXTURES / name, max_bytes=self.contract.max_input_bytes, max_depth=self.contract.max_nesting)
        validate_trace(payload)
        return check_trace(self.contract, payload)

    def test_fixture_reports_match_expected(self) -> None:
        names = [
            "safe-export.json",
            "leaked-prompt.json",
            "leaked-tool-arguments.json",
            "leaked-tool-result.json",
            "leaked-user-identifier.json",
            "missing-operational-fields.json",
            "forbidden-path.json",
        ]
        for name in names:
            with self.subTest(name=name):
                expected = load_json(FIXTURES / "expected" / name, max_bytes=100_000, max_depth=100)
                self.assertEqual(self._check(name), expected)

    def test_every_planted_canary_is_found_without_echoing_value(self) -> None:
        names = ["leaked-prompt.json", "leaked-tool-arguments.json", "leaked-tool-result.json", "leaked-user-identifier.json"]
        for name in names:
            with self.subTest(name=name):
                report = self._check(name)
                self.assertEqual(report["summary"]["canary_leaks"], 1)
                output = render_json(report) + render_human(report)
                payload_text = (FIXTURES / name).read_text(encoding="utf-8")
                for canary in self.contract.canaries:
                    if canary.value in payload_text:
                        self.assertNotIn(canary.value, output)

    def test_safe_export_is_a_negative_control(self) -> None:
        self.assertEqual(self._check("safe-export.json")["status"], "pass")

    def test_forbidden_keys_in_scope_and_link_attributes_are_found(self) -> None:
        payload = load_json(FIXTURES / "safe-export.json", max_bytes=self.contract.max_input_bytes, max_depth=self.contract.max_nesting)
        attribute = {"key": "gen_ai.prompt", "value": {"stringValue": "benign"}}
        scope_span = payload["resourceSpans"][0]["scopeSpans"][0]
        scope_span["scope"]["attributes"] = [attribute]
        scope_span["scope"]["droppedAttributesCount"] = 1
        scope_span["spans"][0]["links"] = [{"attributes": [attribute], "flags": 1}]
        validate_trace(payload)

        report = check_trace(self.contract, payload)

        self.assertEqual(report["summary"]["forbidden_attributes"], 2)
        self.assertEqual(
            {item["scope"] for item in report["violations"]},
            {"scope", "link"},
        )

    def test_canaries_in_non_attribute_string_scalars_are_found_without_echo(self) -> None:
        marker = self.contract.canaries[0].value
        safe = load_json(FIXTURES / "safe-export.json", max_bytes=self.contract.max_input_bytes, max_depth=self.contract.max_nesting)

        def plant_span_name(payload: dict) -> None:
            payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] = marker

        def plant_event_name(payload: dict) -> None:
            payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"][0]["name"] = marker

        def plant_schema_url(payload: dict) -> None:
            payload["resourceSpans"][0]["schemaUrl"] = marker

        def plant_status_message(payload: dict) -> None:
            payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["status"] = {"message": marker}

        def plant_nested_array(payload: dict) -> None:
            payload["resourceSpans"][0]["resource"]["attributes"].append(
                {"key": "synthetic.context", "value": {"arrayValue": {"values": [{"stringValue": marker}]}}}
            )

        for name, plant in (
            ("span-name", plant_span_name),
            ("event-name", plant_event_name),
            ("schema-url", plant_schema_url),
            ("status-message", plant_status_message),
            ("nested-array", plant_nested_array),
        ):
            with self.subTest(location=name):
                payload = copy.deepcopy(safe)
                plant(payload)
                validate_trace(payload)
                report = check_trace(self.contract, payload)
                self.assertEqual(report["status"], "regression")
                self.assertEqual(report["summary"]["canary_leaks"], 1)
                self.assertNotIn(marker, render_json(report) + render_human(report))

    def test_canary_in_a_valid_kvlist_key_is_found_without_echoing_value(self) -> None:
        payload = load_json(FIXTURES / "safe-export.json", max_bytes=self.contract.max_input_bytes, max_depth=self.contract.max_nesting)
        marker = self.contract.canaries[0].value
        attributes = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        attributes.append(
            {
                "key": "synthetic.context",
                "value": {"kvlistValue": {"values": [{"key": marker, "value": {"stringValue": "benign"}}]}},
            }
        )
        validate_trace(payload)
        report = check_trace(self.contract, payload)
        self.assertEqual(report["summary"]["canary_leaks"], 1)
        self.assertNotIn(marker, render_json(report) + render_human(report))

    def test_programmatic_contract_cannot_echo_canary_from_finding_metadata(self) -> None:
        marker = "redacted"
        contract = Contract(
            contract_version="tracecanary/v1",
            semantic_conventions_version="opentelemetry/semconv/1.43.0",
            canaries=(Canary("safe", "test", marker),),
            forbidden_attribute_keys=(marker,),
            forbidden_attribute_key_prefixes=(),
            forbidden_path_prefixes=(),
            required_retained_fields=(),
            max_input_bytes=5_000_000,
            max_nesting=100,
            max_batch_files=256,
        )
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "name": "sample",
                                    "attributes": [{"key": marker, "value": {"stringValue": "benign"}}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        validate_trace(payload)
        report = check_trace(contract, payload)
        self.assertEqual(report["summary"]["forbidden_attributes"], 1)
        self.assertNotIn(marker, render_json(report) + render_human(report))

    def test_programmatic_contract_fails_closed_on_structural_output_collision(self) -> None:
        marker = "tracecanary/v1"
        contract = Contract(
            contract_version=marker,
            semantic_conventions_version="opentelemetry/semconv/1.43.0",
            canaries=(Canary("safe", "test", marker),),
            forbidden_attribute_keys=(),
            forbidden_attribute_key_prefixes=(),
            forbidden_path_prefixes=(),
            required_retained_fields=(),
            max_input_bytes=5_000_000,
            max_nesting=100,
            max_batch_files=256,
        )
        payload = {"resourceSpans": []}
        validate_trace(payload)
        with self.assertRaises(UnsafeReportError) as raised:
            check_trace(contract, payload)
        self.assertEqual(str(raised.exception), "")
