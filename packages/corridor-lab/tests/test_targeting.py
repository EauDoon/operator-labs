import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path

from corridor_lab.canonical import InputError
from corridor_lab.cli import main as cli_main
from corridor_lab.scenario import parse_scenario
from corridor_lab.targeting import parse_constraint, robustness_review, target_search
from helpers import route, scenario


def hand_derived_cost(send_amount: Decimal) -> Decimal:
    """Independent recomputation of the helper route's expected sender cost.

    fixed 1.00 + percent 1% of send + liquidity carry
    (36500 * 1000 bps * 1 day / 365 = 10.00 per period, divided by the
    declared volume of 100) + failure loss 0.2 * max(0, send - recovery 50).
    """
    loss = Decimal("0.2") * max(Decimal(0), send_amount - Decimal(50))
    return Decimal("1.00") + send_amount * Decimal("0.01") + Decimal("0.10") + loss


class ConstraintParsingTests(unittest.TestCase):
    def test_kinds_ops_and_currency_units(self):
        parsed = parse_constraint("expected_sender_cost_at_most=10.50", "SND", "RCV")
        self.assertEqual(parsed["metric"], "expected_sender_cost")
        self.assertEqual(parsed["op"], "at_most")
        self.assertEqual(parsed["unit"], "cost SND")
        self.assertEqual(parsed["threshold"], Decimal("10.50"))
        self.assertEqual(parse_constraint("expected_recipient_amount_at_least=5", "SND", "RCV")["unit"], "amount RCV")

    def test_wrong_direction_and_unknown_names_fail_closed(self):
        with self.assertRaisesRegex(InputError, "does not support"):
            parse_constraint("expected_sender_cost_at_least=10")
        with self.assertRaisesRegex(InputError, "must be NAME=THRESHOLD"):
            parse_constraint("feeling_lucky_at_most=10")
        with self.assertRaisesRegex(InputError, "must be NAME=THRESHOLD"):
            parse_constraint("expected_sender_cost_at_most=")


class TargetSearchTests(unittest.TestCase):
    def setUp(self):
        self.scenario = parse_scenario(scenario(routes=[route("fictional-route-one"), route("fictional-route-two")]))

    def test_smallest_tested_feasible_value_matches_hand_derived_bounds(self):
        values = [Decimal("10"), Decimal("50"), Decimal("100")]
        report = target_search(self.scenario, "send_amount", values, ["expected_sender_cost_at_most=10"])
        rows = report["rows"]
        self.assertEqual(report["analysis"], "target-search")
        invalid = [row for row in rows if row["status"] == "invalid"]
        # send 10 is invalid for the helper routes: declared recovery 50 exceeds the principal
        self.assertEqual(len(invalid), 2)
        self.assertTrue(all(row["value"] == "10" for row in invalid))
        # hand-derived: at 50 recovery is complete so loss is zero; cost 1.55 <= 10
        at_50 = [row for row in rows if row["value"] == "50" and row["constraint"] == "expected_sender_cost_at_most"]
        self.assertEqual(Decimal(at_50[0]["observed"]), hand_derived_cost(Decimal("50")))
        self.assertTrue(at_50[0]["satisfied"])
        summaries = [row for row in rows if row["status"] == "summary"]
        self.assertEqual({row["value"] for row in summaries}, {"50"})
        self.assertEqual({row["constraint"] for row in summaries}, {"smallest_tested_feasible_value"})

    def test_multiple_constraints_and_unreachable(self):
        values = [Decimal("60"), Decimal("100")]
        report = target_search(
            self.scenario, "send_amount", values,
            ["expected_sender_cost_at_most=1.00", "probability_by_deadline_at_least=0.9"],
        )
        # probability 0.8 < 0.9 fails everywhere; sender cost 1.00 also impossible
        summaries = [row for row in report["rows"] if row["status"] == "summary"]
        self.assertEqual({row["constraint"] for row in summaries}, {"unreachable_within_tested_set"})
        self.assertIn("no tested candidate satisfied every declared constraint", summaries[0]["status_detail"])

    def test_deadline_constraint_uses_discrete_probabilities(self):
        values = [Decimal("100")]
        report = target_search(self.scenario, "deadline_hours", values, ["probability_by_deadline_at_least=0.8"])
        probability_rows = [row for row in report["rows"] if row["constraint"] == "probability_by_deadline_at_least"]
        self.assertEqual({row["satisfied"] for row in probability_rows}, {True})
        report = target_search(self.scenario, "deadline_hours", [Decimal("0.5")], ["probability_by_deadline_at_least=0.8"])
        probability_rows = [row for row in report["rows"] if row["constraint"] == "probability_by_deadline_at_least"]
        self.assertEqual({row["satisfied"] for row in probability_rows}, {False})

    def test_validation_and_budgets(self):
        with self.assertRaisesRegex(InputError, "one of"):
            target_search(self.scenario, "fx_rate", [Decimal("1")], ["expected_sender_cost_at_most=1"])
        with self.assertRaisesRegex(InputError, "distinct"):
            target_search(self.scenario, "send_amount", [Decimal("1"), Decimal("1")], ["expected_sender_cost_at_most=1"])
        with self.assertRaisesRegex(InputError, "at least one constraint"):
            target_search(self.scenario, "send_amount", [Decimal("1")], [])
        many_routes = parse_scenario(scenario(routes=[route("r-one"), route("r-two"), route("r-three")]))
        big_values = [Decimal(index) for index in range(1, 65)]
        with self.assertRaisesRegex(InputError, "row budget"):
            target_search(many_routes, "send_amount", big_values,
                          ["expected_sender_cost_at_most=1", "expected_recipient_amount_at_least=1",
                           "probability_by_deadline_at_least=0.5", "tail_completion_time_hours_at_most=1"])


class RobustnessTests(unittest.TestCase):
    def test_first_failing_scenario_per_route(self):
        base = scenario(routes=[route("fictional-route-one")])
        worse = scenario(routes=[route("fictional-route-one")])
        worse["transaction"]["deadline_hours"] = "0.5"  # probability_by_deadline drops to 0
        worse["scenario_id"] = "fictional-worse-case"
        report = robustness_review([parse_scenario(base), parse_scenario(worse)], ["a.json", "b.json"],
                                   ["probability_by_deadline_at_least=0.5"])
        rows = report["rows"]
        satisfied = {(row["scenario"], row["satisfied"]) for row in rows if row["constraint"] == "probability_by_deadline_at_least"}
        self.assertEqual(satisfied, {("fictional-test-scenario", True), ("fictional-worse-case", False)})
        first = [row for row in rows if row["constraint"] == "first_failing_scenario"]
        self.assertEqual(first[0]["scenario"], "fictional-worse-case")
        self.assertEqual(first[0]["route_id"], "fictional-route-one")
        self.assertIn("declared cases, not forecasts", report["scope"])

    def test_robust_scenario_reports_no_failure(self):
        base = scenario(routes=[route("fictional-route-one")])
        variant = scenario(routes=[route("fictional-route-one")])
        variant["scenario_id"] = "fictional-variant"
        report = robustness_review([parse_scenario(base), parse_scenario(variant)], ["a.json", "b.json"],
                                   ["probability_by_deadline_at_least=0.8"])
        first = [row for row in report["rows"] if row["constraint"] == "first_failing_scenario"][0]
        self.assertEqual(first["scenario"], "none in the supplied order")
        self.assertTrue(first["satisfied"])

    def test_mismatched_currencies_fail_closed(self):
        base = scenario(routes=[route()])
        other = scenario(routes=[route()])
        other["transaction"]["receive_currency"] = "ZZZ"
        with self.assertRaisesRegex(InputError, "matching currencies"):
            robustness_review([parse_scenario(base), parse_scenario(other)], ["a.json", "b.json"],
                              ["expected_sender_cost_at_most=1"])


class TargetingCliTests(unittest.TestCase):
    def test_target_search_cli_matches_library(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            scenario_path = Path(temporary) / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            output = Path(temporary) / "targets.json"
            code = cli_main(["target-search", str(scenario_path), "--parameter", "send_amount",
                             "--values", "10,50,100", "--constraint", "expected_sender_cost_at_most=10",
                             "--format", "json", "--output", str(output)])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            library = target_search(parse_scenario(scenario(routes=[route("fictional-embedded")])), "send_amount",
                                    [Decimal("10"), Decimal("50"), Decimal("100")], ["expected_sender_cost_at_most=10"])
            self.assertEqual(report, library)

    def test_robustness_cli_reports_protection_and_errors(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            first = Path(temporary) / "a.json"
            second = Path(temporary) / "b.json"
            first.write_text(json.dumps(scenario(routes=[route("fictional-shared")])), encoding="utf-8")
            other = scenario(routes=[route("fictional-shared")])
            other["transaction"]["deadline_hours"] = "0.1"
            other["scenario_id"] = "fictional-strained"
            second.write_text(json.dumps(other), encoding="utf-8")
            output = Path(temporary) / "robustness.md"
            self.assertEqual(cli_main(["robustness-review", str(first), str(second), "--constraint",
                                       "probability_by_deadline_at_least=0.8", "--format", "markdown", "--output", str(output)]), 0)
            text = output.read_text(encoding="utf-8")
            self.assertIn("fictional-strained", text)
            self.assertIn("first_failing_scenario", text)
            self.assertEqual(cli_main(["robustness-review", str(first), "--constraint", "nonsense"]), 2)


if __name__ == "__main__":
    unittest.main()
