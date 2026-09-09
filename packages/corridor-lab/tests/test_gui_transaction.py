import unittest
from helpers import scenario
from corridor_lab.gui_controller import CorridorGuiController

class GuiTransactionTests(unittest.TestCase):
    def test_demo_sweep_and_invalid_draft_preserve_state(self):
        controller = CorridorGuiController()
        self.assertIsNotNone(controller.transaction_sweep("deadline_hours", "1").error)
        controller.load_builtin_demo()
        source = controller.scenario
        result = controller.transaction_sweep("deadline_hours", "1,2,8")
        self.assertIsNone(result.error)
        self.assertEqual(len(result.report["rows"]), 6)
        self.assertIs(controller.scenario, source)
        self.assertIsNotNone(controller.transaction_sweep("deadline_hours", "1,").error)
        self.assertIs(controller.last_report, result.report)
        self.assertIn("transaction", controller.render_last_report("markdown"))
