"""Measured bounded workloads for parsing, analysis, and rendering.

Run directly to record one measurement. The workloads stay within the
declared input limits; results are recorded in PROGRESS.md together with the
environment. This is an observation aid, not a benchmark suite, and no
limits or outcomes change based on it.
"""

from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import route, scenario  # noqa: E402

from corridor_lab.canonical import parse_json_bytes  # noqa: E402
from corridor_lab.report import render_report  # noqa: E402
from corridor_lab.scenario import parse_scenario  # noqa: E402
from corridor_lab.stress import run_stress_grid  # noqa: E402
from corridor_lab.transaction_sweep import run_transaction_sweep  # noqa: E402

WORKLOAD_NOTES = "Workload: 24-value sweep and 2x24-cell stress grid over 6 declared routes, plus parse and render passes."


def corridor_workload() -> dict[str, float]:
    base = parse_scenario(scenario(routes=[route(f"fictional-route-{index}") for index in range(1, 7)]))
    timings: dict[str, float] = {}
    start = time.monotonic()
    values = [Decimal(index) for index in range(1, 25)]
    run_transaction_sweep(base, "deadline_hours", values)
    timings["corridor_transaction_sweep_24_values_6_routes"] = round(time.monotonic() - start, 4)
    start = time.monotonic()
    run_stress_grid(base, "fx_rate", [Decimal("1.70"), Decimal("1.85")], "fx_spread_bps",
                    [Decimal(index) for index in range(10, 250, 10)])
    timings["corridor_stress_grid_2x24_cells_6_routes"] = round(time.monotonic() - start, 4)
    sweep = run_transaction_sweep(base, "deadline_hours", values)
    start = time.monotonic()
    render_report(sweep, "markdown")
    timings["corridor_render_markdown"] = round(time.monotonic() - start, 4)
    start = time.monotonic()
    rendered = render_report(sweep, "json")
    timings["corridor_render_json"] = round(time.monotonic() - start, 4)
    start = time.monotonic()
    parse_json_bytes(rendered.encode("utf-8"))
    timings["corridor_parse_json"] = round(time.monotonic() - start, 4)
    return timings


def main() -> int:
    results = {"workload_notes": WORKLOAD_NOTES, "corridor": corridor_workload()}
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
