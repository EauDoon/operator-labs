"""Synthetic regression campaigns over declared projects and selections.

A campaign runs the existing checkers and batch logic in one bounded pass
and reports each phase with its separate meaning: contract validity, canary
exercise in the positive control, baseline validity, candidate privacy and
retention findings, a bounded batch phase, and configured coverage gates.
Canary values never enter any campaign output; every phase reuses the
value-free report builders, and the combined document is checked again
before it is returned.

Baseline safeguards: a baseline that does not pass the contract is never
used, and promotion is an explicit, validated action. Nothing here blesses
a failing candidate or implies entity identity.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tracecanary.batching import run_batch
from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, load_contract
from tracecanary.inspection import control_check, coverage_gate, population_gate
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import Report, Status, ensure_object_values_absent

CAMPAIGN_VERSION = "tracecanary.campaign/v1"
STATUS_RANK: dict[str, int] = {"pass": 0, "regression": 1, "unresolved": 2, "skipped": -1}


def _combined(statuses: list[str]) -> Status:
    worst = max(statuses, key=lambda status: STATUS_RANK.get(status, 2)) if statuses else "pass"
    return "unresolved" if worst == "unresolved" else "regression" if worst == "regression" else "pass"


def _phase(status: Status, report: Report | None = None, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    phase: dict[str, Any] = {"status": status}
    if report is not None:
        phase["violations"] = list(report["violations"])
        phase["finding_counts"] = dict(sorted(Counter(item["code"] for item in report["violations"]).items()))
    if detail:
        phase.update(detail)
    return phase


def _load_payload(path: Path, contract: Contract) -> dict[str, Any]:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


def baseline_is_valid(contract: Contract, payload: dict[str, Any]) -> bool:
    try:
        return check_trace(contract, payload, mode="check")["status"] == "pass"
    except (InputError, ValueError, OtlpError):
        return False


def run_campaign(
    contract: Contract,
    *,
    control_payload: dict[str, Any] | None = None,
    baseline_payload: dict[str, Any] | None = None,
    candidates: list[tuple[str, Path]] | None = None,
    batch: Path | None = None,
    batch_recursive: bool = False,
    batch_include_paths: bool = False,
    batch_minimum_ratio: str | None = None,
    minimum_ratio: str | None = None,
    population_scope: str | None = None,
    population_minimum: int | None = None,
) -> dict[str, Any]:
    """Run one bounded campaign from loaded inputs and return a value-free report.

    ``candidates`` pairs stable labels (names or opt-in relative paths) with
    candidate file paths; each is loaded with the contract bounds. The batch
    phase reuses the bounded batch engine directly.
    """
    phases: dict[str, Any] = {}
    statuses: list[str] = []

    phases["contract"] = _phase("pass", detail={"contract_version": contract.contract_version})
    statuses.append("pass")

    if control_payload is not None:
        control_report = control_check(contract, control_payload)
        phases["control"] = _phase(control_report["status"], control_report, detail={
            "meaning": "PASS confirms the unsanitized synthetic control exercised every declared canary; it is not a privacy pass",
        })
        statuses.append(control_report["status"])
    else:
        phases["control"] = {"status": "skipped", "meaning": "no positive control was configured"}

    baseline_usable = False
    if baseline_payload is not None:
        baseline_report = check_trace(contract, baseline_payload, mode="check")
        if baseline_report["status"] != "pass":
            phases["baseline"] = _phase("unresolved", baseline_report, detail={
                "meaning": "a baseline that does not satisfy the contract is never used and never silently replaced",
            })
            statuses.append("unresolved")
        else:
            phases["baseline"] = _phase("pass", baseline_report)
            statuses.append("pass")
            baseline_usable = True
    else:
        phases["baseline"] = {"status": "skipped", "meaning": "no baseline was configured; candidates run standalone checks"}

    candidate_items: list[dict[str, Any]] = []
    for index, (label, path) in enumerate(candidates or [], start=1):
        try:
            payload = _load_payload(path, contract)
            if minimum_ratio is not None:
                report = coverage_gate(contract, payload, minimum_ratio)
            elif baseline_usable:
                report = diff_traces(contract, baseline_payload, payload)
            else:
                report = check_trace(contract, payload, mode="campaign")
        except (InputError, ValueError, OtlpError):
            candidate_items.append({
                "id": f"candidate-{index:04d}", "label": label, "status": "unresolved",
                "violations": [], "finding_counts": {},
            })
            statuses.append("unresolved")
            continue
        candidate_items.append({
            "id": f"candidate-{index:04d}", "label": label, "status": report["status"],
            "violations": list(report["violations"]),
            "finding_counts": dict(sorted(Counter(item["code"] for item in report["violations"]).items())),
        })
        statuses.append(report["status"])
    candidate_status = _combined([item["status"] for item in candidate_items]) if candidate_items else "skipped"
    candidate_counts: Counter = Counter()
    for item in candidate_items:
        for code, count in item["finding_counts"].items():
            candidate_counts[code] += count
    phases["candidates"] = {
        "status": candidate_status,
        "items": candidate_items,
        "count": len(candidate_items),
        "finding_counts": dict(sorted(candidate_counts.items())),
        "meaning": "each candidate keeps its own privacy, retention, and coverage findings",
        "mode": "coverage-gate" if minimum_ratio is not None else "baseline-diff" if baseline_usable else "standalone-check",
    }
    if candidate_status != "skipped":
        statuses.append(candidate_status)

    if population_scope is not None and population_minimum is not None and candidates:
        gate = population_gate(contract, _load_payload(candidates[0][1], contract), population_scope, population_minimum)
        phases["population_gate"] = _phase(gate["status"], gate, detail={
            "scope": population_scope, "minimum": population_minimum,
            "meaning": "evaluated against the named candidate; population coverage across directories belongs to the batch phase",
        })
        statuses.append(gate["status"])

    if batch is not None:
        batch_report = run_batch(contract, batch, batch_recursive, batch_include_paths, None,
                                 coverage=True, minimum_ratio=batch_minimum_ratio)
        phases["batch"] = {
            "status": batch_report["status"],
            "item_count": len(batch_report["items"]),
            "statuses": dict(sorted(Counter(item["status"] for item in batch_report["items"]).items())),
            "batch_version": batch_report["batch_version"],
            "meaning": "bounded directory enumeration with per-file results and unresolved precedence",
        }
        if "coverage_summary" in batch_report:
            phases["batch"]["coverage_summary"] = batch_report["coverage_summary"]
        statuses.append(batch_report["status"])

    status = _combined(statuses)
    totals: Counter = Counter()
    for phase in phases.values():
        for code, count in phase.get("finding_counts", {}).items():
            totals[code] += count
    campaign: dict[str, Any] = {
        "campaign_version": CAMPAIGN_VERSION,
        "contract_version": contract.contract_version,
        "status": status,
        "phases": phases,
        "summary": {"finding_counts": dict(sorted(totals.items()))},
    }
    ensure_object_values_absent(campaign, tuple(canary.value for canary in contract.canaries))
    return campaign


def campaign_summary(campaign: dict[str, Any]) -> dict[str, Any]:
    """A deterministic, value-free digest safe to save explicitly."""
    return {
        "summary_version": "tracecanary.campaign-summary/v1",
        "contract_version": campaign["contract_version"],
        "campaign_status": campaign["status"],
        "phases": {
            name: {"status": phase["status"], "finding_counts": phase.get("finding_counts", {})}
            for name, phase in campaign["phases"].items()
            if isinstance(phase, dict)
        },
        "candidate_count": campaign["phases"]["candidates"].get("count", 0),
    }


def render_campaign_human(campaign: dict[str, Any]) -> str:
    """Value-free campaign rendering shared by the CLI and the desktop."""
    lines = [f"TraceCanary campaign: {campaign['status'].upper()} (contract {campaign['contract_version']})"]
    meanings = {
        "control": "control pass confirms canary exercise, not a privacy pass",
        "baseline": "a failing baseline is never used",
        "candidates": "per-candidate findings with separate privacy and retention meanings",
        "batch": "bounded directory enumeration with per-file results",
        "population_gate": "explicit population requirement",
    }
    for name, phase in campaign["phases"].items():
        counts = phase.get("finding_counts", {})
        counts_text = f"; findings {dict(sorted(counts.items()))}" if counts else ""
        meaning = meanings.get(name)
        lines.append(f"- {name}: {phase['status']}{counts_text}" + (f" ({meaning})" if meaning else ""))
    totals = campaign.get("summary", {}).get("finding_counts", {})
    if totals:
        lines.append(f"Total finding counts by value-free code: {dict(sorted(totals.items()))}")
    lines.append("Canary values never appear in this report.")
    return "\n".join(lines) + "\n"


def render_comparison_human(comparison: dict[str, Any]) -> str:
    lines = [
        f"TraceCanary campaign comparison: {comparison['campaign_status_change'][0]} -> {comparison['campaign_status_change'][1]}",
        f"Contract version: {comparison['contract_version']}",
    ]
    for name, phase in comparison["phases"].items():
        lines.append(f"{name}: {phase['baseline_status']} -> {phase['candidate_status']}")
        for label in ("persistent_findings", "resolved_findings", "new_findings"):
            counts = phase[label]
            if counts:
                rendered = ", ".join(f"{code} x{count}" for code, count in counts.items())
                lines.append(f"  {label.replace('_', ' ')}: {rendered}")
    lines.append("Finding codes are aggregated by value-free code; no entity identity or causal attribution is implied.")
    return "\n".join(lines) + "\n"


def compare_summaries(baseline_summary: dict[str, Any], candidate_summary: dict[str, Any]) -> dict[str, Any]:
    """Compare two saved campaign summaries with strict compatibility checks.

    Findings are aggregated by value-free code. A code present in both is
    persistent, one only in the baseline is resolved, and one only in the
    candidate is new. Nothing implies matched entity identity or causal
    attribution, and incompatible summaries are unsupported rather than
    compared loosely.
    """
    for summary in (baseline_summary, candidate_summary):
        if not isinstance(summary, dict) or summary.get("summary_version") != "tracecanary.campaign-summary/v1":
            raise InputError("campaign comparison requires two saved tracecanary.campaign-summary/v1 documents")
    if baseline_summary.get("contract_version") != candidate_summary.get("contract_version"):
        raise InputError("campaign comparison requires the same contract version in both summaries")
    phases: dict[str, Any] = {}
    for name in sorted(set(baseline_summary.get("phases", {})) | set(candidate_summary.get("phases", {}))):
        before = baseline_summary.get("phases", {}).get(name, {})
        after = candidate_summary.get("phases", {}).get(name, {})
        old_counts = dict(before.get("finding_counts", {}))
        new_counts = dict(after.get("finding_counts", {}))
        phases[name] = {
            "baseline_status": before.get("status", "absent"),
            "candidate_status": after.get("status", "absent"),
            "persistent_findings": {code: new_counts[code] for code in sorted(set(old_counts) & set(new_counts))},
            "resolved_findings": {code: old_counts[code] for code in sorted(set(old_counts) - set(new_counts))},
            "new_findings": {code: new_counts[code] for code in sorted(set(new_counts) - set(old_counts))},
        }
    return {
        "comparison_version": "tracecanary.campaign-comparison/v1",
        "contract_version": baseline_summary.get("contract_version", ""),
        "campaign_status_change": [baseline_summary.get("campaign_status", "absent"), candidate_summary.get("campaign_status", "absent")],
        "phases": phases,
        "meaning": "finding codes are aggregated by value-free code; no entity identity or causal attribution is implied",
    }
