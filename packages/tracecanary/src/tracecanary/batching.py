"""Bounded batch execution shared by the CLI and the desktop controller."""
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract
from tracecanary.coverage import coverage_report
from tracecanary.inspection import _parse_minimum_ratio, coverage_gate
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import (
    BatchItem,
    BatchReport,
    Report,
    Status,
    UnsafeReportError,
    Violation,
    build_report,
    ensure_object_values_absent,
)


def _iter_batch_files(root: Path, recursive: bool) -> Iterator[Path]:
    yield from root.rglob("*.json") if recursive else root.glob("*.json")


def run_batch(
    contract: Contract,
    input_dir: Path,
    recursive: bool,
    include_paths: bool,
    baseline: dict[str, Any] | None = None,
    *,
    coverage: bool = False,
    minimum_ratio: str | None = None,
) -> BatchReport:
    """Check or inspect a bounded directory of OTLP/HTTP JSON exports."""
    if minimum_ratio is not None:
        _parse_minimum_ratio(minimum_ratio)
        if not coverage:
            raise InputError("minimum ratio is only supported for coverage batches")
    if coverage and baseline is not None:
        raise InputError("batch coverage does not accept a baseline")
    if baseline is not None and check_trace(contract, baseline)["status"] != "pass":
        raise InputError("batch baseline does not satisfy the contract")
    try:
        if not input_dir.is_dir():
            raise InputError("--input-dir must be a directory")
        root = input_dir.resolve()
        paths: list[Path] = []
        for item in _iter_batch_files(root, recursive):
            if item.is_file() and not item.is_symlink() and item.resolve().is_relative_to(root):
                paths.append(item)
                if len(paths) > contract.max_batch_files:
                    break
        paths.sort(
            key=lambda item: (
                item.relative_to(root).as_posix().casefold(),
                item.relative_to(root).as_posix(),
            ),
        )
    except InputError:
        raise
    except OSError as exc:
        raise InputError("batch input cannot be read") from exc
    if not paths:
        raise InputError("batch input contains no JSON files")
    if len(paths) > contract.max_batch_files:
        raise InputError(f"batch input exceeds the {contract.max_batch_files}-file limit")
    items: list[BatchItem] = []
    for index, path in enumerate(paths, start=1):
        item_id = f"item-{index:04d}"
        relative = path.relative_to(root).as_posix()
        try:
            payload = _load_trace(path, contract)
            if minimum_ratio is not None:
                report = coverage_gate(contract, payload, minimum_ratio)
            else:
                report = coverage_report(contract, payload) if coverage else check_trace(contract, payload, mode="batch") if baseline is None else diff_traces(contract, baseline, payload)
        except UnsafeReportError:
            raise
        except (InputError, OtlpError, ValueError):
            report = build_report(
                contract.contract_version,
                "unresolved",
                [Violation("TC006", "", "input could not be validated")],
                mode="batch",
            )
        item: BatchItem = {"id": item_id, "status": report["status"], "report": report}
        if include_paths:
            item["path"] = relative
        items.append(item)
    statuses = {item["status"] for item in items}
    status: Status = "unresolved" if "unresolved" in statuses else "regression" if "regression" in statuses else "pass"
    batch_report: BatchReport = {"batch_version": "tracecanary.batch/v1", "contract_version": contract.contract_version, "status": status, "items": items}
    if coverage:
        valid = [item["report"]["coverage"] for item in items if "coverage" in item["report"]]
        fields = []
        for index, field in enumerate(contract.required_retained_fields):
            present = sum(item["required_fields"][index]["present"] for item in valid)
            entities = sum(item["required_fields"][index]["entities"] for item in valid)
            fields.append({"id": f"required-{index + 1:04d}", "scope": field.scope,
                           "present": present, "entities": entities,
                           "ratio": str(Fraction(present, entities)) if entities else None})
        batch_report["coverage_summary"] = {"validated_items": len(valid),
                                            "unresolved_items": sum(item["status"] == "unresolved" for item in items),
                                            "excluded_items": len(items) - len(valid),
                                            "required_fields": fields}
        if minimum_ratio is not None:
            batch_report["coverage_summary"]["minimum_ratio_per_file"] = minimum_ratio
    ensure_object_values_absent(
        batch_report,
        tuple(canary.value for canary in contract.canaries),
    )
    return batch_report


def _load_trace(path: Path, contract: Contract) -> dict[str, Any]:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload
