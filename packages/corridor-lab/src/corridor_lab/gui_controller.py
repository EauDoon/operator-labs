"""Headless-safe controller for the optional Corridor Lab desktop interface."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
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
    InputError,
    atomic_write_text,
    decimal_text,
    parse_json_bytes,
    protect_report_output,
    read_bounded_bytes,
    require_decimal,
)
from .comparison import compare_routes, evaluate_scenario, pareto_frontier
from .model import evaluate_route
from .projects import (
    Experiment,
    build_manifest,
    execute_experiment,
    load_project,
    prepare_project_directory,
    validate_experiment,
    write_project,
)
from .report import render_report
from .variants import (
    DerivedVariant,
    apply_variant as materialize_variant,
    parse_derived_variant,
    validate_changes,
    variant_comparison,
    variant_diff_report,
)
from .route import Route, load_route, load_route_folder
from .scenario import Scenario, parse_scenario, parse_scenario_text
from .scenario_diff import diff_scenarios
from .sensitivity import run_sensitivity
from .stress import run_stress_grid
from .transaction_sweep import (
    TRANSACTION_PARAMETERS,
    run_transaction_grid,
    run_transaction_sweep,
)

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


def _normalize_raw(value):
    """Return a JSON-serializable copy of parsed scenario input.

    Bounded JSON parsing represents numbers as Decimal. Integral values stay
    integers and every other number becomes its exact decimal text, so the
    declared values round-trip without binary floats.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else decimal_text(value)
    if isinstance(value, list):
        return [_normalize_raw(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_raw(item) for key, item in value.items()}
    return value


class CorridorGuiController:
    """State and actions used by the GUI without importing Tkinter."""

    def __init__(self) -> None:
        self.scenario: Scenario | None = None
        self.scenario_raw: dict | None = None
        self.selected_routes: tuple[Route, ...] = ()
        self.scenario_source = "No scenario loaded"
        self.routes_source = "Using routes embedded in the scenario"
        self.scenario_draft_text = self.fictional_template_text()
        self.last_report: dict[str, object] | None = None
        self.last_error: str | None = None
        self.scenario_file: Path | None = None
        self.routes_path: Path | None = None
        self.scenario_unsaved = False
        self.baseline_file: Path | None = None
        self.project_source: str | None = None
        self.project_path: Path | None = None
        self.project_id: str | None = None
        self.experiments: tuple[Experiment, ...] = ()
        self.derived_variants: dict[str, DerivedVariant] = {}
        self.active_variant: str | None = None
        self.last_report_inputs: tuple[Path, ...] = ()
        self.last_report_scanned_dirs: tuple[Path, ...] = ()

    def _report_inputs(self, *, include_routes: bool) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        inputs: list[Path] = []
        scanned: list[Path] = []
        if self.scenario_file is not None:
            inputs.append(self.scenario_file)
        if include_routes and self.routes_path is not None:
            if self.routes_path.is_dir():
                scanned.append(self.routes_path)
            else:
                inputs.append(self.routes_path)
        return tuple(inputs), tuple(scanned)

    def _success(
        self,
        report: dict[str, object],
        *,
        routes_inputs: bool = True,
        extra_inputs: tuple[Path, ...] = (),
    ) -> ActionResult:
        self.last_report = report
        base_inputs, base_scanned = self._report_inputs(include_routes=routes_inputs)
        self.last_report_inputs = tuple(base_inputs) + tuple(extra_inputs)
        self.last_report_scanned_dirs = base_scanned
        self.last_error = None
        return ActionResult(report, None)

    @staticmethod
    def fictional_template_text() -> str:
        """Return a deterministic editable template containing fictional values only."""
        return json.dumps(BUILTIN_DEMO_SCENARIO, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _failure(self, error: Exception | str) -> ActionResult:
        self.last_error = str(error)
        return ActionResult(None, self.last_error)

    def _require_scenario(self) -> Scenario:
        if self.scenario is None:
            raise InputError("load a fictional scenario or the built-in demo first")
        return self.scenario

    def _install_scenario(self, scenario: Scenario, raw: dict, source: str, *, unsaved: bool, draft_text: str | None) -> None:
        self.scenario = scenario
        self.scenario_raw = raw
        self.scenario_source = source
        self.scenario_unsaved = unsaved
        if draft_text is not None:
            self.scenario_draft_text = draft_text
        self.selected_routes = ()
        self.last_report = None
        self.last_error = None

    def load_builtin_demo(self) -> ActionResult:
        try:
            raw = _normalize_raw(copy.deepcopy(BUILTIN_DEMO_SCENARIO))
            scenario = parse_scenario(copy.deepcopy(raw))
            self._install_scenario(scenario, raw, "Built-in fictional Amber to Birch demo", unsaved=False, draft_text=self.fictional_template_text())
            self.routes_source = "Using routes embedded in the built-in demo"
            self.routes_path = None
            return ActionResult({}, None)
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def load_scenario_file(self, path: str | Path) -> ActionResult:
        try:
            raw = read_bounded_bytes(path)
            value = _normalize_raw(parse_json_bytes(raw))
            scenario = parse_scenario(copy.deepcopy(value))
            self._install_scenario(scenario, value, str(Path(path)), unsaved=False, draft_text=raw.decode("utf-8"))
            self.scenario_file = Path(path)
            self.routes_source = "Using routes embedded in the scenario"
            self.routes_path = None
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
            value = _normalize_raw(parse_json_bytes(text.encode("utf-8")))
            candidate = parse_scenario(copy.deepcopy(value))
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)
        self._install_scenario(candidate, value, "Validated in-memory fictional scenario", unsaved=True, draft_text=text)
        self.routes_source = "Using routes embedded in the validated scenario"
        self.routes_path = None
        return ActionResult({}, None)

    def transaction_fields(self) -> dict[str, str]:
        """Show the active transaction's declared fields for structured editing.

        Values come from the declared raw scenario so the editor displays the
        exact digits the user stored, never a canonicalized or float-rounded
        version of them.
        """
        scenario = self._require_scenario()
        transaction = scenario.transaction
        raw_transaction = (self.scenario_raw or {}).get("transaction") if isinstance(self.scenario_raw, dict) else None
        raw_transaction = raw_transaction if isinstance(raw_transaction, dict) else {}

        def declared(field: str, value: Decimal) -> str:
            text = raw_transaction.get(field)
            return text if isinstance(text, str) and text.strip() else decimal_text(value)

        return {
            "send_amount": declared("send_amount", transaction.send_amount),
            "send_currency": transaction.send_currency,
            "send_precision": str(transaction.send_precision),
            "receive_currency": transaction.receive_currency,
            "receive_precision": str(transaction.receive_precision),
            "rounding": transaction.rounding,
            "deadline_hours": declared("deadline_hours", transaction.deadline_hours),
            "volume_per_period": declared("volume_per_period", transaction.volume_per_period),
        }

    def apply_transaction_edits(
        self,
        send_amount: str | None = None,
        deadline_hours: str | None = None,
        volume_per_period: str | None = None,
    ) -> ActionResult:
        """Apply structured transaction edits transactionally to the active scenario.

        The candidate is validated as a whole before it replaces the active
        scenario; a rejected draft leaves the active scenario, draft text, and
        current report untouched. Exact decimal strings are preserved and are
        never converted through binary floats.
        """
        try:
            scenario = self._require_scenario()
            if self.scenario_raw is None:
                raise InputError("no editable scenario data is available")
            raw = copy.deepcopy(self.scenario_raw)
            transaction = raw.get("transaction")
            if not isinstance(transaction, dict):
                raise InputError("scenario transaction must be an object")
            edits = {
                "send_amount": send_amount,
                "deadline_hours": deadline_hours,
                "volume_per_period": volume_per_period,
            }
            for field, value in edits.items():
                if value is None or not str(value).strip():
                    continue
                text = str(value).strip()
                require_decimal(text, f"transaction.{field}")
                transaction[field] = text
            candidate = parse_scenario(copy.deepcopy(raw))
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)
        source = f"{self.scenario_source} (edited in memory, unsaved)" if not self.scenario_unsaved else self.scenario_source
        if self.scenario_file is None and not self.scenario_unsaved:
            source = "Structured edits applied to the built-in demo (unsaved)"
        self._install_scenario(
            candidate,
            raw,
            source,
            unsaved=True,
            draft_text=json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
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
                routes = tuple(load_route_folder(selected))
            else:
                raise InputError(f"route selection is not a file or folder: {selected}")
            identifiers = [route.route_id for route in routes]
            if len(identifiers) != len(set(identifiers)):
                raise InputError("selected routes have duplicate route identifiers")
            self.selected_routes = routes
            self.routes_source = str(selected)
            self.routes_path = selected
            self.last_report = None
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def clear_route_selection(self) -> None:
        self.selected_routes = ()
        self.routes_source = "Using routes embedded in the scenario"
        self.routes_path = None
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
            return self._success(evaluate_scenario(scenario), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def _scenario_analysis(self, analysis) -> ActionResult:
        try:
            scenario = self._require_scenario()
            return self._success(analysis(scenario), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def cost_ledger(self) -> ActionResult:
        return self._scenario_analysis(cost_ledger)

    def loss_profile(self) -> ActionResult:
        return self._scenario_analysis(loss_profile)

    def feasible_amount(self) -> ActionResult:
        return self._scenario_analysis(feasible_amount)

    def outcome_ledger(self) -> ActionResult:
        return self._scenario_analysis(outcome_ledger)

    def deadline_profile(self) -> ActionResult:
        return self._scenario_analysis(deadline_profile)

    def break_even_check(self) -> ActionResult:
        return self._scenario_analysis(break_even_check)

    def guardrail_headroom(self) -> ActionResult:
        return self._scenario_analysis(guardrail_headroom)

    def deadline_target(self, probability_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            probability = str(probability_text).strip()
            require_decimal(probability, "probability")
            return self._success(deadline_target(scenario, probability), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def resolution_quantiles(self, probabilities_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            values = self._parse_values(probabilities_text, "quantile values")
            return self._success(resolution_quantiles(scenario, values), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def diff_against_baseline(self, baseline_path: str | Path) -> ActionResult:
        """Compare the active scenario (candidate) with a saved baseline (before)."""
        try:
            scenario = self._require_scenario()
            path = Path(baseline_path)
            if not str(path).strip():
                raise InputError("select a baseline scenario file before diffing")
            baseline_raw = read_bounded_bytes(path)
            baseline = parse_scenario(parse_json_bytes(baseline_raw))
            self.baseline_file = path
            return self._success(diff_scenarios(baseline, scenario), routes_inputs=False, extra_inputs=(path,))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def open_project(self, path: str | Path) -> ActionResult:
        """Load a saved project: inputs, baseline, and saved experiments.

        Missing or modified inputs are reported instead of accepted, and the
        previous report is cleared because its inputs may no longer apply.
        """
        try:
            loaded = load_project(path)
            if loaded.problems:
                raise InputError("; ".join(loaded.problems))
            scenario_result = self.load_scenario_file(loaded.resolved["scenario"])
            if scenario_result.error is not None:
                return scenario_result
            if "routes" in loaded.resolved:
                routes_result = self.load_routes_path(loaded.resolved["routes"])
                if routes_result.error is not None:
                    return routes_result
            else:
                self.clear_route_selection()
            self.baseline_file = loaded.resolved.get("baseline")
            self.experiments = loaded.manifest.experiments
            self.derived_variants = dict(loaded.manifest.derived_variants or {})
            self.active_variant = None
            self.project_source = str(loaded.path)
            self.project_path = loaded.path.parent
            self.project_id = loaded.manifest.project_id
            return ActionResult(
                {
                    "project_id": loaded.manifest.project_id,
                    "description": loaded.manifest.description,
                    "experiments": [experiment.name for experiment in loaded.manifest.experiments],
                },
                None,
            )
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def save_project(self, destination: str | Path, project_id: str, description: str = "") -> ActionResult:
        """Explicitly save the current inputs and saved experiments as a project."""
        try:
            if self.scenario_file is None:
                raise InputError("load a scenario from a file before saving a project")
            target = Path(destination)
            if not target.is_dir():
                raise InputError(f"choose an existing project directory before saving: {target}")
            placed = prepare_project_directory(target, self.scenario_file, self.routes_path, self.baseline_file)
            manifest = build_manifest(
                target,
                project_id=project_id,
                description=description,
                scenario=placed["scenario"],
                routes=placed.get("routes"),
                baseline=placed.get("baseline"),
                experiments=self.experiments,
                derived_variants=self.derived_variants or None,
            )
            write_project(target, manifest)
            self.project_source = str(target / "corridor-lab.project.json")
            self.project_path = target
            self.project_id = manifest.project_id
            return ActionResult({}, None)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def add_saved_experiment(self, name: str, analysis: str, fields: dict[str, str]) -> ActionResult:
        """Validate and stage a named experiment; persisted by the next project save."""
        try:
            if self.scenario is None:
                raise InputError("load a fictional scenario before saving an experiment configuration")
            experiment = validate_experiment(name, analysis, fields)
            if any(existing.name == experiment.name for existing in self.experiments):
                raise InputError(f"an experiment named {experiment.name} is already saved; choose a new name")
            self.experiments = self.experiments + (experiment,)
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def remove_saved_experiment(self, name: str) -> ActionResult:
        self.experiments = tuple(experiment for experiment in self.experiments if experiment.name != name)
        self.last_error = None
        return ActionResult({}, None)

    def run_saved_experiment(self, name: str) -> ActionResult:
        """Run one saved experiment through the shared library executor."""
        try:
            scenario = self._require_scenario()
            experiment = next((item for item in self.experiments if item.name == name), None)
            if experiment is None:
                raise InputError(f"no saved experiment named {name}; open or create a project first")
            return self._success(execute_experiment(experiment, scenario), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def saved_experiment_names(self) -> tuple[str, ...]:
        return tuple(experiment.name for experiment in self.experiments)

    def add_variant(self, name: str, changes: dict[str, object]) -> ActionResult:
        """Stage a named derived variant; persisted by the next project save."""
        try:
            if self.scenario is None or self.scenario_raw is None:
                raise InputError("load a fictional scenario before adding a variant")
            variant = parse_derived_variant(name.strip(), {"base": "scenario", "changes": changes})
            if variant.name in self.derived_variants:
                raise InputError(f"a variant named {variant.name} already exists; choose a new name")
            # Prove the variant materializes against the current base before staging it.
            parse_scenario(materialize_variant(variant, self.scenario_raw))
            self.derived_variants[variant.name] = variant
            self.last_error = None
            return ActionResult({}, None)
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def apply_variant(self, name: str) -> ActionResult:
        """Install a derived variant as the active scenario (in memory, unsaved)."""
        try:
            scenario = self._require_scenario()
            if self.scenario_raw is None:
                raise InputError("the active scenario has no editable baseline data; load it from a file")
            variant = self.derived_variants.get(name)
            if variant is None:
                raise InputError(f"no derived variant named {name}; open or create a project first")
            raw = materialize_variant(variant, self.scenario_raw)
            candidate = parse_scenario(copy.deepcopy(raw))
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)
        previous_source = self.scenario_source
        self._install_scenario(
            candidate,
            raw,
            f"Variant {name} applied to {self.scenario_source}",
            unsaved=True,
            draft_text=json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        self.active_variant = name
        self.last_report = None
        return ActionResult({"variant": name, "previous_source": previous_source}, None)

    def show_variant_diff(self, name: str) -> ActionResult:
        """Show exactly what a derived variant changes before any results."""
        try:
            self._require_scenario()
            if self.scenario_raw is None:
                raise InputError("the active scenario has no declared base data")
            variant = self.derived_variants.get(name)
            if variant is None:
                raise InputError(f"no derived variant named {name}")
            return self._success(
                variant_diff_report(variant, self.scenario_raw, self.scenario.scenario_id if self.scenario else "fictional-scenario"),
                routes_inputs=False,
            )
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def compare_variants(self, names: tuple[str, ...] | None = None) -> ActionResult:
        """Compare route performance across the declared variant set."""
        try:
            self._require_scenario()
            if self.scenario_raw is None:
                raise InputError("the active scenario has no declared base data")
            missing = sorted(set(names or ()) - set(self.derived_variants))
            if missing:
                raise InputError(f"no derived variant named {', '.join(missing)}")
            chosen = self.derived_variants if names is None else {name: self.derived_variants[name] for name in names}
            return self._success(
                variant_comparison(self.scenario_raw, chosen, self.project_id_or_scenario()),
                routes_inputs=False,
            )
        except (InputError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def project_id_or_scenario(self) -> str:
        return self.project_id or (self.scenario.scenario_id if self.scenario is not None else "fictional-scenario")

    def variant_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.derived_variants))

    @staticmethod
    def _parse_values(values_text: str, description: str) -> list[Decimal]:
        chunks = values_text.split(",")
        if not all(chunk.strip() for chunk in chunks):
            raise InputError(f"{description} must be comma-separated decimals")
        return [require_decimal(chunk.strip(), f"{description} value") for chunk in chunks]

    def sensitivity(self, parameter: str, values_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            values = self._parse_values(values_text, "sensitivity values")
            return self._success(run_sensitivity(scenario, parameter.strip(), values))
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def transaction_sweep(self, parameter: str, values_text: str) -> ActionResult:
        try:
            chunks = values_text.split(",")
            if not all(chunk.strip() for chunk in chunks):
                raise InputError("transaction values must be comma-separated decimals")
            values = [require_decimal(chunk.strip(), "transaction value") for chunk in chunks]
            return self._success(run_transaction_sweep(self._require_scenario(), parameter.strip(), values), routes_inputs=False)
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def transaction_grid(self, parameter_a: str, values_a_text: str, parameter_b: str, values_b_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            if parameter_a.strip() == parameter_b.strip():
                raise InputError("transaction grid requires two distinct transaction parameters")
            if parameter_a.strip() not in TRANSACTION_PARAMETERS or parameter_b.strip() not in TRANSACTION_PARAMETERS:
                raise InputError("transaction grid parameters must be send_amount, deadline_hours, or volume_per_period")
            values_a = self._parse_values(values_a_text, "transaction grid values")
            values_b = self._parse_values(values_b_text, "transaction grid values")
            return self._success(
                run_transaction_grid(scenario, parameter_a.strip(), values_a, parameter_b.strip(), values_b),
                routes_inputs=False,
            )
        except (InputError, OSError, ValueError, DecimalException) as exc:
            return self._failure(exc)

    def stress_grid(self, parameter_a: str, values_a_text: str, parameter_b: str, values_b_text: str) -> ActionResult:
        try:
            scenario = self._require_scenario()
            chunks_a = values_a_text.split(",")
            chunks_b = values_b_text.split(",")
            if not all(chunk.strip() for chunk in chunks_a + chunks_b):
                raise InputError("stress values must be comma-separated decimals")
            values_a = [require_decimal(chunk.strip(), "stress value") for chunk in chunks_a]
            values_b = [require_decimal(chunk.strip(), "stress value") for chunk in chunks_b]
            return self._success(run_stress_grid(scenario, parameter_a.strip(), values_a, parameter_b.strip(), values_b), routes_inputs=False)
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
            self.last_error = "run an analysis before previewing or saving a report"
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
            target = protect_report_output(path, self.last_report_inputs, self.last_report_scanned_dirs)
            atomic_write_text(target, text)
            self.last_error = None
            return ActionResult(self.last_report, None)
        except (InputError, OSError) as exc:
            return self._failure(exc)
