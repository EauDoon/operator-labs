"""Command-line interface for Corridor Lab."""

from __future__ import annotations

import argparse
import json
import os
import stat as stat_module
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException
from pathlib import Path

from .analysis import (
    break_even_check,
    cost_ledger,
    deadline_profile,
    deadline_target,
    feasible_amount,
    guardrail_headroom,
    loss_profile,
    outcome_ledger,
    resolution_quantiles,
)
from .canonical import (
    MAX_BATCH_SCENARIOS,
    MAX_INPUT_BYTES,
    InputError,
    atomic_write_text,
    parse_json_bytes,
    protect_report_output,
    require_decimal_values,
)
from .comparison import compare_routes, evaluate_scenario, pareto_frontier
from .model import evaluate_route
from .projects import (
    ProjectManifest,
    build_manifest,
    execute_experiment,
    load_project,
    parse_experiment_argument,
    prepare_project_directory,
    write_project,
)
from .report import render_report
from .route import SENSITIVITY_PARAMETERS, Route, load_route, load_route_folder
from .scenario import load_scenario, parse_scenario
from .scenario_diff import diff_scenarios
from .sensitivity import run_sensitivity
from .stress import run_stress_grid
from .transaction_sweep import (
    TRANSACTION_PARAMETERS,
    run_transaction_grid,
    run_transaction_sweep,
)

SCENARIO_HELP = "path to a fictional scenario JSON file"
PARAMETER_HELP = "one of " + ", ".join(SENSITIVITY_PARAMETERS)
VALUES_HELP = "comma-separated decimal values"
DEFAULT_REPORT_FORMAT = "json"
REPORT_FORMAT_ENV = "CORRIDOR_LAB_FORMAT"
TABULAR_REPORT_FORMATS = ("json", "csv", "markdown")
FRONTIER_REPORT_FORMATS = ("json", "markdown")
REPORT_FORMAT_BY_SUFFIX = {
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
}


def resolve_report_format(
    explicit: str | None,
    output: str | None,
    allowed: tuple[str, ...],
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Choose a report format from --format, --output suffix, env, then JSON."""
    if explicit is not None:
        if explicit not in allowed:
            raise InputError(f"unsupported report format: {explicit}")
        return explicit
    suffix_format = _format_from_output_path(output)
    if suffix_format is not None:
        if suffix_format not in allowed:
            raise InputError(
                f"--output suffix implies {suffix_format}, which is not supported (choose {', '.join(allowed)})"
            )
        return suffix_format
    env_format = _format_from_env(environ)
    if env_format is not None:
        if env_format not in allowed:
            raise InputError(
                f"{REPORT_FORMAT_ENV}={env_format} is not supported (choose {', '.join(allowed)})"
            )
        return env_format
    if DEFAULT_REPORT_FORMAT in allowed:
        return DEFAULT_REPORT_FORMAT
    return allowed[0]


def _format_from_output_path(output: str | None) -> str | None:
    if output is None:
        return None
    text = output.strip()
    if not text:
        return None
    return REPORT_FORMAT_BY_SUFFIX.get(Path(text).suffix.lower())


def _format_from_env(environ: Mapping[str, str] | None) -> str | None:
    source = os.environ if environ is None else environ
    raw = source.get(REPORT_FORMAT_ENV)
    if raw is None:
        return None
    text = raw.strip().casefold()
    if not text:
        return None
    return text


def _command_formats(command: str) -> tuple[str, ...]:
    if command in {"pareto", "batch"}:
        return FRONTIER_REPORT_FORMATS
    return TABULAR_REPORT_FORMATS


def _add_output_options(
    parser: argparse.ArgumentParser,
    *,
    formats: tuple[str, ...] = TABULAR_REPORT_FORMATS,
) -> None:
    if "csv" in formats:
        format_help = (
            "json, csv, or markdown (default: json; inferred from --output or "
            f"{REPORT_FORMAT_ENV})"
        )
    else:
        format_help = (
            "json or markdown (default: json; csv is not supported; inferred from "
            f"--output or {REPORT_FORMAT_ENV})"
        )
    parser.add_argument("--format", choices=formats, default=None, help=format_help)
    parser.add_argument("--output", help="write the report to this UTF-8 path")


def _add_scenario_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("scenario", help=SCENARIO_HELP)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corridorlab", description="Compare fictional payment route scenarios.")
    commands = parser.add_subparsers(dest="command", required=True)

    starter = commands.add_parser("init", help="create a fictional scenario at a new file path")
    starter.add_argument("--output", required=True, help="new scenario JSON file, never overwritten")
    validate = commands.add_parser("validate", help="validate a synthetic scenario contract")
    _add_scenario_argument(validate)
    costs = commands.add_parser("cost-ledger", help="reconcile unrounded sender-cost components")
    _add_scenario_argument(costs)
    _add_output_options(costs)
    target = commands.add_parser("deadline-target", help="find the earliest time meeting a declared delivery probability")
    _add_scenario_argument(target)
    target.add_argument("--probability", required=True, help="unconditional delivery probability from 0 to 1")
    _add_output_options(target)
    quantiles = commands.add_parser("resolution-quantiles", help="inspect explicit quantiles of final-state time")
    _add_scenario_argument(quantiles)
    quantiles.add_argument("--probabilities", required=True, help="comma-separated probabilities greater than 0 and at most 1")
    _add_output_options(quantiles)
    losses = commands.add_parser("loss-profile", help="inspect declared principal-loss exceedance probabilities")
    _add_scenario_argument(losses)
    _add_output_options(losses)
    feasible = commands.add_parser("feasible-amount", help="inspect minimum amounts satisfying declared fee and recovery bounds")
    _add_scenario_argument(feasible)
    _add_output_options(feasible)
    headroom = commands.add_parser("guardrail-headroom", help="inspect margins against declared guardrails")
    _add_scenario_argument(headroom)
    _add_output_options(headroom)
    ledger = commands.add_parser("outcome-ledger", help="inspect probability-weighted outcome contributions")
    _add_scenario_argument(ledger)
    _add_output_options(ledger)
    profile = commands.add_parser("deadline-profile", help="show exact success and resolution probabilities over time")
    _add_scenario_argument(profile)
    _add_output_options(profile)
    crossing = commands.add_parser("break-even-check", help="verify whole-volume costs near declared break-even points")
    _add_scenario_argument(crossing)
    _add_output_options(crossing)

    diff = commands.add_parser("diff", help="compare two fictional scenario evaluations")
    _add_scenario_argument(diff)
    diff.add_argument("--baseline", required=True, help="baseline fictional scenario JSON")
    _add_output_options(diff)
    evaluate = commands.add_parser("evaluate", help="evaluate routes embedded in a scenario")
    _add_scenario_argument(evaluate)
    _add_output_options(evaluate)

    compare = commands.add_parser("compare", help="compare route files against a scenario transaction")
    _add_scenario_argument(compare)
    compare.add_argument("--routes", required=True, help="a route JSON file or directory of route JSON files")
    _add_output_options(compare)

    sensitivity = commands.add_parser("sensitivity", help="vary one declared route parameter")
    _add_scenario_argument(sensitivity)
    sensitivity.add_argument("--parameter", required=True, help=PARAMETER_HELP)
    sensitivity.add_argument("--values", required=True, help=VALUES_HELP)
    _add_output_options(sensitivity)
    sweep = commands.add_parser("transaction-sweep", help="vary a declared amount, deadline, or volume")
    _add_scenario_argument(sweep)
    sweep.add_argument("--parameter", required=True, choices=TRANSACTION_PARAMETERS)
    sweep.add_argument("--values", required=True, help=VALUES_HELP)
    _add_output_options(sweep)
    transaction_grid = commands.add_parser("transaction-grid", help="vary two transaction parameters together")
    _add_scenario_argument(transaction_grid)
    for axis in ("a", "b"):
        transaction_grid.add_argument(f"--parameter-{axis}", required=True, choices=TRANSACTION_PARAMETERS)
        transaction_grid.add_argument(f"--values-{axis}", required=True, help=VALUES_HELP)
    _add_output_options(transaction_grid)
    stress = commands.add_parser("stress-grid", help="run an explicit bounded two-parameter stress grid")
    _add_scenario_argument(stress)
    stress.add_argument("--parameter-a", required=True, help=PARAMETER_HELP)
    stress.add_argument("--values-a", required=True, help=VALUES_HELP)
    stress.add_argument("--parameter-b", required=True, help=PARAMETER_HELP)
    stress.add_argument("--values-b", required=True, help=VALUES_HELP)
    _add_output_options(stress)
    pareto = commands.add_parser("pareto", help="show the explicit two-metric Pareto frontier")
    _add_scenario_argument(pareto)
    _add_output_options(pareto, formats=FRONTIER_REPORT_FORMATS)
    batch = commands.add_parser("batch", help="evaluate a bounded directory of fictional scenarios")
    batch.add_argument("input_dir", help="directory of fictional scenario JSON files")
    batch.add_argument("--recursive", action="store_true", help="include JSON files in subdirectories")
    batch.add_argument("--include-paths", action="store_true", help="add each scenario's relative path to the batch report")
    _add_output_options(batch, formats=FRONTIER_REPORT_FORMATS)

    project = commands.add_parser("project", help="manage a saved, portable local project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    create = project_commands.add_parser("create", help="create a project manifest from explicit inputs")
    create.add_argument("--directory", required=True, help="project directory that will contain the manifest")
    create.add_argument("--project-id", required=True, help="stable project identifier")
    create.add_argument("--description", help="optional human-readable description")
    create.add_argument("--scenario", required=True, help="scenario JSON inside the project directory")
    create.add_argument("--routes", help="route JSON file or folder inside the project directory")
    create.add_argument("--baseline", help="baseline scenario JSON inside the project directory")
    create.add_argument("--variant", action="append", help="NAME=PATH named scenario reference")
    create.add_argument("--experiment", action="append", help="NAME:ANALYSIS:KEY=VALUE;... saved experiment")
    validate_project = project_commands.add_parser("validate", help="validate a project manifest and inputs")
    validate_project.add_argument("project", help="project directory or manifest JSON path")
    open_project = project_commands.add_parser("open", help="resolve a project and report missing or changed inputs")
    open_project.add_argument("project")
    add_experiment = project_commands.add_parser("add-experiment", help="add saved experiments (explicit save)")
    add_experiment.add_argument("project")
    add_experiment.add_argument("--experiment", action="append", required=True)
    run_project = project_commands.add_parser("run", help="run saved experiments against the project inputs")
    run_project.add_argument("project", help="project directory or manifest JSON path")
    run_project.add_argument("--experiment", action="append", help="run only these named experiments")
    run_project.add_argument("--format", choices=("json", "markdown"), default=None,
                             help="combined project-run report format (default: json)")
    run_project.add_argument("--output", help="write the combined report to this UTF-8 path outside the project")
    return parser


def _require_cli_text(value: str, flag: str) -> str:
    text = value.strip()
    if not text:
        raise InputError(f"{flag} must not be empty")
    return text


def _failure_text(exc: BaseException) -> str:
    """Render a CLI diagnostic that keeps the exception type and chained cause."""
    message = str(exc).strip() or type(exc).__name__
    cause = exc.__cause__
    if cause is None:
        return message
    cause_text = str(cause).strip() or type(cause).__name__
    if cause_text in message:
        return message
    return f"{message}: {cause_text}"


def _write_error(message: str) -> None:
    sys.stderr.write(f"error: {message}\n")


def _load_routes_argument(value: str) -> list[Route]:
    path = Path(_require_cli_text(value, "--routes"))
    if path.is_file():
        return [load_route(path)]
    if not path.is_dir():
        raise InputError(f"--routes is not a file or directory: {path}")
    return load_route_folder(path)


def _parse_values(raw: str, flag: str = "--values") -> list[Decimal]:
    chunks = raw.split(",")
    if not all(chunk.strip() for chunk in chunks):
        raise InputError(f"{flag} must be a comma-separated list of decimals")
    return require_decimal_values([chunk.strip() for chunk in chunks], flag)


def _variants_from_cli(pairs: list[str] | None) -> dict[str, Path]:
    variants: dict[str, Path] = {}
    for pair in pairs or []:
        name, separator, value = pair.partition("=")
        if not separator or not name.strip() or not value.strip():
            raise InputError("--variant must be NAME=PATH")
        if name.strip() in variants:
            raise InputError(f"--variant name repeated: {name.strip()}")
        variants[name.strip()] = Path(value.strip())
    return variants


def _project_experiment_args(raws: list[str] | None) -> tuple:
    if raws is None:
        return ()
    experiments = [parse_experiment_argument(raw) for raw in raws]
    names = [experiment.name for experiment in experiments]
    if len(names) != len(set(names)):
        raise InputError("experiment names must be unique")
    return tuple(experiments)


def _project_inputs_for_protection(loaded) -> tuple[list[Path], list[Path]]:
    inputs: list[Path] = []
    scanned: list[Path] = [loaded.path.parent]
    manifest = loaded.manifest
    if manifest.scenario.folder:
        scanned.append(loaded.path.parent / manifest.scenario.path)
    else:
        inputs.append(loaded.path.parent / manifest.scenario.path)
    for ref in (manifest.routes, manifest.baseline):
        if ref is not None:
            target = loaded.path.parent / ref.path
            (scanned if ref.folder else inputs).append(target)
    for ref in manifest.variants.values():
        target = loaded.path.parent / ref.path
        (scanned if ref.folder else inputs).append(target)
    return inputs, scanned


def _project_run(args: argparse.Namespace) -> int:
    loaded = load_project(_require_cli_text(args.project, "project"))
    if loaded.problems:
        for problem in loaded.problems:
            _write_error(problem)
        return 2
    scenario = load_scenario(loaded.resolved["scenario"])
    chosen = args.experiment or [experiment.name for experiment in loaded.manifest.experiments]
    selected = [experiment for experiment in loaded.manifest.experiments if experiment.name in chosen]
    if len(selected) != len(chosen):
        missing = sorted(set(chosen) - {experiment.name for experiment in selected})
        raise InputError(f"no saved experiment named {', '.join(missing)}")
    items: list[dict[str, object]] = []
    for index, experiment in enumerate(selected, start=1):
        try:
            report = execute_experiment(experiment, scenario)
            status = "pass"
        except (InputError, OSError, ValueError, DecimalException) as exc:
            report = {"status": "unresolved", "error": _failure_text(exc)}
            status = "unresolved"
        items.append({"id": f"experiment-{index:04d}", "name": experiment.name, "analysis": experiment.analysis,
                      "status": status, "report": report})
    combined = {"report_version": "corridor-lab.project-run/v1", "project_id": loaded.manifest.project_id,
                "fictional": True,
                "status": "unresolved" if any(item["status"] == "unresolved" for item in items) else "pass",
                "items": items}
    output_format = resolve_report_format(args.format, args.output, ("json", "markdown"))
    if args.output is None:
        text = render_report(combined, output_format) if output_format == "markdown" else json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        sys.stdout.write(text)
        return 0 if combined["status"] == "pass" else 2
    target = Path(_require_cli_text(args.output, "--output"))
    inputs, scanned = _project_inputs_for_protection(loaded)
    protect_report_output(target, inputs, scanned)
    text = render_report(combined, output_format) if output_format == "markdown" else json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(target, text)
    return 0 if combined["status"] == "pass" else 2


def _project(args: argparse.Namespace) -> int:
    command = args.project_command
    if command == "create":
        directory = Path(_require_cli_text(args.directory, "--directory"))
        if not directory.is_dir():
            raise InputError(f"--directory must be an existing project directory: {directory}")
        scenario_path = Path(_require_cli_text(args.scenario, "--scenario"))
        routes_path = Path(args.routes) if args.routes else None
        baseline_path = Path(args.baseline) if args.baseline else None
        variants = _variants_from_cli(args.variant)
        placed = prepare_project_directory(directory, scenario_path, routes_path, baseline_path, variants)
        experiments = _project_experiment_args(args.experiment)
        manifest = build_manifest(
            directory,
            project_id=_require_cli_text(args.project_id, "--project-id"),
            description=args.description or "",
            scenario=placed["scenario"],
            routes=placed.get("routes"),
            baseline=placed.get("baseline"),
            variants={name: placed[f"variant {name}"] for name in variants},
            experiments=experiments,
        )
        write_project(directory, manifest)
        sys.stdout.write(f"project created: {directory / 'corridor-lab.project.json'}\n")
        return 0
    if command == "validate":
        load_project(_require_cli_text(args.project, "project"))
        sys.stdout.write("valid\n")
        return 0
    if command == "open":
        loaded = load_project(_require_cli_text(args.project, "project"))
        sys.stdout.write(f"project: {loaded.manifest.project_id}\n")
        sys.stdout.write(f"scenario: {loaded.manifest.scenario.path}\n")
        if loaded.manifest.routes is not None:
            sys.stdout.write(f"routes: {loaded.manifest.routes.path}\n")
        if loaded.manifest.baseline is not None:
            sys.stdout.write(f"baseline: {loaded.manifest.baseline.path}\n")
        for name, ref in loaded.manifest.variants.items():
            sys.stdout.write(f"variant {name}: {ref.path}\n")
        for experiment in loaded.manifest.experiments:
            sys.stdout.write(f"experiment {experiment.name}: {experiment.analysis}\n")
        if loaded.problems:
            for problem in loaded.problems:
                _write_error(problem)
            return 2
        return 0
    if command == "add-experiment":
        loaded = load_project(_require_cli_text(args.project, "project"))
        if loaded.problems:
            for problem in loaded.problems:
                _write_error(problem)
            return 2
        additions = _project_experiment_args(args.experiment)
        existing = {experiment.name for experiment in loaded.manifest.experiments}
        if any(experiment.name in existing for experiment in additions):
            raise InputError("add-experiment must not replace an existing saved experiment name")
        manifest = ProjectManifest(
            project_id=loaded.manifest.project_id,
            description=loaded.manifest.description,
            scenario=loaded.manifest.scenario,
            routes=loaded.manifest.routes,
            baseline=loaded.manifest.baseline,
            variants=loaded.manifest.variants,
            experiments=loaded.manifest.experiments + tuple(additions),
        )
        write_project(loaded.path, manifest)
        sys.stdout.write(f"experiments saved: {', '.join(experiment.name for experiment in additions)}\n")
        return 0
    if command == "run":
        return _project_run(args)
    raise InputError(f"unsupported project command: {command}")


def _protect_report_inputs(args: argparse.Namespace) -> None:
    if not getattr(args, "output", None):
        return
    target = Path(_require_cli_text(args.output, "--output"))
    inputs: list[Path] = []
    scanned: list[Path] = []
    for name in ("scenario", "baseline", "routes", "input_dir"):
        raw = getattr(args, name, None)
        if raw is None:
            continue
        source = Path(raw)
        if source.is_dir():
            scanned.append(source)
        else:
            inputs.append(source)
    protect_report_output(target, inputs, scanned)


def _emit(text: str, output: str | None) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    atomic_write_text(Path(_require_cli_text(output, "--output")), text)


def _read_scanned_scenario(path: Path, expected: os.stat_result):
    """Read the same regular scenario file observed during batch discovery."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat_module.S_ISREG(opened.st_mode) or not os.path.samestat(expected, opened):
            raise InputError("batch input changed while being read")
        with os.fdopen(descriptor, "rb") as scenario_file:
            descriptor = None
            raw = scenario_file.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputError("batch input changed while being read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return parse_scenario(parse_json_bytes(raw))


def _batch(input_dir: str, recursive: bool, include_paths: bool) -> dict[str, object]:
    displayed = Path(_require_cli_text(input_dir, "input_dir"))
    root = displayed.resolve()
    if not root.is_dir():
        raise InputError(f"batch input_dir must be a directory: {displayed}")
    iterator = root.rglob("*") if recursive else root.iterdir()
    paths: list[tuple[Path, os.stat_result]] = []
    over_limit = False
    for path in iterator:
        if len(paths) > MAX_BATCH_SCENARIOS:
            # Stop reading the directory as soon as the budget is exceeded.
            # The full enumeration in the previous implementation allocated
            # a Path, an os.stat_result, and a resolve() syscall per entry
            # before raising, which is hostile to large directories on
            # Windows. Mirror the TraceCanary bound pattern from PR #18.
            over_limit = True
            break
        if not path.name.lower().endswith(".json"):
            continue
        try:
            metadata = os.lstat(path)
        except OSError:
            continue
        if not stat_module.S_ISREG(metadata.st_mode):
            continue
        try:
            if not path.resolve().is_relative_to(root):
                continue
        except OSError:
            continue
        paths.append((path, metadata))
    paths.sort(
        key=lambda entry: (
            entry[0].relative_to(root).as_posix().casefold(),
            entry[0].relative_to(root).as_posix(),
        ),
    )
    if not paths:
        raise InputError(f"batch input_dir contains no JSON scenario files: {displayed}")
    if over_limit or len(paths) > MAX_BATCH_SCENARIOS:
        raise InputError(f"batch exceeds the {MAX_BATCH_SCENARIOS}-scenario budget")
    items: list[dict[str, object]] = []
    for index, (path, metadata) in enumerate(paths, start=1):
        relative = path.relative_to(root).as_posix()
        try:
            report = evaluate_scenario(_read_scanned_scenario(path, metadata))
            status = "pass"
        except (InputError, OSError, ValueError, DecimalException) as exc:
            report = {"status": "unresolved", "error": f"{relative}: {_failure_text(exc)}"}
            status = "unresolved"
        item: dict[str, object] = {"id": f"scenario-{index:04d}", "status": status, "report": report}
        if include_paths:
            item["path"] = relative
        items.append(item)
    return {"report_version": "corridor-lab.batch/v1", "status": "unresolved" if any(item["status"] == "unresolved" for item in items) else "pass", "items": items}


def _emit_unresolved_batch_errors(batch_report: dict[str, object]) -> None:
    for item in batch_report.get("items", []):
        if not isinstance(item, dict) or item.get("status") != "unresolved":
            continue
        nested = item.get("report")
        detail = nested.get("error") if isinstance(nested, dict) else None
        if not isinstance(detail, str) or not detail.strip():
            detail = "scenario could not be evaluated"
        _write_error(f"{item.get('id', 'scenario')}: {detail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            from .starter import write_starter
            write_starter(Path(_require_cli_text(args.output, "--output")))
            sys.stdout.write("fictional scenario created\n")
            return 0
        if args.command == "validate":
            load_scenario(_require_cli_text(args.scenario, "scenario"))
            sys.stdout.write("valid\n")
            return 0
        _protect_report_inputs(args)
        output_format = resolve_report_format(
            getattr(args, "format", None),
            getattr(args, "output", None),
            _command_formats(args.command),
        )
        if args.command == "batch":
            batch_report = _batch(args.input_dir, args.recursive, args.include_paths)
            _emit(render_report(batch_report, output_format), args.output)
            if batch_report["status"] == "pass":
                return 0
            _emit_unresolved_batch_errors(batch_report)
            return 2
        if args.command == "project":
            return _project(args)
        scenario = load_scenario(_require_cli_text(args.scenario, "scenario"))
        report: dict[str, object]
        if args.command == "cost-ledger":
            report = cost_ledger(scenario)
        elif args.command == "deadline-target":
            report = deadline_target(scenario, args.probability)
        elif args.command == "resolution-quantiles":
            report = resolution_quantiles(scenario, _parse_values(args.probabilities, "--probabilities"))
        elif args.command == "loss-profile":
            report = loss_profile(scenario)
        elif args.command == "feasible-amount":
            report = feasible_amount(scenario)
        elif args.command == "guardrail-headroom":
            report = guardrail_headroom(scenario)
        elif args.command == "outcome-ledger":
            report = outcome_ledger(scenario)
        elif args.command == "deadline-profile":
            report = deadline_profile(scenario)
        elif args.command == "break-even-check":
            report = break_even_check(scenario)
        elif args.command == "diff":
            report = diff_scenarios(load_scenario(_require_cli_text(args.baseline, "--baseline")), scenario)
        elif args.command == "evaluate":
            report = evaluate_scenario(scenario)
        elif args.command == "compare":
            report = compare_routes(scenario.transaction, _load_routes_argument(args.routes), scenario.objective, scenario.scenario_id)
        elif args.command == "sensitivity":
            report = run_sensitivity(
                scenario,
                _require_cli_text(args.parameter, "--parameter"),
                _parse_values(args.values, "--values"),
            )
        elif args.command == "transaction-sweep":
            report = run_transaction_sweep(scenario, args.parameter, _parse_values(args.values))
        elif args.command == "transaction-grid":
            report = run_transaction_grid(scenario, args.parameter_a, _parse_values(args.values_a),
                                          args.parameter_b, _parse_values(args.values_b))
        elif args.command == "stress-grid":
            report = run_stress_grid(
                scenario,
                _require_cli_text(args.parameter_a, "--parameter-a"),
                _parse_values(args.values_a, "--values-a"),
                _require_cli_text(args.parameter_b, "--parameter-b"),
                _parse_values(args.values_b, "--values-b"),
            )
        elif args.command == "pareto":
            if not scenario.routes:
                raise InputError("pareto requires routes embedded in the scenario")
            evaluations = [evaluate_route(route, scenario.transaction) for route in sorted(scenario.routes, key=lambda item: item.route_id)]
            report = {"report_version": "corridor-lab.pareto/v1", "scenario_id": scenario.scenario_id, "fictional": True, "frontier": pareto_frontier(evaluations)}
        else:
            raise InputError(f"unsupported command: {args.command}")
        _emit(render_report(report, output_format), args.output)
        return 0
    except (InputError, OSError, ValueError, DecimalException) as exc:
        _write_error(_failure_text(exc))
        return 2
