"""Minimal structural validation and attribute extraction for OTLP/HTTP JSON traces."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import sys
from typing import Any, Iterator


class OtlpError(ValueError):
    """An input that is not the supported OTLP trace shape."""


@dataclass(frozen=True)
class Attribute:
    scope: str
    key: str
    path: tuple[str, ...]


_INT64 = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)$")
_UINT64 = re.compile(r"(?:0|[1-9][0-9]*)$")
_HEX_ID = re.compile(r"[0-9a-fA-F]+$")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_UINT64_MAX = 2**64 - 1
_UINT32_MAX = 2**32 - 1


def _validate_int64_string(value: Any, message: str) -> None:
    if not isinstance(value, str) or not _INT64.fullmatch(value):
        raise OtlpError(message)
    if len(value.lstrip("-")) > 19:
        raise OtlpError(message)
    parsed = int(value)
    if parsed < _INT64_MIN or parsed > _INT64_MAX:
        raise OtlpError(message)


def _validate_uint64_string(value: Any, message: str) -> None:
    if not isinstance(value, str) or not _UINT64.fullmatch(value):
        raise OtlpError(message)
    if len(value) > 20 or int(value) > _UINT64_MAX:
        raise OtlpError(message)


def _validate_uint(value: Any, message: str, maximum: int = _UINT32_MAX) -> None:
    if type(value) is not int or value < 0 or value > maximum:
        raise OtlpError(message)


def _validate_optional_string(item: dict[str, Any], key: str, message: str) -> None:
    if key in item and not isinstance(item[key], str):
        raise OtlpError(message)


def _validate_hex_id(value: Any, length: int, message: str) -> None:
    if not isinstance(value, str):
        raise OtlpError(message)
    if value and (len(value) != length or not _HEX_ID.fullmatch(value)):
        raise OtlpError(message)


def _validate_scope(scope: Any) -> None:
    if not isinstance(scope, dict) or set(scope) - {"name", "version", "attributes"}:
        raise OtlpError("scope has unsupported fields")
    _validate_optional_string(scope, "name", "scope.name must be a string")
    _validate_optional_string(scope, "version", "scope.version must be a string")
    if "attributes" in scope:
        _validate_attributes(scope["attributes"], ("scope", "attributes"))


def validate_trace(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) - {"resourceSpans"}:
        raise OtlpError("payload must be an OTLP trace JSON object with resourceSpans")
    resources = payload.get("resourceSpans")
    if not isinstance(resources, list):
        raise OtlpError("resourceSpans must be a list")
    for resource_index, resource_span in enumerate(resources):
        if not isinstance(resource_span, dict) or set(resource_span) - {"resource", "scopeSpans", "schemaUrl"}:
            raise OtlpError("resourceSpans entries have unsupported fields")
        if "resource" not in resource_span or "scopeSpans" not in resource_span:
            raise OtlpError("resourceSpans entries require resource and scopeSpans")
        resource = resource_span["resource"]
        if not isinstance(resource, dict) or set(resource) - {"attributes", "droppedAttributesCount"}:
            raise OtlpError("resource has unsupported fields")
        _validate_attributes(resource.get("attributes", []), ("resourceSpans", str(resource_index), "resource", "attributes"))
        if "droppedAttributesCount" in resource:
            _validate_uint(resource["droppedAttributesCount"], "resource.droppedAttributesCount must be a uint32")
        _validate_optional_string(resource_span, "schemaUrl", "resourceSpans.schemaUrl must be a string")
        scopes = resource_span["scopeSpans"]
        if not isinstance(scopes, list):
            raise OtlpError("scopeSpans must be a list")
        for scope_index, scope_span in enumerate(scopes):
            if not isinstance(scope_span, dict) or set(scope_span) - {"scope", "spans", "schemaUrl"}:
                raise OtlpError("scopeSpans entries have unsupported fields")
            if "scope" in scope_span:
                _validate_scope(scope_span["scope"])
            _validate_optional_string(scope_span, "schemaUrl", "scopeSpans.schemaUrl must be a string")
            spans = scope_span.get("spans")
            if not isinstance(spans, list):
                raise OtlpError("scopeSpans entries require a spans list")
            for span_index, span in enumerate(spans):
                _validate_span(span, ("resourceSpans", str(resource_index), "scopeSpans", str(scope_index), "spans", str(span_index)))


def _validate_span(span: Any, path: tuple[str, ...]) -> None:
    allowed = {"traceId", "spanId", "parentSpanId", "name", "kind", "startTimeUnixNano", "endTimeUnixNano", "attributes", "droppedAttributesCount", "events", "droppedEventsCount", "status", "links", "droppedLinksCount", "flags", "traceState"}
    if not isinstance(span, dict) or set(span) - allowed:
        raise OtlpError("span has unsupported fields")
    if not isinstance(span.get("name"), str):
        raise OtlpError("span requires a string name")
    for key, length in (("traceId", 32), ("spanId", 16), ("parentSpanId", 16)):
        if key in span:
            _validate_hex_id(span[key], length, f"span.{key} must be a {length}-character hexadecimal string")
    _validate_optional_string(span, "traceState", "span.traceState must be a string")
    for key in ("startTimeUnixNano", "endTimeUnixNano"):
        if key in span:
            _validate_uint64_string(span[key], f"span.{key} must be a uint64 string")
    for key in ("kind", "droppedAttributesCount", "droppedEventsCount", "droppedLinksCount", "flags"):
        if key in span:
            _validate_uint(span[key], f"span.{key} must be a uint32", maximum=5 if key == "kind" else _UINT32_MAX)
    _validate_attributes(span.get("attributes", []), path + ("attributes",))
    events = span.get("events", [])
    if not isinstance(events, list):
        raise OtlpError("span events must be a list")
    for event_index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) - {"timeUnixNano", "name", "attributes", "droppedAttributesCount"}:
            raise OtlpError("span event has unsupported fields")
        if not isinstance(event.get("name"), str):
            raise OtlpError("span event requires a string name")
        if "timeUnixNano" in event:
            _validate_uint64_string(event["timeUnixNano"], "span event timeUnixNano must be a uint64 string")
        if "droppedAttributesCount" in event:
            _validate_uint(event["droppedAttributesCount"], "span event droppedAttributesCount must be a uint32")
        _validate_attributes(event.get("attributes", []), path + ("events", str(event_index), "attributes"))
    status = span.get("status")
    if "status" in span:
        if not isinstance(status, dict) or set(status) - {"message", "code"}:
            raise OtlpError("span status has unsupported fields")
        _validate_optional_string(status, "message", "span status message must be a string")
        if "code" in status:
            _validate_uint(status["code"], "span status code must be a uint32", maximum=2)
    links = span.get("links")
    if "links" in span:
        if not isinstance(links, list):
            raise OtlpError("span links must be a list")
        for link in links:
            if not isinstance(link, dict) or set(link) - {"traceId", "spanId", "traceState", "attributes", "droppedAttributesCount"}:
                raise OtlpError("span link has unsupported fields")
            for key, length in (("traceId", 32), ("spanId", 16)):
                if key in link:
                    _validate_hex_id(link[key], length, f"span link {key} must be a {length}-character hexadecimal string")
            _validate_optional_string(link, "traceState", "span link traceState must be a string")
            if "droppedAttributesCount" in link:
                _validate_uint(link["droppedAttributesCount"], "span link droppedAttributesCount must be a uint32")
            _validate_attributes(link.get("attributes", []), path + ("links", "attributes"))


def _validate_attributes(attributes: Any, path: tuple[str, ...]) -> None:
    if not isinstance(attributes, list):
        raise OtlpError("attributes must be a list")
    for index, attribute in enumerate(attributes):
        _validate_key_value(attribute, path + (str(index),))


def _validate_key_value(attribute: Any, path: tuple[str, ...]) -> None:
    if not isinstance(attribute, dict) or set(attribute) != {"key", "value"}:
        raise OtlpError("each attribute requires exactly key and value")
    if not isinstance(attribute["key"], str) or not attribute["key"]:
        raise OtlpError("attribute key is invalid")
    _validate_any_value(attribute["value"], path + ("value",))


def _validate_any_value(value: Any, path: tuple[str, ...]) -> None:
    """Validate the supported OTLP JSON AnyValue forms without recursion."""
    pending: list[tuple[Any, tuple[str, ...]]] = [(value, path)]
    while pending:
        current, current_path = pending.pop()
        if not isinstance(current, dict) or len(current) != 1:
            raise OtlpError("AnyValue must contain exactly one supported value field")
        kind, nested = next(iter(current.items()))
        if kind == "stringValue" or kind == "bytesValue":
            if not isinstance(nested, str):
                raise OtlpError("stringValue and bytesValue must be strings")
        elif kind == "boolValue":
            if type(nested) is not bool:
                raise OtlpError("boolValue must be a boolean")
        elif kind == "intValue":
            _validate_int64_string(nested, "intValue must be an OTLP JSON int64 string")
        elif kind == "doubleValue":
            if type(nested) is int:
                try:
                    finite = abs(nested) <= int(sys.float_info.max)
                except (OverflowError, ValueError):
                    finite = False
            elif type(nested) is float:
                finite = math.isfinite(nested)
            else:
                finite = False
            if not finite:
                raise OtlpError("doubleValue must be a finite JSON number")
        elif kind == "arrayValue":
            if not isinstance(nested, dict) or set(nested) != {"values"} or not isinstance(nested["values"], list):
                raise OtlpError("arrayValue must contain a values list")
            pending.extend((item, current_path + ("arrayValue", "values", str(index))) for index, item in enumerate(nested["values"]))
        elif kind == "kvlistValue":
            if not isinstance(nested, dict) or set(nested) != {"values"} or not isinstance(nested["values"], list):
                raise OtlpError("kvlistValue must contain a values list")
            for index, item in enumerate(nested["values"]):
                if not isinstance(item, dict) or set(item) != {"key", "value"}:
                    raise OtlpError("kvlistValue entries require exactly key and value")
                if not isinstance(item["key"], str) or not item["key"]:
                    raise OtlpError("kvlistValue entry key is invalid")
                pending.append((item["value"], current_path + ("kvlistValue", "values", str(index), "value")))
        else:
            raise OtlpError("AnyValue contains an unsupported value field")


def iter_attributes(payload: dict[str, Any]) -> Iterator[Attribute]:
    for resource_index, resource_span in enumerate(payload["resourceSpans"]):
        resource_path = ("resourceSpans", str(resource_index), "resource", "attributes")
        yield from _attributes("resource", resource_span["resource"].get("attributes", []), resource_path)
        for scope_index, scope_span in enumerate(resource_span["scopeSpans"]):
            for span_index, span in enumerate(scope_span["spans"]):
                span_path = ("resourceSpans", str(resource_index), "scopeSpans", str(scope_index), "spans", str(span_index))
                yield from _attributes("span", span.get("attributes", []), span_path + ("attributes",))
                for event_index, event in enumerate(span.get("events", [])):
                    yield from _attributes("event", event.get("attributes", []), span_path + ("events", str(event_index), "attributes"))


def _attributes(scope: str, attributes: list[dict[str, Any]], base_path: tuple[str, ...]) -> Iterator[Attribute]:
    for index, attribute in enumerate(attributes):
        yield Attribute(scope, attribute["key"], base_path + (str(index),))
