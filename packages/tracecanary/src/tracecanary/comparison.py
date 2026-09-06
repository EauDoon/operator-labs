"""Baseline-to-candidate retained-field regression checks."""

from __future__ import annotations

from collections import Counter
from typing import Any

from tracecanary.contract import Contract
from tracecanary.otlp import iter_attributes
from tracecanary.report import Report, Status, Violation, ViolationDict, build_report, ensure_values_absent
from tracecanary.retention import compare_requirements


def diff_traces(contract: Contract, baseline: dict[str, Any], candidate: dict[str, Any]) -> Report:
    """Compare candidate field counts with a contract-satisfying baseline."""
    baseline_report = _without_mode(contract, baseline)
    if baseline_report["status"] != "pass":
        canary_values = tuple(canary.value for canary in contract.canaries)
        report = build_report(
            contract.contract_version,
            "unresolved",
            [Violation("TC900", "", "baseline does not satisfy the contract")],
            mode="diff",
            redacted_values=canary_values,
        )
        ensure_values_absent(report, canary_values)
        return report
    candidate_report = _without_mode(contract, candidate)
    violations = [Violation(**_violation_kwargs(item)) for item in candidate_report["violations"]]
    baseline_counts = _retained_counts(contract, baseline)
    candidate_counts = _retained_counts(contract, candidate)
    for field in contract.required_retained_fields:
        identity = (field.scope, field.key)
        if candidate_counts[identity] < baseline_counts[identity]:
            violations.append(
                Violation(
                    "TC005",
                    "",
                    "candidate retained fewer required operational fields than baseline",
                    key=field.key,
                    scope=field.scope,
                )
            )
    if contract.retention is not None:
        violations.extend(compare_requirements(contract.retention, baseline, candidate))
    status = _status(violations)
    canary_values = tuple(canary.value for canary in contract.canaries)
    report = build_report(
        contract.contract_version,
        status,
        violations,
        mode="diff",
        redacted_values=canary_values,
    )
    ensure_values_absent(report, canary_values)
    return report


def _status(violations: list[Violation]) -> Status:
    """An unresolved comparison must never be reported as a pass or a regression."""
    if any(issue.code == "TC014" for issue in violations):
        return "unresolved"
    return "pass" if not violations else "regression"


def _without_mode(contract: Contract, payload: dict[str, Any]) -> Report:
    from tracecanary.checker import check_trace

    return check_trace(contract, payload)


def _retained_counts(contract: Contract, payload: dict[str, Any]) -> Counter[tuple[str, str]]:
    wanted = {(field.scope, field.key) for field in contract.required_retained_fields}
    return Counter((attribute.scope, attribute.key) for attribute in iter_attributes(payload) if (attribute.scope, attribute.key) in wanted)


def _violation_kwargs(item: ViolationDict) -> dict[str, str | None]:
    return {
        "code": item["code"],
        "path": item["path"],
        "message": item["message"],
        "label": item.get("label"),
        "category": item.get("category"),
        "key": item.get("key"),
        "scope": item.get("scope"),
        "detail": item.get("detail"),
    }
