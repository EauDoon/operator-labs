from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError
from tracecanary.cli import EXIT_PASS, EXIT_UNRESOLVED, main
from tracecanary.contract import parse_contract
from tracecanary.profiles import PROFILE_IDS, describe, profile, write_profile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Profiles ship as package data alongside the module, not at the package root.
PROFILE_DIR = SRC / "tracecanary" / "profiles"
SEMCONV = "opentelemetry/semconv/1.43.0"


def _run(command: list[str]) -> tuple[int, str, str]:
    output = io.StringIO()
    error = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
        status = main(command)
    return status, output.getvalue(), error.getvalue()


class ProfileDocumentTests(unittest.TestCase):
    def test_at_least_four_profiles_are_shipped(self) -> None:
        self.assertGreaterEqual(len(PROFILE_IDS), 4)
        self.assertEqual(PROFILE_IDS, tuple(sorted(PROFILE_IDS)))

    def test_every_profile_id_has_a_document(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                self.assertTrue((PROFILE_DIR / f"{profile_id}.json").is_file())

    def test_every_profile_parses_through_parse_contract(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                contract = parse_contract(profile(profile_id))
                self.assertEqual(contract.contract_version, "tracecanary/v2")
                self.assertEqual(contract.semantic_conventions_version, SEMCONV)
                self.assertIsNotNone(contract.retention)

    def test_profiles_are_distinct_contracts(self) -> None:
        documents = {profile_id: json.dumps(profile(profile_id), sort_keys=True) for profile_id in PROFILE_IDS}
        self.assertEqual(len(set(documents.values())), len(PROFILE_IDS))

    def test_profile_canary_values_are_unique_and_synthetic(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                contract = profile(profile_id)
                values = [canary["value"] for canary in contract["canaries"]]
                labels = [canary["label"] for canary in contract["canaries"]]
                self.assertEqual(len(set(values)), len(values))
                self.assertEqual(len(set(labels)), len(labels))
                for value in values:
                    self.assertTrue(value.startswith("TCANARY_"), value)
                    self.assertRegex(value, r"^TCANARY_[A-Z0-9_]+_[0-9a-f]{8}$")

    def test_profile_returns_a_deep_copy(self) -> None:
        first = profile(PROFILE_IDS[0])
        first["canaries"][0]["value"] = "mutated"
        second = profile(PROFILE_IDS[0])
        self.assertNotEqual(second["canaries"][0]["value"], "mutated")
        self.assertEqual(second["canaries"][0]["value"][:8], "TCANARY_")

    def test_unknown_profile_id_is_rejected(self) -> None:
        with self.assertRaises(InputError) as raised:
            profile("does-not-exist")
        for profile_id in PROFILE_IDS:
            self.assertIn(profile_id, str(raised.exception))


class ProfileDescribeTests(unittest.TestCase):
    def test_describe_returns_stable_metadata(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                metadata = describe(profile_id)
                self.assertEqual(metadata["profile_id"], profile_id)
                self.assertEqual(metadata["semantic_conventions_version"], SEMCONV)
                self.assertTrue(metadata["title"])
                self.assertTrue(metadata["summary"])
                self.assertTrue(metadata["covered_attributes"])
                self.assertEqual(metadata, describe(profile_id))

    def test_gen_ai_profile_covers_the_documented_attributes(self) -> None:
        metadata = describe("gen-ai-baseline")
        self.assertEqual(metadata["title"], "GenAI baseline")
        self.assertEqual(
            metadata["covered_attributes"],
            [
                "key-prefix:enduser.",
                "key:gen_ai.prompt",
                "key:gen_ai.tool.call.arguments",
                "key:gen_ai.tool.call.result",
                "path-prefix:/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue",
                "resource:service.name",
                "span:gen_ai.operation.name",
            ],
        )
        self.assertEqual(
            metadata["retention_requirements"],
            [
                {"requirement_id": "service-name", "scope": "resource", "key": "service.name", "comparison": "presence"},
                {"requirement_id": "operation-name", "scope": "span", "key": "gen_ai.operation.name", "comparison": "presence"},
            ],
        )

    def test_covered_attributes_match_the_profile_contract(self) -> None:
        """describe() must be derived from the contract, not from a stale list."""
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                contract = profile(profile_id)
                expected = {f"key:{key}" for key in contract.get("forbidden_attribute_keys", [])}
                expected |= {f"key-prefix:{prefix}" for prefix in contract.get("forbidden_attribute_key_prefixes", [])}
                expected |= {f"path-prefix:{prefix}" for prefix in contract.get("forbidden_path_prefixes", [])}
                expected |= {f"{field['scope']}:{field['key']}" for field in contract["required_retained_fields"]}
                for requirement in contract["retention"]["requirements"]:
                    expected.add(f"{requirement['scope']}:{requirement['key']}")
                    for matching_key in requirement.get("matching_keys", []):
                        expected.add(f"identity:{matching_key['scope']}:{matching_key['key']}")
                self.assertEqual(set(describe(profile_id)["covered_attributes"]), expected)

    def test_every_profile_declares_at_least_one_retention_requirement(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                self.assertTrue(describe(profile_id)["retention_requirements"])

    def test_strict_profile_declares_the_matched_ratio_requirement(self) -> None:
        requirements = {item["requirement_id"]: item for item in describe("strict-safety-net")["retention_requirements"]}
        self.assertEqual(requirements["model-annotated-operations"]["comparison"], "matched_ratio")
        self.assertIn("identity:resource:service.name", describe("strict-safety-net")["covered_attributes"])

    def test_documented_profiles_match_describe_output(self) -> None:
        document = (ROOT / "docs" / "PROFILES.md").read_text(encoding="utf-8")
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                self.assertIn(profile_id, document)
                self.assertIn(SEMCONV, document)
                metadata = describe(profile_id)
                self.assertIn(metadata["title"], document)
                for attribute in metadata["covered_attributes"]:
                    self.assertIn(attribute, document)
                for requirement in metadata["retention_requirements"]:
                    self.assertIn(requirement["requirement_id"], document)


class ProfileWriteTests(unittest.TestCase):
    def test_write_profile_creates_a_parsable_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = write_profile("gen-ai-baseline", Path(directory))
            self.assertEqual(target.name, "contract.json")
            self.assertTrue(target.is_file())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data, profile("gen-ai-baseline"))
            self.assertEqual(parse_contract(data).contract_version, "tracecanary/v2")

    def test_write_profile_refuses_a_non_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(InputError) as raised:
                write_profile("gen-ai-baseline", root)
            self.assertIn("empty", str(raised.exception))
            self.assertEqual(json.loads((root / "existing.json").read_text(encoding="utf-8")), {})

    def test_write_profile_never_overwrites_an_existing_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "contract.json"
            existing.write_text("unchanged", encoding="utf-8")
            with self.assertRaises(InputError):
                write_profile("gen-ai-baseline", root)
            self.assertEqual(existing.read_text(encoding="utf-8"), "unchanged")

    def test_write_profile_refuses_a_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InputError) as raised:
                write_profile("gen-ai-baseline", Path(directory) / "missing")
            self.assertIn("does not exist", str(raised.exception))


class ProfileCliTests(unittest.TestCase):
    def test_profile_list_is_deterministic_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _run(["profile", "list"])
            second = _run(["profile", "list"])
            self.assertEqual(first, second)
            self.assertEqual(first[0], EXIT_PASS)
            self.assertEqual(list(root.iterdir()), [])
            for profile_id in PROFILE_IDS:
                self.assertIn(profile_id, first[1])

    def test_profile_list_json_is_canonical(self) -> None:
        status, output, error = _run(["profile", "list", "--format", "json"])
        self.assertEqual(status, EXIT_PASS)
        data = json.loads(output)
        self.assertEqual([item["profile_id"] for item in data["profiles"]], list(PROFILE_IDS))
        self.assertEqual(output, json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")

    def test_profile_show_is_deterministic_and_leaks_no_canary(self) -> None:
        for profile_id in PROFILE_IDS:
            with self.subTest(profile_id=profile_id):
                contract = profile(profile_id)
                status, output, error = _run(["profile", "show", "--profile", profile_id])
                self.assertEqual(status, EXIT_PASS)
                self.assertEqual(output, _run(["profile", "show", "--profile", profile_id])[1])
                for canary in contract["canaries"]:
                    self.assertNotIn(canary["value"], output + error)

    def test_profile_show_json_round_trips_describe(self) -> None:
        status, output, error = _run(["profile", "show", "--profile", "gen-ai-baseline", "--format", "json"])
        self.assertEqual(status, EXIT_PASS)
        self.assertEqual(json.loads(output), describe("gen-ai-baseline"))

    def test_unknown_profile_id_exits_two_with_valid_ids(self) -> None:
        for command in (["profile", "show", "--profile", "nope"], ["profile", "create", "--profile", "nope", "--output", "."]):
            with self.subTest(command=command):
                status, output, error = _run(command)
                self.assertEqual(status, EXIT_UNRESOLVED)
                self.assertEqual(output, "")
                for profile_id in PROFILE_IDS:
                    self.assertIn(profile_id, error)

    def test_profile_create_writes_contract_json_into_an_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, output, error = _run(["profile", "create", "--profile", "http-service-baseline", "--output", str(root)])
            self.assertEqual(status, EXIT_PASS)
            self.assertEqual([item.name for item in root.iterdir()], ["contract.json"])
            self.assertEqual(parse_contract(json.loads((root / "contract.json").read_text(encoding="utf-8"))).contract_version, "tracecanary/v2")
            self.assertNotIn(str(root), output)

    def test_profile_create_refuses_a_non_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("keep", encoding="utf-8")
            status, output, error = _run(["profile", "create", "--profile", "gen-ai-baseline", "--output", str(root)])
            self.assertEqual(status, EXIT_UNRESOLVED)
            self.assertEqual([item.name for item in root.iterdir()], ["notes.txt"])
            self.assertIn("empty", error)

    def test_profile_create_refuses_a_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, output, error = _run(["profile", "create", "--profile", "gen-ai-baseline", "--output", str(Path(directory) / "missing")])
            self.assertEqual(status, EXIT_UNRESOLVED)
            self.assertEqual(output, "")
            self.assertIn("UNRESOLVED", error)

    def test_profile_rejects_unknown_flags(self) -> None:
        status, output, error = _run(["profile", "list", "--bogus"])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertIn("unrecognized arguments", error)


if __name__ == "__main__":
    unittest.main()
