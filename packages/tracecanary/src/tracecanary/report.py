"""Deterministic reports that deliberately avoid matched values."""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET
from urllib.parse import quote
from typing import Any, Literal, NotRequired, TypedDict

from tracecanary.canonical import canonical_json


Status = Literal["pass", "regression", "unresolved"]
ReportMode = Literal["validate", "check", "diff", "batch", "demo", "starter", "coverage", "inspect-contract", "coverage-gate", "coverage-diff"]


class ReportSummary(TypedDict):
    canary_leaks: int
    forbidden_attributes: int
    forbidden_paths: int
    missing_retained_fields: int
    baseline_regressions: int
    total: int


class ViolationDict(TypedDict):
    code: str
    message: str
    path: str
    category: NotRequired[str]
    key: NotRequired[str]
    label: NotRequired[str]
    scope: NotRequired[str]


class Report(TypedDict):
    contract_version: str
    mode: ReportMode
    status: Status
    summary: ReportSummary
    violations: list[ViolationDict]
    coverage: NotRequired[dict[str, Any]]
    inspection: NotRequired[dict[str, Any]]
    coverage_gate: NotRequired[dict[str, Any]]
    coverage_diff: NotRequired[dict[str, Any]]


class BatchItem(TypedDict):
    id: str
    status: Status
    report: Report
    path: NotRequired[str]


class BatchReport(TypedDict):
    batch_version: str
    contract_version: str
    status: Status
    items: list[BatchItem]


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    label: str | None = None
    category: str | None = None
    key: str | None = None
    scope: str | None = None

    def as_dict(self) -> ViolationDict:
        data: ViolationDict = {"code": self.code, "message": self.message, "path": self.path}
        if self.category is not None:
            data["category"] = self.category
        if self.key is not None:
            data["key"] = self.key
        if self.label is not None:
            data["label"] = self.label
        if self.scope is not None:
            data["scope"] = self.scope
        return data


class UnsafeReportError(ValueError):
    """A report cannot be emitted without exposing a protected value."""


def build_report(
    contract_version: str,
    status: Status,
    violations: list[Violation],
    *,
    mode: ReportMode,
    redacted_values: tuple[str, ...] = (),
) -> Report:
    safe_violations = [_redact_violation(issue, redacted_values) for issue in violations]
    ordered = sorted(safe_violations, key=lambda issue: (issue.code, issue.path, issue.label or "", issue.key or ""))
    summary: ReportSummary = {
        "canary_leaks": sum(issue.code == "TC001" for issue in ordered),
        "forbidden_attributes": sum(issue.code == "TC002" for issue in ordered),
        "forbidden_paths": sum(issue.code == "TC003" for issue in ordered),
        "missing_retained_fields": sum(issue.code == "TC004" for issue in ordered),
        "baseline_regressions": sum(issue.code == "TC005" for issue in ordered),
        "total": len(ordered),
    }
    return {
        "contract_version": contract_version,
        "mode": mode,
        "status": status,
        "summary": summary,
        "violations": [issue.as_dict() for issue in ordered],
    }


def _redact_violation(issue: Violation, values: tuple[str, ...]) -> Violation:
    def redact(value: str | None) -> str | None:
        if value is None:
            return None
        if any(secret in value for secret in values):
            return None
        return value

    return Violation(
        code=issue.code,
        path=redact(issue.path) or "",
        message=redact(issue.message) or "",
        label=redact(issue.label),
        category=redact(issue.category),
        key=redact(issue.key),
        scope=redact(issue.scope),
    )


def render_json(report: Report | BatchReport) -> str:
    return canonical_json(report)


def render_human(report: Report) -> str:
    headline = f"TraceCanary: {report['status'].upper()} ({report['summary']['total']} finding(s))"
    lines = [headline]
    if "coverage_diff" in report:
        for field in report["coverage_diff"]["fields"]:
            lines.append(f"{field['id']}: {field['baseline_present']}/{field['baseline_entities']} -> {field['candidate_present']}/{field['candidate_entities']}; rate delta {field['rate_delta']}")
    if "coverage_gate" in report:
        lines.append(f"Explicit minimum retained-field ratio: {report['coverage_gate']['minimum_ratio']}.")
    if "inspection" in report:
        inspection = report["inspection"]
        lines.append(f"Contract checks: {inspection['canary_count']} canaries, {len(inspection['required_fields'])} retained fields.")
        lines.append(f"Direct retention conflicts: {len(inspection['retention_conflicts'])}. No canary values or field keys are displayed.")
    for item in report["violations"]:
        detail = item["message"]
        if "label" in item or "category" in item:
            detail += f" [label={item.get('label', '')}; category={item.get('category', '')}]"
        if "key" in item or "scope" in item:
            detail += f" [key={item.get('key', '')}; scope={item.get('scope', '')}]"
        location = f" at {item['path']}" if item["path"] else ""
        lines.append(f"- {item['code']} {detail}{location}")
    if "coverage" in report:
        coverage = report["coverage"]
        lines.append("Coverage counts describe this export only; a passing check is not proof of complete telemetry.")
        for scope, count in coverage["entities"].items():
            lines.append(f"- {scope}: {count} entities, {coverage['attributes'][scope]} attributes")
        for field in coverage["required_fields"]:
            lines.append(f"- {field['id']} ({field['scope']}): present on {field['present']} of {field['entities']} entities")
    return "\n".join(lines) + "\n"


def ensure_values_absent(report: Report, values: tuple[str, ...]) -> None:
    """Fail closed if either supported rendering still contains a protected value."""
    output = render_json(report) + render_human(report)
    ensure_text_values_absent(output, values)


def ensure_text_values_absent(output: str, values: tuple[str, ...]) -> None:
    """Fail closed if report text contains a protected value."""
    if any(value in output for value in values):
        raise UnsafeReportError


def ensure_object_values_absent(value: Any, values: tuple[str, ...]) -> None:
    """Fail closed if nested JSON keys or string values contain a protected value."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            ensure_text_values_absent(current, values)
        elif isinstance(current, dict):
            for key, child in current.items():
                if isinstance(key, str):
                    ensure_text_values_absent(key, values)
                pending.append(child)
        elif isinstance(current, list):
            pending.extend(current)


def render_sarif(batch: BatchReport) -> str:
    """Render a deterministic SARIF 2.1.0 batch report without host paths."""
    results: list[dict[str, Any]] = []
    for item in batch.get("items", []):
        location = item.get("path") or item.get("id", "item")
        report = item.get("report", {})
        for violation in report.get("violations", []):
            result: dict[str, Any] = {
                "level": "error" if item.get("status") in {"regression", "unresolved"} else "warning",
                "message": {"text": str(violation.get("message", "TraceCanary finding"))},
                "ruleId": str(violation.get("code", "TC000")),
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": quote(str(location), safe="/")}}}],
            }
            result["properties"] = {"jsonPointer": str(violation.get("path", "")), "itemId": item.get("id", "item")}
            results.append(result)
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "TraceCanary", "informationUri": "https://github.com/EauDoon/operator-labs/tree/main/packages/tracecanary"}}, "results": results}],
    }
    return canonical_json(payload)


def render_junit(batch: BatchReport) -> str:
    """Render a deterministic JUnit XML batch report without timestamps."""
    items = list(batch.get("items", []))
    failures = sum(item.get("status") == "regression" for item in items)
    errors = sum(item.get("status") == "unresolved" for item in items)
    suite = ET.Element("testsuite", name="TraceCanary", tests=str(len(items)), failures=str(failures), errors=str(errors))
    for item in items:
        case = ET.SubElement(suite, "testcase", name=str(item.get("id", "item")))
        if "path" in item:
            case.set("file", _xml_text(str(item["path"])))
        details = "\n".join(f"{v.get('code', 'TC000')}: {v.get('message', '')} at {v.get('path', '')}" for v in item.get("report", {}).get("violations", []))
        status = item.get("status")
        if status == "regression":
            failure = ET.SubElement(case, "failure", type="regression")
            failure.text = _xml_text(details or "TraceCanary regression")
        elif status == "unresolved":
            error = ET.SubElement(case, "error", type="unresolved")
            error.text = _xml_text(details or "TraceCanary input unresolved")
    return ET.tostring(suite, encoding="unicode", short_empty_elements=True) + "\n"


def _xml_text(value: str) -> str:
    """Replace characters XML 1.0 cannot represent, including filename controls."""
    return "".join(character if character in "\t\n\r" or 0x20 <= ord(character) <= 0xD7FF or 0xE000 <= ord(character) <= 0xFFFD or 0x10000 <= ord(character) <= 0x10FFFF else "\ufffd" for character in value)
