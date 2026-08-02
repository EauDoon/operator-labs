import unittest
from decimal import getcontext, setcontext

from helpers import route, scenario
from corridor_lab.comparison import compare_routes
from corridor_lab.model import evaluate_route
from corridor_lab.route import parse_route
from corridor_lab.scenario import parse_scenario


class ComparisonTests(unittest.TestCase):
    def test_default_comparison_has_no_ranking(self):
        tx = parse_scenario(scenario()).transaction
        report = compare_routes(tx, [parse_route(route("z")), parse_route(route("a"))])
        self.assertNotIn("ranking", report)
        self.assertEqual([item["route_id"] for item in report["routes"]], ["a", "z"])

    def test_explicit_objective_with_guardrail_enables_ranking(self):
        objective = {
            "metric": "maximize_expected_recipient_amount",
            "guardrails": {"minimum_probability_by_deadline": "0.5"},
        }
        parsed = parse_scenario(scenario(objective=objective))
        report = compare_routes(parsed.transaction, [parse_route(route())], parsed.objective)
        self.assertEqual(report["ranking"]["eligible_routes"][0]["route_id"], "fictional-route")

    def test_break_even_volume(self):
        left = route("left")
        right = route("right")
        for item in (left, right):
            item["outcomes"] = [{"outcome_id": "success", "probability": "1", "completion": "success", "delay_hours": "1", "recovery_amount_send": "0", "recovery_delay_hours": "0"}]
            item["percent_fee_bps"] = "0"
            item["fx_spread_bps"] = "0"
        left["fixed_fee_send"] = "2"
        right["fixed_fee_send"] = "1"
        left["liquidity"] = {"prefunding_amount_send": "36500", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        right["liquidity"] = {"prefunding_amount_send": "73000", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        tx = parse_scenario(scenario()).transaction
        report = compare_routes(tx, [parse_route(left), parse_route(right)])
        self.assertEqual(report["break_even_volumes"][0]["volume_transactions_per_period"], "10")

    def test_route_report_declared_inputs_reconstruct_golden_result(self):
        objective = {
            "metric": "maximize_expected_recipient_amount",
            "guardrails": {"minimum_probability_by_deadline": "0.5"},
        }
        original = parse_scenario(scenario(routes=[route()], objective=objective))
        report = compare_routes(original.transaction, original.routes, original.objective, original.scenario_id)
        declared = report["routes"][0]["declared_inputs"]
        self.assertEqual(declared["route"]["fixed_fee_send"], "1")
        self.assertEqual(declared["route"]["percent_fee_bps"], "100")
        self.assertEqual(len(declared["route"]["outcomes"]), 2)
        self.assertEqual(declared["transaction"]["send_precision"], 2)
        self.assertEqual(declared["objective"]["guardrails"]["minimum_probability_by_deadline"], "0.5")
        reconstructed = parse_scenario(
            {
                "contract_version": "corridor-lab.scenario/v1",
                "scenario_id": "fictional-reconstructed",
                "description": "A fictional reconstruction.",
                "fictional": True,
                "transaction": declared["transaction"],
                "routes": [declared["route"]],
                "objective": declared["objective"],
            }
        )
        rerun = evaluate_route(reconstructed.routes[0], reconstructed.transaction).as_dict()
        self.assertEqual(rerun["recipient_amount"], report["routes"][0]["recipient_amount"])
        self.assertEqual(rerun["expected_sender_cost"], report["routes"][0]["expected_sender_cost"])

    def test_break_even_is_independent_of_ambient_decimal_context(self):
        tx = parse_scenario(scenario()).transaction
        left = parse_route(route("left"))
        right = parse_route(route("right"))
        expected = compare_routes(tx, [left, right])
        original_context = getcontext().copy()
        try:
            getcontext().prec = 2
            getcontext().Emax = 2
            getcontext().Emin = -2
            actual = compare_routes(tx, [left, right])
        finally:
            setcontext(original_context)
        self.assertEqual(actual, expected)
