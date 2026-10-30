"""CLI and desktop contract review read drafts with the contract loader's limits."""

import json
import tempfile
import unittest
from pathlib import Path

from support import run_cli
from tracecanary.contract import CONTRACT_MAX_BYTES, CONTRACT_MAX_DEPTH, load_contract
from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


def _nested(depth: int) -> dict:
    """A fixture contract with one extra field nested so the document has ``depth`` levels."""
    document = dict(bundle()["contract.json"])
    value: object = "leaf"
    for _ in range(depth - 1):
        value = [value]
    document["unsupported"] = value
    return document


class ContractReviewLimitTests(unittest.TestCase):
    def test_the_limits_are_the_contract_loader_limits(self):
        self.assertEqual((CONTRACT_MAX_BYTES, CONTRACT_MAX_DEPTH), (1_000_000, 50))

    def test_an_oversized_contract_is_refused_by_cli_and_desktop_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.json"
            text = json.dumps(bundle()["contract.json"])
            path.write_text(text + " " * (1_500_000 - len(text)), encoding="utf-8", newline="\n")
            code, stdout, stderr = run_cli("contract", "review", path)
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("1000000-byte limit", stderr)
            result = TraceCanaryController().review_contract(path)
            self.assertEqual(result.exit_code, 2)
            self.assertIn("GUI001", result.json)
            self.assertIn("1000000-byte limit", result.human)

    def test_depth_within_the_loader_limit_reaches_the_validator_in_both(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            accepted = root / "depth-40.json"
            accepted.write_text(json.dumps(_nested(40)), encoding="utf-8", newline="\n")
            refused = root / "depth-60.json"
            refused.write_text(json.dumps(_nested(60)), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(Exception, "unsupported fields"):
                load_contract(accepted)
            code, _, stderr = run_cli("contract", "review", accepted)
            self.assertEqual(code, 2)
            self.assertIn("unsupported fields", stderr)
            desktop = TraceCanaryController().review_contract(accepted)
            self.assertEqual(desktop.exit_code, 2)
            self.assertIn("unsupported fields", desktop.human)
            code, _, stderr = run_cli("contract", "review", refused)
            self.assertIn("nesting limit of 50", stderr)
            self.assertIn("nesting limit of 50", TraceCanaryController().review_contract(refused).human)


if __name__ == "__main__":
    unittest.main()
