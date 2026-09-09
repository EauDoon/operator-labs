import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.gui_controller import TraceCanaryController

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/v1"
class GuiCoverageTests(unittest.TestCase):
    def test_guidance_safe_coverage_and_regression(self):
        controller = TraceCanaryController()
        self.assertEqual(controller.coverage("", "").status, "unresolved")
        result = controller.coverage(FIXTURES / "contract.json", FIXTURES / "safe-export.json")
        self.assertEqual(result.status, "pass")
        self.assertIn("entities", result.human)
        self.assertIn("coverage", json.loads(result.json))
        bad = controller.coverage(FIXTURES / "contract.json", FIXTURES / "leaked-prompt.json")
        self.assertEqual(bad.exit_code, 1)
        self.assertNotIn("TCANARY_", bad.json + bad.human)
        self.assertEqual(controller.coverage(FIXTURES / "contract.json", FIXTURES / "absent.json").exit_code, 2)
