"""Minimal structural validation and attribute extraction for OTLP/HTTP JSON traces."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterator


class OtlpError(ValueError):
    """An input that is not the supported OTLP trace shape."""


@dataclass(frozen=True)
class Attribute:
    scope: str
    key: str
    path: tuple[str, ...]


_INT64 = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)$")


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
        scopes = resource_span["scopeSpans"]
        if not isinstance(scopes, list):
            raise OtlpError("scopeSpans must be a list")
        for scope_index, scope_span in enumerate(scopes):
            if not isinstance(scope_span, dict) or set(scope_span) - {"scope", "spans", "schemaUrl"}:
                raise OtlpError("scopeSpans entries have unsupported fields")
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
    _validate_attributes(span.get("attributes", []), path + ("attributes",))
    events = span.get("events", [])
    if not isinstance(events, list):
        raise OtlpError("span events must be a list")
    for event_index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) - {"timeUnixNano", "name", "attributes", "droppedAttributesCount"}:
            raise OtlpError("span event has unsupported fields")
        if not isinstance(event.get("name"), str):
            raise OtlpError("span event requires a string name")
        _validate_attributes(event.get("attributes", []), path + ("events", str(event_index), "attributes"))


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
            if not isinstance(nested, str) or not _INT64.fullmatch(nested):
                raise OtlpError("intValue must be an OTLP JSON int64 string")
        elif kind == "doubleValue":
            if type(nested) not in {int, float} or not math.isfinite(nested):
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
