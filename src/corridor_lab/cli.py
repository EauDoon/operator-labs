"""Command-line interface for Corridor Lab."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Sequence

from .canonical import InputError, require_decimal
from .comparison import compare_routes, evaluate_scenario
from .report import render_report
from .route import load_route
from .scenario import load_scenario
from .sensitivity import run_sensitivity


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
    path = Path(output)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
        if args.command == "validate":
            sys.stdout.write("valid\n")
            return 0
        if args.command == "evaluate":
            report = evaluate_scenario(scenario)
        elif args.command == "compare":
            report = compare_routes(scenario.transaction, _load_routes_argument(args.routes), scenario.objective, scenario.scenario_id)
        else:
            report = run_sensitivity(scenario, args.parameter, _parse_values(args.values))
        _emit(render_report(report, args.format), args.output)
        return 0
    except (InputError, OSError, ValueError, DecimalException) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
