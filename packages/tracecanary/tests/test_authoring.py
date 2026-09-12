import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.authoring import (
    empty_template,
    render_review_human,
    review_contract,
    validate_draft,
)
from tracecanary.contract import ContractError
from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


class AuthoringLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = bundle()

    def test_template_is_valid_and_placeholder_is_flagged_by_validation(self):
        template = empty_template()
        validate_draft(template)
        self.assertTrue(template["canaries"][0]["value"].startswith("TCANARY_"))

    def test_clean_contract_reviews_clean(self):
        report = review_contract(self.files["contract.json"])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["review"]["findings"], [])
        self.assertNotIn("TCANARY", json.dumps(report))

    def test_conflicts_and_ineffective_paths_are_actionable(self):
        bad = {
            **self.files["contract.json"],
            "required_retained_fields": self.files["contract.json"]["required_retained_fields"]
            + [{"scope": "span", "key": "gen_ai.prompt"}],
            "forbidden_path_prefixes": [
                "/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/key",
                "/resourceSpans/*/scopeSpans/*/spans/attributes/*",
            ],
        }
        report = review_contract(bad)
        self.assertEqual(report["status"], "regression")
        locations = {finding["location"] for finding in report["review"]["findings"]}
        self.assertIn("required_retained_fields[4]", locations)
        self.assertIn("forbidden_path_prefixes[1]", locations)
        for finding in report["review"]["findings"]:
            self.assertTrue(finding["message"])
            self.assertTrue(finding["suggestion"])
            self.assertNotIn("TCANARY", json.dumps(finding))

    def test_malformed_paths_fail_with_suggestions(self):
        for prefix in ("//double//slash", "/resourceSpans/*/span*/key"):
            with self.subTest(prefix=prefix):
                draft = {**self.files["contract.json"], "forbidden_path_prefixes": [prefix]}
                report = review_contract(draft)
                self.assertEqual(report["status"], "regression")
                self.assertEqual(report["review"]["findings"][0]["severity"], "malformed")
        with self.assertRaisesRegex(ContractError, "JSON pointers"):
            review_contract({**self.files["contract.json"], "forbidden_path_prefixes": ["no-leading-slash"]})

    def test_shadowed_forbidden_key_is_reported_conservatively(self):
        draft = {
            **self.files["contract.json"],
            "forbidden_attribute_keys": ["enduser.id"],
            "forbidden_attribute_key_prefixes": ["enduser."],
        }
        report = review_contract(draft)
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["review"]["findings"][0]["severity"], "ineffective")

    def test_validator_rejects_what_it_catches_first(self):
        duplicate = {**self.files["contract.json"], "canaries": self.files["contract.json"]["canaries"] + [dict(self.files["contract.json"]["canaries"][0])]}
        with self.assertRaisesRegex(ContractError, "unique"):
            review_contract(duplicate)

    def test_human_render_explains_and_stays_value_free(self):
        draft = {**self.files["contract.json"], "forbidden_path_prefixes": ["/resourceSpans/*/scopeSpans/*/spans/attributes/*"]}
        human = render_review_human(review_contract(draft))
        self.assertIn("suggestion:", human)
        self.assertIn("not a privacy guarantee", human)
        self.assertNotIn("TCANARY", human)


class ControllerAuthoringTests(unittest.TestCase):
    def test_template_round_trip_and_transactional_draft(self):
        controller = TraceCanaryController()
        template = controller.contract_template_text()
        self.assertEqual(controller.validate_draft_text(template), json.loads(template))
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "contract.json"
            saved = controller.save_contract_draft(template, destination)
            self.assertEqual(saved.status, "pass")
            self.assertIn("canary configuration", saved.human)
            refused = controller.save_contract_draft(template, destination)
            self.assertEqual(refused.status, "unresolved")
            self.assertIn("must not replace", refused.human)
            broken = controller.save_contract_draft("{not json", Path(temporary) / "broken.json")
            self.assertEqual(broken.status, "unresolved")
            self.assertIn("not valid JSON", broken.human)
            invalid = controller.save_contract_draft(json.dumps({"contract_version": "wrong"}), Path(temporary) / "invalid.json")
            self.assertEqual(invalid.status, "unresolved")
            self.assertIn("failed validation", invalid.human)
            self.assertFalse((Path(temporary) / "invalid.json").exists())

    def test_review_via_controller_matches_cli(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            bad = {
                **bundle()["contract.json"],
                "forbidden_path_prefixes": ["/resourceSpans/*/scopeSpans/*/spans/attributes/*"],
            }
            draft = root / "draft.json"
            draft.write_text(json.dumps(bad), encoding="utf-8")
            from tracecanary.cli import main

            self.assertEqual(main(["contract", "review", str(draft), "--format", "json", "--output", str(root / "review.json")]), 1)
            controller = TraceCanaryController()
            result = controller.review_contract(draft)
            self.assertEqual(result.status, "regression")
            self.assertEqual(json.loads(result.json), json.loads((root / "review.json").read_text(encoding="utf-8")))
            self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
