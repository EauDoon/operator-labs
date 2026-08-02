from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def route(route_id: str = "fictional-route") -> dict:
    return {
        "contract_version": "corridor-lab.route/v1",
        "route_id": route_id,
        "label": f"{route_id} (fictional)",
        "fictional": True,
        "fx_rate": "2.00",
        "fixed_fee_send": "1.00",
        "percent_fee_bps": "100",
        "fx_spread_bps": "100",
        "liquidity": {
            "prefunding_amount_send": "36500",
            "annual_cost_of_capital_bps": "1000",
            "holding_days": "1",
        },
        "outcomes": [
            {
                "outcome_id": "success",
                "probability": "0.8",
                "completion": "success",
                "delay_hours": "2",
                "recovery_amount_send": "0",
                "recovery_delay_hours": "0",
            },
            {
                "outcome_id": "failure",
                "probability": "0.2",
                "completion": "failure",
                "delay_hours": "1",
                "recovery_amount_send": "50",
                "recovery_delay_hours": "4",
            },
        ],
    }


def scenario(routes: list[dict] | None = None, objective: dict | None = None) -> dict:
    result = {
        "contract_version": "corridor-lab.scenario/v1",
        "scenario_id": "fictional-test-scenario",
        "description": "A fully fictional test scenario.",
        "fictional": True,
        "transaction": {
            "send_amount": "100.00",
            "send_currency": "SND",
            "send_precision": 2,
            "receive_currency": "RCV",
            "receive_precision": 2,
            "rounding": "ROUND_HALF_UP",
            "deadline_hours": "3",
            "volume_per_period": "100",
        },
    }
    if routes is not None:
        result["routes"] = copy.deepcopy(routes)
    if objective is not None:
        result["objective"] = copy.deepcopy(objective)
    return result
