"""Trace privacy and retained-field checks."""

from __future__ import annotations

from typing import Any, Iterator

from tracecanary.canonical import json_pointer, pointer_matches
from tracecanary.contract import Contract
from tracecanary.otlp import iter_attributes
from tracecanary.report import Violation, build_report, ensure_values_absent


def check_trace(contract: Contract, payload: dict[str, Any], *, mode: str = "check") -> dict[str, Any]:
    """Evaluate a validated OTLP trace, without carrying any canary value into a report."""
    violations: list[Violation] = []
    for path, scalar in _iter_scalars(payload):
        if isinstance(scalar, str):
            for canary in contract.canaries:
                if scalar == canary.value:
                    violations.append(Violation("TC001", json_pointer(path), "synthetic canary survived export", canary.label, canary.category))
        for prefix in contract.forbidden_path_prefixes:
            if pointer_matches(prefix, path):
                violations.append(Violation("TC003", json_pointer(path), "forbidden JSON path is populated"))
    present: set[tuple[str, str]] = set()
    for attribute in iter_attributes(payload):
        present.add((attribute.scope, attribute.key))
        if attribute.key in contract.forbidden_attribute_keys or any(attribute.key.startswith(prefix) for prefix in contract.forbidden_attribute_key_prefixes):
            violations.append(Violation("TC002", json_pointer(attribute.path), "forbidden telemetry attribute is present", key=attribute.key, scope=attribute.scope))
    for field in contract.required_retained_fields:
        if (field.scope, field.key) not in present:
            violations.append(Violation("TC004", "", "required operational field is absent", key=field.key, scope=field.scope))
    status = "pass" if not violations else "regression"
    canary_values = tuple(canary.value for canary in contract.canaries)
    report = build_report(
        contract.contract_version,
        status,
        violations,
        mode=mode,
        redacted_values=canary_values,
    )
    ensure_values_absent(report, canary_values)
    return report


def _iter_scalars(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield scalar values in the recursive walk order without using recursion."""
    pending: list[tuple[Any, tuple[str, ...]]] = [(value, path)]
    while pending:
        current, current_path = pending.pop()
        if isinstance(current, dict):
            items = list(current.items())
            for key, child in reversed(items):
                pending.append((child, current_path + (key,)))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], current_path + (str(index),)))
        else:
            yield current_path, current
