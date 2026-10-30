"""contract review flags canary values that clash with any report's fixed wording."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import get_args

from support import run_cli, write_fixture, write_json
from tracecanary.authoring import REPORT_CODES, _report_vocabulary, review_contract
from tracecanary.fixture import bundle
from tracecanary.report import ReportMode

SOURCE = Path(__file__).resolve().parents[1] / "src" / "tracecanary"


def contract_with(value: str, **changes: object) -> dict:
    contract = json.loads(json.dumps(bundle()["contract.json"]))
    contract["canaries"].append({"label": "clash-canary", "category": "prompt", "value": value})
    contract.update(changes)
    return contract


def flagged(contract: dict) -> list[str]:
    report = review_contract(contract)
    return [finding["location"] for finding in report["review"]["findings"]
            if finding["severity"] == "conflict" and finding["location"].startswith("canaries[")]


class ReviewVocabularyTests(unittest.TestCase):
    def test_values_that_withhold_real_reports_are_flagged(self):
        for value in ("TC004", "coverage-gate", "retention-matrix", "required-0001", "Gate:", "standalone-check",
                      "anonymization", "population_gate", "TC013", "GUI007", "baseline-diff"):
            with self.subTest(value=value):
                self.assertEqual(flagged(contract_with(value)), ["canaries[5]"])

    def test_unique_synthetic_values_and_the_fixture_contract_pass(self):
        self.assertEqual(review_contract(bundle()["contract.json"])["status"], "pass")
        for value in ("TCANARY_9f2c4e1a7b3d5068", "TCANARY_ZZ_0001", "item-0300"):
            with self.subTest(value=value):
                self.assertEqual(flagged(contract_with(value)), [])

    def test_structural_identifiers_follow_the_draft(self):
        self.assertEqual(flagged(contract_with("required-0003")), ["canaries[5]"])
        self.assertEqual(flagged(contract_with("required-0004")), [])
        self.assertEqual(flagged(contract_with("item-0256")), ["canaries[5]"])
        small = {"max_input_bytes": 5000000, "max_nesting": 100, "max_batch_files": 10}
        self.assertEqual(flagged(contract_with("item-0010", limits=small)), ["canaries[5]"])
        self.assertEqual(flagged(contract_with("item-0011", limits=small)), [])
        self.assertEqual(flagged(contract_with("candidate-0003")), ["canaries[5]"])
        self.assertEqual(flagged(contract_with("candidate-0004")), [])

    def test_the_vocabulary_holds_none_of_the_bundle_contract_configuration(self):
        raw = bundle()["contract.json"]
        vocabulary = _report_vocabulary()
        configuration = [item for canary in raw["canaries"] for item in (canary["label"], canary["category"], canary["value"])]
        for key in ("forbidden_attribute_keys", "forbidden_attribute_key_prefixes", "forbidden_path_prefixes"):
            configuration.extend(raw[key])
        configuration.extend(field["key"] for field in raw["required_retained_fields"])
        for item in configuration:
            with self.subTest(item=item):
                self.assertNotIn(item, vocabulary)

    def test_flagged_values_really_withhold_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = write_fixture(root / "missing.json", "missing-operational-fields.json")
            for value, command in (("TC004", "check"), ("required-0001", "coverage")):
                with self.subTest(value=value):
                    contract = write_json(root / f"{command}.json", contract_with(value))
                    code, stdout, stderr = run_cli(command, "--contract", contract, "--input", missing, "--format", "json")
                    self.assertEqual((code, stdout, stderr), (2, "", ""))
                    code, stdout, _ = run_cli("contract", "review", contract, "--format", "json")
                    self.assertEqual(code, 1)
                    self.assertEqual(json.loads(stdout)["review"]["findings"][0]["location"], "canaries[5]")


class VocabularyDriftTests(unittest.TestCase):
    def _source_literals(self, pattern: str) -> set[str]:
        found: set[str] = set()
        for path in SOURCE.glob("*.py"):
            found.update(re.findall(pattern, path.read_text(encoding="utf-8")))
        return found

    def test_every_mode_the_source_assigns_is_a_vocabulary_mode(self):
        modes = self._source_literals(r'mode="([a-z-]+)"') | self._source_literals(r'\["mode"\] = "([a-z-]+)"')
        self.assertTrue(modes)
        self.assertEqual(modes - set(get_args(ReportMode)), set())

    def test_every_finding_code_in_the_source_is_listed(self):
        codes = self._source_literals(r'"((?:TC|GUI)[0-9]{3})"')
        self.assertEqual(codes - set(REPORT_CODES), set())
        self.assertEqual(set(REPORT_CODES) - codes, set())


if __name__ == "__main__":
    unittest.main()
