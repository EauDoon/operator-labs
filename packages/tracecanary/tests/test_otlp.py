from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError, load_json
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

    def test_int64_and_double_bounds_fail_closed(self) -> None:
        for value in ("9223372036854775808", "-9223372036854775809"):
            with self.subTest(value=value), self.assertRaises(OtlpError):
                validate_trace({"resourceSpans": [{"resource": {"attributes": [{"key": "x", "value": {"intValue": value}}]}, "scopeSpans": []}]})
        with self.assertRaises(OtlpError):
            validate_trace({"resourceSpans": [{"resource": {"attributes": [{"key": "x", "value": {"doubleValue": 10**5000}}]}, "scopeSpans": []}]})

    def test_timestamps_use_the_otlp_uint64_range(self) -> None:
        def payload(value: str) -> dict:
            return {
                "resourceSpans": [{
                    "resource": {},
                    "scopeSpans": [{"spans": [{"name": "x", "startTimeUnixNano": value}]}],
                }]
            }

        validate_trace(payload("18446744073709551615"))
        for value in ("-1", "18446744073709551616"):
            with self.subTest(value=value), self.assertRaises(OtlpError):
                validate_trace(payload(value))

    def test_trace_and_span_ids_are_empty_or_fixed_width_hex(self) -> None:
        span = {
            "name": "x",
            "traceId": "A" * 32,
            "spanId": "b" * 16,
            "parentSpanId": "C" * 16,
            "links": [{"traceId": "d" * 32, "spanId": "E" * 16}],
        }
        payload = {"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [span]}]}]}
        validate_trace(payload)

        for target, key in (
            (span, "traceId"),
            (span, "spanId"),
            (span, "parentSpanId"),
            (span["links"][0], "traceId"),
            (span["links"][0], "spanId"),
        ):
            target[key] = ""
        validate_trace(payload)

        for target, key, value in (
            (span, "traceId", "not-hex"),
            (span, "spanId", "0" * 15),
            (span, "parentSpanId", "0" * 17),
            (span["links"][0], "traceId", "g" * 32),
            (span["links"][0], "spanId", "0" * 15),
        ):
            original = target[key]
            target[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(OtlpError):
                validate_trace(payload)
            target[key] = original

    def test_scope_dropped_count_and_link_flags_are_uint32(self) -> None:
        scope = {"droppedAttributesCount": 2**32 - 1}
        link = {"flags": 2**32 - 1}
        payload = {
            "resourceSpans": [{
                "resource": {},
                "scopeSpans": [{"scope": scope, "spans": [{"name": "x", "links": [link]}]}],
            }]
        }
        validate_trace(payload)

        for target, key in ((scope, "droppedAttributesCount"), (link, "flags")):
            for value in (-1, 2**32, True, "1"):
                target[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(OtlpError):
                    validate_trace(payload)
            target[key] = 0

    def test_malformed_shapes_fail_closed(self) -> None:
        cases = (
            ({"resourceSpans": None}, "resourceSpans"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": None}]}, "scopeSpans"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": None}]}]}, "spans"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [{"kind": 1}]}]}]}, "name"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [{"name": "x", "kind": 6}]}]}]}, "kind"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [{"name": "x", "kind": True}]}]}]}, "kind"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [{"name": "x", "status": {"code": 3}}]}]}]}, "status"),
            ({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [{"name": "x", "events": None}]}]}]}, "events"),
            ({"resourceSpans": [{"resource": {"attributes": [{"key": "", "value": {"stringValue": "x"}}]}, "scopeSpans": []}]}, "key"),
            ({"resourceSpans": [{"resource": {"attributes": [{"key": "x", "value": {"intValue": 1}}]}, "scopeSpans": []}]}, "intValue"),
            ({"resourceSpans": [{"resource": {"attributes": [{"key": "x", "value": {"boolValue": 1}}]}, "scopeSpans": []}]}, "boolValue"),
            ({"resourceSpans": [{"resource": {"attributes": [{"key": "x", "value": {"arrayValue": {"values": "x"}}}]}, "scopeSpans": []}]}, "arrayValue"),
        )
        for payload, fragment in cases:
            with self.subTest(fragment=fragment), self.assertRaisesRegex(OtlpError, fragment):
                validate_trace(payload)

    def test_non_json_constants_are_rejected_before_validation(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nan.json"
            path.write_text('{"resourceSpans":[],"unexpected":NaN}', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(path, max_bytes=1000, max_depth=10)

    def test_span_errors_name_the_failing_json_pointer(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {},
                    "scopeSpans": [{"spans": [{"name": "ok"}, {"kind": 1}]}],
                }
            ]
        }
        with self.assertRaisesRegex(OtlpError, r"span requires a string name at /resourceSpans/0/scopeSpans/0/spans/1"):
            validate_trace(payload)

    def test_attribute_errors_name_the_failing_json_pointer_without_keys(self) -> None:
        marker = "TCANARY_ATTRIBUTE_KEY_9d2a"
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "synthetic"}},
                            {"key": marker, "value": {"intValue": 1}},
                        ]
                    },
                    "scopeSpans": [],
                }
            ]
        }
        with self.assertRaisesRegex(OtlpError, r"intValue must be an OTLP JSON int64 string at /resourceSpans/0/resource/attributes/1/value") as caught:
            validate_trace(payload)
        self.assertNotIn(marker, str(caught.exception))

    def test_duplicate_attribute_keys_are_rejected(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "synthetic"}},
                            {"key": "service.name", "value": {"stringValue": "other"}},
                        ]
                    },
                    "scopeSpans": [],
                }
            ]
        }
        with self.assertRaisesRegex(OtlpError, r"attribute keys must be unique at /resourceSpans/0/resource/attributes/1"):
            validate_trace(payload)

    def test_duplicate_kvlist_keys_are_rejected(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "structured",
                                "value": {
                                    "kvlistValue": {
                                        "values": [
                                            {"key": "nested", "value": {"stringValue": "one"}},
                                            {"key": "nested", "value": {"stringValue": "two"}},
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
        with self.assertRaisesRegex(
            OtlpError,
            r"kvlistValue keys must be unique at /resourceSpans/0/resource/attributes/0/value/kvlistValue/values/1",
        ):
            validate_trace(payload)

    def test_duplicate_span_ids_within_a_trace_are_rejected(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {},
                    "scopeSpans": [
                        {
                            "spans": [
                                {"name": "first", "traceId": "A" * 32, "spanId": "b" * 16},
                                {"name": "second", "traceId": "a" * 32, "spanId": "B" * 16},
                            ]
                        }
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(OtlpError, r"spanId must be unique within a trace at /resourceSpans/0/scopeSpans/0/spans/1"):
            validate_trace(payload)

        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][1]["traceId"] = "c" * 32
        validate_trace(payload)

        for span in payload["resourceSpans"][0]["scopeSpans"][0]["spans"]:
            span["spanId"] = ""
        validate_trace(payload)

    def test_event_and_link_errors_include_indexes(self) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "name": "ok",
                                    "events": [{"name": "first"}, {"name": 1}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(OtlpError, r"span event requires a string name at /resourceSpans/0/scopeSpans/0/spans/0/events/1"):
            validate_trace(payload)

        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"] = [{"name": "ok"}]
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["links"] = [{}, {"traceId": "not-hex"}]
        with self.assertRaisesRegex(
            OtlpError,
            r"span link traceId must be a 32-character hexadecimal string at /resourceSpans/0/scopeSpans/0/spans/0/links/1",
        ):
            validate_trace(payload)
