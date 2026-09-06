import unittest
from decimal import Decimal

import fee_helpers as fh
from corridor_lab.canonical import InputError
from corridor_lab.fees import parse_fee_schedule
from corridor_lab.model import evaluate_route
from corridor_lab.route import parse_route
from corridor_lab.scenario import parse_scenario


class FeeScheduleParsingTests(unittest.TestCase):
    def test_rejects_unknown_fields(self):
        schedule = fh.fee_schedule()
        schedule["surprise"] = 1
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_unsupported_basis(self):
        schedule = fh.fee_schedule("graduated")
        with self.assertRaisesRegex(InputError, "basis must be one of marginal, whole_band"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_empty_tiers(self):
        schedule = fh.fee_schedule()
        schedule["tiers"] = []
        with self.assertRaisesRegex(InputError, "non-empty array"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_null_upper_bound_before_the_final_tier(self):
        schedule = fh.fee_schedule()
        schedule["tiers"][0]["upper_bound_send"] = None
        with self.assertRaisesRegex(InputError, "null only on the final tier"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_non_increasing_bounds(self):
        schedule = fh.fee_schedule()
        schedule["tiers"][1]["upper_bound_send"] = "500"
        with self.assertRaisesRegex(InputError, "greater than the previous tier bound"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_negative_bounds_and_out_of_range_bps(self):
        for patch in ({"upper_bound_send": "0"},):
            schedule = fh.fee_schedule()
            schedule["tiers"][0].update(patch)
            with self.assertRaises(InputError):
                parse_fee_schedule(schedule, "route.fee_schedule")
        schedule = fh.fee_schedule()
        schedule["tiers"][0]["percent_fee_bps"] = "10001"
        with self.assertRaises(InputError):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_period_transactions_with_scenario_volume(self):
        schedule = fh.fee_schedule()
        schedule["period_charges"][0]["amortization_over"] = "scenario_volume"
        schedule["period_charges"][0]["period_transactions"] = "10"
        with self.assertRaisesRegex(InputError, "not used when amortization_over is scenario_volume"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_requires_period_transactions_for_declared_amortization(self):
        schedule = fh.fee_schedule()
        schedule["period_charges"][0]["amortization_over"] = "declared_transactions"
        with self.assertRaisesRegex(InputError, "period_transactions is required"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_duplicate_period_charge_labels(self):
        schedule = fh.fee_schedule()
        schedule["period_charges"].append(dict(schedule["period_charges"][0]))
        with self.assertRaisesRegex(InputError, "duplicate label"):
            parse_fee_schedule(schedule, "route.fee_schedule")

    def test_rejects_unsupported_amortization_mode(self):
        schedule = fh.fee_schedule()
        schedule["period_charges"][0]["amortization_over"] = "guess"
        with self.assertRaisesRegex(InputError, "amortization_over must be one of"):
            parse_fee_schedule(schedule, "route.fee_schedule")


class FeeCalculationTests(unittest.TestCase):
    def _fee(self, amount: str, basis: str):
        route = parse_route(fh.tiered_route("tiered", basis))
        assert route.fee_schedule is not None
        return route.fee_schedule.transaction_fee(Decimal(amount))

    def test_marginal_bands_split_the_amount(self):
        # 1000 = 500 in band 1 (40 bps) + 500 in band 2 (25 bps).
        # 500 * 0.0040 = 2.00 ; 500 * 0.0025 = 1.25 ; fixed = 3.00 (band 2).
        breakdown = self._fee("1000", "marginal")
        self.assertEqual(breakdown.percentage_fee_send, Decimal("3.25"))
        self.assertEqual(breakdown.fixed_fee_send, Decimal("3.00"))
        self.assertEqual(breakdown.total_send, Decimal("6.25"))
        self.assertEqual(breakdown.band_index, 1)

    def test_whole_band_applies_one_band_to_the_whole_amount(self):
        # 1000 * 0.0025 = 2.50 ; fixed = 3.00.
        breakdown = self._fee("1000", "whole_band")
        self.assertEqual(breakdown.percentage_fee_send, Decimal("2.50"))
        self.assertEqual(breakdown.total_send, Decimal("5.50"))

    def test_boundary_amount_belongs_to_the_lower_band(self):
        breakdown = self._fee("500", "marginal")
        self.assertEqual(breakdown.band_index, 0)
        self.assertEqual(breakdown.fixed_fee_send, Decimal("5.00"))
        self.assertEqual(breakdown.percentage_fee_send, Decimal("2.00"))

    def test_final_band_is_unbounded(self):
        breakdown = self._fee("2000", "marginal")
        self.assertEqual(breakdown.band_index, 2)
        # 500*0.0040 + 1000*0.0025 + 500*0.0015 = 2.00 + 2.50 + 0.75
        self.assertEqual(breakdown.percentage_fee_send, Decimal("5.25"))
        self.assertEqual(breakdown.fixed_fee_send, Decimal("0"))

    def test_marginal_percentage_is_continuous_across_a_boundary(self):
        below = self._fee("500", "marginal").percentage_fee_send
        above = self._fee("500.01", "marginal").percentage_fee_send
        self.assertLess(above - below, Decimal("0.01"))

    def test_marginal_never_less_than_the_cheapest_whole_band_above_small_amounts(self):
        small = self._fee("1", "marginal")
        self.assertEqual(small.band_index, 0)
        self.assertEqual(small.fixed_fee_send, Decimal("5.00"))

    def test_amortized_period_charge_uses_the_scenario_volume(self):
        route = parse_route(fh.tiered_route())
        assert route.fee_schedule is not None
        self.assertEqual(route.fee_schedule.amortized_period_charges(Decimal("100")), Decimal("4"))
        self.assertEqual(route.fee_schedule.amortized_period_charges(Decimal("400")), Decimal("1"))

    def test_declared_transactions_amortization_ignores_scenario_volume(self):
        schedule = fh.fee_schedule()
        schedule["period_charges"][0]["amortization_over"] = "declared_transactions"
        schedule["period_charges"][0]["period_transactions"] = "200"
        parsed = parse_fee_schedule(schedule, "fee_schedule")
        self.assertEqual(parsed.amortized_period_charges(Decimal("100")), Decimal("2"))
        self.assertEqual(parsed.amortized_period_charges(Decimal("400")), Decimal("2"))


class RouteContractV2Tests(unittest.TestCase):
    def test_v2_route_without_schedule_requires_flat_fees(self):
        data = fh.tiered_route()
        data.pop("fee_schedule")
        with self.assertRaisesRegex(InputError, r"fixed_fee_send"):
            parse_route(data)

    def test_v2_route_rejects_flat_fee_next_to_a_schedule(self):
        data = fh.tiered_route()
        data["fixed_fee_send"] = "1.00"
        with self.assertRaisesRegex(InputError, "double count fees"):
            parse_route(data)
        other = fh.tiered_route()
        other["percent_fee_bps"] = "10"
        with self.assertRaisesRegex(InputError, "double count fees"):
            parse_route(other)

    def test_v1_route_still_rejects_a_fee_schedule(self):
        data = fh.tiered_route()
        data["contract_version"] = "corridor-lab.route/v1"
        data["fixed_fee_send"] = "1.00"
        data["percent_fee_bps"] = "10"
        with self.assertRaisesRegex(InputError, r"unsupported field\(s\): fee_schedule"):
            parse_route(data)

    def test_unknown_route_version_is_rejected(self):
        data = fh.tiered_route()
        data["contract_version"] = "corridor-lab.route/v9"
        with self.assertRaisesRegex(InputError, "contract_version must be one of"):
            parse_route(data)

    def test_hierarchical_schedule_never_exceeds_a_flat_maximum(self):
        route = parse_route(fh.tiered_route("tiered", "marginal"))
        assert route.fee_schedule is not None
        highest_bps = max(tier.percent_fee_bps for tier in route.fee_schedule.tiers)
        breakdown = route.fee_schedule.transaction_fee(Decimal("900"))
        self.assertLessEqual(breakdown.percentage_fee_send, Decimal("900") * highest_bps / Decimal("10000"))

    def test_hand_calculated_tiered_evaluation(self):
        scenario = parse_scenario(fh.v2_scenario([fh.tiered_route("tiered", "marginal")]))
        result = evaluate_route(scenario.routes[0], scenario.transaction).as_dict()
        # transaction fee 6.25 + amortized period charge 400/100 = 4.00
        self.assertEqual(result["explicit_fee_transaction_send"], "6.25")
        self.assertEqual(result["explicit_fee_period_amortized_send"], "4.00")
        self.assertEqual(result["explicit_fee_send"], "10.25")
        self.assertEqual(result["amount_converted_send"], "989.75")
        # 989.75 * 1.75 = 1732.0625 ; spread 50 bps = 8.6603125
        self.assertEqual(result["recipient_amount"], "1723.40")
        self.assertEqual(result["fee_basis"], "marginal")

    def test_sensitivity_on_a_tiered_route_rejects_inactive_flat_fees(self):
        route = parse_route(fh.tiered_route())
        with self.assertRaisesRegex(InputError, "not an active assumption"):
            route.changed_parameter("fixed_fee_send", Decimal("1"))

    def test_v2_scenario_rejects_unknown_fields(self):
        data = fh.v2_scenario([fh.tiered_route()])
        data["guess"] = 1
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_scenario(data)

    def test_v1_scenario_rejects_a_v2_route(self):
        data = fh.v2_scenario([fh.tiered_route()])
        data["contract_version"] = "corridor-lab.scenario/v1"
        with self.assertRaisesRegex(InputError, "corridor-lab.route/v1 in a corridor-lab.scenario/v1 scenario"):
            parse_scenario(data)

    def test_v1_scenario_rejects_workload_scenarios(self):
        data = fh.v2_scenario([], fh.workloads())
        data["contract_version"] = "corridor-lab.scenario/v1"
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_scenario(data)

    def test_v2_scenario_accepts_mixed_v1_and_v2_routes(self):
        flat = {
            "contract_version": "corridor-lab.route/v1",
            "route_id": "flat",
            "label": "flat (fictional)",
            "fictional": True,
            "fx_rate": "1.75",
            "fixed_fee_send": "2.00",
            "percent_fee_bps": "20",
            "fx_spread_bps": "50",
            "liquidity": {
                "prefunding_amount_send": "36500",
                "annual_cost_of_capital_bps": "1000",
                "holding_days": "1",
            },
            "outcomes": [
                {
                    "outcome_id": "success",
                    "probability": "1",
                    "completion": "success",
                    "delay_hours": "2",
                    "recovery_amount_send": "0",
                    "recovery_delay_hours": "0",
                }
            ],
        }
        scenario = parse_scenario(fh.v2_scenario([flat, fh.tiered_route()]))
        self.assertEqual(
            [route.contract_version for route in scenario.routes],
            ["corridor-lab.route/v1", "corridor-lab.route/v2"],
        )


if __name__ == "__main__":
    unittest.main()
