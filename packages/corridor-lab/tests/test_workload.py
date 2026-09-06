import unittest
from decimal import Decimal

import fee_helpers as fh
from corridor_lab.canonical import InputError
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario
from corridor_lab.workload import break_even_workloads, run_workload


def _scenario(routes=None, workloads=None):
    return parse_scenario(
        fh.v2_scenario(
            routes if routes is not None else [fh.tiered_route("tiered")],
            workloads if workloads is not None else fh.workloads(),
        )
    )


class WorkloadTests(unittest.TestCase):
    def test_requires_declared_workloads(self):
        scenario = parse_scenario(fh.v2_scenario([fh.tiered_route()]))
        with self.assertRaisesRegex(InputError, "declares no workload_scenarios"):
            run_workload(scenario)

    def test_rejects_unknown_workload_ids(self):
        with self.assertRaisesRegex(InputError, "unknown workload id"):
            run_workload(_scenario(), ["nope"])

    def test_rejects_empty_selection(self):
        with self.assertRaisesRegex(InputError, "must not be empty"):
            run_workload(_scenario(), [""])

    def test_selection_is_filtered_and_ordered_by_declaration(self):
        report = run_workload(_scenario(), ["peak", "low"])
        self.assertEqual([row["workload_id"] for row in report["rows"]], ["low", "peak"])

    def test_hand_calculated_rows(self):
        report = run_workload(_scenario())
        rows = {(row["workload_id"]): row for row in report["rows"]}
        # Transaction fee is volume independent: 6.25 (see test_fees).
        # Period charge of 400 amortized over the declared volume: 8.00 / 4.00 / 1.00.
        # Liquidity numerator is 36500 * 1000/10000 * 1/365 = 10.00 per period.
        self.assertEqual(rows["low"]["transactions_per_period"], "50")
        self.assertEqual(rows["low"]["explicit_fee_transaction_send"], "6.25")
        self.assertEqual(rows["low"]["explicit_fee_period_amortized_send"], "8.00")
        self.assertEqual(rows["low"]["explicit_fee_send"], "14.25")
        self.assertEqual(rows["low"]["liquidity_carry_cost_send"], "0.20")
        self.assertEqual(rows["low"]["expected_sender_cost"], "14.45")

        self.assertEqual(rows["base"]["explicit_fee_send"], "10.25")
        self.assertEqual(rows["base"]["liquidity_carry_cost_send"], "0.10")
        self.assertEqual(rows["base"]["expected_sender_cost"], "10.35")

        self.assertEqual(rows["peak"]["explicit_fee_period_amortized_send"], "1.00")
        self.assertEqual(rows["peak"]["liquidity_carry_cost_send"], "0.03")
        self.assertEqual(rows["peak"]["period_expected_sender_cost_send"], "2910.00")

    def test_higher_volume_never_raises_the_amortized_period_charge(self):
        report = run_workload(_scenario())
        rows = [row for row in report["rows"]]
        charges = [Decimal(row["explicit_fee_period_amortized_send"]) for row in rows]
        volumes = [Decimal(row["transactions_per_period"]) for row in rows]
        for index in range(1, len(rows)):
            if volumes[index] > volumes[index - 1]:
                self.assertLessEqual(charges[index], charges[index - 1])

    def test_recipient_amount_rises_with_volume_when_period_charges_use_scenario_volume(self):
        report = run_workload(_scenario())
        rows = sorted(report["rows"], key=lambda row: Decimal(row["transactions_per_period"]))
        recipients = [Decimal(row["recipient_amount"]) for row in rows]
        self.assertEqual(recipients, sorted(recipients))
        self.assertLess(recipients[0], recipients[-1])

    def test_recipient_amount_is_constant_without_scenario_volume_charges(self):
        data = fh.v2_scenario([fh.tiered_route()], fh.workloads())
        data["routes"][0]["fee_schedule"]["period_charges"] = []
        report = run_workload(parse_scenario(data))
        self.assertEqual(len({row["recipient_amount"] for row in report["rows"]}), 1)

    def test_workload_row_budget_is_enforced(self):
        routes = [fh.tiered_route(f"route-{index}") for index in range(64)]
        workloads = [
            {"workload_id": f"w{index}", "label": "w", "transactions_per_period": str(index + 1)}
            for index in range(9)
        ]
        scenario = parse_scenario(fh.v2_scenario(routes, workloads))
        with self.assertRaisesRegex(InputError, "512-row budget"):
            run_workload(scenario)

    def test_declared_transactions_amortization_ignores_workload_volume(self):
        data = fh.v2_scenario([fh.tiered_route()], fh.workloads())
        data["routes"][0]["fee_schedule"]["period_charges"][0]["amortization_over"] = "declared_transactions"
        data["routes"][0]["fee_schedule"]["period_charges"][0]["period_transactions"] = "80"
        report = run_workload(parse_scenario(data))
        for row in report["rows"]:
            self.assertEqual(row["explicit_fee_period_amortized_send"], "5.00")

    def test_json_csv_and_markdown_render(self):
        report = run_workload(_scenario())
        json_text = render_report(report, "json")
        self.assertIn('"report_version":"corridor-lab.workload/v1"', json_text)
        csv_text = render_report(report, "csv")
        self.assertIn("workload_id,route_id,transactions_per_period", csv_text)
        markdown = render_report(report, "markdown")
        self.assertIn("## How to read this workload report", markdown)
        self.assertIn("not measured or forecast", markdown)

    def test_report_is_deterministic(self):
        scenario = _scenario()
        self.assertEqual(render_report(run_workload(scenario), "json"), render_report(run_workload(scenario), "json"))

    def test_workload_scenario_rejects_duplicate_ids(self):
        data = fh.v2_scenario([fh.tiered_route()], fh.workloads())
        data["workload_scenarios"][1]["workload_id"] = "low"
        with self.assertRaisesRegex(InputError, "duplicate workload_id"):
            parse_scenario(data)

    def test_workload_scenario_rejects_non_positive_volume(self):
        data = fh.v2_scenario([fh.tiered_route()], fh.workloads())
        data["workload_scenarios"][0]["transactions_per_period"] = "0"
        with self.assertRaises(InputError):
            parse_scenario(data)


def _fixed_fee_route(route_id: str, fixed_fee: str, period_charge: str | None = None) -> dict:
    """A one-band declared schedule: a flat transaction fee plus an optional period charge."""
    route = fh.tiered_route(route_id, "whole_band")
    route["fee_schedule"] = {
        "basis": "whole_band",
        "tiers": [{"upper_bound_send": None, "fixed_fee_send": fixed_fee, "percent_fee_bps": "0"}],
        "period_charges": (
            [
                {
                    "label": "platform-period-charge",
                    "amount_send": period_charge,
                    "amortization_over": "scenario_volume",
                }
            ]
            if period_charge is not None
            else []
        ),
    }
    return route


class BreakEvenWorkloadTests(unittest.TestCase):
    def _crossing_scenario(self):
        # high-fixed: 20.00 per transaction, no period charge  -> 20 + 10/V
        # metered:    no transaction fee, 4000 per period      -> 4000/V + 10/V
        # At V=50 the metered route costs more; by V=400 it costs less.
        routes = [
            _fixed_fee_route("high-fixed", "20.00"),
            _fixed_fee_route("metered", "0", "4000"),
        ]
        return parse_scenario(fh.v2_scenario(routes, fh.workloads()))

    def test_hand_calculated_crossing(self):
        scenario = self._crossing_scenario()
        report = break_even_workloads(scenario, "high-fixed", "metered")
        points = {point["workload_id"]: point for point in report["points"]}
        self.assertEqual(points["low"]["left_expected_sender_cost"], "20.20")
        self.assertEqual(points["low"]["right_expected_sender_cost"], "80.20")
        self.assertEqual(points["low"]["difference_send"], "-60.00")
        self.assertEqual(points["base"]["difference_send"], "-20.00")
        self.assertEqual(points["peak"]["left_expected_sender_cost"], "20.03")
        self.assertEqual(points["peak"]["right_expected_sender_cost"], "10.03")
        self.assertEqual(points["peak"]["difference_send"], "10.00")

    def test_detects_a_crossing_between_declared_workloads(self):
        report = break_even_workloads(self._crossing_scenario(), "high-fixed", "metered")
        self.assertEqual(report["status"], "crossing_between_declared_workloads")
        self.assertEqual(report["lower_workload_id"], "base")
        self.assertEqual(report["upper_workload_id"], "peak")

    def test_reports_no_crossing_when_ordering_is_stable(self):
        routes = [_fixed_fee_route("high-fixed", "20.00"), _fixed_fee_route("metered", "0", "400")]
        scenario = parse_scenario(fh.v2_scenario(routes, fh.workloads()))
        report = break_even_workloads(scenario, "high-fixed", "metered")
        self.assertEqual(report["status"], "no_crossing_between_declared_workloads")
        self.assertIn("note", report)

    def test_rejects_unknown_routes_and_identical_pairs(self):
        scenario = self._crossing_scenario()
        with self.assertRaisesRegex(InputError, "unknown route id"):
            break_even_workloads(scenario, "ghost", "metered")
        with self.assertRaisesRegex(InputError, "two different routes"):
            break_even_workloads(scenario, "metered", "metered")

    def test_requires_at_least_two_workloads(self):
        routes = [_fixed_fee_route("high-fixed", "20.00"), _fixed_fee_route("metered", "0", "4000")]
        scenario = parse_scenario(fh.v2_scenario(routes, fh.workloads()[:1]))
        with self.assertRaisesRegex(InputError, "at least two declared workloads"):
            break_even_workloads(scenario, "high-fixed", "metered")

    def test_break_even_markdown_explains_the_lack_of_interpolation(self):
        scenario = self._crossing_scenario()
        markdown = render_report(break_even_workloads(scenario, "high-fixed", "metered"), "markdown")
        self.assertIn("does not interpolate", markdown)
        self.assertIn("not a recommendation", markdown)


if __name__ == "__main__":
    unittest.main()
