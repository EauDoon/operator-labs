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
