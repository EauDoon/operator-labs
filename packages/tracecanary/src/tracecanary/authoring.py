"""Guided contract authoring with conservative, actionable diagnostics.

Contract drafts are ordinary strict TraceCanary contracts: editing applies
as a whole or not at all, and the runtime validator remains authoritative.
Synthetic canary values are protected configuration — diagnostics never
include them, and an explicit contract export (which necessarily contains
canary values) is a separate, clearly labeled action from a value-free
report export.

The runtime validator already rejects structurally invalid drafts,
duplicate rules, and unusable canary configuration, so this review covers
what it cannot: direct retention conflicts, malformed wildcard paths, and
conservatively detectable ineffective or shadowed rules. Every diagnostic
names a safe structural location (rule ordinal or key), explains the issue,
and suggests a correction without silently weakening the contract.
"""

from __future__ import annotations

import re
from typing import Any

from tracecanary.contract import ContractError, parse_contract
from tracecanary.report import Report, Status, build_report, ensure_object_values_absent

REVIEW_VERSION = "tracecanary.contract-review/v1"
MAX_PATH_SEGMENTS = 32
_SEGMENT = re.compile(r"(?:\*|[^*/]+)")


def empty_template() -> dict[str, Any]:
    """A minimal, valid contract the user can extend."""
    return {
        "contract_version": "tracecanary/v1",
        "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
        "canaries": [{"label": "synthetic-canary", "category": "prompt", "value": "TCANARY_REPLACE_ME_0000000000000000"}],
        "forbidden_attribute_keys": ["gen_ai.prompt"],
        "forbidden_attribute_key_prefixes": ["enduser."],
        "forbidden_path_prefixes": [],
        "required_retained_fields": [{"scope": "resource", "key": "service.name"}],
    }


def validate_draft(raw: Any) -> dict[str, Any]:
    """Validate a draft contract without weakening anything.

    Raises ContractError exactly like the runtime validator; the returned
    document is the draft itself.
    """
    if not isinstance(raw, dict):
        raise ContractError("a contract draft must be a JSON object")
    parse_contract(raw)
    return raw


def review_contract(raw: Any) -> Report:
    """Value-free diagnostics for a contract draft.

    Diagnostics are structural: rule ordinals, scope/key-safe locations, and
    never canary values. Conflicts, duplicates, malformed paths, and
    conservatively provable ineffective rules are regressions.
    """
    if not isinstance(raw, dict):
        raise ContractError("a contract draft must be a JSON object")
    findings: list[dict[str, Any]] = []

    def add(severity: str, location: str, message: str, suggestion: str) -> None:
        findings.append({"severity": severity, "location": location, "message": message, "suggestion": suggestion})

    # Parse strictly first: structural validity is a precondition for the
    # conservative review below.
    parse_contract(raw)

    required = raw.get("required_retained_fields", [])
    forbidden_keys = list(raw.get("forbidden_attribute_keys", []))
    forbidden_prefixes = list(raw.get("forbidden_attribute_key_prefixes", []))
    path_prefixes = list(raw.get("forbidden_path_prefixes", []))
    canaries = raw.get("canaries", [])

    # 1. Direct retention conflicts (the same provable conflict the CLI
    #    inspect-contract reports, here with actionable locations).
    for index, field in enumerate(required, start=1):
        identity = (field.get("scope", ""), field.get("key", ""))
        if identity[1] in forbidden_keys:
            add("conflict", f"required_retained_fields[{index}]",
                f"requires key {identity[1]!r}, which forbidden_attribute_keys forbids",
                "drop one of the two rules; a requirement and a prohibition cannot both hold")
        elif any(identity[1].startswith(prefix) for prefix in forbidden_prefixes):
            add("conflict", f"required_retained_fields[{index}]",
                f"requires key {identity[1]!r}, which a forbidden_attribute_key_prefixes entry forbids",
                "narrow the forbidden prefix or drop the requirement")

    # 3. Malformed wildcard path prefixes: the checker only ever matches
    #    literal segments and single-segment wildcards, so anything else can
    #    never match and silently protects nothing.
    for index, prefix in enumerate(path_prefixes, start=1):
        problem = _path_prefix_problem(prefix)
        if problem is not None:
            add("malformed", f"forbidden_path_prefixes[{index}]", problem,
                "use literal '/'-separated segments with '*' matching exactly one segment, and stop at a scalar value")

    # 4. Ineffective configuration, determined conservatively.
    for index, prefix in enumerate(path_prefixes, start=1):
        if "value" not in prefix.split("/"):
            add("ineffective", f"forbidden_path_prefixes[{index}]",
                "the path stops before a scalar value, so it can never block a value",
                "extend the path to the value leaf, for example .../attributes/*/value/stringValue")
    shadowed_keys = [key for key in forbidden_keys
                     if any(key != other and key.startswith(other) for other in forbidden_keys)
                     or any(key.startswith(prefix) for prefix in forbidden_prefixes)]
    for key in shadowed_keys:
        add("ineffective", f"forbidden_attribute_keys[{forbidden_keys.index(key)}]",
            f"another forbidden prefix already covers {key!r}",
            "keep the broader prefix rule and drop the redundant exact key")

    # 5. Canary configuration is validated strictly by the runtime validator
    #    (unique non-empty labels and values, required-field uniqueness, JSON
    #    pointer shape); diagnostics only cover what it does not catch.

    severity_order = {"conflict": 0, "malformed": 1, "ineffective": 2}
    findings.sort(key=lambda item: (severity_order[item["severity"]], item["location"]))
    status: Status = "regression" if findings else "pass"
    report = build_report(raw.get("contract_version", "tracecanary/v1"), status, [], mode="contract-review")
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    report["review"] = {"findings": findings, "counts": counts}
    canary_values = tuple(str(canary.get("value", "")) for canary in canaries if isinstance(canary, dict))
    ensure_object_values_absent(report, canary_values)
    return report


def render_review_human(report: Report) -> str:
    """Value-free review rendering shared by the CLI and the desktop."""
    counts = report["review"]["counts"]
    headline = ", ".join(f"{count} {severity}" for severity, count in sorted(counts.items())) or "no findings"
    lines = [f"TraceCanary contract review: {report['status'].upper()} ({headline})"]
    for finding in report["review"]["findings"]:
        lines.append(f"- {finding['severity']} at {finding['location']}: {finding['message']}")
        lines.append(f"  suggestion: {finding['suggestion']}")
    lines.append("Diagnostics are structural and value-free; canary values never appear. Validation is not a privacy guarantee.")
    return "\n".join(lines) + "\n"


def _path_prefix_problem(prefix: Any) -> str | None:
    if not isinstance(prefix, str) or not prefix.startswith("/") or not prefix.strip("/"):
        return "path prefixes must start with '/' and name at least one segment"
    if "//" in prefix or prefix.endswith("//"):
        return "path prefixes must not contain empty segments"
    segments = prefix.strip("/").split("/")
    if len(segments) > MAX_PATH_SEGMENTS:
        return f"path prefixes are limited to {MAX_PATH_SEGMENTS} segments"
    for segment in segments:
        if segment != "*" and ("/" in segment or "*" in segment):
            return "only whole segments may be '*'; partial wildcards can never match"
    return None
