"""Value-free inspection of declared synthetic privacy checks and coverage."""
import re
from collections import Counter
from fractions import Fraction

from .canonical import InputError
from .checker import _iter_scalars
from .contract import Contract
from .coverage import coverage_report
from .otlp import validate_trace
from .report import (
    Violation,
    build_report,
    ensure_object_values_absent,
    ensure_values_absent,
)


def _privacy_checked(contract: Contract, report):
    values = tuple(canary.value for canary in contract.canaries)
    ensure_object_values_absent(report, values)
    ensure_values_absent(report, values)
    return report


def control_check(contract: Contract, payload):
    """Verify every synthetic canary is exercised in an unsanitized positive control."""
    validate_trace(payload)
    wanted = {canary.value for canary in contract.canaries}
    counts = Counter(scalar for _, scalar in _iter_scalars(payload)
                     if isinstance(scalar, str) and scalar in wanted)
    fields, issues = [], []
    for index, canary in enumerate(contract.canaries, 1):
        identifier = f"canary-{index:04d}"
        fields.append({"id": identifier, "occurrences": counts[canary.value]})
        if not counts[canary.value]:
            issues.append(Violation("TC902", "", "positive control does not exercise a declared canary", label=identifier))
    report = build_report(contract.contract_version, "unresolved" if issues else "pass", issues,
                          mode="control-check", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["control"] = {"canaries": fields}
    return _privacy_checked(contract, report)


def population_gate(contract: Contract, payload, scope: str, minimum: int):
    """Require an explicit population while preserving all existing privacy checks."""
    if scope not in ("resource", "scope", "span", "event", "link") or type(minimum) is not int or not 1 <= minimum <= 1_000_000:
        raise InputError("population gate requires a supported scope and integer minimum from 1 to 1000000")
    base = coverage_report(contract, payload)
    observed = base["coverage"]["entities"][scope]
    issues = [Violation(**item) for item in base["violations"]]
    if observed < minimum:
        issues.append(Violation("TC013", "", "export population is below the explicitly required minimum", scope=scope))
    report = build_report(contract.contract_version, "regression" if issues else "pass", issues,
                          mode="population-gate", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["coverage"] = base["coverage"]
    report["population_gate"] = {"scope": scope, "minimum": minimum, "observed": observed}
    return _privacy_checked(contract, report)


def dropped_telemetry(contract: Contract, payload, *, require_zero: bool = False):
    """Sum declared OTLP dropped counters, optionally enforcing an explicit zero gate."""
    if type(require_zero) is not bool:
        raise InputError("require_zero must be a boolean")
    base = coverage_report(contract, payload)
    totals = {scope: {"scope": scope, "attributes": 0, "events": 0, "links": 0}
              for scope in ("resource", "scope", "span", "event", "link")}
    for scope, _, entity in _retention_entities(payload):
        for name in ("attributes", "events", "links"):
            totals[scope][name] += entity.get(f"dropped{name.title()}Count", 0)
    issues = [Violation(**item) for item in base["violations"]]
    if require_zero:
        for scope, counts in totals.items():
            if any(counts[name] for name in ("attributes", "events", "links")):
                issues.append(Violation("TC014", "", "declared dropped telemetry violates the explicit zero-drop gate", scope=scope))
    report = build_report(contract.contract_version, "regression" if issues else "pass", issues,
                          mode="dropped-telemetry", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["dropped_telemetry"] = {"require_zero": require_zero, "scopes": list(totals.values())}
    return _privacy_checked(contract, report)


def inspect_contract(contract: Contract):
    """Inventory effective checks and find directly contradictory retention requirements."""
    conflicts = []
    for index, field in enumerate(contract.required_retained_fields, 1):
        if field.key in contract.forbidden_attribute_keys or any(
            field.key.startswith(prefix) for prefix in contract.forbidden_attribute_key_prefixes
        ):
            conflicts.append(f"required-{index:04d}")
    violations = [Violation("TC010", "", "contract requires a field forbidden by its attribute rules")] if conflicts else []
    report = build_report(contract.contract_version, "regression" if conflicts else "pass", violations,
                          mode="inspect-contract", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["inspection"] = {"semantic_conventions_version": contract.semantic_conventions_version,
        "canary_count": len(contract.canaries), "forbidden_key_count": len(contract.forbidden_attribute_keys),
        "forbidden_key_prefix_count": len(contract.forbidden_attribute_key_prefixes),
        "forbidden_path_prefix_count": len(contract.forbidden_path_prefixes),
        "required_fields": [{"id": f"required-{index:04d}", "scope": field.scope}
                            for index, field in enumerate(contract.required_retained_fields, 1)],
        "retention_conflicts": conflicts,
        "limits": {"max_input_bytes": contract.max_input_bytes, "max_nesting": contract.max_nesting,
                   "max_batch_files": contract.max_batch_files}}
    return _privacy_checked(contract, report)


def _parse_minimum_ratio(minimum_ratio: str) -> Fraction:
    if not isinstance(minimum_ratio, str) or not re.fullmatch(r"(?:0(?:\.[0-9]{1,6})?|1(?:\.0{1,6})?)", minimum_ratio):
        raise InputError("minimum ratio must be a decimal from 0 to 1 with at most six places")
    return Fraction(minimum_ratio)


def coverage_gate(contract: Contract, payload, minimum_ratio: str):
    """Opt-in per-required-field ratio gate, layered on the unchanged privacy check."""
    threshold = _parse_minimum_ratio(minimum_ratio)
    base = coverage_report(contract, payload)
    fields, extra = [], []
    unresolved = not contract.required_retained_fields
    for field in base["coverage"]["required_fields"]:
        meets = None if not field["entities"] else Fraction(field["present"], field["entities"]) >= threshold
        fields.append({**field, "meets_minimum": meets})
        if meets is None:
            unresolved = True
        elif not meets:
            extra.append(Violation("TC011", "", "required field coverage is below the explicitly requested ratio", label=field["id"]))
    if unresolved:
        extra.append(Violation("TC901", "", "coverage gate has no population for at least one requirement, or no requirements"))
    issues = [Violation(**item) for item in base["violations"]] + extra
    status = "unresolved" if unresolved else "regression" if issues else "pass"
    report = build_report(contract.contract_version, status, issues, mode="coverage-gate",
                          redacted_values=tuple(canary.value for canary in contract.canaries))
    report["coverage"] = base["coverage"]
    report["coverage_gate"] = {"minimum_ratio": minimum_ratio, "fields": fields}
    return _privacy_checked(contract, report)


def coverage_diff(contract: Contract, baseline, candidate):
    """Compare exact retained-field rates, with both population denominators visible."""
    before = coverage_report(contract, baseline)
    after = coverage_report(contract, candidate)
    fields, issues = [], []
    unresolved = before["status"] != "pass" or not contract.required_retained_fields
    if before["status"] != "pass":
        issues.append(Violation("TC900", "", "baseline does not satisfy the contract"))
    else:
        issues.extend(Violation(**item) for item in after["violations"])
        for left, right in zip(before["coverage"]["required_fields"], after["coverage"]["required_fields"], strict=True):
            delta = None
            if not left["entities"] or not right["entities"]:
                unresolved = True
            else:
                delta = Fraction(right["present"], right["entities"]) - Fraction(left["present"], left["entities"])
                if delta < 0:
                    issues.append(Violation("TC012", "", "required field coverage rate decreased", label=left["id"]))
            fields.append({"id": left["id"], "scope": left["scope"],
                           "baseline_present": left["present"], "baseline_entities": left["entities"],
                           "candidate_present": right["present"], "candidate_entities": right["entities"],
                           "rate_delta": str(delta) if delta is not None else None})
    if unresolved:
        issues.append(Violation("TC901", "", "coverage comparison has an invalid baseline, no requirements, or an empty population"))
    report = build_report(contract.contract_version, "unresolved" if unresolved else "regression" if issues else "pass",
                          issues, mode="coverage-diff", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["coverage_diff"] = {"fields": fields}
    return _privacy_checked(contract, report)


MAX_MATRIX_CHECKS = 10000


def _retention_entities(payload):
    for ri, resource in enumerate(payload["resourceSpans"]):
        rp = f"/resourceSpans/{ri}"
        yield "resource", rp + "/resource", resource.get("resource", {})
        for si, scope in enumerate(resource["scopeSpans"]):
            yield "scope", f"{rp}/scopeSpans/{si}/scope", scope.get("scope", {})
            for pi, span in enumerate(scope["spans"]):
                sp = f"{rp}/scopeSpans/{si}/spans/{pi}"
                yield "span", sp, span
                for ei, event in enumerate(span.get("events", [])):
                    yield "event", f"{sp}/events/{ei}", event
                for li, link in enumerate(span.get("links", [])):
                    yield "link", f"{sp}/links/{li}", link


def retention_matrix(contract: Contract, payload):
    """Locate missing required attributes without including keys or attribute values."""
    report = coverage_report(contract, payload)
    checks = sum(field["entities"] for field in report["coverage"]["required_fields"])
    if checks > MAX_MATRIX_CHECKS:
        raise InputError("retention matrix exceeds the 10000 entity-requirement check limit")
    fields = [{"id": f"required-{index:04d}", "scope": field.scope, "missing_paths": []}
              for index, field in enumerate(contract.required_retained_fields, 1)]
    for scope, path, entity in _retention_entities(payload):
        keys = {attribute["key"] for attribute in entity.get("attributes", [])}
        for index, field in enumerate(contract.required_retained_fields):
            if field.scope == scope and field.key not in keys:
                fields[index]["missing_paths"].append(path)
    report["mode"] = "retention-matrix"
    report["retention_matrix"] = {"entity_requirement_checks": checks, "fields": fields}
    return _privacy_checked(contract, report)
