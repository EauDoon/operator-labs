"""Headless-safe controller for the TraceCanary desktop interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.coverage import coverage_report
from tracecanary.contract import Contract, ContractError, load_contract, parse_contract
from tracecanary.fixture import bundle, write_bundle
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import Report, Status, UnsafeReportError, Violation, build_report, ensure_values_absent, render_human, render_json


EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_UNRESOLVED = 2

GUI001 = "GUI001"
GUI002 = "GUI002"
GUI003 = "GUI003"
GUI004 = "GUI004"
GUI005 = "GUI005"
GUI006 = "GUI006"


@dataclass(frozen=True)
class GuiResult:
    """A rendered result that never carries input values or canary values."""

    status: str
    exit_code: int
    human: str
    json: str
    starter_paths: StarterPaths | None = None


@dataclass(frozen=True)
class StarterPaths:
    """Generated synthetic paths that the GUI may place into its selectors."""

    contract: Path
    input: Path
    baseline: Path
    candidate: Path


class TraceCanaryController:
    """Run TraceCanary library operations without subprocesses or Tk imports."""

    def validate(self, contract_path: str | Path) -> GuiResult:
        guidance = self._require("validate", (contract_path, GUI001, "Select a contract JSON file before validating."))
        if guidance is not None:
            return guidance
        return self._run("validate", lambda: self._validate(Path(contract_path)))

    def check(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        guidance = self._require(
            "check",
            (contract_path, GUI001, "Select a contract JSON file before checking."),
            (input_path, GUI002, "Select an OTLP trace JSON input before checking."),
        )
        if guidance is not None:
            return guidance
        return self._run("check", lambda: self._check(Path(contract_path), Path(input_path)))

    def coverage(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        guidance = self._require(
            "coverage",
            (contract_path, GUI001, "Select a contract JSON file before inspecting coverage."),
            (input_path, GUI002, "Select an OTLP trace JSON input before inspecting coverage."),
        )
        if guidance is not None:
            return guidance
        return self._run("coverage", lambda: self._coverage(Path(contract_path), Path(input_path)))

    def _coverage(self, contract_path: Path, input_path: Path) -> Report:
        contract = load_contract(contract_path)
        return coverage_report(contract, self._load_trace(input_path, contract))

    def diff(self, contract_path: str | Path, baseline_path: str | Path, candidate_path: str | Path) -> GuiResult:
        guidance = self._require(
            "diff",
            (contract_path, GUI001, "Select a contract JSON file before comparing."),
            (baseline_path, GUI003, "Select a baseline OTLP trace JSON file before comparing."),
            (candidate_path, GUI004, "Select a candidate OTLP trace JSON file before comparing."),
        )
        if guidance is not None:
            return guidance
        return self._run("diff", lambda: self._diff(Path(contract_path), Path(baseline_path), Path(candidate_path)))

    def built_in_demo(self) -> GuiResult:
        """Check a safe synthetic trace entirely in memory, with no file writes."""
        return self._run("demo", self._demo)

    def create_starter_files(self, destination: str | Path) -> GuiResult:
        """Write the explicit synthetic starter bundle and return its useful paths."""
        guidance = self._require("starter", (destination, GUI006, "Select an empty destination directory for synthetic starter files."))
        if guidance is not None:
            return guidance
        directory = Path(destination)
        paths = StarterPaths(
            contract=directory / "contract.json",
            input=directory / "safe-export.json",
            baseline=directory / "safe-export.json",
            candidate=directory / "missing-operational-fields.json",
        )
        return self._run(
            "starter",
            lambda: self._create_starter(directory),
            starter_paths=paths,
            failure_code=GUI006,
            failure_message="The selected destination must be an empty directory for synthetic starter files.",
        )

    def _validate(self, contract_path: Path) -> Report:
        contract = load_contract(contract_path)
        report = build_report(contract.contract_version, "pass", [], mode="validate")
        ensure_values_absent(report, tuple(canary.value for canary in contract.canaries))
        return report

    def _check(self, contract_path: Path, input_path: Path) -> Report:
        contract = load_contract(contract_path)
        return check_trace(contract, self._load_trace(input_path, contract), mode="check")

    def _diff(self, contract_path: Path, baseline_path: Path, candidate_path: Path) -> Report:
        contract = load_contract(contract_path)
        return diff_traces(contract, self._load_trace(baseline_path, contract), self._load_trace(candidate_path, contract))

    def _demo(self) -> Report:
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        validate_trace(payload)
        return check_trace(contract, payload, mode="demo")

    @staticmethod
    def _create_starter(destination: Path) -> Report:
        write_bundle(destination)
        return build_report("tracecanary/v1", "pass", [], mode="starter")

    @staticmethod
    def _load_trace(path: Path, contract: Contract) -> dict[str, Any]:
        payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
        validate_trace(payload)
        return payload

    def _require(self, mode: str, *selections: tuple[str | Path, str, str]) -> GuiResult | None:
        for value, code, message in selections:
            if not str(value).strip():
                return self._guidance(mode, code, message)
        return None

    def _run(
        self,
        mode: str,
        operation: Callable[[], Report],
        *,
        starter_paths: StarterPaths | None = None,
        failure_code: str = GUI005,
        failure_message: str = "The selected files could not be analyzed. Check that they are readable supported JSON files.",
    ) -> GuiResult:
        try:
            report = operation()
        except UnsafeReportError:
            return GuiResult("unresolved", EXIT_UNRESOLVED, "", "")
        except (ContractError, InputError, OtlpError, OSError, ValueError):
            return self._guidance(mode, failure_code, failure_message)
        status = report["status"]
        return GuiResult(status, _exit_code(status), render_human(report), render_json(report), starter_paths)

    @staticmethod
    def _guidance(mode: str, code: str, message: str) -> GuiResult:
        report = build_report("tracecanary/v1", "unresolved", [Violation(code, "", message)], mode=mode)
        return GuiResult("unresolved", EXIT_UNRESOLVED, render_human(report), render_json(report))


def _exit_code(status: Status) -> int:
    if status == "pass":
        return EXIT_PASS
    if status == "regression":
        return EXIT_REGRESSION
    return EXIT_UNRESOLVED
