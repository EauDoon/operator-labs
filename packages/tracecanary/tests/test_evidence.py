import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


class TraceCanaryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.files = bundle()
        for name, data in cls.files.items():
            (cls.root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")
        cls.controller = TraceCanaryController()

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_evidence_is_value_free_and_self_explaining(self):
        campaign = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=str(self.root / "leaked-prompt.json"),
            baseline_path=str(self.root / "safe-export.json"),
            batch_path=None, control_path=str(self.root / "positive-control.json"),
            minimum_ratio=None, population_scope=None, population_minimum=None)
        destination = self.root / "evidence.json"
        saved = self.controller.save_campaign_evidence(destination, campaign)
        self.assertEqual(saved.status, "pass")
        document = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(document["evidence_version"], "tracecanary.evidence/v1")
        self.assertIn("not bundled", document["meaning"])
        self.assertEqual(document["summary"]["campaign_status"], "regression")
        text = destination.read_text(encoding="utf-8")
        self.assertNotIn("TCANARY", text)
        self.assertNotIn("gen_ai.prompt", text)

    def test_evidence_respects_input_and_batch_protection(self):
        campaign = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=str(self.root / "safe-export.json"),
            baseline_path=None, batch_path=None, control_path=None,
            minimum_ratio=None, population_scope=None, population_minimum=None)
        refusal = self.controller.save_campaign_evidence(self.root / "contract.json", campaign)
        self.assertEqual(refusal.status, "unresolved")
        self.assertIn("must not replace", refusal.human)
        self.assertFalse((self.root / "evidence2.json").exists())

    def test_evidence_rejects_unsafe_content_before_writing(self):
        campaign = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=None, baseline_path=None, batch_path=None, control_path=None,
            minimum_ratio=None, population_scope=None, population_minimum=None)
        # The summary is rebuilt from known fields, so a poisoned unknown key
        # is dropped by construction; poisoning a kept field proves the
        # protected-value check still runs before any write.
        poisoned = GuiResultLike(campaign)
        refusal = self.controller.save_campaign_evidence(self.root / "poisoned.json", poisoned)
        self.assertEqual(refusal.status, "unresolved")
        self.assertIn("protected-value", refusal.human)
        self.assertFalse((self.root / "poisoned.json").exists())


class GuiResultLike:
    """A campaign result whose payload embeds a canary value in a kept field."""

    def __init__(self, campaign):
        poisoned = json.loads(campaign.json)
        poisoned["contract_version"] = "tracecanary/v1 TCANARY_PROMPT_71f0e04f"
        from tracecanary.gui_controller import GuiResult

        self.status = campaign.status
        self.exit_code = campaign.exit_code
        self.human = campaign.human
        self.json = json.dumps(poisoned)
        self.inputs = campaign.inputs
        self.input_dir = campaign.input_dir
        self.mode = campaign.mode


if __name__ == "__main__":
    unittest.main()
