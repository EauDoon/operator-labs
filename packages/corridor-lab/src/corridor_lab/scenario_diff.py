"""Compare deterministic metric changes between two fictional scenarios."""
from decimal import Decimal

from .canonical import InputError, decimal_text, local_decimal_context
from .comparison import evaluate_scenario
from .scenario import Scenario

METRICS = ("expected_recipient_amount", "expected_sender_cost", "probability_by_deadline", "tail_completion_time_hours")

def diff_scenarios(baseline: Scenario, candidate: Scenario) -> dict[str, object]:
    for field in ("send_currency", "receive_currency", "send_precision", "receive_precision", "rounding"):
        if getattr(baseline.transaction, field) != getattr(candidate.transaction, field):
            raise InputError("scenario diff requires matching currencies, precisions, and rounding")
    left = evaluate_scenario(baseline)
    right = evaluate_scenario(candidate)
    before = {r["route_id"]: r for r in left["routes"]}
    after = {r["route_id"]: r for r in right["routes"]}
    rows = []
    with local_decimal_context():
        for route_id in sorted(before.keys() & after.keys()):
            for metric in METRICS:
                a, b = before[route_id][metric], after[route_id][metric]
                rows.append({"route_id": route_id, "metric": metric, "baseline": a, "candidate": b,
                             "delta": decimal_text(Decimal(b) - Decimal(a))})
    return {"report_version": "corridor-lab.scenario-diff/v1", "fictional": True,
            "scenario_id": candidate.scenario_id, "baseline_scenario_id": baseline.scenario_id,
            "transaction": right["transaction"], "baseline_transaction": left["transaction"],
            "added_routes": sorted(after.keys() - before.keys()), "removed_routes": sorted(before.keys() - after.keys()),
            "rows": rows}
