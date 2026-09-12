"""Headless-safe controller for the TraceCanary desktop interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tracecanary.batching import run_batch
from tracecanary.canonical import InputError, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract, parse_contract
from tracecanary.coverage import coverage_report
from tracecanary.fixture import bundle, write_bundle
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
from tracecanary.report import (
    BatchReport,
    Report,
    Status,
    UnsafeReportError,
    Violation,
    build_report,
    ensure_values_absent,
    render_batch_human,
    render_human,
    render_json,
)

EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_UNRESOLVED = 2

GUI001 = "GUI001"
GUI002 = "GUI002"
GUI003 = "GUI003"
GUI004 = "GUI004"
GUI005 = "GUI005"
GUI006 = "GUI006"
GUI007 = "GUI007"
GUI008 = "GUI008"


@dataclass(frozen=True)
class GuiResult:
    """A rendered result that never carries input values or canary values."""

    status: str
    exit_code: int
    human: str
    json: str
    starter_paths: StarterPaths | None = None
    inputs: tuple[Path, ...] = ()
    input_dir: Path | None = None
    mode: str | None = None


@dataclass(frozen=True)
class StarterPaths:
    """Generated synthetic paths that the GUI may place into its selectors."""

    contract: Path
    input: Path
    baseline: Path
    candidate: Path
    sparse: Path
    invalid: Path
    batch_dir: Path


class TraceCanaryController:
    """Run TraceCanary library operations without subprocesses or Tk imports."""

    def validate(self, contract_path: str | Path) -> GuiResult:
        guidance = self._require("validate", (contract_path, GUI001, "Select a contract JSON file before validating."))
        if guidance is not None:
            return guidance
        return self._run("validate", lambda: self._validate(Path(contract_path)), inputs=(Path(contract_path),))

    def check(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        guidance = self._require(
            "check",
            (contract_path, GUI001, "Select a contract JSON file before checking."),
            (input_path, GUI002, "Select an OTLP trace JSON input before checking."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "check",
            lambda: self._check(Path(contract_path), Path(input_path)),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def coverage(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        guidance = self._require(
            "coverage",
            (contract_path, GUI001, "Select a contract JSON file before inspecting coverage."),
            (input_path, GUI002, "Select an OTLP trace JSON input before inspecting coverage."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "coverage",
            lambda: self._coverage(Path(contract_path), Path(input_path)),
            inputs=(Path(contract_path), Path(input_path)),
        )

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
        return self._run(
            "diff",
            lambda: self._diff(Path(contract_path), Path(baseline_path), Path(candidate_path)),
            inputs=(Path(contract_path), Path(baseline_path), Path(candidate_path)),
        )

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
            sparse=directory / "sparse-retention.json",
            invalid=directory / "invalid-export.json",
            batch_dir=directory,
        )
        return self._run(
            "starter",
            lambda: self._create_starter(directory),
            starter_paths=paths,
            failure_code=GUI006,
            failure_message="The selected destination must be an empty directory for synthetic starter files.",
        )

    def inspect(self, contract_path: str | Path) -> GuiResult:
        """Inventory the effective value-free checks declared by the contract."""
        guidance = self._require("inspect-contract", (contract_path, GUI001, "Select a contract JSON file before inspecting it."))
        if guidance is not None:
            return guidance
        return self._run("inspect-contract", lambda: inspect_contract(load_contract(Path(contract_path))), inputs=(Path(contract_path),))

    def control_check(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        """Verify the unsanitized synthetic positive control exercises every canary.

        A pass here only confirms canary exercise; it is never a privacy pass.
        """
        guidance = self._require(
            "control-check",
            (contract_path, GUI001, "Select a contract JSON file before checking the positive control."),
            (input_path, GUI002, "Select an unsanitized synthetic positive control before checking it."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "control-check",
            self._trace_operation(contract_path, input_path, control_check),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def population_gate(self, contract_path: str | Path, input_path: str | Path, scope: str, minimum_text: str) -> GuiResult:
        guidance = self._require(
            "population-gate",
            (contract_path, GUI001, "Select a contract JSON file before gating a population."),
            (input_path, GUI002, "Select an OTLP trace JSON input before gating a population."),
            (minimum_text, GUI007, "Enter an explicit minimum population before gating."),
        )
        if guidance is not None:
            return guidance
        try:
            minimum = int(str(minimum_text).strip())
        except ValueError:
            return self._guidance("population-gate", GUI007, "The population minimum must be a whole number.")
        return self._run(
            "population-gate",
            lambda: population_gate(*self._contract_trace(contract_path, input_path), scope.strip(), minimum),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def dropped_telemetry(self, contract_path: str | Path, input_path: str | Path, require_zero: bool) -> GuiResult:
        guidance = self._require(
            "dropped-telemetry",
            (contract_path, GUI001, "Select a contract JSON file before inspecting dropped telemetry."),
            (input_path, GUI002, "Select an OTLP trace JSON input before inspecting dropped telemetry."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "dropped-telemetry",
            lambda: dropped_telemetry(*self._contract_trace(contract_path, input_path), require_zero=require_zero),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def retention_matrix(self, contract_path: str | Path, input_path: str | Path) -> GuiResult:
        """Locate missing retained fields by value-free structural pointer."""
        guidance = self._require(
            "retention-matrix",
            (contract_path, GUI001, "Select a contract JSON file before locating missing retention."),
            (input_path, GUI002, "Select an OTLP trace JSON input before locating missing retention."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "retention-matrix",
            self._trace_operation(contract_path, input_path, retention_matrix),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def coverage_gate(self, contract_path: str | Path, input_path: str | Path, minimum_ratio: str) -> GuiResult:
        guidance = self._require(
            "coverage-gate",
            (contract_path, GUI001, "Select a contract JSON file before gating coverage."),
            (input_path, GUI002, "Select an OTLP trace JSON input before gating coverage."),
            (minimum_ratio, GUI008, "Enter an explicit minimum retained-field ratio before gating."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "coverage-gate",
            lambda: coverage_gate(*self._contract_trace(contract_path, input_path), minimum_ratio.strip()),
            inputs=(Path(contract_path), Path(input_path)),
        )

    def coverage_diff(self, contract_path: str | Path, baseline_path: str | Path, candidate_path: str | Path) -> GuiResult:
        guidance = self._require(
            "coverage-diff",
            (contract_path, GUI001, "Select a contract JSON file before comparing coverage."),
            (baseline_path, GUI003, "Select a baseline OTLP trace JSON file before comparing coverage."),
            (candidate_path, GUI004, "Select a candidate OTLP trace JSON file before comparing coverage."),
        )
        if guidance is not None:
            return guidance
        return self._run(
            "coverage-diff",
            self._pair_operation(contract_path, baseline_path, candidate_path, coverage_diff),
            inputs=(Path(contract_path), Path(baseline_path), Path(candidate_path)),
        )

    def batch(self, contract_path: str | Path, input_dir: str | Path, *, recursive: bool = False, include_paths: bool = False, baseline_path: str | Path | None = None) -> GuiResult:
        """Check a bounded directory of exports, optionally against a baseline."""
        guidance = self._require(
            "batch",
            (contract_path, GUI001, "Select a contract JSON file before running a batch."),
            (input_dir, GUI008, "Select a directory of OTLP trace JSON exports before running a batch."),
        )
        if guidance is not None:
            return guidance
        return self._run_batch_op(
            "batch",
            lambda: self._batch(Path(contract_path), Path(input_dir), recursive, include_paths, baseline_path),
            contract_path=Path(contract_path),
            input_dir=Path(input_dir),
            baseline_path=None if baseline_path is None else Path(baseline_path),
        )

    def coverage_batch(self, contract_path: str | Path, input_dir: str | Path, *, recursive: bool = False, include_paths: bool = False, minimum_ratio: str | None = None) -> GuiResult:
        """Aggregate coverage counts across a bounded directory of exports."""
        guidance = self._require(
            "coverage-batch",
            (contract_path, GUI001, "Select a contract JSON file before aggregating coverage."),
            (input_dir, GUI008, "Select a directory of OTLP trace JSON exports before aggregating coverage."),
        )
        if guidance is not None:
            return guidance
        return self._run_batch_op(
            "coverage-batch",
            lambda: run_batch(load_contract(Path(contract_path)), Path(input_dir), recursive, include_paths, None, coverage=True, minimum_ratio=minimum_ratio),
            contract_path=Path(contract_path),
            input_dir=Path(input_dir),
            baseline_path=None,
        )

    def _batch(self, contract_path: Path, input_dir: Path, recursive: bool, include_paths: bool, baseline_path: str | Path | None) -> BatchReport:
        contract = load_contract(contract_path)
        baseline = self._load_trace(Path(baseline_path), contract) if baseline_path is not None and str(baseline_path).strip() else None
        return run_batch(contract, input_dir, recursive, include_paths, baseline)

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

    def _contract_trace(self, contract_path: str | Path, input_path: str | Path) -> tuple[Contract, dict[str, Any]]:
        contract = load_contract(Path(contract_path))
        return contract, self._load_trace(Path(input_path), contract)

    def _trace_operation(self, contract_path: str | Path, input_path: str | Path, analysis) -> Callable[[], Report]:
        def operation() -> Report:
            contract, trace = self._contract_trace(contract_path, input_path)
            return analysis(contract, trace)

        return operation

    def _pair_operation(self, contract_path: str | Path, baseline_path: str | Path, candidate_path: str | Path, analysis) -> Callable[[], Report]:
        def operation() -> Report:
            contract = load_contract(Path(contract_path))
            baseline = self._load_trace(Path(baseline_path), contract)
            candidate = self._load_trace(Path(candidate_path), contract)
            return analysis(contract, baseline, candidate)

        return operation

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
        inputs: tuple[Path, ...] = (),
        failure_code: str = GUI005,
        failure_message: str = "The selected files could not be analyzed. Check that they are readable supported JSON files.",
    ) -> GuiResult:
        try:
            report = operation()
        except UnsafeReportError:
            return GuiResult("unresolved", EXIT_UNRESOLVED, "", "", mode=mode)
        except (ContractError, InputError, OtlpError, OSError, ValueError) as exc:
            return self._guidance(mode, failure_code, self._failure_text(failure_message, exc))
        status = report["status"]
        return GuiResult(
            status,
            _exit_code(status),
            render_human(report),
            render_json(report),
            starter_paths,
            inputs,
            None,
            mode,
        )

    def _run_batch_op(
        self,
        mode: str,
        operation: Callable[[], BatchReport],
        *,
        contract_path: Path,
        input_dir: Path,
        baseline_path: Path | None = None,
        failure_code: str = GUI005,
        failure_message: str = "The selected batch directory could not be analyzed. Check that it is a readable directory of supported JSON files.",
    ) -> GuiResult:
        inputs: tuple[Path, ...] = (contract_path,) + ((baseline_path,) if baseline_path is not None else ())
        try:
            report = operation()
        except UnsafeReportError:
            return GuiResult("unresolved", EXIT_UNRESOLVED, "", "", inputs=inputs, input_dir=input_dir, mode=mode)
        except (ContractError, InputError, OtlpError, OSError, ValueError) as exc:
            return self._guidance(mode, failure_code, self._failure_text(failure_message, exc))
        status = report["status"]
        return GuiResult(
            status,
            _exit_code(status),
            render_batch_human(report),
            render_json(report),
            None,
            inputs,
            input_dir,
            mode,
        )

    @staticmethod
    def _failure_text(default: str, exc: BaseException) -> str:
        """Keep the fixed guidance and the CLI-level diagnostic together."""
        detail = str(exc).strip()
        return f"{default} ({detail})" if detail and detail != default else default

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
