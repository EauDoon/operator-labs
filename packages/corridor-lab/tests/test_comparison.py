import unittest
from decimal import getcontext, setcontext

from helpers import route, scenario

from corridor_lab.canonical import MAX_ROUTE_PAIRS, InputError
from corridor_lab.comparison import compare_routes, evaluate_scenario
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

    def test_empty_route_list_is_rejected(self):
        tx = parse_scenario(scenario()).transaction
        with self.assertRaisesRegex(InputError, "at least one route is required"):
            compare_routes(tx, [])
        with self.assertRaisesRegex(InputError, "evaluate requires routes embedded in the scenario"):
            evaluate_scenario(parse_scenario(scenario()))

    def test_duplicate_route_identifiers_are_rejected(self):
        tx = parse_scenario(scenario()).transaction
        with self.assertRaisesRegex(InputError, "route identifiers must be unique"):
            compare_routes(tx, [parse_route(route("same")), parse_route(route("same"))])

    def test_route_pair_budget_is_enforced_before_evaluation(self):
        tx = parse_scenario(scenario()).transaction
        count = 2
        while count * (count - 1) // 2 <= MAX_ROUTE_PAIRS:
            count += 1
        routes = [parse_route(route(f"r{index:02d}")) for index in range(count)]
        with self.assertRaisesRegex(InputError, f"{MAX_ROUTE_PAIRS}-pair budget"):
            compare_routes(tx, routes)

    def test_matching_fixed_costs_have_no_finite_break_even(self):
        left = route("left")
        right = route("right")
        for item in (left, right):
            item["outcomes"] = [
                {
                    "outcome_id": "success",
                    "probability": "1",
                    "completion": "success",
                    "delay_hours": "1",
                    "recovery_amount_send": "0",
                    "recovery_delay_hours": "0",
                }
            ]
            item["percent_fee_bps"] = "0"
            item["fx_spread_bps"] = "0"
            item["fixed_fee_send"] = "1"
        left["liquidity"] = {"prefunding_amount_send": "36500", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        right["liquidity"] = {"prefunding_amount_send": "73000", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        tx = parse_scenario(scenario()).transaction
        report = compare_routes(tx, [parse_route(left), parse_route(right)])
        self.assertEqual(report["break_even_volumes"][0]["status"], "no_finite_break_even")
        self.assertNotIn("volume_transactions_per_period", report["break_even_volumes"][0])

    def test_dominated_cost_structure_has_no_positive_break_even(self):
        left = route("left")
        right = route("right")
        for item in (left, right):
            item["outcomes"] = [
                {
                    "outcome_id": "success",
                    "probability": "1",
                    "completion": "success",
                    "delay_hours": "1",
                    "recovery_amount_send": "0",
                    "recovery_delay_hours": "0",
                }
            ]
            item["percent_fee_bps"] = "0"
            item["fx_spread_bps"] = "0"
        left["fixed_fee_send"] = "2"
        right["fixed_fee_send"] = "1"
        left["liquidity"] = {"prefunding_amount_send": "73000", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        right["liquidity"] = {"prefunding_amount_send": "36500", "annual_cost_of_capital_bps": "1000", "holding_days": "1"}
        tx = parse_scenario(scenario()).transaction
        report = compare_routes(tx, [parse_route(left), parse_route(right)])
        self.assertEqual(report["break_even_volumes"][0]["status"], "no_positive_break_even")

    def test_guardrails_reject_ineligible_routes_without_ranking_them(self):
        objective = {
            "metric": "maximize_expected_recipient_amount",
            "guardrails": {"minimum_probability_by_deadline": "0.9", "maximum_tail_hours": "4"},
        }
        parsed = parse_scenario(scenario(objective=objective))
        report = compare_routes(parsed.transaction, [parse_route(route())], parsed.objective)
        self.assertEqual(report["ranking"]["eligible_routes"], [])
        self.assertEqual(
            report["ranking"]["guardrail_rejections"],
            [{"route_id": "fictional-route", "failed_guardrails": ["minimum_probability_by_deadline", "maximum_tail_hours"]}],
        )

    def test_minimize_sender_cost_ranks_cheaper_eligible_route_first(self):
        cheap = route("cheap")
        expensive = route("expensive")
        expensive["fixed_fee_send"] = "2.00"
        objective = {
            "metric": "minimize_expected_sender_cost",
            "guardrails": {"maximum_tail_hours": "24"},
        }
        parsed = parse_scenario(scenario(objective=objective))
        report = compare_routes(parsed.transaction, [parse_route(expensive), parse_route(cheap)], parsed.objective)
        self.assertEqual([item["route_id"] for item in report["ranking"]["eligible_routes"]], ["cheap", "expensive"])
        self.assertEqual(report["ranking"]["guardrail_rejections"], [])
