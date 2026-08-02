"""Command-line interface for Corridor Lab."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Sequence

from .canonical import MAX_BATCH_SCENARIOS, InputError, atomic_write_text, require_decimal
from .comparison import compare_routes, evaluate_scenario, pareto_frontier
from .model import evaluate_route
from .report import render_report
from .route import load_route
from .scenario import load_scenario
from .sensitivity import run_sensitivity
from .stress import run_stress_grid


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "csv", "markdown"), default="json")
    parser.add_argument("--output", help="write the report to this UTF-8 path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corridorlab", description="Compare fictional payment route scenarios.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a synthetic scenario contract")
    validate.add_argument("scenario")

    evaluate = commands.add_parser("evaluate", help="evaluate routes embedded in a scenario")
    evaluate.add_argument("scenario")
    _add_output_options(evaluate)

    compare = commands.add_parser("compare", help="compare route files against a scenario transaction")
    compare.add_argument("scenario")
    compare.add_argument("--routes", required=True, help="a route JSON file or directory of route JSON files")
    _add_output_options(compare)

    sensitivity = commands.add_parser("sensitivity", help="vary one declared route parameter")
    sensitivity.add_argument("scenario")
    sensitivity.add_argument("--parameter", required=True)
    sensitivity.add_argument("--values", required=True, help="comma-separated decimal values")
    _add_output_options(sensitivity)
    stress = commands.add_parser("stress-grid", help="run an explicit bounded two-parameter stress grid")
    stress.add_argument("scenario")
    stress.add_argument("--parameter-a", required=True)
    stress.add_argument("--values-a", required=True)
    stress.add_argument("--parameter-b", required=True)
    stress.add_argument("--values-b", required=True)
    _add_output_options(stress)
    pareto = commands.add_parser("pareto", help="show the explicit two-metric Pareto frontier")
    pareto.add_argument("scenario")
    pareto.add_argument("--format", choices=("json", "markdown"), default="json")
    pareto.add_argument("--output")
    batch = commands.add_parser("batch", help="evaluate a bounded directory of fictional scenarios")
    batch.add_argument("input_dir")
    batch.add_argument("--recursive", action="store_true")
    batch.add_argument("--include-paths", action="store_true")
    batch.add_argument("--format", choices=("json", "markdown"), default="json")
    batch.add_argument("--output")
    return parser


def _load_routes_argument(value: str) -> list:
    path = Path(value)
    if path.is_file():
        return [load_route(path)]
    if not path.is_dir():
        raise InputError(f"--routes is not a file or directory: {path}")
    files = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".json")
    if not files:
        raise InputError(f"--routes directory contains no JSON files: {path}")
    if len(files) > 64:
        raise InputError("--routes directory exceeds the 64-route budget")
    return [load_route(item) for item in files]


def _parse_values(raw: str) -> list[Decimal]:
    chunks = raw.split(",")
    if not all(chunk.strip() for chunk in chunks):
        raise InputError("--values must be a comma-separated list of decimals")
    return [require_decimal(chunk.strip(), "sensitivity value") for chunk in chunks]


def _emit(text: str, output: str | None) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    atomic_write_text(Path(output), text)


def _batch(input_dir: str, recursive: bool, include_paths: bool) -> dict[str, object]:
    root = Path(input_dir).resolve()
    if not root.is_dir():
        raise InputError("batch input_dir must be a directory")
    iterator = root.rglob("*.json") if recursive else root.glob("*.json")
    paths = sorted(
        (path for path in iterator if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)),
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    )
    if len(paths) > MAX_BATCH_SCENARIOS:
        raise InputError(f"batch exceeds the {MAX_BATCH_SCENARIOS}-scenario budget")
    items: list[dict[str, object]] = []
    for index, path in enumerate(paths, start=1):
        try:
            report = evaluate_scenario(load_scenario(path))
            status = "pass"
        except (InputError, OSError, ValueError, DecimalException):
            report = {"status": "unresolved", "error": "scenario could not be evaluated"}
            status = "unresolved"
        item: dict[str, object] = {"id": f"scenario-{index:04d}", "status": status, "report": report}
        if include_paths:
            item["path"] = path.relative_to(root).as_posix()
        items.append(item)
    return {"report_version": "corridor-lab.batch/v1", "status": "unresolved" if any(item["status"] == "unresolved" for item in items) else "pass", "items": items}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "batch":
            batch_report = _batch(args.input_dir, args.recursive, args.include_paths)
            _emit(render_report(batch_report, args.format), args.output)
            return 0 if batch_report["status"] == "pass" else 2
        scenario = load_scenario(args.scenario)
        if args.command == "validate":
            sys.stdout.write("valid\n")
            return 0
        if args.command == "evaluate":
            report = evaluate_scenario(scenario)
        elif args.command == "compare":
            report = compare_routes(scenario.transaction, _load_routes_argument(args.routes), scenario.objective, scenario.scenario_id)
        elif args.command == "sensitivity":
            report = run_sensitivity(scenario, args.parameter, _parse_values(args.values))
        elif args.command == "stress-grid":
            report = run_stress_grid(scenario, args.parameter_a, _parse_values(args.values_a), args.parameter_b, _parse_values(args.values_b))
        elif args.command == "pareto":
            if not scenario.routes:
                raise InputError("pareto requires routes embedded in the scenario")
            evaluations = [evaluate_route(route, scenario.transaction) for route in sorted(scenario.routes, key=lambda item: item.route_id)]
            report = {"report_version": "corridor-lab.pareto/v1", "scenario_id": scenario.scenario_id, "fictional": True, "frontier": pareto_frontier(evaluations)}
        _emit(render_report(report, args.format), args.output)
        return 0
    except (InputError, OSError, ValueError, DecimalException) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
