import unittest

from helpers import route, scenario

from corridor_lab.comparison import compare_routes
from corridor_lab.model import evaluate_route
from corridor_lab.route import parse_route
from corridor_lab.scenario import parse_scenario


class InvariantTests(unittest.TestCase):
    def test_zero_cost_route_preserves_principal(self):
        data = route()
        data["fx_rate"] = "1"
        data["fixed_fee_send"] = "0"
        data["percent_fee_bps"] = "0"
        data["fx_spread_bps"] = "0"
        data["liquidity"] = {"prefunding_amount_send": "0", "annual_cost_of_capital_bps": "0", "holding_days": "0"}
        data["outcomes"] = [{"outcome_id": "success", "probability": "1", "completion": "success", "delay_hours": "0", "recovery_amount_send": "0", "recovery_delay_hours": "0"}]
        result = evaluate_route(parse_route(data), parse_scenario(scenario()).transaction).as_dict()
        self.assertEqual(result["recipient_amount"], "100.00")
        self.assertEqual(result["expected_sender_cost"], "0.00")

    def test_higher_fee_cannot_improve_recipient_amount(self):
        low = route("low")
        high = route("high")
        high["fixed_fee_send"] = "2"
        tx = parse_scenario(scenario()).transaction
        self.assertLessEqual(
            evaluate_route(parse_route(high), tx).recipient_amount,
            evaluate_route(parse_route(low), tx).recipient_amount,
        )

    def test_higher_failure_probability_cannot_improve_expected_value(self):
        low = route("low")
        high = route("high")
        high["outcomes"][0]["probability"] = "0.7"
        high["outcomes"][1]["probability"] = "0.3"
        tx = parse_scenario(scenario()).transaction
        self.assertGreaterEqual(
            evaluate_route(parse_route(high), tx).expected_sender_cost,
            evaluate_route(parse_route(low), tx).expected_sender_cost,
        )

    def test_input_order_does_not_change_comparison(self):
        tx = parse_scenario(scenario()).transaction
        left = parse_route(route("left"))
        right = parse_route(route("right"))
        first = compare_routes(tx, [left, right])
        second = compare_routes(tx, [right, left])
        self.assertEqual(first, second)
