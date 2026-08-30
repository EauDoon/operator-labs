import unittest

from helpers import route
from corridor_lab.route import parse_route
from corridor_lab.scenario import ScenarioError


class OutcomeTests(unittest.TestCase):
    def test_failure_resolution_adds_recovery_delay(self):
        parsed = parse_route(route())
        failure = parsed.outcomes[1]
        self.assertEqual(str(failure.resolution_hours), "5")

    def test_nonexclusive_probability_total_fails(self):
        data = route()
        data["outcomes"].append(dict(data["outcomes"][1], outcome_id="third", probability="0.1"))
        with self.assertRaises(ScenarioError):
            parse_route(data)
