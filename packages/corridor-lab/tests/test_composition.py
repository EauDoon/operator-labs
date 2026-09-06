"""Hand-worked tests for bounded multi-leg route composition."""

import copy
import dataclasses
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fee_helpers as fh  # noqa: E402
from corridor_lab.canonical import InputError  # noqa: E402
from corridor_lab.comparison import compare_routes  # noqa: E402
from corridor_lab.legs import compose, parse_legs  # noqa: E402
from corridor_lab.model import evaluate_route  # noqa: E402
from corridor_lab.report import render_report  # noqa: E402
from corridor_lab.route import parse_route  # noqa: E402
from corridor_lab.scenario import parse_scenario  # noqa: E402

LEGS = [
    {
        "leg_id": "onshore",
        "from_currency": "SND",
        "to_currency": "USD",
        "fx_rate": "1.25",
        "fx_spread_bps": "20",
        "fixed_fee_send": "1.00",
        "percent_fee_bps": "10",
        "delay_hours": "1",
    },
    {
        "leg_id": "offshore",
        "from_currency": "USD",
        "to_currency": "RCV",
        "fx_rate": "1.40",
        "fx_spread_bps": "30",
        "fixed_fee_send": "2.00",
        "percent_fee_bps": "15",
        "delay_hours": "3",
    },
]


def composed_route(legs=None, outcomes=None) -> dict:
    route = {
        "contract_version": "corridor-lab.route/v2",
        "route_id": "two-leg",
        "label": "two-leg (fictional)",
        "fictional": True,
        "liquidity": {
            "prefunding_amount_send": "36500",
            "annual_cost_of_capital_bps": "1000",
            "holding_days": "1",
        },
        "legs": copy.deepcopy(LEGS if legs is None else legs),
        "outcomes": copy.deepcopy(
            outcomes
            if outcomes is not None
            else [
                {
                    "outcome_id": "completed",
                    "probability": "1",
                    "completion": "success",
                    "terminal_leg": "offshore",
                    "delay_hours": "0",
                    "recovery_amount_send": "0",
                    "recovery_delay_hours": "0",
                }
            ]
        ),
    }
    return route


def _scenario(routes=None):
    return parse_scenario(fh.v2_scenario(routes if routes is not None else [composed_route()]))


class LegParsingTests(unittest.TestCase):
    def test_rejects_a_single_leg(self):
        with self.assertRaisesRegex(InputError, "at least two legs"):
            parse_legs(LEGS[:1], "legs")

    def test_rejects_unknown_fields(self):
        legs = copy.deepcopy(LEGS)
        legs[0]["guess"] = 1
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_legs(legs, "legs")

    def test_rejects_a_leg_that_does_not_convert(self):
        legs = copy.deepcopy(LEGS)
        legs[0]["to_currency"] = "SND"
        with self.assertRaisesRegex(InputError, "two different currencies"):
            parse_legs(legs, "legs")

    def test_rejects_a_discontinuous_chain(self):
        legs = copy.deepcopy(LEGS)
        legs[1]["from_currency"] = "EUR"
        with self.assertRaisesRegex(InputError, "contiguous chain"):
            parse_legs(legs, "legs")

    def test_rejects_a_cycle(self):
        legs = copy.deepcopy(LEGS)
        legs[1]["to_currency"] = "SND"
        with self.assertRaisesRegex(InputError, "must not contain a cycle"):
            parse_legs(legs, "legs")

    def test_rejects_duplicate_leg_ids(self):
        legs = copy.deepcopy(LEGS)
        legs[1]["leg_id"] = "onshore"
        with self.assertRaisesRegex(InputError, "duplicate leg_id"):
            parse_legs(legs, "legs")

    def test_rejects_out_of_range_bps(self):
        legs = copy.deepcopy(LEGS)
        legs[0]["fx_spread_bps"] = "10001"
        with self.assertRaises(InputError):
            parse_legs(legs, "legs")


class ComposedRouteParsingTests(unittest.TestCase):
    def test_scalar_fee_fields_must_be_omitted(self):
        for field in ("fx_rate", "fx_spread_bps", "fixed_fee_send", "percent_fee_bps", "fee_schedule"):
            data = composed_route()
            data[field] = "1" if field != "fee_schedule" else fh.fee_schedule()
            with self.assertRaisesRegex(InputError, "must be omitted when legs are declared"):
                parse_route(data)

    def test_composed_outcomes_require_a_terminal_leg(self):
        data = composed_route()
        data["outcomes"][0].pop("terminal_leg")
        with self.assertRaisesRegex(InputError, "terminal_leg"):
            parse_route(data)

    def test_terminal_leg_must_name_a_declared_leg(self):
        data = composed_route()
        data["outcomes"][0]["terminal_leg"] = "ghost"
        with self.assertRaisesRegex(InputError, "must name a declared leg_id"):
            parse_route(data)

    def test_success_must_terminate_at_the_final_leg(self):
        data = composed_route()
        data["outcomes"][0]["terminal_leg"] = "onshore"
        with self.assertRaisesRegex(InputError, "success outcome, so terminal_leg must be the final leg"):
            parse_route(data)

    def test_non_composed_routes_reject_a_terminal_leg(self):
        data = fh.tiered_route()
        data["outcomes"][0]["terminal_leg"] = "onshore"
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_route(data)

    def test_v1_routes_reject_legs(self):
        data = composed_route()
        data["contract_version"] = "corridor-lab.route/v1"
        data["fx_rate"] = "1"
        data["fx_spread_bps"] = "0"
        data["fixed_fee_send"] = "0"
        data["percent_fee_bps"] = "0"
        with self.assertRaisesRegex(InputError, r"unsupported field\(s\): legs"):
            parse_route(data)

    def test_chain_endpoints_are_checked_against_the_transaction(self):
        scenario = _scenario()
        route = parse_route(composed_route())
        with self.assertRaisesRegex(InputError, "must equal the declared send currency"):
            evaluate_route(route, dataclasses.replace(scenario.transaction, send_currency="OTHER"))

    def test_receive_endpoint_is_checked(self):
        scenario = _scenario()
        route = parse_route(composed_route())
        with self.assertRaisesRegex(InputError, "must equal the declared receive currency"):
            evaluate_route(route, dataclasses.replace(scenario.transaction, receive_currency="OTHER"))


class CompositionCalculationTests(unittest.TestCase):
    def _plan(self):
        return compose(parse_legs(copy.deepcopy(LEGS), "legs"), Decimal("1000.00"))

    def test_hand_calculated_leg_fees(self):
        plan = self._plan()
        onshore, offshore = plan.leg_fees
        # leg 1: 1.00 fixed + 1000 * 10/10000 = 1.00 percentage, in SND
        self.assertEqual(onshore.fixed_fee, Decimal("1.00"))
        self.assertEqual(onshore.percentage_fee, Decimal("1.00"))
        self.assertEqual(onshore.total_fee, Decimal("2.00"))
        self.assertEqual(onshore.currency, "SND")
        # leg 2: amount reaching it is (1000 - 2) * 1.25 * (1 - 20/10000) = 1245.005
        # 2.00 fixed + 1245.005 * 15/10000 = 1.8675075, in USD
        self.assertEqual(offshore.currency, "USD")
        self.assertEqual(offshore.fixed_fee, Decimal("2.00"))
        self.assertEqual(offshore.percentage_fee, Decimal("1.8675075"))

    def test_hand_calculated_send_equivalent_fee(self):
        plan = self._plan()
        # effective rate of leg 1 is 1.25 * (1 - 20/10000) = 1.2475
        # 2.00 + 3.8675075 / 1.2475 = 2.00 + 3.10020641...
        self.assertAlmostEqual(plan.explicit_fee_send, Decimal("5.1002064128256513"), places=15)

    def test_aggregated_and_step_by_step_results_agree(self):
        plan = self._plan()
        self.assertAlmostEqual(
            plan.amount_converted_send * plan.effective_fx_rate, plan.recipient_amount, places=15
        )

    def test_hand_calculated_effective_rate(self):
        plan = self._plan()
        # (1.25 * 0.998) * (1.40 * 0.997) = 1.2475 * 1.3958
        self.assertEqual(plan.effective_fx_rate, Decimal("1.2475") * Decimal("1.3958"))

    def test_hand_calculated_recipient_amount(self):
        plan = self._plan()
        self.assertAlmostEqual(plan.recipient_amount, Decimal("1732.3797120315"), places=10)

    def test_spread_cost_is_the_reference_gap(self):
        plan = self._plan()
        reference = Decimal("1.25") * Decimal("1.40")
        self.assertAlmostEqual(
            plan.fx_spread_cost_receive,
            plan.amount_converted_send * reference - plan.recipient_amount,
            places=15,
        )
        self.assertGreater(plan.fx_spread_cost_receive, Decimal("0"))

    def test_terminal_delays_are_cumulative(self):
        plan = self._plan()
        self.assertEqual(plan.terminal_delay_hours["onshore"], Decimal("1"))
        self.assertEqual(plan.terminal_delay_hours["offshore"], Decimal("4"))

    def test_a_leg_fee_above_the_amount_reaching_it_is_rejected(self):
        legs = copy.deepcopy(LEGS)
        legs[1]["fixed_fee_send"] = "99999"
        with self.assertRaisesRegex(InputError, "fees exceed the amount reaching that leg"):
            compose(parse_legs(legs, "legs"), Decimal("1000.00"))

    def test_zero_cost_chain_preserves_the_converted_principal(self):
        legs = copy.deepcopy(LEGS)
        for leg in legs:
            leg["fixed_fee_send"] = "0"
            leg["percent_fee_bps"] = "0"
            leg["fx_spread_bps"] = "0"
        plan = compose(parse_legs(legs, "legs"), Decimal("1000.00"))
        self.assertEqual(plan.explicit_fee_send, Decimal("0"))
        self.assertEqual(plan.fx_spread_cost_receive, Decimal("0"))
        self.assertEqual(plan.recipient_amount, Decimal("1000") * Decimal("1.25") * Decimal("1.40"))


class ComposedEvaluationTests(unittest.TestCase):
    def _joint_outcomes(self):
        return [
            {
                "outcome_id": "completed",
                "probability": "0.95",
                "completion": "success",
                "terminal_leg": "offshore",
                "delay_hours": "0",
                "recovery_amount_send": "0",
                "recovery_delay_hours": "0",
            },
            {
                "outcome_id": "failed-on-leg-1",
                "probability": "0.03",
                "completion": "failure",
                "terminal_leg": "onshore",
                "delay_hours": "0",
                "recovery_amount_send": "995",
                "recovery_delay_hours": "12",
            },
            {
                "outcome_id": "failed-on-leg-2",
                "probability": "0.02",
                "completion": "failure",
                "terminal_leg": "offshore",
                "delay_hours": "0",
                "recovery_amount_send": "990",
                "recovery_delay_hours": "24",
            },
        ]

    def test_success_probability_is_declared_not_multiplied(self):
        route = parse_route(composed_route(outcomes=self._joint_outcomes()))
        scenario = _scenario()
        result = evaluate_route(route, scenario.transaction)
        # The declared success probability is 0.95. Multiplying leg-level
        # success rates would produce something else; Corridor Lab never does.
        self.assertEqual(result.success_probability, Decimal("0.95"))

    def test_hand_calculated_resolution_times(self):
        route = parse_route(composed_route(outcomes=self._joint_outcomes()))
        scenario = _scenario()
        result = evaluate_route(route, scenario.transaction).as_dict()
        # completed: 1 + 3 = 4 ; leg-1 failure: 1 + 12 = 13 ; leg-2 failure: 4 + 24 = 28
        # expected = 0.95*4 + 0.03*13 + 0.02*28 = 3.8 + 0.39 + 0.56
        self.assertEqual(result["expected_completion_time_hours"], "4.75")
        self.assertEqual(result["median_completion_time_hours"], "4")
        self.assertEqual(result["tail_completion_time_hours"], "4")

    def test_tail_time_reflects_the_slowest_declared_outcome(self):
        outcomes = self._joint_outcomes()
        outcomes[0]["probability"] = "0.5"
        outcomes[1]["probability"] = "0.25"
        outcomes[2]["probability"] = "0.25"
        route = parse_route(composed_route(outcomes=outcomes))
        scenario = _scenario()
        result = evaluate_route(route, scenario.transaction).as_dict()
        # cumulative: 4h -> 0.5, 13h -> 0.75, 28h -> 1.0 ; the 95th percentile is 28h
        self.assertEqual(result["tail_completion_time_hours"], "28")

    def test_deadline_probability_counts_only_success_within_the_deadline(self):
        route = parse_route(composed_route(outcomes=self._joint_outcomes()))
        scenario = _scenario()
        tight = evaluate_route(route, dataclasses.replace(scenario.transaction, deadline_hours=Decimal("3")))
        loose = evaluate_route(route, dataclasses.replace(scenario.transaction, deadline_hours=Decimal("24")))
        self.assertEqual(tight.probability_by_deadline, Decimal("0"))
        self.assertEqual(loose.probability_by_deadline, Decimal("0.95"))

    def test_expected_failure_cost_uses_the_declared_recoveries(self):
        route = parse_route(composed_route(outcomes=self._joint_outcomes()))
        scenario = _scenario()
        result = evaluate_route(route, scenario.transaction)
        # 0.03 * (1000 - 995) + 0.02 * (1000 - 990) = 0.15 + 0.20
        self.assertEqual(result.expected_failure_recovery_cost_send, Decimal("0.35"))

    def test_scalar_sensitivity_is_rejected_on_a_composed_route(self):
        route = parse_route(composed_route())
        with self.assertRaisesRegex(InputError, "unsupported sensitivity parameter"):
            route.changed_parameter("legs", Decimal("1"))

    def test_composed_and_scalar_routes_compare_together(self):
        direct = fh.tiered_route("direct")
        direct.pop("fee_schedule")
        direct["fixed_fee_send"] = "5.10"
        direct["percent_fee_bps"] = "0"
        direct["fx_rate"] = "1.7412605"
        direct["fx_spread_bps"] = "0"
        scenario = parse_scenario(
            fh.v2_scenario([composed_route(outcomes=self._joint_outcomes()), direct])
        )
        report = compare_routes(scenario.transaction, scenario.routes, None, scenario.scenario_id)
        self.assertEqual([item["route_id"] for item in report["routes"]], ["direct", "two-leg"])
        composed = report["routes"][1]
        self.assertIn("legs", composed["declared_inputs"]["route"])
        self.assertNotIn("fx_rate", composed["declared_inputs"]["route"])
        self.assertEqual(composed["declared_inputs"]["route"]["outcomes"][0]["terminal_leg"], "offshore")

    def test_csv_rendering_marks_composed_scalar_fields(self):
        scenario = parse_scenario(fh.v2_scenario([composed_route(outcomes=self._joint_outcomes())]))
        report = compare_routes(scenario.transaction, scenario.routes, None, scenario.scenario_id)
        csv_text = render_report(report, "csv")
        self.assertIn("two-leg", csv_text)
        self.assertIn("composed", csv_text)

    def test_json_report_is_deterministic(self):
        scenario = parse_scenario(fh.v2_scenario([composed_route(outcomes=self._joint_outcomes())]))
        first = render_report(compare_routes(scenario.transaction, scenario.routes), "json")
        second = render_report(compare_routes(scenario.transaction, scenario.routes), "json")
        self.assertEqual(first, second)


class MultiLegExampleTests(unittest.TestCase):
    EXAMPLE = ROOT / "examples" / "fictional-multi-leg"

    def test_example_evaluates(self):
        scenario = parse_scenario(
            json.loads((self.EXAMPLE / "scenario.json").read_text(encoding="utf-8"))
        )
        results = {item.route_id: evaluate_route(item, scenario.transaction) for item in scenario.routes}
        self.assertEqual(results["two-leg-chain"].success_probability, Decimal("0.95"))
        self.assertEqual(results["two-leg-chain"].expected_completion_time_hours, Decimal("4.75"))
        self.assertAlmostEqual(
            results["two-leg-chain"].recipient_amount, Decimal("1732.3797120315"), places=10
        )

    def test_declared_fees_are_reported_per_leg_and_aggregated(self):
        scenario = parse_scenario(
            json.loads((self.EXAMPLE / "scenario.json").read_text(encoding="utf-8"))
        )
        route = next(item for item in scenario.routes if item.route_id == "two-leg-chain")
        plan = compose(route.legs, scenario.transaction.send_amount)
        self.assertEqual([fee.leg_id for fee in plan.leg_fees], ["onshore", "offshore"])
        self.assertEqual([fee.currency for fee in plan.leg_fees], ["AMR", "USD"])


if __name__ == "__main__":
    unittest.main()
