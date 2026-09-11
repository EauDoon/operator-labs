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
