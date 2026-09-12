"""Portable evidence exports that explain themselves.

An evidence document bundles the deterministic report with the tool
version, the analysis identity, the declared input sources, and the
standing limitations, so another operator can understand what was tested
without the original operator's memory. Reports are fictional and carry no
secrets, so evidence documents may include them verbatim; TraceCanary
evidence is value-free by separate design. Every write is explicit, bounded,
and atomic, with the same input-collision protection as reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical import InputError, atomic_write_text

EVIDENCE_VERSION = "corridor-lab.evidence/v1"
TOOL_VERSION = "0.2.0"
MAX_EVIDENCE_BYTES = 5_000_000

STANDING_LIMITATIONS = (
    "All entities, currencies, rates, fees, probabilities, and timings are declared fiction. "
    "No live rates, provider data, regulatory judgments, or route recommendations are involved. "
    "Results are deterministic given the declared inputs; sampled scenarios are not a "
    "statistically representative distribution, and no composite score is computed across metrics."
)


def analysis_kind(report: dict[str, Any]) -> str:
    version = report.get("report_version", "")
    known = {
        "corridor-lab.report/v1": "route comparison",
        "corridor-lab.analysis/v1": str(report.get("analysis", "analysis")),
        "corridor-lab.sensitivity/v1": "sensitivity",
        "corridor-lab.transaction-sweep/v1": "transaction sweep",
        "corridor-lab.transaction-grid/v1": "transaction grid",
        "corridor-lab.stress-grid/v1": "stress grid",
        "corridor-lab.pareto/v1": "pareto frontier",
        "corridor-lab.scenario-diff/v1": "scenario diff",
        "corridor-lab.batch/v1": "scenario batch",
        "corridor-lab.project-run/v1": "project experiments",
    }
    return known.get(version, version or "unknown analysis")


def build_evidence(
    report: dict[str, Any],
    *,
    scenario_source: str = "",
    routes_source: str = "",
    project_source: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Assemble the evidence document; the report is embedded verbatim."""
    if not isinstance(report, dict) or "report_version" not in report:
        raise InputError("evidence requires a rendered corridor-lab report")
    document: dict[str, Any] = {
        "evidence_version": EVIDENCE_VERSION,
        "tool": {"name": "corridor-lab", "version": TOOL_VERSION},
        "analysis": analysis_kind(report),
        "report": report,
        "inputs": {
            "scenario": scenario_source or "built-in fictional demo",
            "routes": routes_source or "routes embedded in the scenario",
            "project": project_source or None,
        },
        "limitations": STANDING_LIMITATIONS,
    }
    if notes:
        if len(notes) > 2000:
            raise InputError("evidence notes must be at most 2000 characters")
        document["operator_notes"] = notes
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(text.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise InputError(f"evidence exceeds {MAX_EVIDENCE_BYTES} bytes")
    return document


def evidence_text(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_evidence(path: str | Path, document: dict[str, Any], *, inputs: tuple[Path, ...] = (), scanned_dirs: tuple[Path, ...] = ()) -> Path:
    """Explicitly write an evidence document with input-collision protection."""
    from .canonical import protect_report_output

    target = protect_report_output(path, inputs, scanned_dirs)
    atomic_write_text(target, evidence_text(document), max_bytes=MAX_EVIDENCE_BYTES)
    return target
