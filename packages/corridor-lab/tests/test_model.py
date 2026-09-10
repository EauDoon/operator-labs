import unittest
from decimal import getcontext, setcontext

from corridor_lab.common import InputError
from corridor_lab.model import evaluate_route
from corridor_lab.route import parse_route
from corridor_lab.scenario import parse_scenario
from helpers import route, scenario


class ModelTests(unittest.TestCase):
    def test_hand_calculated_golden(self):
        tx = parse_scenario(scenario()).transaction
        result = evaluate_route(parse_route(route()), tx).as_dict()
        self.assertEqual(result["explicit_fee_send"], "2.00")
        self.assertEqual(result["amount_converted_send"], "98.00")
        self.assertEqual(result["fx_spread_cost_receive"], "1.96")
        self.assertEqual(result["recipient_amount"], "194.04")
        self.assertEqual(result["expected_recipient_amount"], "155.23")
        self.assertEqual(result["liquidity_carry_cost_send"], "0.10")
        self.assertEqual(result["expected_failure_recovery_cost_send"], "10.00")
        self.assertEqual(result["expected_sender_cost"], "12.10")
        self.assertEqual(result["probability_by_deadline"], "0.8")
        self.assertEqual(result["expected_completion_time_hours"], "2.6")
        self.assertEqual(result["median_completion_time_hours"], "2")
        self.assertEqual(result["tail_completion_time_hours"], "5")

    def test_recovery_above_principal_fails(self):
        data = route()
        data["outcomes"][1]["recovery_amount_send"] = "101"
        tx = parse_scenario(scenario()).transaction
        with self.assertRaises(InputError):
            evaluate_route(parse_route(data), tx)

    def test_evaluation_and_rendering_ignore_ambient_decimal_context(self):
        tx = parse_scenario(scenario()).transaction
        parsed_route = parse_route(route())
        expected = evaluate_route(parsed_route, tx).as_dict()
        original_context = getcontext().copy()
        try:
            getcontext().prec = 2
            getcontext().Emax = 2
            getcontext().Emin = -2
            actual = evaluate_route(parsed_route, tx).as_dict()
        finally:
            setcontext(original_context)
        self.assertEqual(actual, expected)
