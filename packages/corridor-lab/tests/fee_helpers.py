import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def transaction(
    send_amount: str = "1000.00",
    deadline_hours: str = "8",
    volume_per_period: str = "100",
) -> dict:
    return {
        "send_amount": send_amount,
        "send_currency": "SND",
        "send_precision": 2,
        "receive_currency": "RCV",
        "receive_precision": 2,
        "rounding": "ROUND_HALF_UP",
        "deadline_hours": deadline_hours,
        "volume_per_period": volume_per_period,
    }


def tiered_route(route_id: str = "tiered", basis: str = "marginal") -> dict:
    return {
        "contract_version": "corridor-lab.route/v2",
        "route_id": route_id,
        "label": f"{route_id} (fictional tiered)",
        "fictional": True,
        "fx_rate": "1.75",
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
        "fee_schedule": fee_schedule(basis),
    }


def fee_schedule(basis: str = "marginal") -> dict:
    """Three declared bands: (0,500], (500,1500], (1500, infinity)."""
    return {
        "basis": basis,
        "tiers": [
            {"upper_bound_send": "500", "fixed_fee_send": "5.00", "percent_fee_bps": "40"},
            {"upper_bound_send": "1500", "fixed_fee_send": "3.00", "percent_fee_bps": "25"},
            {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "15"},
        ],
        "period_charges": [
            {
                "label": "monthly-platform-fee",
                "amount_send": "400.00",
                "amortization_over": "scenario_volume",
            }
        ],
    }


def v2_scenario(routes: list[dict] | None = None, workloads: list[dict] | None = None) -> dict:
    result = {
        "contract_version": "corridor-lab.scenario/v2",
        "scenario_id": "fictional-tiered-scenario",
        "description": "A fully fictional scenario with tiered fees and declared workloads.",
        "fictional": True,
        "transaction": transaction(),
    }
    if routes is not None:
        result["routes"] = copy.deepcopy(routes)
    if workloads is not None:
        result["workload_scenarios"] = copy.deepcopy(workloads)
    return result


def workloads() -> list[dict]:
    return [
        {"workload_id": "low", "label": "Low declared volume", "transactions_per_period": "50"},
        {"workload_id": "base", "label": "Base declared volume", "transactions_per_period": "100"},
        {"workload_id": "peak", "label": "Peak declared volume", "transactions_per_period": "400"},
    ]
