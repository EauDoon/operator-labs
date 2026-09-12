"""Bounded baseline/candidate batch pairing with explicit pairing rules.

Pairing is never guessed. Two rules exist and both are declared by the caller:

``filename`` (default)
    Pair by directory-relative POSIX path. The two relative name sets must be
    identical. A name present on only one side, or two names on one side that
    differ only by case, is an unresolved pairing error.

``order``
    Pair the i-th baseline with the i-th candidate in the documented sort order
    (relative POSIX path casefolded, then exact). The two directories must
    contain the same number of files.

Both rules fail closed: a missing, extra, duplicate, unreadable, or invalid pair
makes the whole batch unresolved, because a pair that cannot be compared must
never look like a pass. Host paths are never echoed: only directory-relative
POSIX names are reported, and only when the caller asks for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from tracecanary.canonical import InputError, load_json
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import (
    BatchItem,
    BatchReport,
    Report,
    ReportMode,
    Status,
    UnsafeReportError,
    Violation,
    build_report,
    ensure_object_values_absent,
    ensure_text_values_absent,
)


BATCH_VERSION = "tracecanary.batch/v1"
BATCH_DIFF_VERSION = "tracecanary.batch-diff/v1"
PAIRING_MODES: tuple[str, ...] = ("filename", "order")
DEFAULT_PAIRING = "filename"


class PairItem(BatchItem):
    """One paired diff, optionally carrying its directory-relative names."""

    pairing: NotRequired[str]
    baseline_name: NotRequired[str]
    candidate_name: NotRequired[str]


class BatchDiffReport(TypedDict):
    """A batch diff report. It is structurally a batch report, so the existing
    SARIF and JUnit renderers accept it unchanged."""

    batch_version: str
    contract_version: str
    status: Status
    pairing: str
    items: list[PairItem]


@dataclass(frozen=True)
class Pairing:
    """One baseline/candidate pair produced by an explicit pairing rule."""

    identifier: str
    baseline: Path
    candidate: Path
    baseline_name: str
    candidate_name: str


def batch_diff(
    contract: Contract,
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    pairing: str = DEFAULT_PAIRING,
    recursive: bool = False,
    include_paths: bool = False,
    redacted_values: tuple[str, ...] = (),
) -> BatchDiffReport:
    """Diff paired baseline and candidate traces from two directories.

    Raises :class:`InputError` for every pairing shape that cannot be resolved,
    and :class:`UnsafeReportError` if an output would carry a protected value.
    """
    if pairing not in PAIRING_MODES:
        raise InputError("--pairing must be one of " + ", ".join(PAIRING_MODES))
    for label, directory in (("baseline", baseline_dir), ("candidate", candidate_dir)):
        if not directory.is_dir():
            raise InputError(f"{label}-dir must be a directory")
    baseline = _discover(contract, baseline_dir, recursive, "baseline")
    candidate = _discover(contract, candidate_dir, recursive, "candidate")
    pairs = _pair(pairing, baseline, candidate, include_paths)
    values = tuple(dict.fromkeys((*redacted_values, *(canary.value for canary in contract.canaries))))
    items: list[PairItem] = []
    for pair in pairs:
        report = _diff_pair(contract, pair)
        item: PairItem = {"id": pair.identifier, "status": report["status"], "report": report, "pairing": pairing}
        if include_paths:
            # Only the directory-relative POSIX name is echoed, never a host path.
            item["path"] = pair.candidate_name
            item["baseline_name"] = pair.baseline_name
            item["candidate_name"] = pair.candidate_name
        items.append(item)
    report_batch: BatchDiffReport = {
        "batch_version": BATCH_DIFF_VERSION,
        "contract_version": contract.contract_version,
        "status": _status(items),
        "pairing": pairing,
        "items": items,
    }
    ensure_object_values_absent(report_batch, values)
    return report_batch


def render_batch_human(batch: BatchReport, *, redacted_values: tuple[str, ...] = ()) -> str:
    """Render a deterministic human batch summary without host paths.

    The same renderer serves the single-directory batch and the paired diff, so
    both read the same way and both omit host paths.
    """
    items = batch.get("items", [])
    label, unit = ("batch", "file") if batch.get("batch_version") == BATCH_VERSION else ("batch-diff", "pair")
    headline = f"TraceCanary {label}: {str(batch.get('status', 'unresolved')).upper()} ({len(items)} {unit}(s)"
    pairing = batch.get("pairing") if "pairing" in batch else None
    headline += f", pairing={pairing})" if pairing else ")"
    lines = [headline]
    for item in items:
        line = f"- {item.get('id', 'item')}: {item.get('status', 'unresolved')}"
        if "baseline_name" in item and "candidate_name" in item:
            line += f" [{item['baseline_name']} -> {item['candidate_name']}]"
        lines.append(line)
    text = "\n".join(lines) + "\n"
    ensure_text_values_absent(text, redacted_values)
    return text


def _status(items: list[PairItem]) -> Status:
    """Aggregate strictly: an unresolved pair outranks any regression."""
    statuses = {item["status"] for item in items}
    if "unresolved" in statuses or not items:
        return "unresolved"
    return "regression" if "regression" in statuses else "pass"


def _discover(contract: Contract, directory: Path, recursive: bool, side: str) -> list[tuple[str, Path]]:
    """List JSON files under a directory in the documented deterministic order."""
    try:
        root = directory.resolve()
        iterator = root.rglob("*.json") if recursive else root.glob("*.json")
        found: list[tuple[str, Path]] = []
        for path in iterator:
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            found.append((path.relative_to(root).as_posix(), path))
            if len(found) > contract.max_batch_files:
                break
    except OSError as exc:
        raise InputError(f"{side} directory cannot be read") from exc
    if not found:
        raise InputError(f"{side} directory contains no JSON files")
    if len(found) > contract.max_batch_files:
        raise InputError(f"{side} directory exceeds the {contract.max_batch_files}-file limit")
    found.sort()
    return found


def _pair(pairing: str, baseline: list[tuple[str, Path]], candidate: list[tuple[str, Path]], include_paths: bool) -> list[Pairing]:
    if pairing == "filename":
        return _pair_by_name(baseline, candidate, include_paths)
    return _pair_by_order(baseline, candidate)


def _pair_by_name(baseline: list[tuple[str, Path]], candidate: list[tuple[str, Path]], include_paths: bool) -> list[Pairing]:
    """Pair by relative POSIX name, requiring the two name sets to be identical."""
    baseline_map = _by_name(baseline, "baseline")
    candidate_map = _by_name(candidate, "candidate")
    missing_candidate = [name for name, _ in baseline if name not in candidate_map]
    missing_baseline = [name for name, _ in candidate if name not in baseline_map]
    if missing_candidate or missing_baseline:
        raise InputError("batch-diff pairing is unresolved: " + _missing_detail(missing_candidate, missing_baseline, include_paths))
    return [
        Pairing(f"pair-{index:04d}", baseline_map[name], candidate_map[name], name, name)
        for index, (name, _) in enumerate(baseline, start=1)
    ]


def _pair_by_order(baseline: list[tuple[str, Path]], candidate: list[tuple[str, Path]]) -> list[Pairing]:
    """Pair the i-th baseline with the i-th candidate in the documented sort order."""
    if len(baseline) != len(candidate):
        raise InputError(
            f"batch-diff pairing is unresolved: order pairing requires the same number of files in both directories; "
            f"the baseline directory provides {len(baseline)} and the candidate directory provides {len(candidate)}"
        )
    return [
        Pairing(
            f"pair-{index:04d}",
            baseline_path,
            candidate_path,
            baseline_name,
            candidate_name,
        )
        for index, ((baseline_name, baseline_path), (candidate_name, candidate_path)) in enumerate(zip(baseline, candidate), start=1)
    ]


def _by_name(entries: list[tuple[str, Path]], side: str) -> dict[str, Path]:
    """Index entries by relative name, rejecting any ambiguity."""
    by_name: dict[str, Path] = {}
    folded: dict[str, str] = {}
    for name, path in entries:
        if name in by_name:
            raise InputError(f"batch-diff pairing is ambiguous: the {side} directory contains the relative name more than once")
        key = name.casefold()
        if key in folded:
            raise InputError(
                f"batch-diff pairing is ambiguous: the {side} directory contains relative names that differ only by case, "
                "so they cannot be paired by name deterministically"
            )
        folded[key] = name
        by_name[name] = path
    return by_name


def _missing_detail(missing_candidate: list[str], missing_baseline: list[str], include_paths: bool) -> str:
    """Name the side that is missing a pair, and the names only when asked."""
    parts: list[str] = []
    if missing_candidate:
        parts.append(f"{len(missing_candidate)} file(s) are present only in the baseline directory, so the candidate side is missing")
        if include_paths:
            parts.append("baseline-only names: " + ", ".join(missing_candidate))
    if missing_baseline:
        parts.append(f"{len(missing_baseline)} file(s) are present only in the candidate directory, so the baseline side is missing")
        if include_paths:
            parts.append("candidate-only names: " + ", ".join(missing_baseline))
    return "; ".join(parts)


def _diff_pair(contract: Contract, pair: Pairing) -> Report:
    """Diff one pair, reporting an unresolved item when either side cannot be read."""
    try:
        baseline = _load_trace(contract, pair.baseline)
        candidate = _load_trace(contract, pair.candidate)
    except (InputError, OtlpError, ValueError):
        return _unresolved(contract, "the baseline or candidate input of this pair could not be loaded and validated")
    try:
        return diff_traces(contract, baseline, candidate)
    except UnsafeReportError:
        raise
    except (InputError, OtlpError, ValueError):
        return _unresolved(contract, "this pair could not be compared")


def _load_trace(contract: Contract, path: Path) -> dict[str, Any]:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


def _unresolved(contract: Contract, message: str) -> Report:
    """Build an unresolved pair report, which can never be mistaken for a pass."""
    return build_report(
        contract.contract_version,
        "unresolved",
        [Violation("TC006", "", message)],
        mode=cast(ReportMode, "batch"),
        redacted_values=tuple(canary.value for canary in contract.canaries),
    )
