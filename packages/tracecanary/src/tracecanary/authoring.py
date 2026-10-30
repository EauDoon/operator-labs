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

import functools
import json
import re
import tempfile
from pathlib import Path
from typing import Any, get_args

from tracecanary.contract import DEFAULT_MAX_BATCH_FILES, ContractError, parse_contract
from tracecanary.report import (
    BatchReport,
    Report,
    ReportMode,
    Status,
    build_report,
    ensure_object_values_absent,
    render_batch_human,
    render_human,
    render_json,
    render_junit,
    render_sarif,
)

REVIEW_VERSION = "tracecanary.contract-review/v1"
MAX_PATH_SEGMENTS = 32
_SEGMENT = re.compile(r"(?:\*|[^*/]+)")
# These JSON keys are arrays in the supported OTLP shape. The checker records
# an index there, so a literal next segment can never reach a scalar.
_ARRAY_FIELDS = {"resourceSpans", "scopeSpans", "spans", "attributes", "events", "links", "values"}
_ARRAY_STEP = re.compile(r"\*|0|[1-9][0-9]*")
# Every report mode, enumerated from the ReportMode literal; a drift test
# checks that every mode the source assigns is listed there.
_VOCABULARY_MODES: tuple[str, ...] = get_args(ReportMode)
_VOCABULARY_STATUSES: tuple[Status, ...] = ("pass", "regression", "unresolved")
# Every value-free finding code a report can carry; a drift test checks the
# source against this list.
REPORT_CODES = (
    "TC000", "TC001", "TC002", "TC003", "TC004", "TC005", "TC006",
    "TC010", "TC011", "TC012", "TC013", "TC014", "TC900", "TC901", "TC902",
    "GUI001", "GUI002", "GUI003", "GUI004", "GUI005", "GUI006", "GUI007", "GUI008",
)
# Per-report identifiers whose numbering depends on the draft; they are
# generated per draft by _structural_identifiers instead of being cached.
_STRUCTURAL_ID = re.compile(r"(?:required|item|candidate)-[0-9]{4}")
_MAX_CAMPAIGN_CANDIDATES = 3


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


@functools.lru_cache(maxsize=1)
def _report_vocabulary() -> str:
    """TraceCanary's own fixed report wording, rendered by the real renderers.

    Two sources feed it. Value-free skeletons cover every report mode and
    status. Real reports with findings come from running every checker over
    the built-in synthetic fixture bundle: check on every fixture, diff,
    coverage, coverage-gate, coverage-diff, retention-matrix, control-check,
    population-gate, dropped-telemetry, inspect-contract, batch in all four
    formats, campaigns as JSON and human text, the summary, the comparison
    with and without the gate, the evidence document, and a review with
    findings. The bundle contract's own labels, categories, keys, prefixes
    and path prefixes are then removed, because they are that contract's
    configuration rather than TraceCanary's wording, as are identifiers
    numbered per draft (see ``_structural_identifiers``); the value-free
    finding codes are added. The fixture canary values never reach any
    report, so building this can never fail closed.
    """
    from tracecanary.campaign import render_campaign_human

    parts: list[str] = list(REPORT_CODES)
    for status in _VOCABULARY_STATUSES:
        for mode in _VOCABULARY_MODES:
            report = build_report("tracecanary/v1", status, [], mode=mode)
            parts.extend((render_human(report), render_json(report)))
        batch: BatchReport = {"batch_version": "tracecanary.batch/v1", "contract_version": "tracecanary/v1",
                              "status": status, "items": []}
        parts.extend((render_batch_human(batch), render_json(batch), render_sarif(batch), render_junit(batch)))
        campaign = {
            "status": status,
            "contract_version": "tracecanary/v1",
            "phases": {name: {"status": status} for name in ("contract", "control", "baseline", "candidates", "batch", "population_gate")},
            "summary": {"finding_counts": {}},
        }
        parts.append(render_campaign_human(campaign))
        review = build_report("tracecanary/v1", status, [], mode="contract-review")
        review["review"] = {"findings": [], "counts": {}}  # type: ignore[typeddict-unknown-key]
        parts.extend((render_review_human(review), render_json(review)))
    fixture_text, configuration = _fixture_report_text()
    parts.append(fixture_text)
    text = "\n".join(parts)
    # A canary value cannot contain a newline, so a newline separator never
    # joins two fragments into a new match.
    for token in sorted(configuration, key=len, reverse=True):
        text = text.replace(token, "\n")
    return _STRUCTURAL_ID.sub("\n", text)


def _fixture_report_text() -> tuple[str, set[str]]:
    """Render real reports with findings over the built-in fixture bundle.

    Returns the rendered text and the bundle contract's own configuration
    strings, which the caller removes from the vocabulary.
    """
    from tracecanary.batching import run_batch
    from tracecanary.campaign import (
        campaign_evidence,
        campaign_summary,
        compare_summaries,
        render_campaign_human,
        render_comparison_human,
        run_campaign,
    )
    from tracecanary.checker import check_trace
    from tracecanary.comparison import diff_traces
    from tracecanary.coverage import coverage_report
    from tracecanary.fixture import bundle
    from tracecanary.inspection import (
        control_check,
        coverage_diff,
        coverage_gate,
        dropped_telemetry,
        inspect_contract,
        population_gate,
        retention_matrix,
    )
    from tracecanary.otlp import OtlpError, validate_trace

    files = bundle()
    raw_contract = files["contract.json"]
    contract = parse_contract(raw_contract)
    configuration: set[str] = set()
    for canary in raw_contract["canaries"]:
        configuration.update((canary["label"], canary["category"]))
    for key in ("forbidden_attribute_keys", "forbidden_attribute_key_prefixes", "forbidden_path_prefixes"):
        configuration.update(raw_contract.get(key, []))
    configuration.update(field["key"] for field in raw_contract["required_retained_fields"])

    payloads: dict[str, dict[str, Any]] = {}
    for name, payload in files.items():
        if name == "contract.json":
            continue
        try:
            validate_trace(payload)
        except (OtlpError, ValueError):
            continue
        payloads[name] = payload
    safe = payloads["safe-export.json"]
    parts: list[str] = []

    def add(report: Any) -> None:
        parts.append(render_json(report))
        if isinstance(report, dict) and "violations" in report and "items" not in report:
            parts.append(render_human(report))

    add(inspect_contract(contract))
    for payload in payloads.values():
        add(check_trace(contract, payload, mode="check"))
        add(diff_traces(contract, safe, payload))
        add(coverage_report(contract, payload))
        add(coverage_gate(contract, payload, "1"))
        add(coverage_diff(contract, safe, payload))
        add(retention_matrix(contract, payload))
        add(control_check(contract, payload))
        add(population_gate(contract, payload, "span", 1_000_000))
        add(dropped_telemetry(contract, payload, require_zero=True))

    with tempfile.TemporaryDirectory(prefix="tracecanary-vocabulary-") as temporary:
        exports = Path(temporary)
        for index, name in enumerate(sorted(files)):
            if name != "contract.json":
                (exports / f"e{index}.json").write_text(json.dumps(files[name]), encoding="utf-8")
        batches = (
            run_batch(contract, exports, False, False),
            run_batch(contract, exports, False, False, safe),
            run_batch(contract, exports, False, False, coverage=True, minimum_ratio="1",
                      population_scope="span", population_minimum=1_000_000),
        )
        for batch in batches:
            parts.extend((render_batch_human(batch), render_json(batch), render_sarif(batch), render_junit(batch)))
        candidates = [("candidate", exports / f"e{sorted(files).index(name)}.json")
                      for name in ("leaked-prompt.json", "missing-operational-fields.json", "invalid-export.json")]
        campaigns = (
            run_campaign(contract, control_payload=payloads["positive-control.json"], baseline_payload=safe,
                         candidates=candidates, batch=exports, batch_minimum_ratio="1",
                         population_scope="span", population_minimum=1_000_000),
            run_campaign(contract, baseline_payload=payloads["leaked-prompt.json"], candidates=candidates,
                         minimum_ratio="1"),
            run_campaign(contract, candidates=candidates[:1]),
            run_campaign(contract, baseline_payload=safe, candidates=[
                ("candidate", exports / f"e{sorted(files).index('safe-export.json')}.json")]),
            run_campaign(contract, baseline_payload=safe, candidates=candidates),
        )
    for campaign in campaigns:
        parts.extend((render_json(campaign), render_campaign_human(campaign), render_json(campaign_summary(campaign)),
                      render_json(campaign_evidence(campaign))))
    summaries = [campaign_summary(campaign) for campaign in campaigns]
    # Campaigns 3 and 4 share one configuration, so their summaries compare.
    for before, after in ((summaries[3], summaries[4]), (summaries[4], summaries[3]), (summaries[3], summaries[3])):
        for gate in (False, True):
            comparison = compare_summaries(before, after, gate=gate)
            parts.extend((render_json(comparison), render_comparison_human(comparison)))
    draft = _review_findings_draft(raw_contract)
    review = review_contract(draft, _with_vocabulary=False)
    parts.extend((render_json(review), render_review_human(review)))
    configuration.update(draft["forbidden_attribute_keys"] + draft["forbidden_path_prefixes"])
    return "\n".join(parts), configuration


def _review_findings_draft(raw_contract: dict[str, Any]) -> dict[str, Any]:
    """The fixture contract altered to raise every kind of review finding."""
    draft = json.loads(json.dumps(raw_contract))
    draft["required_retained_fields"].append({"scope": "span", "key": "enduser.id"})
    draft["forbidden_attribute_keys"].append("enduser.id")
    draft["forbidden_path_prefixes"].extend(["/resourceSpans/*/scopeSpans", "/resourceSpans/name/value"])
    return draft


def _structural_identifiers(raw: dict[str, Any]) -> str:
    """Report identifiers whose numbering depends on this draft, one per line.

    required-NNNN runs to the draft's required-field count, item-NNNN to its
    batch file limit, and candidate-NNNN to the most candidates a campaign
    names. They are generated per draft because they cannot be cached.
    """
    required = raw.get("required_retained_fields", [])
    limits = raw.get("limits", {}) if isinstance(raw.get("limits", {}), dict) else {}
    max_files = limits.get("max_batch_files", DEFAULT_MAX_BATCH_FILES)
    if type(max_files) is not int:
        max_files = DEFAULT_MAX_BATCH_FILES
    identifiers = [f"required-{index:04d}" for index in range(1, len(required) + 1)]
    identifiers.extend(f"item-{index:04d}" for index in range(1, max_files + 1))
    identifiers.extend(f"candidate-{index:04d}" for index in range(1, _MAX_CAMPAIGN_CANDIDATES + 1))
    return "\n".join(identifiers)


def draft_canary_values(raw: Any) -> tuple[str, ...]:
    """The protected canary values a contract draft declares.

    Callers check every rendering of a review against these values, so a
    review whose own text would contain one is withheld rather than printed.
    """
    canaries = raw.get("canaries", []) if isinstance(raw, dict) else []
    if not isinstance(canaries, list):
        return ()
    return tuple(str(canary.get("value", "")) for canary in canaries if isinstance(canary, dict))


def review_contract(raw: Any, *, _with_vocabulary: bool = True) -> Report:
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
        # Locations elsewhere in this review are 1-based rule ordinals.
        # list.index is 0-based, so the second key was reported as the first.
        ordinal = forbidden_keys.index(key) + 1
        add("ineffective", f"forbidden_attribute_keys[{ordinal}]",
            f"another forbidden prefix already covers {key!r}",
            "keep the broader prefix rule and drop the redundant exact key")

    # 5. Canary configuration is validated strictly by the runtime validator
    #    (unique non-empty labels and values, required-field uniqueness, JSON
    #    pointer shape); diagnostics only cover what it does not catch.
    #    A canary that occurs in TraceCanary's own report wording makes every
    #    report containing that wording fail closed with no output, so flag it
    #    here, before any run. The value itself is never echoed.
    if _with_vocabulary:
        vocabulary = _report_vocabulary() + "\n" + _structural_identifiers(raw)
    else:
        vocabulary = ""
    for index, value in enumerate(draft_canary_values(raw), start=1):
        if value and value in vocabulary:
            add("conflict", f"canaries[{index}]",
                "this canary value occurs in TraceCanary report text, so reports containing that text are withheld (exit 2, no output)",
                "use a unique synthetic value such as TCANARY_<random hex>")

    severity_order = {"conflict": 0, "malformed": 1, "ineffective": 2}
    findings.sort(key=lambda item: (severity_order[item["severity"]], item["location"]))
    status: Status = "regression" if findings else "pass"
    report = build_report(raw.get("contract_version", "tracecanary/v1"), status, [], mode="contract-review")
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    report["review"] = {"findings": findings, "counts": counts}
    ensure_object_values_absent(report, draft_canary_values(raw))
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
    # A single trailing slash is an empty segment. endswith("//") missed it,
    # and pointer_matches then never reached the scalar the prefix named.
    if "//" in prefix or prefix.endswith("/"):
        return "path prefixes must not contain empty segments"
    segments = prefix.strip("/").split("/")
    if len(segments) > MAX_PATH_SEGMENTS:
        return f"path prefixes are limited to {MAX_PATH_SEGMENTS} segments"
    for segment in segments:
        if segment != "*" and ("/" in segment or "*" in segment):
            return "only whole segments may be '*'; partial wildcards can never match"
    for index, segment in enumerate(segments[:-1]):
        if segment in _ARRAY_FIELDS and _ARRAY_STEP.fullmatch(segments[index + 1]) is None:
            return "an array field must be followed by '*' or an index; a literal next segment can never match a scalar"
    return None
