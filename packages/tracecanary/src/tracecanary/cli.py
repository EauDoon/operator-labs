"""Command-line interface for TraceCanary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract
from tracecanary.fixture import write_bundle
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
    check = commands.add_parser("check", help="check one OTLP trace export")
    check.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    check.add_argument("--input", required=True, type=_cli_path, help="OTLP/HTTP JSON trace export")
    check.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
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
    batch.add_argument("--recursive", action="store_true", help="include *.json files in subdirectories")
    batch.add_argument("--include-paths", action="store_true", help="include input-relative POSIX paths in reports")
    batch.add_argument("--format", choices=("human", "json", "sarif", "junit"), default="json", help="report format (default: json)")
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
        contract = load_contract(args.contract)
        if args.command == "validate":
            report = build_report(contract.contract_version, "pass", [], mode="validate")
            ensure_values_absent(report, tuple(canary.value for canary in contract.canaries))
            _print(report, args.format)
            return EXIT_PASS
        if args.command == "check":
            report = check_trace(contract, _load_trace(args.input, contract), mode="check")
        elif args.command == "diff":
            report = diff_traces(contract, _load_trace(args.baseline, contract), _load_trace(args.candidate, contract))
            _print(report, args.format)
            return _status_exit(report["status"])
        else:
            batch_report = _run_batch(contract, args.input_dir, args.recursive, args.include_paths)
            _print_batch(
                batch_report,
                args.format,
                tuple(canary.value for canary in contract.canaries),
            )
            return _status_exit(batch_report["status"])
        _print(report, args.format)
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


def _run_batch(contract: Contract, input_dir: Path, recursive: bool, include_paths: bool) -> BatchReport:
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
            report = check_trace(contract, _load_trace(path, contract), mode="batch")
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
    ensure_object_values_absent(
        batch_report,
        tuple(canary.value for canary in contract.canaries),
    )
    return batch_report


def _print(report: Report, output_format: str) -> None:
    print(render_json(report) if output_format == "json" else render_human(report), end="")


def _print_batch(report: BatchReport, output_format: str, redacted_values: tuple[str, ...]) -> None:
    if output_format == "json":
        output = render_json(report)
    elif output_format == "sarif":
        output = render_sarif(report)
    elif output_format == "junit":
        output = render_junit(report)
    else:
        lines = [f"TraceCanary batch: {report['status'].upper()} ({len(report['items'])} file(s))"]
        lines.extend(f"- {item['id']}: {item['status']}" for item in report["items"])
        output = "\n".join(lines) + "\n"
    ensure_text_values_absent(output, redacted_values)
    print(output, end="")


def _status_exit(status: Status) -> int:
    return EXIT_PASS if status == "pass" else EXIT_REGRESSION if status == "regression" else EXIT_UNRESOLVED
