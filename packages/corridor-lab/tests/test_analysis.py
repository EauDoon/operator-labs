"""Independent Decimal oracles for explicit fictional scenario inspection."""
import unittest
from decimal import Decimal, localcontext

from helpers import route, scenario
from corridor_lab.analysis import guardrail_headroom, outcome_ledger, deadline_profile, break_even_check
from corridor_lab.canonical import InputError
from corridor_lab.scenario import parse_scenario
from corridor_lab.report import render_report


class HeadroomTests(unittest.TestCase):
    def test_signed_margins_and_equality_match_declared_guards(self):
        objective = {"metric": "minimize_expected_sender_cost", "guardrails": {
            "minimum_probability_by_deadline": "0.9", "maximum_tail_hours": "4"}}
        source = parse_scenario(scenario([route()], objective))
        expected = guardrail_headroom(source)
        self.assertEqual([row["headroom"] for row in expected["rows"]], ["-0.1", "-1"])
        self.assertTrue(all(not row["passes"] for row in expected["rows"]))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(guardrail_headroom(source), expected)
        objective["guardrails"].update(minimum_probability_by_deadline="0.8", maximum_tail_hours="5")
        self.assertTrue(all(row["passes"] for row in guardrail_headroom(parse_scenario(scenario([route()], objective)))["rows"]))
        for output_format in ("json", "csv", "markdown"):
            self.assertIn("headroom", render_report(expected, output_format))

    def test_missing_objective_does_not_infer_guardrails(self):
        with self.assertRaises(InputError):
            guardrail_headroom(parse_scenario(scenario([route()])))


class LedgerTests(unittest.TestCase):
    def test_contributions_reconcile_against_independent_decimal_oracle(self):
        report = outcome_ledger(parse_scenario(scenario([route()])))
        rows = report["rows"]
        self.assertEqual(sum(Decimal(row["expected_recipient_receive"]) for row in rows),
                         (Decimal(100) - Decimal(1) - Decimal(1)) * 2 * Decimal("0.99") * Decimal("0.8"))
        self.assertEqual(sum(Decimal(row["expected_failure_loss_send"]) for row in rows), Decimal(10))
        self.assertEqual(sum(Decimal(row["expected_recovery_send"]) for row in rows), Decimal(10))
        self.assertEqual(sum(Decimal(row["expected_resolution_hours"]) for row in rows), Decimal("2.6"))
        self.assertEqual([row["outcome_id"] for row in rows], ["failure", "success"])

    def test_ledger_requires_embedded_routes(self):
        with self.assertRaises(InputError):
            outcome_ledger(parse_scenario(scenario()))


class DeadlineTests(unittest.TestCase):
    def test_success_and_final_resolution_are_distinct_cdfs(self):
        rows = deadline_profile(parse_scenario(scenario([route()])))["rows"]
        self.assertEqual([row["hours"] for row in rows], ["0", "2", "3", "5"])
        self.assertEqual([row["successful_by_time"] for row in rows], ["0", "0.8", "0.8", "0.8"])
        self.assertEqual([row["resolved_by_time"] for row in rows], ["0", "0.8", "0.8", "1"])
        self.assertEqual([row["unresolved_probability"] for row in rows], ["1", "0.2", "0.2", "0"])
        self.assertTrue(rows[2]["declared_deadline"])

    def test_simultaneous_outcomes_and_zero_time(self):
        raw = route()
        for outcome in raw["outcomes"]:
            outcome.update(delay_hours="0", recovery_delay_hours="0")
        first = deadline_profile(parse_scenario(scenario([raw])))["rows"][0]
        self.assertEqual(first["successful_by_time"], "0.8")
        self.assertEqual(first["resolved_by_time"], "1")


class BreakEvenTests(unittest.TestCase):
    def test_nearest_integer_volumes_recompute_cost_difference(self):
        left, right = route("left"), route("right")
        right["fixed_fee_send"] = "5"
        right["liquidity"]["prefunding_amount_send"] = "0"
        row = break_even_check(parse_scenario(scenario([right, left])))["rows"][0]
        # Costs are 12 + 10/V and 16, so the independent intersection is 2.5.
        self.assertEqual(row["volume_transactions_per_period"], "2.5")
        self.assertEqual((row["lower_volume"], row["upper_volume"]), ("2", "3"))
        self.assertEqual(Decimal(row["lower_cost_delta_send"]), Decimal(1))
        self.assertLess(Decimal(row["upper_cost_delta_send"]), Decimal(0))

    def test_parallel_cost_curves_do_not_claim_a_crossover(self):
        row = break_even_check(parse_scenario(scenario([route("left"), route("right")])))["rows"][0]
        self.assertEqual(row["status"], "no_finite_break_even")
        self.assertNotIn("lower_volume", row)
