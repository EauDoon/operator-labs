"""Minimal structural validation and attribute extraction for OTLP/HTTP JSON traces."""

from __future__ import annotations

import math
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from tracecanary.canonical import json_pointer


class OtlpError(ValueError):
    """An input that is not the supported OTLP trace shape."""


def _located(message: str, path: tuple[str, ...]) -> str:
    """Attach a JSON pointer so failures name the resource, span, event, or attribute."""
    return f"{message} at {json_pointer(path)}"


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


def _validate_scope(scope: Any, path: tuple[str, ...]) -> None:
    if not isinstance(scope, dict) or set(scope) - {"name", "version", "attributes", "droppedAttributesCount"}:
        raise OtlpError(_located("scope has unsupported fields", path))
    _validate_optional_string(scope, "name", _located("scope.name must be a string", path))
    _validate_optional_string(scope, "version", _located("scope.version must be a string", path))
    if "attributes" in scope:
        _validate_attributes(scope["attributes"], path + ("attributes",))
    if "droppedAttributesCount" in scope:
        _validate_uint(scope["droppedAttributesCount"], _located("scope.droppedAttributesCount must be a uint32", path))


def validate_trace(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) - {"resourceSpans"}:
        raise OtlpError("payload must be an OTLP trace JSON object with resourceSpans")
    resources = payload.get("resourceSpans")
    if not isinstance(resources, list):
        raise OtlpError("resourceSpans must be a list")
    seen_span_ids: set[tuple[str, str]] = set()
    for resource_index, resource_span in enumerate(resources):
        resource_path = ("resourceSpans", str(resource_index))
        if not isinstance(resource_span, dict) or set(resource_span) - {"resource", "scopeSpans", "schemaUrl"}:
            raise OtlpError(_located("resourceSpans entries have unsupported fields", resource_path))
        if "resource" not in resource_span or "scopeSpans" not in resource_span:
            raise OtlpError(_located("resourceSpans entries require resource and scopeSpans", resource_path))
        resource = resource_span["resource"]
        resource_object_path = resource_path + ("resource",)
        if not isinstance(resource, dict) or set(resource) - {"attributes", "droppedAttributesCount"}:
            raise OtlpError(_located("resource has unsupported fields", resource_object_path))
        _validate_attributes(resource.get("attributes", []), resource_object_path + ("attributes",))
        if "droppedAttributesCount" in resource:
            _validate_uint(
                resource["droppedAttributesCount"],
                _located("resource.droppedAttributesCount must be a uint32", resource_object_path),
            )
        _validate_optional_string(
            resource_span,
            "schemaUrl",
            _located("resourceSpans.schemaUrl must be a string", resource_path),
        )
        scopes = resource_span["scopeSpans"]
        if not isinstance(scopes, list):
            raise OtlpError(_located("scopeSpans must be a list", resource_path + ("scopeSpans",)))
        for scope_index, scope_span in enumerate(scopes):
            scope_path = resource_path + ("scopeSpans", str(scope_index))
            if not isinstance(scope_span, dict) or set(scope_span) - {"scope", "spans", "schemaUrl"}:
                raise OtlpError(_located("scopeSpans entries have unsupported fields", scope_path))
            if "scope" in scope_span:
                _validate_scope(scope_span["scope"], scope_path + ("scope",))
            _validate_optional_string(
                scope_span,
                "schemaUrl",
                _located("scopeSpans.schemaUrl must be a string", scope_path),
            )
            spans = scope_span.get("spans")
            if not isinstance(spans, list):
                raise OtlpError(_located("scopeSpans entries require a spans list", scope_path))
            for span_index, span in enumerate(spans):
                span_path = scope_path + ("spans", str(span_index))
                _validate_span(span, span_path)
                _reject_duplicate_span_id(span, span_path, seen_span_ids)


def _validate_span(span: Any, path: tuple[str, ...]) -> None:
    allowed = {"traceId", "spanId", "parentSpanId", "name", "kind", "startTimeUnixNano", "endTimeUnixNano", "attributes", "droppedAttributesCount", "events", "droppedEventsCount", "status", "links", "droppedLinksCount", "flags", "traceState"}
    if not isinstance(span, dict) or set(span) - allowed:
        raise OtlpError(_located("span has unsupported fields", path))
    if not isinstance(span.get("name"), str):
        raise OtlpError(_located("span requires a string name", path))
    for key, length in (("traceId", 32), ("spanId", 16), ("parentSpanId", 16)):
        if key in span:
            _validate_hex_id(span[key], length, _located(f"span.{key} must be a {length}-character hexadecimal string", path))
    _validate_optional_string(span, "traceState", _located("span.traceState must be a string", path))
    for key in ("startTimeUnixNano", "endTimeUnixNano"):
        if key in span:
            _validate_uint64_string(span[key], _located(f"span.{key} must be a uint64 string", path))
    for key in ("kind", "droppedAttributesCount", "droppedEventsCount", "droppedLinksCount", "flags"):
        if key in span:
            _validate_uint(span[key], _located(f"span.{key} must be a uint32", path), maximum=5 if key == "kind" else _UINT32_MAX)
    _validate_attributes(span.get("attributes", []), path + ("attributes",))
    events = span.get("events", [])
    if not isinstance(events, list):
        raise OtlpError(_located("span events must be a list", path))
    for event_index, event in enumerate(events):
        event_path = path + ("events", str(event_index))
        if not isinstance(event, dict) or set(event) - {"timeUnixNano", "name", "attributes", "droppedAttributesCount"}:
            raise OtlpError(_located("span event has unsupported fields", event_path))
        if not isinstance(event.get("name"), str):
            raise OtlpError(_located("span event requires a string name", event_path))
        if "timeUnixNano" in event:
            _validate_uint64_string(event["timeUnixNano"], _located("span event timeUnixNano must be a uint64 string", event_path))
        if "droppedAttributesCount" in event:
            _validate_uint(event["droppedAttributesCount"], _located("span event droppedAttributesCount must be a uint32", event_path))
        _validate_attributes(event.get("attributes", []), event_path + ("attributes",))
    status = span.get("status")
    if "status" in span:
        status_path = path + ("status",)
        if not isinstance(status, dict) or set(status) - {"message", "code"}:
            raise OtlpError(_located("span status has unsupported fields", status_path))
        _validate_optional_string(status, "message", _located("span status message must be a string", status_path))
        if "code" in status:
            _validate_uint(status["code"], _located("span status code must be a uint32", status_path), maximum=2)
    links = span.get("links")
    if "links" in span:
        if not isinstance(links, list):
            raise OtlpError(_located("span links must be a list", path))
        for link_index, link in enumerate(links):
            link_path = path + ("links", str(link_index))
            if not isinstance(link, dict) or set(link) - {"traceId", "spanId", "traceState", "attributes", "droppedAttributesCount", "flags"}:
                raise OtlpError(_located("span link has unsupported fields", link_path))
            for key, length in (("traceId", 32), ("spanId", 16)):
                if key in link:
                    _validate_hex_id(link[key], length, _located(f"span link {key} must be a {length}-character hexadecimal string", link_path))
            _validate_optional_string(link, "traceState", _located("span link traceState must be a string", link_path))
            if "droppedAttributesCount" in link:
                _validate_uint(link["droppedAttributesCount"], _located("span link droppedAttributesCount must be a uint32", link_path))
            if "flags" in link:
                _validate_uint(link["flags"], _located("span link flags must be a uint32", link_path))
            _validate_attributes(link.get("attributes", []), link_path + ("attributes",))


def _reject_duplicate_span_id(span: dict[str, Any], path: tuple[str, ...], seen: set[tuple[str, str]]) -> None:
    span_id = span.get("spanId") or ""
    if not span_id:
        return
    identity = ((span.get("traceId") or "").casefold(), span_id.casefold())
    if identity in seen:
        raise OtlpError(_located("spanId must be unique within a trace", path))
    seen.add(identity)


def _validate_attributes(attributes: Any, path: tuple[str, ...]) -> None:
    if not isinstance(attributes, list):
        raise OtlpError(_located("attributes must be a list", path))
    seen_keys: set[str] = set()
    for index, attribute in enumerate(attributes):
        item_path = path + (str(index),)
        _validate_key_value(attribute, item_path)
        key = attribute["key"]
        if key in seen_keys:
            raise OtlpError(_located("attribute keys must be unique", item_path))
        seen_keys.add(key)


def _validate_key_value(attribute: Any, path: tuple[str, ...]) -> None:
    if not isinstance(attribute, dict) or set(attribute) != {"key", "value"}:
        raise OtlpError(_located("each attribute requires exactly key and value", path))
    if not isinstance(attribute["key"], str) or not attribute["key"]:
        raise OtlpError(_located("attribute key is invalid", path))
    _validate_any_value(attribute["value"], path + ("value",))


def _validate_any_value(value: Any, path: tuple[str, ...]) -> None:
    """Validate the supported OTLP JSON AnyValue forms without recursion."""
    pending: list[tuple[Any, tuple[str, ...]]] = [(value, path)]
    while pending:
        current, current_path = pending.pop()
        if not isinstance(current, dict) or len(current) != 1:
            raise OtlpError(_located("AnyValue must contain exactly one supported value field", current_path))
        kind, nested = next(iter(current.items()))
        if kind == "stringValue" or kind == "bytesValue":
            if not isinstance(nested, str):
                raise OtlpError(_located("stringValue and bytesValue must be strings", current_path))
        elif kind == "boolValue":
            if type(nested) is not bool:
                raise OtlpError(_located("boolValue must be a boolean", current_path))
        elif kind == "intValue":
            _validate_int64_string(nested, _located("intValue must be an OTLP JSON int64 string", current_path))
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
                raise OtlpError(_located("doubleValue must be a finite JSON number", current_path))
        elif kind == "arrayValue":
            if not isinstance(nested, dict) or set(nested) != {"values"} or not isinstance(nested["values"], list):
                raise OtlpError(_located("arrayValue must contain a values list", current_path))
            pending.extend((item, current_path + ("arrayValue", "values", str(index))) for index, item in enumerate(nested["values"]))
        elif kind == "kvlistValue":
            if not isinstance(nested, dict) or set(nested) != {"values"} or not isinstance(nested["values"], list):
                raise OtlpError(_located("kvlistValue must contain a values list", current_path))
            seen_keys: set[str] = set()
            for index, item in enumerate(nested["values"]):
                entry_path = current_path + ("kvlistValue", "values", str(index))
                if not isinstance(item, dict) or set(item) != {"key", "value"}:
                    raise OtlpError(_located("kvlistValue entries require exactly key and value", entry_path))
                if not isinstance(item["key"], str) or not item["key"]:
                    raise OtlpError(_located("kvlistValue entry key is invalid", entry_path))
                if item["key"] in seen_keys:
                    raise OtlpError(_located("kvlistValue keys must be unique", entry_path))
                seen_keys.add(item["key"])
                pending.append((item["value"], entry_path + ("value",)))
        else:
            raise OtlpError(_located("AnyValue contains an unsupported value field", current_path))


def iter_attributes(payload: dict[str, Any]) -> Iterator[Attribute]:
    for resource_index, resource_span in enumerate(payload["resourceSpans"]):
        resource_path = ("resourceSpans", str(resource_index), "resource", "attributes")
        yield from _attributes("resource", resource_span["resource"].get("attributes", []), resource_path)
        for scope_index, scope_span in enumerate(resource_span["scopeSpans"]):
            if "scope" in scope_span:
                scope_path = ("resourceSpans", str(resource_index), "scopeSpans", str(scope_index), "scope", "attributes")
                yield from _attributes("scope", scope_span["scope"].get("attributes", []), scope_path)
            for span_index, span in enumerate(scope_span["spans"]):
                span_path = ("resourceSpans", str(resource_index), "scopeSpans", str(scope_index), "spans", str(span_index))
                yield from _attributes("span", span.get("attributes", []), span_path + ("attributes",))
                for event_index, event in enumerate(span.get("events", [])):
                    yield from _attributes("event", event.get("attributes", []), span_path + ("events", str(event_index), "attributes"))
                for link_index, link in enumerate(span.get("links", [])):
                    yield from _attributes("link", link.get("attributes", []), span_path + ("links", str(link_index), "attributes"))


def _attributes(scope: str, attributes: list[dict[str, Any]], base_path: tuple[str, ...]) -> Iterator[Attribute]:
    for index, attribute in enumerate(attributes):
        yield Attribute(scope, attribute["key"], base_path + (str(index),))
