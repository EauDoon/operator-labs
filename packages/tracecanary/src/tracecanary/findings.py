"""Deterministic summary, grouping, filtering, and explanation over reports.

Every function in this module is pure: it takes a report document and returns a
new document, string, or mapping. Nothing here reads files, clocks, environment
variables, or global state, so two calls with the same report always produce the
same result.

The one rule that shapes every function: **filtering and grouping are a view
over a report, never a re-run of the analysis.** Hiding a finding must not turn
a regression into a pass, so :func:`filter_findings` recomputes the summary but
never recomputes or relaxes the status.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from tracecanary.canonical import InputError
from tracecanary.report import (
    BatchItem,
    BatchReport,
    Report,
    ReportMode,
    Status,
    Violation,
    ViolationDict,
    build_report,
    ensure_object_values_absent,
    ensure_text_values_absent,
)


GROUP_KEYS: tuple[str, ...] = ("code", "scope", "category", "key")

# Every code TraceCanary can currently emit. `--filter-code` validates against
# this set so a typo is an actionable error instead of an empty report that
# looks like a pass.
KNOWN_CODES: tuple[str, ...] = (
    "TC001",
    "TC002",
    "TC003",
    "TC004",
    "TC005",
    "TC006",
    "TC010",
    "TC011",
    "TC012",
    "TC013",
    "TC014",
    "TC900",
    "GUI001",
    "GUI002",
    "GUI003",
    "GUI004",
    "GUI005",
    "GUI006",
    "GUI007",
    "GUI008",
    "GUI009",
    "GUI010",
    "GUI011",
)

# Findings that only exist because two traces were compared. Everything else in
# a diff report came from checking the candidate on its own.
_COMPARISON_CODES: tuple[str, ...] = ("TC005", "TC012", "TC013", "TC014")

UNKNOWN_CONTRACT_VERSION = "unknown"

_EXACT_MATCH_NOTE = (
    "canary detection is exact matching of the declared canary values only; "
    "a substring, encoding, hash, reformatting, truncation, or any other "
    "transformation is not covered by this contract"
)
_PATH_NOTE = (
    "`path` pointers are structural and omit values by design; they locate a "
    "finding without echoing trace data"
)
_VALUE_NOTE = (
    "values are never rendered, so no report can tell you which value matched "
    "or how many times a value appeared"
)
_PASS_NOTE = (
    "a pass means this contract found no configured regression in this input; "
    "it is not evidence of safety, redaction correctness, or policy compliance"
)
_UNKNOWN_HEADING = "what remains unknown"

_COMMON_CHECKS: tuple[str, ...] = (
    "every scalar string was compared by exact equality with each declared synthetic canary value",
    "declared forbidden attribute keys and key prefixes were matched against resource, scope, span, event, and link attributes",
    "declared forbidden JSON-pointer path prefixes were evaluated where a matching scalar is populated",
    "every required retained field was checked for presence at its declared scope",
)
_RETENTION_CHECK = (
    "each declared retention requirement was evaluated against the attributes actually present, including value kinds and counts",
)
_VALIDATE_CHECKS: tuple[str, ...] = (
    "the contract was parsed with duplicate-key, size, nesting, field, and version checks",
    "no trace was checked in this run",
)
_DIFF_CHECKS: tuple[str, ...] = (
    "the baseline was required to satisfy the contract before any comparison was made",
)


def summarize(report: Report | BatchReport, *, redacted_values: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a deterministic summary of one report or batch report.

    ``by_scope`` and ``by_category`` count only findings that carry the field,
    because a finding without a scope has no scope to attribute it to.
    """
    violations = list_violations(report)
    status = report_status(report)
    summary: dict[str, Any] = {
        "status": status,
        "total": len(violations),
        "by_code": _counts(violations, "code"),
        "by_scope": _counts(violations, "scope"),
        "by_category": _counts(violations, "category"),
        "by_key": _counts(violations, "key"),
        "unresolved": status == "unresolved",
    }
    ensure_object_values_absent(summary, redacted_values)
    return summary


def group_findings(
    report: Report | BatchReport,
    by: str,
    *,
    redacted_values: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Group findings by one declared key, sorted by group value.

    Findings with no value for the chosen key are collected into the group whose
    value is the empty string, so a group is never silently dropped. An unknown
    ``by`` is rejected rather than grouped by accident.
    """
    if by not in GROUP_KEYS:
        raise InputError(f"group-by must be one of " + ", ".join(GROUP_KEYS))
    buckets: dict[str, list[ViolationDict]] = {}
    for violation in list_violations(report):
        value = violation.get(by)
        key = value if isinstance(value, str) and value else ""
        buckets.setdefault(key, []).append(violation)
    groups: list[dict[str, Any]] = []
    for value in sorted(buckets):
        members = buckets[value]
        groups.append(
            {
                "group": value,
                "count": len(members),
                "codes": sorted({str(item.get("code", "")) for item in members}),
                "messages": sorted({str(item.get("message", "")) for item in members}),
            }
        )
    ensure_object_values_absent(groups, redacted_values)
    return groups


def filter_findings(
    report: Report | BatchReport,
    codes: Iterable[str] | None = None,
    scopes: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
    *,
    redacted_values: tuple[str, ...] = (),
) -> Report | BatchReport:
    """Return a new report holding only the findings that match every selection.

    The summary is recomputed so it always describes the filtered set. The
    status is copied unchanged: hiding a finding is a viewing decision and must
    never turn a regression into a pass. A ``None`` or empty selection applies
    no constraint for that field, so an empty filter is not a way to empty a
    report by accident.
    """
    wanted_codes = _selection(codes, "code")
    wanted_scopes = _selection(scopes, "scope")
    wanted_categories = _selection(categories, "category")

    def keep(violation: ViolationDict) -> bool:
        if wanted_codes is not None and violation.get("code") not in wanted_codes:
            return False
        if wanted_scopes is not None and violation.get("scope") not in wanted_scopes:
            return False
        if wanted_categories is not None and violation.get("category") not in wanted_categories:
            return False
        return True

    if _is_batch(report):
        return _filter_batch(cast(BatchReport, report), keep, redacted_values)
    return _filter_report(cast(Report, report), keep, redacted_values)


def explain(report: Report | BatchReport, *, redacted_values: tuple[str, ...] = ()) -> str:
    """Return a deterministic explanation of what was checked, failed, and is unknown.

    The explanation never contains a matched value. It states the two coverage
    caveats that a reader otherwise cannot see from a report: that canary
    detection is exact matching of declared values only, and that ``path``
    pointers are structural and omit values by design.
    """
    status = report_status(report)
    summary = summarize(report, redacted_values=redacted_values)
    mode = str(report.get("mode", UNKNOWN_CONTRACT_VERSION))
    version = str(report.get("contract_version", UNKNOWN_CONTRACT_VERSION))
    lines = [
        f"TraceCanary explanation: {status.upper()}",
        f"mode: {mode}",
        f"contract version: {version}",
        f"findings: {summary['total']}",
        "",
        "what was checked",
    ]
    lines.extend(f"- {item}" for item in _checked_lines(mode, version))
    lines.append("")
    lines.extend(_failed_lines(report, mode))
    if _is_batch(report):
        lines.append("")
        lines.extend(_batch_lines(cast(BatchReport, report)))
    lines.append("")
    lines.append(_UNKNOWN_HEADING)
    lines.extend(f"- {item}" for item in _unknown_lines(mode))
    text = "\n".join(lines) + "\n"
    ensure_text_values_absent(text, redacted_values)
    return text


def grouped_report(report: Report | BatchReport, groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap grouped findings in the report envelope so the status stays visible."""
    return {
        "contract_version": str(report.get("contract_version", UNKNOWN_CONTRACT_VERSION)),
        "mode": str(report.get("mode", UNKNOWN_CONTRACT_VERSION)),
        "status": report_status(report),
        "summary": _summary_of(report),
        "groups": groups,
    }


def render_summary(report: Report | BatchReport, *, redacted_values: tuple[str, ...] = ()) -> str:
    """Render a human summary panel, which never includes a value."""
    summary = summarize(report, redacted_values=redacted_values)
    lines = [
        f"TraceCanary summary: {str(summary['status']).upper()}",
        f"status: {summary['status']}",
        f"findings: {summary['total']}",
        f"unresolved: {'yes' if summary['unresolved'] else 'no'}",
        _render_counts("by code", cast(dict[str, int], summary["by_code"])),
        _render_counts("by scope", cast(dict[str, int], summary["by_scope"])),
        _render_counts("by category", cast(dict[str, int], summary["by_category"])),
    ]
    text = "\n".join(lines) + "\n"
    ensure_text_values_absent(text, redacted_values)
    return text


def render_groups(groups: list[dict[str, Any]], by: str, *, redacted_values: tuple[str, ...] = ()) -> str:
    """Render grouped findings as deterministic human text."""
    lines = [f"TraceCanary groups by {by} ({len(groups)} group(s))"]
    if not groups:
        lines.append("- no findings to group")
    for group in groups:
        label = group["group"] if group["group"] else "(no value)"
        lines.append(f"- {label}: {group['count']} finding(s)")
        lines.append(f"  codes: {', '.join(group['codes']) or 'none'}")
        lines.append(f"  messages: {' | '.join(group['messages']) or 'none'}")
    text = "\n".join(lines) + "\n"
    ensure_text_values_absent(text, redacted_values)
    return text


def list_violations(report: Report | BatchReport) -> list[ViolationDict]:
    """Return every violation of a report, or of every item of a batch report."""
    if _is_batch(report):
        found: list[ViolationDict] = []
        for item in cast(BatchReport, report).get("items", []):
            found.extend(_violations_of(item.get("report", {})))
        return found
    return _violations_of(cast(Report, report))


def report_status(report: Report | BatchReport) -> str:
    """Return the status of a report, or ``unresolved`` when it is not a status."""
    status = report.get("status")
    if status in ("pass", "regression", "unresolved"):
        return cast(str, status)
    return "unresolved"


def validate_codes(codes: Iterable[str]) -> tuple[str, ...]:
    """Reject any code TraceCanary cannot emit, so a typo cannot look like a filter."""
    result = tuple(codes)
    unknown = [item for item in result if item not in KNOWN_CODES]
    if unknown:
        raise InputError("unknown TraceCanary code " + ", ".join(sorted(unknown)) + "; known codes are " + ", ".join(KNOWN_CODES))
    return result


def _is_batch(report: Report | BatchReport) -> bool:
    return "items" in report


def _violations_of(report: Report) -> list[ViolationDict]:
    return [cast(ViolationDict, item) for item in report.get("violations", [])]


def _summary_of(report: Report | BatchReport) -> dict[str, Any]:
    summary = report.get("summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    return summarize(report)


def _counts(violations: list[ViolationDict], field: str) -> dict[str, int]:
    counter: dict[str, int] = {}
    for violation in violations:
        value = violation.get(field)
        if isinstance(value, str) and value:
            counter[value] = counter.get(value, 0) + 1
    return dict(sorted(counter.items()))


def _selection(values: Iterable[str] | None, field: str) -> frozenset[str] | None:
    """Return the selected values, or None when the field is unconstrained."""
    if values is None:
        return None
    result = frozenset(values)
    if not result:
        return None
    if field == "code":
        validate_codes(sorted(result))
    return result


def _filter_report(report: Report, keep: Any, redacted_values: tuple[str, ...]) -> Report:
    kept = [_as_violation(item) for item in _violations_of(report) if keep(item)]
    return build_report(
        str(report.get("contract_version", UNKNOWN_CONTRACT_VERSION)),
        cast(Status, report_status(report)),
        kept,
        mode=cast(ReportMode, str(report.get("mode", "check"))),
        redacted_values=redacted_values,
    )


def _filter_batch(batch: BatchReport, keep: Any, redacted_values: tuple[str, ...]) -> BatchReport:
    items: list[BatchItem] = []
    for item in batch.get("items", []):
        report = _filter_report(cast(Report, item.get("report", {})), keep, redacted_values)
        filtered: BatchItem = {"id": str(item.get("id", "item")), "status": cast(Status, item.get("status", "unresolved")), "report": report}
        if "path" in item:
            filtered["path"] = str(item["path"])
        items.append(filtered)
    result = dict(batch)
    result["items"] = items
    ensure_object_values_absent(result, redacted_values)
    return cast(BatchReport, result)


def _as_violation(item: ViolationDict) -> Violation:
    return Violation(
        code=str(item.get("code", "")),
        path=str(item.get("path", "")),
        message=str(item.get("message", "")),
        label=item.get("label"),
        category=item.get("category"),
        key=item.get("key"),
        scope=item.get("scope"),
        detail=item.get("detail"),
    )


def _render_counts(label: str, counts: dict[str, int]) -> str:
    if not counts:
        return f"{label}: none"
    return f"{label}: " + "; ".join(f"{key}={count}" for key, count in counts.items())


def _checked_lines(mode: str, version: str) -> tuple[str, ...]:
    if mode == "validate":
        return _VALIDATE_CHECKS
    checks = list(_COMMON_CHECKS)
    if version == "tracecanary/v2":
        checks.extend(_RETENTION_CHECK)
    if mode == "diff":
        checks.extend(_DIFF_CHECKS)
    return tuple(checks)


def _failed_lines(report: Report | BatchReport, mode: str) -> list[str]:
    groups = group_findings(report, "code")
    lines = ["what failed"]
    if not groups:
        lines.append("- no finding was reported by this contract for this input")
        return lines
    for group in groups:
        message = group["messages"][0] if group["messages"] else ""
        lines.append(f"- {group['group']} x{group['count']}: {message}")
    if mode == "diff":
        lines.extend(_diff_contribution_lines(report))
    return lines


def _diff_contribution_lines(report: Report | BatchReport) -> list[str]:
    """State what the baseline and the candidate each contributed to a diff."""
    by_code = summarize(report)["by_code"]
    comparison = sum(int(by_code.get(code, 0)) for code in _COMPARISON_CODES)
    direct = int(summarize(report)["total"]) - comparison
    unresolved = int(by_code.get("TC014", 0))
    lines = [
        "",
        "diff contribution",
        "- baseline: required to satisfy the contract before any comparison; it contributed the reference counts and no findings of its own",
        f"- candidate: contributed {direct} finding(s) from checking the candidate on its own",
        f"- comparison: contributed {comparison - unresolved} baseline-to-candidate finding(s)",
        f"- unresolved comparisons: {unresolved}",
    ]
    if int(by_code.get("TC900", 0)):
        lines.append("- the baseline did not satisfy the contract, so no comparison was made at all")
    return lines


def _batch_lines(batch: BatchReport) -> list[str]:
    statuses = [str(item.get("status", "unresolved")) for item in batch.get("items", [])]
    counts = {status: statuses.count(status) for status in ("pass", "regression", "unresolved")}
    return [
        "batch",
        f"- {len(statuses)} item(s): {counts['pass']} pass, {counts['regression']} regression, {counts['unresolved']} unresolved",
        "- the batch status is the strict aggregation of its items: any unresolved item makes the batch unresolved, otherwise any regression makes it a regression",
    ]


def _unknown_lines(mode: str) -> tuple[str, ...]:
    notes = [_EXACT_MATCH_NOTE, _PATH_NOTE, _VALUE_NOTE]
    if mode == "diff":
        notes.extend(
            (
                "baseline comparison uses counts of contract-declared fields; it does not establish semantic equivalence of arbitrary spans or attributes",
                "a matched ratio is compared only for identities present in both traces, so a population that disappears entirely is unresolved rather than a regression",
            )
        )
    if mode in ("batch", "batch-diff"):
        notes.append("each item is checked on its own; a batch result is never a statement about files that were not paired or loaded")
    notes.append(_PASS_NOTE)
    return tuple(notes)
