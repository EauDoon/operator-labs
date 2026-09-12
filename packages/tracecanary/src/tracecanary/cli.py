"""Command-line interface for TraceCanary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, load_json
from tracecanary.batching import _load_trace, run_batch
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract
from tracecanary.coverage import coverage_report
from tracecanary.fixture import write_bundle
from tracecanary.inspection import (
    _parse_minimum_ratio,
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
from tracecanary.project import build_manifest, load_project, write_project
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
    render_batch_human,
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
    "  control-check: 0 means all canaries were exercised, not a privacy pass\n"
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
    batch_coverage.add_argument("--minimum-ratio", help="require this exact retained-field ratio in every file")
    batch_coverage.add_argument("--format", choices=("human", "json"), default="json")
    for command in (validate, check, diff, batch, coverage, inspect, gate, rate_diff, matrix, batch_coverage, control, population, dropped):
        command.add_argument("--output", type=_cli_path, help="write a UTF-8 report atomically; cannot replace inputs")
    fixture = commands.add_parser("fixture", help="write synthetic fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True, parser_class=_ArgumentParser)
    create = fixture_commands.add_parser("create", help="write the synthetic fixture bundle")
    create.add_argument("--output", required=True, type=_cli_path, help="empty directory for the synthetic fixture bundle")

    project = commands.add_parser("project", help="manage a saved, portable local project")
    project_commands = project.add_subparsers(dest="project_command", required=True, parser_class=_ArgumentParser)
    project_create = project_commands.add_parser("create", help="create a project manifest from explicit synthetic inputs")
    project_create.add_argument("--directory", required=True, type=_cli_path, help="project directory that will contain the manifest")
    project_create.add_argument("--project-id", required=True, help="stable project identifier")
    project_create.add_argument("--description")
    project_create.add_argument("--contract", required=True, type=_cli_path, help="contract JSON inside the project directory")
    project_create.add_argument("--input", type=_cli_path, help="synthetic trace JSON inside the project directory")
    project_create.add_argument("--baseline", type=_cli_path)
    project_create.add_argument("--candidate", type=_cli_path)
    project_create.add_argument("--batch-dir", type=_cli_path, help="directory of synthetic exports")
    project_create.add_argument("--batch-recursive", action="store_true")
    project_create.add_argument("--batch-include-paths", action="store_true")
    project_create.add_argument("--batch-minimum-ratio", help="per-file coverage gate for the saved batch configuration")
    project_create.add_argument("--minimum-ratio", help="saved coverage threshold")
    project_create.add_argument("--population-scope", choices=("resource", "scope", "span", "event", "link"))
    project_create.add_argument("--population-minimum", type=int)
    project_validate = project_commands.add_parser("validate", help="validate a project manifest and inputs")
    project_validate.add_argument("project", type=_cli_path)
    project_open = project_commands.add_parser("open", help="resolve a project and report missing or changed inputs")
    project_open.add_argument("project", type=_cli_path)
    promote = project_commands.add_parser("promote-baseline", help="explicitly promote a passing candidate to the project baseline")
    promote.add_argument("project", type=_cli_path)
    promote.add_argument("--candidate", required=True, type=_cli_path, help="candidate export that must satisfy the contract first")

    campaign = commands.add_parser("campaign", help="run a bounded synthetic regression campaign")
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True, parser_class=_ArgumentParser)
    campaign_run = campaign_run_options(campaign_commands.add_parser("run", help="run a campaign from a saved project"))
    campaign_run.add_argument("project", type=_cli_path, help="project directory or manifest path")
    campaign_run.add_argument("--control", type=_cli_path, help="unsanitized synthetic positive control")
    campaign_run.add_argument("--save-summary", type=_cli_path, help="explicitly save the value-free summary to this JSON path")
    campaign_compare = campaign_commands.add_parser("compare", help="compare two saved value-free campaign summaries")
    campaign_compare.add_argument("baseline_summary", type=_cli_path)
    campaign_compare.add_argument("candidate_summary", type=_cli_path)
    campaign_compare.add_argument("--format", choices=("human", "json"), default="human")
    campaign_compare.add_argument("--output", type=_cli_path)

    contract_cmd = commands.add_parser("contract", help="authoring helpers for synthetic contracts")
    contract_commands = contract_cmd.add_subparsers(dest="contract_command", required=True, parser_class=_ArgumentParser)
    contract_review = contract_commands.add_parser("review", help="conservative value-free diagnostics for a contract draft")
    contract_review.add_argument("contract_path", type=_cli_path)
    contract_review.add_argument("--format", choices=("human", "json"), default="human")
    contract_review.add_argument("--output", type=_cli_path)
    contract_template = contract_commands.add_parser("template", help="write a minimal valid synthetic contract template")
    contract_template.add_argument("--output", required=True, type=_cli_path, help="new file, never overwritten")
    return parser


def campaign_run_options(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--contract", type=_cli_path, help="override the project contract")
    parser.add_argument("--baseline", type=_cli_path, help="override the project baseline")
    parser.add_argument("--candidate", type=_cli_path, help="additional named candidate")
    parser.add_argument("--input-dir", type=_cli_path, help="override the project batch directory")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--include-paths", action="store_true")
    parser.add_argument("--minimum-ratio", help="per-file coverage gate for named candidates")
    parser.add_argument("--population-scope", choices=("resource", "scope", "span", "event", "link"))
    parser.add_argument("--population-minimum", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "fixture":
            write_bundle(args.output)
            print(f"Synthetic fixture bundle created at {args.output}")
            return EXIT_PASS
        if args.command == "project":
            return _project(args)
        if args.command == "campaign":
            return _campaign(args)
        if args.command == "contract":
            return _contract_authoring(args)
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
            batch_report = _run_batch(contract, args.input_dir, args.recursive, args.include_paths, baseline,
                                      coverage=args.command == "coverage-batch", minimum_ratio=getattr(args, "minimum_ratio", None))
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


def _project(args: Any) -> int:
    command = args.project_command
    try:
        if command == "create":
            directory = args.directory
            if not directory.is_dir():
                raise InputError(f"--directory must be an existing project directory: {directory}")
            placed = _project_prepare(
                directory,
                contract=args.contract,
                input=args.input,
                baseline=args.baseline,
                candidate=args.candidate,
                batch=args.batch_dir,
            )
            manifest = build_manifest(
                directory,
                project_id=args.project_id,
                description=args.description or "",
                contract=placed["contract"],
                input=placed.get("input"),
                baseline=placed.get("baseline"),
                candidate=placed.get("candidate"),
                batch=placed.get("batch directory"),
                batch_recursive=bool(args.batch_recursive),
                batch_include_paths=bool(args.batch_include_paths),
                batch_minimum_ratio=args.batch_minimum_ratio,
                minimum_ratio=args.minimum_ratio,
                population_scope=args.population_scope,
                population_minimum=args.population_minimum,
            )
            write_project(directory, manifest)
            print(f"Project created: {directory / 'tracecanary.project.json'}")
            return EXIT_PASS
        if command == "validate":
            loaded = load_project(args.project)
            if not loaded.ok:
                for problem in loaded.problems:
                    print(f"TraceCanary: UNRESOLVED: {problem}", file=sys.stderr)
                return EXIT_UNRESOLVED
            print("valid")
            return EXIT_PASS
        if command == "open":
            loaded = load_project(args.project)
            print(f"project: {loaded.manifest.project_id}")
            print(f"contract: {loaded.manifest.contract.path}")
            if loaded.manifest.input is not None:
                print(f"input: {loaded.manifest.input.path}")
            if loaded.manifest.baseline is not None:
                print(f"baseline: {loaded.manifest.baseline.path}")
            if loaded.manifest.candidate is not None:
                print(f"candidate: {loaded.manifest.candidate.path}")
            if loaded.manifest.batch is not None:
                print(f"batch directory: {loaded.manifest.batch.path} (recursive={loaded.manifest.batch.recursive}, include_paths={loaded.manifest.batch.include_paths}, minimum_ratio={loaded.manifest.batch.minimum_ratio})")
            if loaded.manifest.coverage.minimum_ratio is not None:
                print(f"coverage threshold: {loaded.manifest.coverage.minimum_ratio}")
            if loaded.manifest.coverage.population_scope is not None:
                print(f"population gate: {loaded.manifest.coverage.population_scope} >= {loaded.manifest.coverage.population_minimum}")
            for problem in loaded.problems:
                print(f"TraceCanary: UNRESOLVED: {problem}", file=sys.stderr)
            return EXIT_PASS if loaded.ok else EXIT_UNRESOLVED
        if command == "promote-baseline":
            return _project_promote_baseline(args.project, args.candidate)
        raise InputError(f"unsupported project command: {command}")
    except (InputError, ValueError) as exc:
        print(f"TraceCanary: UNRESOLVED: {exc}", file=sys.stderr)
        return EXIT_UNRESOLVED
    except OSError:
        print("TraceCanary: UNRESOLVED: input or output could not be accessed", file=sys.stderr)
        return EXIT_UNRESOLVED


def _project_prepare(directory: Path, *, contract: Path, input: Path | None, baseline: Path | None, candidate: Path | None, batch: Path | None) -> dict[str, Path]:
    """Make the chosen synthetic inputs self-contained inside the project directory."""
    from tracecanary.project import _copy_project_input

    project_dir = directory.resolve()
    if not project_dir.is_dir():
        raise InputError(f"--directory must be an existing project directory: {directory}")
    placed: dict[str, Path] = {}
    copied_sources: dict[Path, Path] = {}

    def place(source: Path | None, *, folder: bool = False) -> Path | None:
        if source is None:
            return None
        resolved_source = source.resolve()
        if resolved_source in copied_sources:
            return copied_sources[resolved_source]
        target = _copy_project_input(project_dir, source, folder=folder)
        copied_sources[resolved_source] = target
        return target

    placed["contract"] = place(contract)
    for label, source in (("input", input), ("baseline", baseline), ("candidate", candidate)):
        target = place(source)
        if target is not None:
            placed[label] = target
    batch_target = place(batch, folder=True)
    if batch_target is not None:
        placed["batch directory"] = batch_target
    return placed


def _project_promote_baseline(directory: Path, candidate: Path) -> int:
    """Explicitly promote a candidate to the project baseline after it passes."""
    from tracecanary.project import _copy_project_input, fingerprint_file, load_project, parse_manifest, write_report

    loaded = load_project(directory)
    if not loaded.ok:
        for problem in loaded.problems:
            print(f"TraceCanary: UNRESOLVED: {problem}", file=sys.stderr)
        return EXIT_UNRESOLVED
    contract = load_contract(loaded.resolved["contract"])
    payload = _load_trace(candidate, contract)
    if check_trace(contract, payload, mode="check")["status"] != "pass":
        raise InputError("baseline promotion requires a candidate that satisfies the contract; failing candidates are never blessed")
    project_dir = directory.resolve() if directory.is_dir() else directory.parent.resolve()
    target = _copy_project_input(project_dir, candidate)
    manifest = parse_manifest(load_json(loaded.path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting))
    document = load_json(loaded.path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    from tracecanary.project import DEFAULT_MAX_INPUT_BYTES

    document["baseline"] = {"path": manifest_text_relative(project_dir, target),
                            "sha256": fingerprint_file(target, max_bytes=DEFAULT_MAX_INPUT_BYTES)}
    write_report(loaded.path, canonical_json_text(document))
    print(f"Baseline promoted from {candidate.name}: the candidate satisfied the contract first.")
    return EXIT_PASS


def manifest_text_relative(project_dir: Path, target: Path) -> str:
    from tracecanary.project import _validate_relative_path

    return _validate_relative_path(target.relative_to(project_dir).as_posix(), "baseline.path")


def canonical_json_text(value: Any) -> str:
    from tracecanary.canonical import canonical_json

    return canonical_json(value)


def _campaign(args: Any) -> int:
    from tracecanary.campaign import CAMPAIGN_VERSION, campaign_summary, compare_summaries, run_campaign
    from tracecanary.project import load_project
    from tracecanary.report import ensure_text_values_absent

    command = args.campaign_command
    try:
        if command == "run":
            loaded = load_project(args.project)
            if not loaded.ok:
                for problem in loaded.problems:
                    print(f"TraceCanary: UNRESOLVED: {problem}", file=sys.stderr)
                return EXIT_UNRESOLVED
            manifest = loaded.manifest
            contract_path = args.contract or loaded.resolved["contract"]
            contract = load_contract(contract_path)
            control = args.control
            baseline = args.baseline or loaded.resolved.get("baseline")
            candidates: list[tuple[str, Path]] = []
            if args.candidate is not None:
                candidates.append((args.candidate.name, args.candidate))
            if manifest.input is not None:
                candidates.append((manifest.input.path, loaded.resolved["input"]))
            batch = args.input_dir or loaded.resolved.get("batch directory")
            population_scope = args.population_scope or manifest.coverage.population_scope
            population_minimum = args.population_minimum if args.population_minimum is not None else manifest.coverage.population_minimum
            campaign = run_campaign(
                contract,
                control_payload=_load_trace(control, contract) if control is not None else None,
                baseline_payload=_load_trace(baseline, contract) if baseline is not None else None,
                candidates=candidates,
                batch=batch,
                batch_recursive=args.recursive or (manifest.batch.recursive if manifest.batch is not None else False),
                batch_include_paths=args.include_paths or (manifest.batch.include_paths if manifest.batch is not None else False),
                batch_minimum_ratio=args.minimum_ratio or (manifest.batch.minimum_ratio if manifest.batch is not None else None),
                minimum_ratio=args.minimum_ratio,
                population_scope=population_scope,
                population_minimum=population_minimum,
            )
            output = render_json(campaign)
            ensure_text_values_absent(output, tuple(canary.value for canary in contract.canaries))
            _emit(output, args.output if hasattr(args, "output") else None)
            summary_path = args.save_summary
            if summary_path is not None:
                summary = campaign_summary(campaign)
                summary_text = render_json(summary)
                protect_inputs(summary_path, [loaded.resolved["contract"]], loaded.path.parent)
                write_report(summary_path, summary_text)
                print(f"Value-free campaign summary saved to {summary_path}")
            return _status_exit(campaign["status"])
        if command == "compare":
            baseline_summary = load_json(args.baseline_summary, max_bytes=MAX_CAMPAIGN_SUMMARY_BYTES, max_depth=32)
            candidate_summary = load_json(args.candidate_summary, max_bytes=MAX_CAMPAIGN_SUMMARY_BYTES, max_depth=32)
            comparison = compare_summaries(baseline_summary, candidate_summary)
            output = render_json(comparison) if args.format == "json" else render_campaign_human(comparison)
            _emit(output, args.output)
            return EXIT_PASS
        raise InputError(f"unsupported campaign command: {command}")
    except (ContractError, InputError, OtlpError, ValueError) as exc:
        print(f"TraceCanary: UNRESOLVED: {exc}", file=sys.stderr)
        return EXIT_UNRESOLVED
    except OSError:
        print("TraceCanary: UNRESOLVED: input or output could not be accessed", file=sys.stderr)
        return EXIT_UNRESOLVED


MAX_CAMPAIGN_SUMMARY_BYTES = 1_000_000


def render_campaign_human(comparison: dict[str, Any]) -> str:
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


def _contract_authoring(args: Any) -> int:
    from tracecanary.authoring import empty_template, review_contract, validate_draft
    from tracecanary.canonical import canonical_json

    command = args.contract_command
    try:
        if command == "review":
            raw = load_json(args.contract_path, max_bytes=MAX_CAMPAIGN_SUMMARY_BYTES, max_depth=MAX_CAMPAIGN_SUMMARY_DEPTH)
            report = review_contract(raw)
            output = render_json(report) if args.format == "json" else render_contract_review_human(report)
            _emit(output, args.output)
            return _status_exit(report["status"])
        if command == "template":
            template = empty_template()
            text = canonical_json(validate_draft(template))
            if args.output.exists():
                raise InputError("template output must not replace an existing file")
            write_report(args.output, text)
            print(f"Synthetic contract template written to {args.output}; replace the placeholder canary value before use.")
            return EXIT_PASS
        raise InputError(f"unsupported contract command: {command}")
    except (ContractError, InputError, ValueError) as exc:
        print(f"TraceCanary: UNRESOLVED: {exc}", file=sys.stderr)
        return EXIT_UNRESOLVED
    except OSError:
        print("TraceCanary: UNRESOLVED: input or output could not be accessed", file=sys.stderr)
        return EXIT_UNRESOLVED


MAX_CAMPAIGN_SUMMARY_DEPTH = 32


def render_contract_review_human(report: dict[str, Any]) -> str:
    from tracecanary.authoring import render_review_human

    return render_review_human(report)


def _load_trace(path: Path, contract: Contract) -> dict[str, Any]:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


def _run_batch(contract: Contract, input_dir: Path, recursive: bool, include_paths: bool, baseline: dict[str, Any] | None = None, *, coverage: bool = False, minimum_ratio: str | None = None) -> BatchReport:
    """Compatibility wrapper; the shared engine lives in batching.run_batch."""
    return run_batch(contract, input_dir, recursive, include_paths, baseline, coverage=coverage, minimum_ratio=minimum_ratio)


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
        output = render_batch_human(report)
    ensure_text_values_absent(output, redacted_values)
    _emit(output, output_path)


def _status_exit(status: Status) -> int:
    return EXIT_PASS if status == "pass" else EXIT_REGRESSION if status == "regression" else EXIT_UNRESOLVED
