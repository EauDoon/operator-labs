"""Measured bounded workloads for contract parsing and batch checking.

Run directly to record one measurement. The workloads stay within the
declared input limits; results are recorded in PROGRESS.md together with the
environment. This is an observation aid, not a benchmark suite, and no
limits or outcomes change based on it.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.batching import run_batch  # noqa: E402
from tracecanary.contract import parse_contract  # noqa: E402
from tracecanary.fixture import _attribute, _safe_trace, bundle  # noqa: E402

WORKLOAD_NOTES = "Workload: 32-file batch of about 120 KB synthetic traces each, within the default contract limits."


def _padded_trace(size_target: int) -> dict:
    trace = _safe_trace()
    filler = "F" * 900
    events = max(1, size_target // (len(json.dumps({"key": filler})) + 1))
    trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"] = [
        {"name": "telemetry.exported", "attributes": [_attribute("synthetic.pad", filler)]} for _ in range(events)
    ]
    return trace


def main() -> int:
    fixtures = bundle()
    contract = parse_contract(fixtures["contract.json"])
    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for index in range(32):
            (root / f"export-{index:02d}.json").write_text(json.dumps(_padded_trace(120_000)))
        start = time.monotonic()
        report = run_batch(contract, root, False, False)
        timings["tracecanary_batch_32_files_120kb"] = round(time.monotonic() - start, 4)
        assert report["status"] in {"pass", "regression"}
    print(json.dumps({"workload_notes": WORKLOAD_NOTES, "tracecanary": timings}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
