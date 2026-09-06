"""Command-line interface for Corridor Lab."""

from __future__ import annotations

import argparse
import os
import stat as stat_module
import sys
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Mapping, Sequence

from .canonical import (
    MAX_BATCH_SCENARIOS,
    MAX_INPUT_BYTES,
    InputError,
    atomic_write_text,
    load_json,
    parse_json_bytes,
    require_decimal_values,
)
from .comparison import compare_routes, evaluate_scenario, pareto_frontier
from .funding import run_funding
from .model import evaluate_route
from .report import render_report
from .route import SENSITIVITY_PARAMETERS, Route, load_route, load_route_folder
from .scenario import load_scenario, parse_scenario
from .diff import diff_scenario_files
from .revisions import RevisionError, list_revisions, revision_path, save_revision
from .sensitivity import run_sensitivity
from .stress import run_stress_grid
from .templates import TEMPLATE_KINDS, describe_all, template, template_ids, write_template
from .workload import break_even_workloads, run_workload

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

    templates = commands.add_parser("templates", help="list, show, or create synthetic templates")
    template_commands = templates.add_subparsers(dest="template_command", required=True)
    list_templates = template_commands.add_parser("list", help="list the shipped synthetic templates")
    list_templates.add_argument("--kind", choices=TEMPLATE_KINDS, help="restrict the listing to one template kind")
    list_templates.add_argument("--format", choices=("human", "json"), default="human", help="output format (default: human)")
    list_templates.add_argument("--output", help="write the listing to this UTF-8 path")
    show_template = template_commands.add_parser("show", help="show one synthetic template")
    show_template.add_argument("--template", required=True, help="template id")
    show_template.add_argument("--output", help="write the description to this UTF-8 path")
    create_template = template_commands.add_parser("create", help="write a synthetic template to a chosen path")
    create_template.add_argument("--template", required=True, help="template id")
    create_template.add_argument("--output", required=True, help="path for the new template file")

    revision = commands.add_parser("revision", help="manage explicitly saved scenario revisions")
    revision_commands = revision.add_subparsers(dest="revision_command", required=True)
    revision_save = revision_commands.add_parser("save", help="validate a scenario and save it as the next revision")
    revision_save.add_argument("scenario")
    revision_save.add_argument("--folder", required=True, help="existing revision folder")
    revision_list = revision_commands.add_parser("list", help="list the revisions in a folder")
    revision_list.add_argument("--folder", required=True, help="existing revision folder")
    _add_output_options(revision_list, formats=FRONTIER_REPORT_FORMATS)

    scenario_diff = commands.add_parser("scenario-diff", help="compare two explicitly selected scenario files")
    scenario_diff.add_argument("before")
    scenario_diff.add_argument("after")
    _add_output_options(scenario_diff)

    validate = commands.add_parser("validate", help="validate a synthetic scenario contract")
    _add_scenario_argument(validate)

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
    stress = commands.add_parser("stress-grid", help="run an explicit bounded two-parameter stress grid")
    _add_scenario_argument(stress)
    stress.add_argument("--parameter-a", required=True, help=PARAMETER_HELP)
    stress.add_argument("--values-a", required=True, help=VALUES_HELP)
    stress.add_argument("--parameter-b", required=True, help=PARAMETER_HELP)
    stress.add_argument("--values-b", required=True, help=VALUES_HELP)
    _add_output_options(stress)
    workload = commands.add_parser("workload", help="re-evaluate routes under declared transaction volumes")
    workload.add_argument("scenario")
    workload.add_argument("--workloads", help="comma-separated declared workload ids (default: every declared workload)")
    _add_output_options(workload)
    funding = commands.add_parser("funding", help="evaluate declared multi-period funding and liquidity")
    funding.add_argument("scenario")
    funding.add_argument("--delays", help="comma-separated declared recovery delays in periods (default: the schedule's own value)")
    _add_output_options(funding)
    break_even = commands.add_parser("break-even", help="explore where two routes cross across declared workloads")
    break_even.add_argument("scenario")
    break_even.add_argument("--left", required=True, help="first route id")
    break_even.add_argument("--right", required=True, help="second route id")
    break_even.add_argument("--workloads", help="comma-separated declared workload ids (default: every declared workload)")
    _add_output_options(break_even, formats=FRONTIER_REPORT_FORMATS)
    pareto = commands.add_parser("pareto", help="show the explicit two-metric Pareto frontier")
    _add_scenario_argument(pareto)
    _add_output_options(pareto, formats=FRONTIER_REPORT_FORMATS)
    batch = commands.add_parser("batch", help="evaluate a bounded directory of fictional scenarios")
    batch.add_argument("input_dir", help="directory of fictional scenario JSON files")
    batch.add_argument("--recursive", action="store_true", help="include JSON files in subdirectories")
    batch.add_argument("--include-paths", action="store_true", help="add each scenario's relative path to the batch report")
    _add_output_options(batch, formats=FRONTIER_REPORT_FORMATS)
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


def _parse_delays(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    chunks = raw.split(",")
    if not all(chunk.strip() for chunk in chunks):
        raise InputError("--delays must be a comma-separated list of whole periods")
    parsed: list[int] = []
    for chunk in chunks:
        try:
            parsed.append(int(chunk.strip()))
        except ValueError as exc:
            raise InputError("--delays must contain whole numbers of periods") from exc
    return parsed


def _run_templates(args: argparse.Namespace) -> int:
    if args.template_command == "list":
        entries = describe_all(args.kind)
        if args.format == "json":
            _emit(_canonical({"templates": entries}), args.output)
        else:
            _emit(_template_listing_text(entries), args.output)
        return 0
    if args.template_command == "show":
        _emit(_canonical(_template_text(args.template)), args.output)
        return 0
    path = write_template(args.template, _require_cli_text(args.output, "--output"))
    sys.stdout.write(f"Template {args.template} written to {path}\n")
    return 0


def _canonical(value: dict[str, object]) -> str:
    from .canonical import canonical_dumps

    return canonical_dumps(value)


def _template_listing_text(entries: list[dict[str, object]]) -> str:
    lines = ["Corridor Lab templates", ""]
    for entry in entries:
        lines.append(f"- {entry['template_id']} [{entry['kind']}]: {entry['title']}")
    lines.extend(["", "All template values are fictional. Use `templates show --template ID` for detail."])
    return "\n".join(lines) + "\n"


def _template_text(template_id: str) -> dict[str, object]:
    from .templates import describe

    return describe(template_id)


def _run_revision(args: argparse.Namespace) -> int:
    folder = Path(_require_cli_text(args.folder, "--folder"))
    if args.revision_command == "list":
        entries = list_revisions(folder)
        output_format = resolve_report_format(getattr(args, "format", None), getattr(args, "output", None), FRONTIER_REPORT_FORMATS)
        if output_format == "json":
            _emit(_canonical({"revisions": entries}), args.output)
        else:
            lines = ["Corridor Lab revisions", ""]
            lines.extend(f"- {item['name']} ({item['scenario_id']})" for item in entries)
            _emit("\n".join(lines) + "\n" if entries else "No revisions in this folder.\n", args.output)
        return 0
    document = load_json(Path(_require_cli_text(args.scenario, "scenario")))
    from .scenario import parse_scenario

    parsed = parse_scenario(document)
    target = save_revision(folder, document)
    sys.stdout.write(f"Revision saved: {target} ({parsed.scenario_id})\n")
    return 0


def _parse_workload_ids(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    chunks = raw.split(",")
    if not all(chunk.strip() for chunk in chunks):
        raise InputError("--workloads must be a comma-separated list of declared workload ids")
    return [chunk.strip() for chunk in chunks]


def _parse_values(raw: str, flag: str = "--values") -> list[Decimal]:
    chunks = raw.split(",")
    if not all(chunk.strip() for chunk in chunks):
        raise InputError(f"{flag} must be a comma-separated list of decimals")
    return require_decimal_values([chunk.strip() for chunk in chunks], flag)


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
        if args.command == "validate":
            load_scenario(_require_cli_text(args.scenario, "scenario"))
            sys.stdout.write("valid\n")
            return 0
        if args.command == "templates":
            return _run_templates(args)
        if args.command == "revision":
            return _run_revision(args)
        if args.command == "scenario-diff":
            scenario_diff_format = resolve_report_format(
                getattr(args, "format", None), getattr(args, "output", None), TABULAR_REPORT_FORMATS
            )
            report = diff_scenario_files(
                _require_cli_text(args.before, "before"), _require_cli_text(args.after, "after")
            )
            _emit(render_report(report, scenario_diff_format), args.output)
            return 0
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
        scenario = load_scenario(_require_cli_text(args.scenario, "scenario"))
        report: dict[str, object]
        if args.command == "evaluate":
            report = evaluate_scenario(scenario)
        elif args.command == "compare":
            report = compare_routes(scenario.transaction, _load_routes_argument(args.routes), scenario.objective, scenario.scenario_id)
        elif args.command == "sensitivity":
            report = run_sensitivity(
                scenario,
                _require_cli_text(args.parameter, "--parameter"),
                _parse_values(args.values, "--values"),
            )
        elif args.command == "stress-grid":
            report = run_stress_grid(
                scenario,
                _require_cli_text(args.parameter_a, "--parameter-a"),
                _parse_values(args.values_a, "--values-a"),
                _require_cli_text(args.parameter_b, "--parameter-b"),
                _parse_values(args.values_b, "--values-b"),
            )
        elif args.command == "workload":
            report = run_workload(scenario, _parse_workload_ids(getattr(args, "workloads", None)))
        elif args.command == "funding":
            report = run_funding(scenario, _parse_delays(getattr(args, "delays", None)))
        elif args.command == "break-even":
            report = break_even_workloads(
                scenario,
                _require_cli_text(args.left, "--left"),
                _require_cli_text(args.right, "--right"),
                _parse_workload_ids(getattr(args, "workloads", None)),
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
    except RevisionError as exc:
        _write_error(_failure_text(exc))
        return 2
    except (InputError, OSError, ValueError, DecimalException) as exc:
        _write_error(_failure_text(exc))
        return 2
