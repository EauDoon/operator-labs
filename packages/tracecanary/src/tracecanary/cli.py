"""Command-line interface for TraceCanary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tracecanary import batch_pairs, contract_diff, findings
from tracecanary.canonical import InputError, canonical_json, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract
from tracecanary.fixture import write_bundle
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.profiles import PROFILE_FILENAME, PROFILE_IDS, describe, profile, write_profile
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


def _code_list(value: str) -> tuple[str, ...]:
    """Parse a comma-separated list of TraceCanary codes, rejecting unknown ones.

    An unknown code is rejected instead of silently matching nothing, because a
    filter that matches nothing must not look like a clean report.
    """
    parts = tuple(item.strip() for item in value.split(","))
    if any(not item for item in parts):
        raise argparse.ArgumentTypeError("--filter-code takes a comma-separated list of TraceCanary codes, for example TC001,TC002")
    try:
        return findings.validate_codes(parts)
    except InputError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_finding_views(parser: argparse.ArgumentParser) -> None:
    """Add the grouping, filtering, and summary flags shared by check and diff."""
    parser.add_argument("--group-by", choices=list(findings.GROUP_KEYS), help="group findings by code, scope, category, or key")
    parser.add_argument("--filter-code", type=_code_list, metavar="CODE,CODE", help="keep only findings with these TraceCanary codes")
    parser.add_argument("--summary", action="store_true", help="print a human summary panel instead of the full report")


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
    _add_finding_views(check)
    diff = commands.add_parser("diff", help="compare a baseline and a candidate OTLP trace export")
    diff.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    diff.add_argument("--baseline", required=True, type=_cli_path, help="baseline OTLP/HTTP JSON trace export")
    diff.add_argument("--candidate", required=True, type=_cli_path, help="candidate OTLP/HTTP JSON trace export")
    diff.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    _add_finding_views(diff)
    batch_diff = commands.add_parser("batch-diff", help="diff paired baseline and candidate OTLP trace directories")
    batch_diff.add_argument("--contract", required=True, type=_cli_path, help="TraceCanary contract JSON file")
    batch_diff.add_argument("--baseline-dir", required=True, type=_cli_path, help="directory of baseline OTLP/HTTP JSON trace exports")
    batch_diff.add_argument("--candidate-dir", required=True, type=_cli_path, help="directory of candidate OTLP/HTTP JSON trace exports")
    batch_diff.add_argument("--recursive", action="store_true", help="include *.json files in subdirectories")
    batch_diff.add_argument(
        "--pairing",
        choices=list(batch_pairs.PAIRING_MODES),
        default=batch_pairs.DEFAULT_PAIRING,
        help="pair by identical relative filename (default), or by documented sort order",
    )
    batch_diff.add_argument("--include-paths", action="store_true", help="include directory-relative POSIX names in the report")
    batch_diff.add_argument("--format", choices=("human", "json", "sarif", "junit"), default="json", help="report format (default: json)")
    contract_review = commands.add_parser("contract-diff", help="review how a contract change alters checking coverage")
    contract_review.add_argument("--before", required=True, type=_cli_path, help="previous TraceCanary contract JSON file")
    contract_review.add_argument("--after", required=True, type=_cli_path, help="updated TraceCanary contract JSON file")
    contract_review.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
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
    profiles = commands.add_parser("profile", help="list, show, or create synthetic contract profiles")
    profile_commands = profiles.add_subparsers(dest="profile_command", required=True, parser_class=_ArgumentParser)
    list_profiles = profile_commands.add_parser("list", help="list the available contract profiles")
    list_profiles.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    show_profile = profile_commands.add_parser("show", help="show one contract profile")
    show_profile.add_argument("--profile", required=True, help="profile id")
    show_profile.add_argument("--format", choices=("human", "json"), default="human", help="report format (default: human)")
    create_profile = profile_commands.add_parser("create", help="write a contract profile as contract.json")
    create_profile.add_argument("--profile", required=True, help="profile id")
    create_profile.add_argument("--output", required=True, type=_cli_path, help="empty directory for contract.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "fixture":
            write_bundle(args.output)
            print(f"Synthetic fixture bundle created at {args.output}")
            return EXIT_PASS
        if args.command == "profile":
            return _run_profile(args)
        if args.command == "contract-diff":
            return _run_contract_diff(args.before, args.after, args.format)
        contract = load_contract(args.contract)
        values = tuple(canary.value for canary in contract.canaries)
        if args.command == "validate":
            report = build_report(contract.contract_version, "pass", [], mode="validate")
            ensure_values_absent(report, values)
            _print(report, args.format)
            return EXIT_PASS
        if args.command == "check":
            report = check_trace(contract, _load_trace(args.input, contract), mode="check")
        elif args.command == "diff":
            report = diff_traces(contract, _load_trace(args.baseline, contract), _load_trace(args.candidate, contract))
        elif args.command == "batch-diff":
            batch_report = batch_pairs.batch_diff(
                contract,
                args.baseline_dir,
                args.candidate_dir,
                pairing=args.pairing,
                recursive=args.recursive,
                include_paths=args.include_paths,
                redacted_values=values,
            )
            _print_batch_diff(batch_report, args.format, values)
            return _status_exit(batch_report["status"])
        else:
            batch_report = _run_batch(contract, args.input_dir, args.recursive, args.include_paths)
            _print_batch(
                batch_report,
                args.format,
                values,
            )
            return _status_exit(batch_report["status"])
        _print_findings(report, args, values)
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


def _run_profile(args: argparse.Namespace) -> int:
    """List, show, or create a synthetic contract profile without writing traces."""
    if args.profile_command == "list":
        profiles = [describe(profile_id) for profile_id in PROFILE_IDS]
        if args.format == "json":
            print(canonical_json({"profiles": profiles}), end="")
        else:
            lines = ["TraceCanary profile list"]
            lines.extend(f"- {item['profile_id']}: {item['title']}" for item in profiles)
            print("\n".join(lines) + "\n", end="")
        return EXIT_PASS
    if args.profile_command == "show":
        metadata = describe(args.profile)
        values = tuple(str(canary["value"]) for canary in profile(args.profile).get("canaries", []))
        if args.format == "json":
            ensure_object_values_absent(metadata, values)
            print(canonical_json(metadata), end="")
        else:
            lines = [
                f"TraceCanary profile {metadata['profile_id']}",
                f"title: {metadata['title']}",
                f"semantic conventions: {metadata['semantic_conventions_version']}",
                f"summary: {metadata['summary']}",
                "covered attributes:",
            ]
            lines.extend(f"- {item}" for item in metadata["covered_attributes"])
            lines.append("retention requirements:")
            lines.extend(
                f"- {item['requirement_id']} [{item['scope']}:{item['key']}; {item['comparison']}]"
                for item in metadata["retention_requirements"]
            )
            ensure_text_values_absent("\n".join(lines), values)
            print("\n".join(lines) + "\n", end="")
        return EXIT_PASS
    write_profile(args.profile, args.output)
    print(f"Contract profile {args.profile} written as {PROFILE_FILENAME}")
    return EXIT_PASS


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
        output = batch_pairs.render_batch_human(report, redacted_values=redacted_values)
    ensure_text_values_absent(output, redacted_values)
    print(output, end="")


def _run_contract_diff(before: Path, after: Path, output_format: str) -> int:
    """Review a contract change and exit 1 when checking coverage was reduced."""
    previous = load_contract(before)
    current = load_contract(after)
    values = tuple(dict.fromkeys((*(canary.value for canary in previous.canaries), *(canary.value for canary in current.canaries))))
    review = contract_diff.review_contract_change(previous, current, redacted_values=values)
    if output_format == "json":
        output = canonical_json(review)
    else:
        output = contract_diff.render_contract_review_human(review, redacted_values=values)
    ensure_text_values_absent(output, values)
    print(output, end="")
    return EXIT_REGRESSION if review["verdict"] == contract_diff.REDUCED else EXIT_PASS


def _print_findings(report: Report, args: argparse.Namespace, redacted_values: tuple[str, ...]) -> None:
    """Print a report with the requested filtering, grouping, and summary view.

    Exit codes are decided by the caller from the unfiltered status: a view over
    a report never changes what the run concluded.
    """
    codes = getattr(args, "filter_code", None)
    view = findings.filter_findings(report, codes=codes, redacted_values=redacted_values)
    group_by = getattr(args, "group_by", None)
    if getattr(args, "summary", False):
        output = findings.render_summary(view, redacted_values=redacted_values)
        if group_by:
            output += findings.render_groups(findings.group_findings(view, group_by, redacted_values=redacted_values), group_by, redacted_values=redacted_values)
    elif group_by:
        groups = findings.group_findings(view, group_by, redacted_values=redacted_values)
        payload = findings.grouped_report(view, groups)
        ensure_object_values_absent(payload, redacted_values)
        output = canonical_json(payload) if args.format == "json" else findings.render_groups(groups, group_by, redacted_values=redacted_values)
    else:
        output = render_json(view) if args.format == "json" else render_human(view)
    ensure_text_values_absent(output, redacted_values)
    print(output, end="")


def _print_batch_diff(report: BatchReport, output_format: str, redacted_values: tuple[str, ...]) -> None:
    if output_format == "json":
        output = render_json(report)
    elif output_format == "sarif":
        output = render_sarif(report)
    elif output_format == "junit":
        output = render_junit(report)
    else:
        output = batch_pairs.render_batch_human(report, redacted_values=redacted_values)
    ensure_text_values_absent(output, redacted_values)
    print(output, end="")


def _status_exit(status: Status) -> int:
    return EXIT_PASS if status == "pass" else EXIT_REGRESSION if status == "regression" else EXIT_UNRESOLVED
