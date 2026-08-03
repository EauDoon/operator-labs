"""Deterministic reports that deliberately avoid matched values."""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET
from typing import Any

from tracecanary.canonical import canonical_json


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    label: str | None = None
    category: str | None = None
    key: str | None = None
    scope: str | None = None

    def as_dict(self) -> dict[str, str]:
        data = {"code": self.code, "message": self.message, "path": self.path}
        for name in ("category", "key", "label", "scope"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        return data


class UnsafeReportError(ValueError):
    """A report cannot be emitted without exposing a protected value."""


def build_report(
    contract_version: str,
    status: str,
    violations: list[Violation],
    *,
    mode: str,
    redacted_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    safe_violations = [_redact_violation(issue, redacted_values) for issue in violations]
    ordered = sorted(safe_violations, key=lambda issue: (issue.code, issue.path, issue.label or "", issue.key or ""))
    counts = {
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
        "summary": counts,
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


def render_json(report: dict[str, Any]) -> str:
    return canonical_json(report)


def render_human(report: dict[str, Any]) -> str:
    headline = f"TraceCanary: {report['status'].upper()} ({report['summary']['total']} finding(s))"
    lines = [headline]
    for item in report["violations"]:
        detail = item["message"]
        if "label" in item:
            detail += f" [label={item['label']}; category={item['category']}]"
        if "key" in item:
            detail += f" [key={item['key']}; scope={item['scope']}]"
        location = f" at {item['path']}" if item["path"] else ""
        lines.append(f"- {item['code']} {detail}{location}")
    return "\n".join(lines) + "\n"


def ensure_values_absent(report: dict[str, Any], values: tuple[str, ...]) -> None:
    """Fail closed if either supported rendering still contains a protected value."""
    output = render_json(report) + render_human(report)
    if any(value in output for value in values):
        raise UnsafeReportError


def render_sarif(batch: dict[str, Any]) -> str:
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
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": str(location)}}}],
            }
            results.append(result)
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "TraceCanary", "informationUri": "https://github.com/EauDoon/tracecanary"}}, "results": results}],
    }
    return canonical_json(payload)


def render_junit(batch: dict[str, Any]) -> str:
    """Render a deterministic JUnit XML batch report without timestamps."""
    items = list(batch.get("items", []))
    failures = sum(item.get("status") == "regression" for item in items)
    errors = sum(item.get("status") == "unresolved" for item in items)
    suite = ET.Element("testsuite", name="TraceCanary", tests=str(len(items)), failures=str(failures), errors=str(errors))
    for item in items:
        case = ET.SubElement(suite, "testcase", name=str(item.get("id", "item")))
        status = item.get("status")
        if status == "regression":
            failure = ET.SubElement(case, "failure", type="regression")
            failure.text = "TraceCanary regression"
        elif status == "unresolved":
            error = ET.SubElement(case, "error", type="unresolved")
            error.text = "TraceCanary input unresolved"
    return ET.tostring(suite, encoding="unicode", short_empty_elements=True) + "\n"
