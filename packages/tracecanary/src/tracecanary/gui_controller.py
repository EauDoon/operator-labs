"""Headless-safe controller for the TraceCanary desktop interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from tracecanary import batch_pairs, contract_diff, findings
from tracecanary.canonical import InputError, canonical_json, load_json
from tracecanary.checker import check_trace
from tracecanary.comparison import diff_traces
from tracecanary.contract import Contract, ContractError, load_contract, parse_contract
from tracecanary.fixture import bundle, write_bundle
from tracecanary.history import DEFAULT_HISTORY_BOUND, UNKNOWN_CONTRACT_VERSION, RunHistory, RunRecord, RunReport
from tracecanary.otlp import OtlpError, validate_trace
from tracecanary.report import (
    BatchReport,
    Report,
    ReportMode,
    Status,
    UnsafeReportError,
    Violation,
    build_report,
    ensure_object_values_absent,
    ensure_text_values_absent,
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
GUI009 = "GUI009"
GUI010 = "GUI010"
GUI011 = "GUI011"


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
    """Run TraceCanary library operations without subprocesses or Tk imports.

    The controller owns an in-memory :class:`RunHistory`. Every analysis run is
    recorded there so the desktop window can show what happened in this session.
    The history is not persisted: closing the window discards it.
    """

    def __init__(self, *, history_bound: int = DEFAULT_HISTORY_BOUND) -> None:
        self._history = RunHistory(history_bound)
        self._last_report: RunReport | None = None
        self._last_values: tuple[str, ...] = ()

    def validate(self, contract_path: str | Path, *, group: str | None = None) -> GuiResult:
        guidance = self._require(
            "validate",
            (contract_path, GUI001, "Select a contract JSON file before validating."),
            record=True,
        )
        if guidance is not None:
            return guidance
        return self._run("validate", lambda: self._validate(Path(contract_path)), record=True, group=group)

    def check(self, contract_path: str | Path, input_path: str | Path, *, group: str | None = None) -> GuiResult:
        guidance = self._require(
            "check",
            (contract_path, GUI001, "Select a contract JSON file before checking."),
            (input_path, GUI002, "Select an OTLP trace JSON input before checking."),
            record=True,
        )
        if guidance is not None:
            return guidance
        return self._run("check", lambda: self._check(Path(contract_path), Path(input_path)), record=True, group=group)

    def diff(self, contract_path: str | Path, baseline_path: str | Path, candidate_path: str | Path, *, group: str | None = None) -> GuiResult:
        guidance = self._require(
            "diff",
            (contract_path, GUI001, "Select a contract JSON file before comparing."),
            (baseline_path, GUI003, "Select a baseline OTLP trace JSON file before comparing."),
            (candidate_path, GUI004, "Select a candidate OTLP trace JSON file before comparing."),
            record=True,
        )
        if guidance is not None:
            return guidance
        return self._run("diff", lambda: self._diff(Path(contract_path), Path(baseline_path), Path(candidate_path)), record=True, group=group)

    def batch_diff(
        self,
        contract_path: str | Path,
        baseline_dir: str | Path,
        candidate_dir: str | Path,
        *,
        pairing: str = batch_pairs.DEFAULT_PAIRING,
        recursive: bool = False,
        include_paths: bool = False,
        group: str | None = None,
    ) -> GuiResult:
        """Diff two directories under one of the two explicit pairing rules."""
        guidance = self._require(
            "batch-diff",
            (contract_path, GUI001, "Select a contract JSON file before comparing directories."),
            (baseline_dir, GUI007, "Select a baseline directory of OTLP trace JSON files before comparing directories."),
            (candidate_dir, GUI008, "Select a candidate directory of OTLP trace JSON files before comparing directories."),
            record=True,
        )
        if guidance is not None:
            return guidance
        return self._run(
            "batch-diff",
            lambda: self._batch_diff(Path(contract_path), Path(baseline_dir), Path(candidate_dir), pairing, recursive, include_paths),
            record=True,
            group=group,
            failure_code=GUI009,
            failure_message="The two directories could not be paired and compared. Pairing is never guessed: every baseline file needs exactly one candidate file.",
        )

    def contract_review(self, before_path: str | Path, after_path: str | Path) -> GuiResult:
        """Review how a contract change alters checking coverage.

        A review is not a trace run, so it is rendered but not recorded in the
        run history: the history exists to answer what happened to traces.
        """
        guidance = self._require(
            "contract-review",
            (before_path, GUI010, "Select the previous contract JSON file before reviewing."),
            (after_path, GUI011, "Select the updated contract JSON file before reviewing."),
        )
        if guidance is not None:
            return guidance
        return self._review(Path(before_path), Path(after_path))

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

    def summary(self, report: Report | BatchReport, *, redacted_values: tuple[str, ...] = ()) -> str:
        """Render a deterministic summary panel for one report."""
        return findings.render_summary(report, redacted_values=redacted_values)

    def explain(self, report: Report | BatchReport, *, redacted_values: tuple[str, ...] = ()) -> str:
        """Render a deterministic explanation for one report."""
        return findings.explain(report, redacted_values=redacted_values)

    def last_report(self) -> RunReport | None:
        """Return the report of the most recent run, or None when nothing ran."""
        return self._last_report

    def last_summary(self) -> str:
        """Render the summary of the most recent run, or an empty string."""
        if self._last_report is None:
            return ""
        return self.summary(self._last_report, redacted_values=self._last_values)

    def last_explanation(self) -> str:
        """Render the explanation of the most recent run, or an empty string."""
        if self._last_report is None:
            return ""
        return self.explain(self._last_report, redacted_values=self._last_values)

    def history_records(self) -> tuple[RunRecord, ...]:
        """Return the in-memory run records in insertion order."""
        return self._history.records()

    def clear_history(self) -> None:
        """Discard the in-memory run history. This cannot be undone."""
        self._history.clear()

    def export_history(self, *, redacted_values: tuple[str, ...] = ()) -> str:
        """Return the run history as deterministic canonical JSON.

        The caller decides where, if anywhere, the text is written. The export is
        rejected if any recorded run could carry a matched value into it.
        """
        return self._history.export(redacted_values=redacted_values)

    def _validate(self, contract_path: Path) -> tuple[Report, tuple[str, ...]]:
        contract = load_contract(contract_path)
        report = build_report(contract.contract_version, "pass", [], mode="validate")
        ensure_object_values_absent(report, self._values(contract))
        return report, self._values(contract)

    def _check(self, contract_path: Path, input_path: Path) -> tuple[Report, tuple[str, ...]]:
        contract = load_contract(contract_path)
        return check_trace(contract, self._load_trace(input_path, contract), mode="check"), self._values(contract)

    def _diff(self, contract_path: Path, baseline_path: Path, candidate_path: Path) -> tuple[Report, tuple[str, ...]]:
        contract = load_contract(contract_path)
        report = diff_traces(contract, self._load_trace(baseline_path, contract), self._load_trace(candidate_path, contract))
        return report, self._values(contract)

    def _batch_diff(
        self,
        contract_path: Path,
        baseline_dir: Path,
        candidate_dir: Path,
        pairing: str,
        recursive: bool,
        include_paths: bool,
    ) -> tuple[BatchReport, tuple[str, ...]]:
        contract = load_contract(contract_path)
        report = batch_pairs.batch_diff(
            contract,
            baseline_dir,
            candidate_dir,
            pairing=pairing,
            recursive=recursive,
            include_paths=include_paths,
            redacted_values=self._values(contract),
        )
        return report, self._values(contract)

    def _review(self, before_path: Path, after_path: Path) -> GuiResult:
        try:
            previous = load_contract(before_path)
            current = load_contract(after_path)
            values = tuple(dict.fromkeys((*self._values(previous), *self._values(current))))
            review = contract_diff.review_contract_change(previous, current, redacted_values=values)
            human = contract_diff.render_contract_review_human(review, redacted_values=values)
        except UnsafeReportError:
            return GuiResult("unresolved", EXIT_UNRESOLVED, "", "")
        except (ContractError, InputError, OSError, ValueError):
            return self._guidance(
                "contract-review",
                GUI009,
                "The two contracts could not be reviewed. Check that both are readable supported TraceCanary contract files.",
            )
        ensure_text_values_absent(human, values)
        outcome: dict[str, Any] = {"review": review, "human": human}
        ensure_object_values_absent(outcome, values)
        status = "regression" if review["verdict"] == contract_diff.REDUCED else "pass"
        return GuiResult(status, _exit_code(cast(Status, status)), human, canonical_json(review))

    def _demo(self) -> tuple[Report, tuple[str, ...]]:
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        validate_trace(payload)
        return check_trace(contract, payload, mode="demo"), self._values(contract)

    @staticmethod
    def _create_starter(destination: Path) -> tuple[Report, tuple[str, ...]]:
        write_bundle(destination)
        return build_report("tracecanary/v1", "pass", [], mode="starter"), ()

    @staticmethod
    def _values(contract: Contract) -> tuple[str, ...]:
        return tuple(canary.value for canary in contract.canaries)

    @staticmethod
    def _load_trace(path: Path, contract: Contract) -> dict[str, Any]:
        payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
        validate_trace(payload)
        return payload

    def _require(self, mode: str, *selections: tuple[str | Path, str, str], record: bool = False) -> GuiResult | None:
        for value, code, message in selections:
            if not str(value).strip():
                return self._guidance(mode, code, message, record=record)
        return None

    def _record(self, mode: str, report: Report | BatchReport, values: tuple[str, ...], group: str | None = None) -> None:
        """Record one run, clearing the oldest records only when the bound is hit.

        Losing history is strictly better than failing an analysis that already
        produced a result, so the controller clears rather than raises here.
        """
        if self._history.is_full():
            self._history.clear()
        summary = dict(report["summary"]) if "summary" in report else findings.summarize(report, redacted_values=values)
        try:
            self._history.append(
                mode=mode,
                contract_version=str(report.get("contract_version", UNKNOWN_CONTRACT_VERSION)),
                status=findings.report_status(report),
                summary=summary,
                report=report,
                group=group,
                redacted_values=values,
            )
        except InputError:
            return

    def _run(
        self,
        mode: str,
        operation: Callable[[], tuple[RunReport, tuple[str, ...]]],
        *,
        record: bool = False,
        group: str | None = None,
        starter_paths: StarterPaths | None = None,
        failure_code: str = GUI005,
        failure_message: str = "The selected files could not be analyzed. Check that they are readable supported JSON files.",
    ) -> GuiResult:
        try:
            report, values = operation()
        except UnsafeReportError:
            if record:
                self._record(mode, self._guidance_report(mode, failure_code, failure_message), (), group)
            return GuiResult("unresolved", EXIT_UNRESOLVED, "", "")
        except (ContractError, InputError, OtlpError, OSError, ValueError):
            return self._guidance(mode, failure_code, failure_message, record=record, group=group)
        if record:
            self._record(mode, report, values, group)
        self._last_report = report
        self._last_values = values
        status = report["status"]
        rendered = _render(report)
        return GuiResult(status, _exit_code(status), rendered[0], rendered[1], starter_paths)

    def _guidance_report(self, mode: str, code: str, message: str) -> Report:
        return build_report(
            UNKNOWN_CONTRACT_VERSION,
            "unresolved",
            [Violation(code, "", message)],
            mode=cast(ReportMode, mode),
        )

    def _guidance(
        self,
        mode: str,
        code: str,
        message: str,
        *,
        record: bool = False,
        group: str | None = None,
    ) -> GuiResult:
        report = self._guidance_report(mode, code, message)
        if record:
            self._record(mode, report, (), group)
        return GuiResult("unresolved", EXIT_UNRESOLVED, render_human(report), render_json(report))


def _render(report: RunReport) -> tuple[str, str]:
    if "items" in report:
        return batch_pairs.render_batch_human(report), render_json(report)
    return render_human(report), render_json(report)


def _exit_code(status: Status) -> int:
    if status == "pass":
        return EXIT_PASS
    if status == "regression":
        return EXIT_REGRESSION
    return EXIT_UNRESOLVED
