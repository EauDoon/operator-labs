"""Command-line interface for TraceCanary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract
from tracecanary.fixture import write_bundle
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import UnsafeReportError, build_report, ensure_values_absent, render_human, render_json


EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_UNRESOLVED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracecanary", description="Check synthetic canaries in OTLP/HTTP JSON traces.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a TraceCanary contract")
    validate.add_argument("contract", type=Path)
    validate.add_argument("--format", choices=("human", "json"), default="human")
    check = commands.add_parser("check", help="check one OTLP trace export")
    check.add_argument("--contract", required=True, type=Path)
    check.add_argument("--input", required=True, type=Path)
    check.add_argument("--format", choices=("human", "json"), default="human")
    diff = commands.add_parser("diff", help="compare a baseline and a candidate OTLP trace export")
    diff.add_argument("--contract", required=True, type=Path)
    diff.add_argument("--baseline", required=True, type=Path)
    diff.add_argument("--candidate", required=True, type=Path)
    diff.add_argument("--format", choices=("human", "json"), default="human")
    fixture = commands.add_parser("fixture", help="write synthetic fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    create = fixture_commands.add_parser("create", help="write the synthetic fixture bundle")
    create.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
        else:
            report = diff_traces(contract, _load_trace(args.baseline, contract), _load_trace(args.candidate, contract))
        _print(report, args.format)
        return EXIT_PASS if report["status"] == "pass" else EXIT_REGRESSION if report["status"] == "regression" else EXIT_UNRESOLVED
    except UnsafeReportError:
        return EXIT_UNRESOLVED
    except (ContractError, InputError, OtlpError, ValueError) as exc:
        print(f"TraceCanary: UNRESOLVED: {exc}", file=sys.stderr)
        return EXIT_UNRESOLVED


def _load_trace(path: Path, contract: Contract) -> dict:
    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


def _print(report: dict, output_format: str) -> None:
    print(render_json(report) if output_format == "json" else render_human(report), end="")
