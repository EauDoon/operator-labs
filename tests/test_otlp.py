from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import load_json
from tracecanary.otlp import OtlpError, iter_attributes, validate_trace


ROOT = Path(__file__).resolve().parents[1]


class OtlpTests(unittest.TestCase):
    def test_safe_fixture_has_all_attribute_scopes(self) -> None:
        payload = load_json(ROOT / "fixtures" / "v1" / "safe-export.json", max_bytes=5_000_000, max_depth=100)
        validate_trace(payload)
        scopes = {attribute.scope for attribute in iter_attributes(payload)}
        self.assertEqual(scopes, {"resource", "span", "event"})

    def test_invalid_root_is_rejected(self) -> None:
        with self.assertRaisesRegex(OtlpError, "resourceSpans"):
            validate_trace({"spans": []})

    def test_attribute_with_extra_field_is_rejected(self) -> None:
        payload = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {}, "extra": True}]}, "scopeSpans": []}]}
        with self.assertRaisesRegex(OtlpError, "exactly"):
            validate_trace(payload)

    def test_recursive_anyvalue_shapes_are_supported(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "structured",
                                "value": {
                                    "arrayValue": {
                                        "values": [
                                            {"stringValue": "text"},
                                            {"boolValue": True},
                                            {"intValue": "42"},
                                            {"doubleValue": 1.5},
                                            {"bytesValue": "c3ludGhldGlj"},
                                            {"kvlistValue": {"values": [{"key": "nested", "value": {"stringValue": "value"}}]}},
                                        ]
                                    }
                                },
                            }
                        ]
                    },
                    "scopeSpans": [],
                }
            ]
        }
        validate_trace(payload)
