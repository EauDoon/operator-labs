"""Independent oracles for declared scenario inspection workflows."""
import unittest
from decimal import Decimal, localcontext

from corridor_lab.analysis import cost_ledger
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario
from helpers import route, scenario


class CostLedgerTests(unittest.TestCase):
    def test_components_reconcile_without_cross_currency_or_double_counting(self):
        source = parse_scenario(scenario([route()]))
        report = cost_ledger(source)
        rows = report["rows"]
        self.assertEqual([row["amount_send"] for row in rows], ["1", "1", "0.1", "10"])
        self.assertEqual(sum(Decimal(row["amount_send"]) for row in rows), Decimal("12.1"))
        self.assertTrue(all(row["send_currency"] == "SND" for row in rows))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(cost_ledger(source), report)
        for output_format in ("json", "csv", "markdown"):
            self.assertIn("failure_loss", render_report(report, output_format))

    def test_zero_cost_has_no_invented_share(self):
        raw = route()
        raw.update(fixed_fee_send="0", percent_fee_bps="0")
        raw["liquidity"]["prefunding_amount_send"] = "0"
        raw["outcomes"][1]["recovery_amount_send"] = "100"
        self.assertTrue(all(row["share_of_sender_cost"] is None
                            for row in cost_ledger(parse_scenario(scenario([raw])))["rows"]))


class DeadlineTargetTests(unittest.TestCase):
    def test_target_is_unconditional_success_and_never_interpolates(self):
        from corridor_lab.analysis import deadline_target
        source = parse_scenario(scenario([route()]))
        row = deadline_target(source, "0.8")["rows"][0]
        self.assertEqual((row["status"], row["earliest_hours"]), ("reached", "2"))
        self.assertEqual(deadline_target(source, "0")["rows"][0]["earliest_hours"], "0")
        row = deadline_target(source, "0.800001")["rows"][0]
        self.assertEqual((row["status"], row["earliest_hours"]), ("unreachable", None))
        self.assertEqual(row["maximum_success_probability"], "0.8")

    def test_tied_success_times_and_invalid_targets(self):
        from corridor_lab.analysis import deadline_target
        from corridor_lab.canonical import InputError
        raw = route()
        raw["outcomes"][1].update(completion="success", delay_hours="2", recovery_amount_send="0", recovery_delay_hours="0")
        source = parse_scenario(scenario([raw]))
        self.assertEqual(deadline_target(source, "1")["rows"][0]["earliest_hours"], "2")
        for target in ("NaN", "-0.1", "1.1", True):
            with self.assertRaises(InputError):
                deadline_target(source, target)


class ResolutionQuantileTests(unittest.TestCase):
    def test_exact_mass_boundaries_include_failure_recovery_time(self):
        from corridor_lab.analysis import resolution_quantiles
        source = parse_scenario(scenario([route()]))
        rows = resolution_quantiles(source, [Decimal("0.8"), Decimal("0.800001"), Decimal(1)])["rows"]
        self.assertEqual([row["resolution_hours"] for row in rows], ["2", "5", "5"])
        for output_format in ("json", "csv", "markdown"):
            self.assertIn("resolution_hours", render_report(resolution_quantiles(source, [Decimal(1)]), output_format))

    def test_invalid_probabilities_and_budgets_fail_closed(self):
        from corridor_lab.analysis import resolution_quantiles
        from corridor_lab.canonical import InputError
        source = parse_scenario(scenario([route()]))
        for values in ([], [Decimal(0)], [Decimal("1.01")], [Decimal("NaN")], [Decimal(1)] * 65,
                       [Decimal("0.5"), Decimal("0.50")]):
            with self.assertRaises(InputError):
                resolution_quantiles(source, values)


class LossProfileTests(unittest.TestCase):
    def test_loss_exceedance_is_strict_and_excludes_sender_fees(self):
        from corridor_lab.analysis import loss_profile
        rows = loss_profile(parse_scenario(scenario([route()])))["rows"]
        self.assertEqual([row["loss_threshold_send"] for row in rows], ["0", "50"])
        self.assertEqual([row["probability_above_threshold"] for row in rows], ["0.2", "0"])
        self.assertEqual([row["expected_excess_loss_send"] for row in rows], ["10", "0"])

    def test_full_recovery_has_zero_principal_loss_despite_failure(self):
        from corridor_lab.analysis import loss_profile
        raw = route()
        raw["outcomes"][1]["recovery_amount_send"] = "100"
        rows = loss_profile(parse_scenario(scenario([raw])))["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["probability_above_threshold"], "0")


class FeasibleAmountTests(unittest.TestCase):
    def test_fee_boundary_rounds_up_and_recovery_floor_is_respected(self):
        from corridor_lab.analysis import feasible_amount
        raw = route()
        raw["outcomes"][1]["recovery_amount_send"] = "0"
        row = feasible_amount(parse_scenario(scenario([raw])))["rows"][0]
        self.assertEqual(row["minimum_send_amount"], "1.02")
        self.assertEqual(feasible_amount(parse_scenario(scenario([route()])))["rows"][0]["minimum_send_amount"], "50")

    def test_hundred_percent_fee_and_zero_cost_bounds(self):
        from corridor_lab.analysis import feasible_amount
        raw = route()
        raw["percent_fee_bps"] = "10000"
        row = feasible_amount(parse_scenario(scenario([raw])))["rows"][0]
        self.assertEqual((row["status"], row["minimum_send_amount"]), ("infeasible", None))
        raw["fixed_fee_send"] = "0"
        raw["outcomes"][1]["recovery_amount_send"] = "0"
        row = feasible_amount(parse_scenario(scenario([raw])))["rows"][0]
        self.assertEqual(row["minimum_send_amount"], "0.01")

    def test_inspection_can_explain_a_currently_infeasible_amount(self):
        from corridor_lab.analysis import feasible_amount
        raw = scenario([route()])
        raw["transaction"]["send_amount"] = "1"
        row = feasible_amount(parse_scenario(raw))["rows"][0]
        self.assertFalse(row["current_amount_meets_bounds"])

    def test_current_bounds_are_checked_before_precision_grid_rounding(self):
        from corridor_lab.analysis import feasible_amount
        raw = route()
        raw["outcomes"][1]["recovery_amount_send"] = "0"
        source = scenario([raw])
        source["transaction"]["send_amount"] = "1.015"
        row = feasible_amount(parse_scenario(source))["rows"][0]
        self.assertEqual(row["minimum_send_amount"], "1.02")
        self.assertTrue(row["current_amount_meets_bounds"])
