import unittest

from helpers import route
from corridor_lab.route import parse_route
from corridor_lab.scenario import ScenarioError


class RouteTests(unittest.TestCase):
    def test_parses_fictional_route(self):
        parsed = parse_route(route())
        self.assertEqual(parsed.route_id, "fictional-route")
        self.assertEqual(len(parsed.outcomes), 2)

    def test_nonfictional_route_is_rejected(self):
        data = route()
        data["fictional"] = False
        with self.assertRaises(ScenarioError):
            parse_route(data)

    def test_duplicate_outcomes_are_rejected(self):
        data = route()
        data["outcomes"][1]["outcome_id"] = "success"
        with self.assertRaises(ScenarioError):
            parse_route(data)

    def test_probabilities_must_sum_exactly_one(self):
        data = route()
        data["outcomes"][1]["probability"] = "0.19"
        with self.assertRaises(ScenarioError):
            parse_route(data)

    def test_success_cannot_have_recovery(self):
        data = route()
        data["outcomes"][0]["recovery_amount_send"] = "1"
        with self.assertRaises(ScenarioError):
            parse_route(data)
