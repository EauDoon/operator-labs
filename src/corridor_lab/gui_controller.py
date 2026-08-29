"""Headless-safe controller for the optional Corridor Lab desktop interface."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from pathlib import Path

from .canonical import MAX_ROUTES, InputError, atomic_write_text, parse_json_bytes, read_bounded_bytes, require_decimal
from .comparison import compare_routes, evaluate_scenario, pareto_frontier
from .model import evaluate_route
from .report import render_report
from .route import Route, load_route
from .scenario import Scenario, parse_scenario, parse_scenario_text
from .sensitivity import run_sensitivity
from .stress import run_stress_grid


BUILTIN_DEMO_SCENARIO = {
    "contract_version": "corridor-lab.scenario/v1",
    "scenario_id": "fictional-gui-amber-to-birch",
    "description": "A built-in fictional GUI demonstration with invented values.",
    "fictional": True,
    "transaction": {
        "send_amount": "1000.00",
        "send_currency": "AMR",
        "send_precision": 2,
        "receive_currency": "BRC",
        "receive_precision": 2,
        "rounding": "ROUND_HALF_UP",
        "deadline_hours": "8",
        "volume_per_period": "100",
    },
    "objective": {
        "metric": "maximize_expected_recipient_amount",
        "guardrails": {"minimum_probability_by_deadline": "0.80", "maximum_tail_hours": "24"},
    },
    "routes": [
        {
            "contract_version": "corridor-lab.route/v1",
            "route_id": "fictional-gui-linked-instant",
            "label": "Linked instant-payment demonstration route (fictional)",
            "fictional": True,
            "fx_rate": "1.7500",
            "fixed_fee_send": "3.00",
            "percent_fee_bps": "30",
            "fx_spread_bps": "75",
            "liquidity": {
                "prefunding_amount_send": "6500",
                "annual_cost_of_capital_bps": "650",
                "holding_days": "1.4",
            },
            "outcomes": [
                {"outcome_id": "on-time", "probability": "0.94", "completion": "success", "delay_hours": "1.5", "recovery_amount_send": "0", "recovery_delay_hours": "0"},
                {"outcome_id": "late-success", "probability": "0.04", "completion": "success", "delay_hours": "8", "recovery_amount_send": "0", "recovery_delay_hours": "0"},
                {"outcome_id": "failed-recovered", "probability": "0.02", "completion": "failure", "delay_hours": "2", "recovery_amount_send": "980", "recovery_delay_hours": "12"},
            ],
        },
        {
            "contract_version": "corridor-lab.route/v1",
            "route_id": "fictional-gui-tokenized-deposit",
            "label": "Tokenized-deposit demonstration route (fictional)",
            "fictional": True,
            "fx_rate": "1.7500",
            "fixed_fee_send": "2.00",
            "percent_fee_bps": "20",
            "fx_spread_bps": "45",
            "liquidity": {
                "prefunding_amount_send": "4000",
                "annual_cost_of_capital_bps": "600",
                "holding_days": "0.5",
            },
            "outcomes": [
                {"outcome_id": "on-time", "probability": "0.96", "completion": "success", "delay_hours": "0.5", "recovery_amount_send": "0", "recovery_delay_hours": "0"},
                {"outcome_id": "late-success", "probability": "0.025", "completion": "success", "delay_hours": "2", "recovery_amount_send": "0", "recovery_delay_hours": "0"},
                {"outcome_id": "failed-recovered", "probability": "0.015", "completion": "failure", "delay_hours": "1", "recovery_amount_send": "975", "recovery_delay_hours": "8"},
            ],
        },
    ],
}


@dataclass(frozen=True)
class ActionResult:
    report: dict[str, object] | None
    error: str | None


class CorridorGuiController:
    """State and actions used by the GUI without importing Tkinter."""

    def __init__(self) -> None:
        self.scenario: Scenario | None = None
        self.selected_routes: tuple[Route, ...] = ()
        self.scenario_source = "No scenario loaded"
        self.routes_source = "Using routes embedded in the scenario"
        self.scenario_draft_text = self.fictional_template_text()
        self.last_report: dict[str, object] | None = None
        self.last_error: str | None = None

    @staticmethod
    def fictional_template_text() -> str:
        """Return a deterministic editable template containing fictional values only."""
        return json.dumps(BUILTIN_DEMO_SCENARIO, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _success(self, report: dict[str, object]) -> ActionResult:
        self.last_report = report
        self.last_error = None
        return ActionResult(report, None)

    def _failure(self, error: Exception | str) -> ActionResult:
        self.last_error = str(error)
        return ActionResult(None, self.last_error)

    def _require_scenario(self) -> Scenario:
        if self.scenario is None:
            raise InputError("load a fictional scenario or the built-in demo first")
        return self.scenario

    def load_builtin_demo(self) -> ActionResult:
        try:
            self.scenario = parse_scenario(copy.deepcopy(BUILTIN_DEMO_SCENARIO))
            self.scenario_draft_text = self.fictional_template_text()
            self.selected_routes = ()
            self.scenario_source = "Built-in fictional Amber to Birch demo"
            self.routes_source = "Using routes embedded in the built-in demo"
            self.last_report = None
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def load_scenario_file(self, path: str | Path) -> ActionResult:
        try:
            raw = read_bounded_bytes(path)
            self.scenario = parse_scenario(parse_json_bytes(raw))
            self.scenario_draft_text = raw.decode("utf-8")
            self.selected_routes = ()
            self.scenario_source = str(Path(path))
            self.routes_source = "Using routes embedded in the scenario"
            self.last_report = None
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def load_fictional_template(self) -> str:
        """Reset only the editor draft, never the active scenario or report."""
        self.scenario_draft_text = self.fictional_template_text()
        self.last_error = None
        return self.scenario_draft_text

    def validate_and_use_scenario_text(self, text: str) -> ActionResult:
        """Validate a draft first, then atomically replace the active scenario."""
        try:
            candidate = parse_scenario_text(text)
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)
        self.scenario = candidate
        self.scenario_draft_text = text
        self.selected_routes = ()
        self.scenario_source = "Validated in-memory fictional scenario"
        self.routes_source = "Using routes embedded in the validated scenario"
        self.last_report = None
        self.last_error = None
        return ActionResult({}, None)

    def save_scenario_text(self, path: str | Path, text: str) -> ActionResult:
        """Validate then explicitly save a draft without changing active state."""
        try:
            parse_scenario_text(text)
            atomic_write_text(Path(path), text)
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def load_routes_path(self, path: str | Path) -> ActionResult:
        try:
            selected = Path(path)
            if selected.is_file():
                routes = (load_route(selected),)
            elif selected.is_dir():
                files = sorted(item for item in selected.iterdir() if item.is_file() and item.suffix.lower() == ".json")
                if not files:
                    raise InputError(f"route folder contains no JSON files: {selected}")
                if len(files) > MAX_ROUTES:
                    raise InputError(f"route folder exceeds the {MAX_ROUTES}-route budget")
                routes = tuple(load_route(item) for item in files)
            else:
                raise InputError(f"route selection is not a file or folder: {selected}")
            identifiers = [route.route_id for route in routes]
            if len(identifiers) != len(set(identifiers)):
                raise InputError("selected routes have duplicate route identifiers")
            self.selected_routes = routes
            self.routes_source = str(selected)
            self.last_report = None
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def clear_route_selection(self) -> None:
        self.selected_routes = ()
        self.routes_source = "Using routes embedded in the scenario"
        self.last_report = None
        self.last_error = None

    def compare(self) -> ActionResult:
        try:
            scenario = self._require_scenario()
            routes = self.selected_routes or scenario.routes
            return self._success(compare_routes(scenario.transaction, routes, scenario.objective, scenario.scenario_id))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def evaluate(self) -> ActionResult:
        try:
            scenario = self._require_scenario()
            return self._success(evaluate_scenario(scenario))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def sensitivity(self, parameter: str, values_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            chunks = values_text.split(",")
            if not chunks or not all(chunk.strip() for chunk in chunks):
                raise InputError("sensitivity values must be comma-separated decimals")
            values: list[Decimal] = [require_decimal(chunk.strip(), "sensitivity value") for chunk in chunks]
            return self._success(run_sensitivity(scenario, parameter.strip(), values))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def stress_grid(self, parameter_a: str, values_a_text: str, parameter_b: str, values_b_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            values_a = [require_decimal(chunk.strip(), "stress value") for chunk in values_a_text.split(",") if chunk.strip()]
            values_b = [require_decimal(chunk.strip(), "stress value") for chunk in values_b_text.split(",") if chunk.strip()]
            return self._success(run_stress_grid(scenario, parameter_a.strip(), values_a, parameter_b.strip(), values_b))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def pareto(self) -> ActionResult:
        try:
            scenario = self._require_scenario()
            routes = self.selected_routes or scenario.routes
            if not routes:
                raise InputError("Pareto frontier requires routes embedded in the scenario or a route selection")
            evaluations = [evaluate_route(route, scenario.transaction) for route in sorted(routes, key=lambda item: item.route_id)]
            return self._success({"report_version": "corridor-lab.pareto/v1", "scenario_id": scenario.scenario_id, "fictional": True, "frontier": pareto_frontier(evaluations)})
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def render_last_report(self, output_format: str) -> str | None:
        if self.last_report is None:
            self.last_error = "run Compare, Evaluate, or Sensitivity before previewing or saving a report"
            return None
        try:
            text = render_report(self.last_report, output_format)
            self.last_error = None
            return text
        except (InputError, ValueError, DecimalException) as exc:
            self.last_error = str(exc)
            return None

    def save_last_report(self, path: str | Path, output_format: str) -> ActionResult:
        text = self.render_last_report(output_format)
        if text is None:
            return ActionResult(None, self.last_error)
        try:
            atomic_write_text(Path(path), text)
            self.last_error = None
            return ActionResult(self.last_report, None)
        except OSError as exc:
            return self._failure(exc)
