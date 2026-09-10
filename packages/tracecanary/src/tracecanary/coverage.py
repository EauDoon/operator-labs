"""Value-free visibility into the synthetic export actually inspected."""
from collections import Counter
from typing import Any

from .checker import check_trace
from .contract import Contract
from .otlp import iter_attributes, validate_trace
from .report import Report, ensure_object_values_absent, ensure_values_absent


def coverage_report(contract: Contract, payload: dict[str, Any]) -> Report:
    validate_trace(payload)
    report = check_trace(contract, payload, mode="coverage")
    entities = dict.fromkeys(("resource", "scope", "span", "event", "link"), 0)
    for resource in payload["resourceSpans"]:
        entities["resource"] += 1
        for scope in resource["scopeSpans"]:
            entities["scope"] += 1
            for span in scope["spans"]:
                entities["span"] += 1
                entities["event"] += len(span.get("events", []))
                entities["link"] += len(span.get("links", []))
    attributes = Counter()
    retained = Counter()
    wanted = {(field.scope, field.key) for field in contract.required_retained_fields}
    for attribute in iter_attributes(payload):
        attributes[attribute.scope] += 1
        if (attribute.scope, attribute.key) in wanted:
            retained[(attribute.scope, attribute.key)] += 1
    report["coverage"] = {
        "entities": entities,
        "attributes": {scope: attributes[scope] for scope in entities},
        "required_fields": [
            {"id": f"required-{index:04d}", "scope": field.scope,
             "present": retained[(field.scope, field.key)], "entities": entities[field.scope]}
            for index, field in enumerate(contract.required_retained_fields, 1)
        ],
    }
    values = tuple(canary.value for canary in contract.canaries)
    ensure_object_values_absent(report, values)
    ensure_values_absent(report, values)
    return report
