"""Command-line interface for TraceCanary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract
from tracecanary.coverage import coverage_report
from tracecanary.fixture import write_bundle
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
from tracecanary.output import protect_inputs, write_report
from tracecanary.report import (
    BatchItem,
    BatchReport,
    Report,
    Status,
    UnsafeReportError,
    Violation,
    build_report,
    ensure_object_values_absent,
    ensure_text_values_absent,
    ensure_values_absent,
    render_human,
    render_json,
    render_junit,
    render_sarif,
)

EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_UNRESOLVED = 2

_EXIT_STATUS_HELP = (
    "Exit status:\n"
    "  0  contract satisfied\n"
    "  1  privacy or retention regression detected\n"
    "  2  invalid input, unsupported version, or unresolved comparison\n"
    "\n"
    "Reports never include matched canary values."
)


class _ArgumentParser(argparse.ArgumentParser):
    """Reject unknown flags closed and return usage errors through main()."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise InputError(message)


def _cli_path(value: str) -> Path:
    """Parse a CLI path without treating an empty string as the working directory."""
    if not value.strip():
        raise argparse.ArgumentTypeError("path must not be empty")
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="tracecanary",
        description="Check synthetic canaries in OTLP/HTTP JSON traces.",
        epilog=_EXIT_STATUS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    validate = commands.add_parser("validate", help="validate a TraceCanary contract")
    validate.add_argument("contract", type=_cli_path, help="TraceCanary contract JSON file")
    validate.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    inspect = commands.add_parser("inspect-contract", help="inspect value-free check inventory and direct conflicts")
    inspect.add_argument("contract", type=_cli_path)
    inspect.add_argument("--format", choices=("human", "json"), default="human")
    check = commands.add_parser("check", help="check one OTLP trace export")
    check.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    check.add_argument("--input", required=True, type=_cli_path, help="OTLP/HTTP JSON trace export")
    check.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    control = commands.add_parser("control-check", help="verify every canary occurs in an unsanitized synthetic positive control")
    control.add_argument("--contract", required=True, type=_cli_path)
    control.add_argument("--input", required=True, type=_cli_path)
    control.add_argument("--format", choices=("human", "json"), default="human")
    population = commands.add_parser("population-gate", help="require an explicit minimum entity population")
    population.add_argument("--contract", required=True, type=_cli_path)
    population.add_argument("--input", required=True, type=_cli_path)
    population.add_argument("--scope", required=True, choices=("resource", "scope", "span", "event", "link"))
    population.add_argument("--minimum", required=True, type=int)
    population.add_argument("--format", choices=("human", "json"), default="human")
    dropped = commands.add_parser("dropped-telemetry", help="inspect declared dropped counters and optionally require zero")
    dropped.add_argument("--contract", required=True, type=_cli_path)
    dropped.add_argument("--input", required=True, type=_cli_path)
    dropped.add_argument("--require-zero", action="store_true")
    dropped.add_argument("--format", choices=("human", "json"), default="human")
    coverage = commands.add_parser("coverage", help="show value-free entity and required-field coverage")
    coverage.add_argument("--contract", required=True, type=_cli_path)
    coverage.add_argument("--input", required=True, type=_cli_path)
    coverage.add_argument("--format", choices=("human", "json"), default="human")
    matrix = commands.add_parser("retention-matrix", help="locate missing retained fields by safe entity pointer")
    matrix.add_argument("--contract", required=True, type=_cli_path)
    matrix.add_argument("--input", required=True, type=_cli_path)
    matrix.add_argument("--format", choices=("human", "json"), default="human")
    gate = commands.add_parser("coverage-gate", help="require an explicit per-entity retained-field ratio")
    gate.add_argument("--contract", required=True, type=_cli_path)
    gate.add_argument("--input", required=True, type=_cli_path)
    gate.add_argument("--minimum-ratio", required=True)
    gate.add_argument("--format", choices=("human", "json"), default="human")
    rate_diff = commands.add_parser("coverage-diff", help="compare exact retained-field rates across populations")
    rate_diff.add_argument("--contract", required=True, type=_cli_path)
    rate_diff.add_argument("--baseline", required=True, type=_cli_path)
    rate_diff.add_argument("--candidate", required=True, type=_cli_path)
    rate_diff.add_argument("--format", choices=("human", "json"), default="human")
    diff = commands.add_parser("diff", help="compare a baseline and a candidate OTLP trace export")
    diff.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    diff.add_argument("--baseline", required=True, type=_cli_path, help="baseline OTLP/HTTP JSON trace export")
    diff.add_argument("--candidate", required=True, type=_cli_path, help="candidate OTLP/HTTP JSON trace export")
    diff.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    batch = commands.add_parser("batch", help="check a bounded directory of OTLP trace exports")
    batch.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    batch.add_argument(
        "--input-dir",
        required=True,
        type=_cli_path,
        help="directory of OTLP/HTTP JSON trace exports (bounded by contract limits.max_batch_files, default 256)",
    )
    batch.add_argument("--baseline", type=_cli_path, help="compare every candidate with this passing synthetic baseline")
    batch.add_argument("--recursive", action="store_true", help="include *.json files in subdirectories")
    batch.add_argument("--include-paths", action="store_true", help="include input-relative POSIX paths in reports")
    batch.add_argument("--format", choices=("human", "json", "sarif", "junit"), default="json", help="report format (default: json)")
    batch_coverage = commands.add_parser("coverage-batch", help="aggregate coverage counts across a bounded directory")
    batch_coverage.add_argument("--contract", required=True, type=_cli_path)
    batch_coverage.add_argument("--input-dir", required=True, type=_cli_path)
    batch_coverage.add_argument("--recursive", action="store_true")
    batch_coverage.add_argument("--include-paths", action="store_true")
    batch_coverage.add_argument("--format", choices=("human", "json"), default="json")
    for command in (validate, check, diff, batch, coverage, inspect, gate, rate_diff, matrix, batch_coverage, control, population, dropped):
        command.add_argument("--output", type=_cli_path, help="write a UTF-8 report atomically; cannot replace inputs")
    fixture = commands.add_parser("fixture", help="write synthetic fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True, parser_class=_ArgumentParser)
    create = fixture_commands.add_parser("create", help="write the synthetic fixture bundle")
    create.add_argument("--output", required=True, type=_cli_path, help="empty directory for the synthetic fixture bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "fixture":
            write_bundle(args.output)
            print(f"Synthetic fixture bundle created at {args.output}")
            return EXIT_PASS
        protect_inputs(args.output, [getattr(args, name) for name in ("contract", "input", "baseline", "candidate") if getattr(args, name, None) is not None], getattr(args, "input_dir", None))
        contract = load_contract(args.contract)
        if args.command == "validate":
            report = build_report(contract.contract_version, "pass", [], mode="validate")
            ensure_values_absent(report, tuple(canary.value for canary in contract.canaries))
            _print(report, args.format, args.output)
            return EXIT_PASS
        if args.command == "inspect-contract":
            report = inspect_contract(contract)
        elif args.command == "control-check":
            report = control_check(contract, _load_trace(args.input, contract))
        elif args.command == "population-gate":
            report = population_gate(contract, _load_trace(args.input, contract), args.scope, args.minimum)
        elif args.command == "dropped-telemetry":
            report = dropped_telemetry(contract, _load_trace(args.input, contract), require_zero=args.require_zero)
        elif args.command == "coverage":
            report = coverage_report(contract, _load_trace(args.input, contract))
        elif args.command == "retention-matrix":
            report = retention_matrix(contract, _load_trace(args.input, contract))
        elif args.command == "coverage-gate":
            report = coverage_gate(contract, _load_trace(args.input, contract), args.minimum_ratio)
        elif args.command == "check":
            report = check_trace(contract, _load_trace(args.input, contract), mode="check")
        elif args.command == "coverage-diff":
            report = coverage_diff(contract, _load_trace(args.baseline, contract), _load_trace(args.candidate, contract))
        elif args.command == "diff":
            report = diff_traces(contract, _load_trace(args.baseline, contract), _load_trace(args.candidate, contract))
            _print(report, args.format, args.output)
            return _status_exit(report["status"])
        else:
            baseline = _load_trace(args.baseline, contract) if getattr(args, "baseline", None) is not None else None
            batch_report = _run_batch(contract, args.input_dir, args.recursive, args.include_paths, baseline, coverage=args.command == "coverage-batch")
            _print_batch(
                batch_report,
                args.format,
                tuple(canary.value for canary in contract.canaries),
                args.output,
            )
            return _status_exit(batch_report["status"])
        _print(report, args.format, args.output)
        return _status_exit(report["status"])
    except SystemExit as exc:
        return EXIT_PASS if exc.code in (0, None) else EXIT_UNRESOLVED
    except UnsafeReportError:
        return EXIT_UNRESOLVED
    except (ContractError, InputError, OtlpError, ValueError) as exc:
        print(f"TraceCanary: UNRESOLVED: {exc}", file=sys.stderr)
        return EXIT_UNRESOLVED
    except OSError:
        print("TraceCanary: UNRESOLVED: input or output could not be accessed", file=sys.stderr)
        return EXIT_UNRESOLVED


def _load_trace(path: Path, contract: Contract) -> dict[str, Any]:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


def _run_batch(contract: Contract, input_dir: Path, recursive: bool, include_paths: bool, baseline: dict[str, Any] | None = None, *, coverage: bool = False) -> BatchReport:
    if coverage and baseline is not None:
        raise InputError("batch coverage does not accept a baseline")
    if baseline is not None and check_trace(contract, baseline)["status"] != "pass":
        raise InputError("batch baseline does not satisfy the contract")
    try:
        if not input_dir.is_dir():
            raise InputError("--input-dir must be a directory")
        root = input_dir.resolve()
        iterator = root.rglob("*.json") if recursive else root.glob("*.json")
        paths: list[Path] = []
        for item in iterator:
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
        batch_report["coverage_summary"] = {"validated_items": len(valid), "unresolved_items": len(items) - len(valid),
                                             "required_fields": fields}
    ensure_object_values_absent(
        batch_report,
        tuple(canary.value for canary in contract.canaries),
    )
    return batch_report


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="")
    else:
        write_report(output, text)


def _print(report: Report, output_format: str, output: Path | None = None) -> None:
    _emit(render_json(report) if output_format == "json" else render_human(report), output)


def _print_batch(report: BatchReport, output_format: str, redacted_values: tuple[str, ...], output_path: Path | None = None) -> None:
    if output_format == "json":
        output = render_json(report)
    elif output_format == "sarif":
        output = render_sarif(report)
    elif output_format == "junit":
        output = render_junit(report)
    else:
        lines = [f"TraceCanary batch: {report['status'].upper()} ({len(report['items'])} file(s))"]
        lines.extend(f"- {item['id']}: {item['status']}" for item in report["items"])
        if "coverage_summary" in report:
            summary = report["coverage_summary"]
            lines.append(f"Coverage: {summary['validated_items']} validated item(s); {summary['unresolved_items']} unresolved item(s) excluded.")
            lines.extend(f"{field['id']}: {field['present']}/{field['entities']} ({field['ratio']})" for field in summary["required_fields"])
        output = "\n".join(lines) + "\n"
    ensure_text_values_absent(output, redacted_values)
    _emit(output, output_path)


def _status_exit(status: Status) -> int:
    return EXIT_PASS if status == "pass" else EXIT_REGRESSION if status == "regression" else EXIT_UNRESOLVED
