"""Tests for the template library, explicit revisions, and scenario differences."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from corridor_lab.canonical import InputError  # noqa: E402
from corridor_lab.diff import diff_scenarios, flatten_declared  # noqa: E402
from corridor_lab.report import render_report  # noqa: E402
from corridor_lab.revisions import (  # noqa: E402
    RevisionError,
    list_revisions,
    next_revision_number,
    revision_path,
    save_revision,
)
from corridor_lab.route import parse_route  # noqa: E402
from corridor_lab.scenario import parse_scenario  # noqa: E402
from corridor_lab.templates import (  # noqa: E402
    describe,
    describe_all,
    template,
    template_ids,
    write_template,
)


def _round_trip(document: dict) -> dict:
    """Round-trip a document through JSON text so it looks like a loaded file."""
    return json.loads(json.dumps(document))


class TemplateLibraryTests(unittest.TestCase):
    def test_every_scenario_template_is_valid(self):
        self.assertGreaterEqual(len(template_ids("scenario")), 6)
        for template_id in template_ids("scenario"):
            with self.subTest(template_id=template_id):
                parse_scenario(template(template_id))

    def test_every_route_template_is_valid(self):
        self.assertGreaterEqual(len(template_ids("route")), 4)
        for template_id in template_ids("route"):
            with self.subTest(template_id=template_id):
                parse_route(template(template_id))

    def test_templates_are_not_renames_of_one_example(self):
        fingerprints = {canonical_id: _round_trip(template(canonical_id)) for canonical_id in template_ids("scenario")}
        shapes = set()
        for document in fingerprints.values():
            shape = (
                document["transaction"]["send_amount"],
                document["transaction"]["deadline_hours"],
                document["transaction"]["volume_per_period"],
                tuple(
                    (
                        route["route_id"],
                        route["contract_version"],
                        "fee_schedule" in route,
                        "legs" in route,
                        route["liquidity"]["prefunding_amount_send"],
                    )
                    for route in document["routes"]
                ),
            )
            shapes.add(shape)
        self.assertEqual(len(shapes), len(fingerprints), "two scenario templates share an identical declared shape")

    def test_templates_cover_distinct_declared_cost_structures(self):
        structures = set()
        for template_id in template_ids("scenario"):
            for route in template(template_id)["routes"]:
                if "fee_schedule" in route:
                    structures.add(route["fee_schedule"]["basis"])
                elif "legs" in route:
                    structures.add("legs")
                else:
                    structures.add("flat")
        self.assertIn("marginal", structures)
        self.assertIn("whole_band", structures)
        self.assertIn("flat", structures)
        self.assertIn("legs", structures)

    def test_at_least_one_template_declares_each_new_capability(self):
        documents = [template(template_id) for template_id in template_ids("scenario")]
        self.assertTrue(any("workload_scenarios" in item for item in documents))
        self.assertTrue(any("funding" in item for item in documents))
        self.assertTrue(any(any("legs" in route for route in item["routes"]) for item in documents))

    def test_v1_and_v2_contracts_are_both_demonstrated(self):
        versions = {template(template_id)["contract_version"] for template_id in template_ids("scenario")}
        self.assertEqual(versions, {"corridor-lab.scenario/v1", "corridor-lab.scenario/v2"})

    def test_describe_matches_the_document(self):
        for template_id in template_ids():
            with self.subTest(template_id=template_id):
                metadata = describe(template_id)
                document = template(template_id)
                self.assertEqual(metadata["contract_version"], document["contract_version"])
                self.assertTrue(metadata["notes"].strip())
                self.assertTrue(metadata["title"].strip())
                if metadata["kind"] == "scenario":
                    self.assertEqual(metadata["routes"], [route["route_id"] for route in document["routes"]])

    def test_unknown_template_is_actionable(self):
        with self.assertRaisesRegex(InputError, "unknown template"):
            template("does-not-exist")

    def test_write_template_refuses_to_replace_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scenario.json"
            write_template("flat-fee-low-volume", target)
            self.assertTrue(target.is_file())
            with self.assertRaisesRegex(InputError, "already exists"):
                write_template("flat-fee-low-volume", target)

    def test_written_template_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            target = write_template("funding-shortfall", Path(directory) / "scenario.json")
            parse_scenario(json.loads(target.read_text(encoding="utf-8")))

    def test_describe_all_is_deterministic(self):
        self.assertEqual(describe_all(), describe_all())


class FlattenTests(unittest.TestCase):
    def test_array_entries_use_declared_identifiers(self):
        route = template("multi-leg-joint-outcomes")
        flat = flatten_declared(route)
        self.assertIn("routes.route_id=two-leg-chain.legs.leg_id=onshore.fx_rate", flat)
        self.assertIn("routes.route_id=two-leg-chain.outcomes.outcome_id=failed-on-leg-1.recovery_delay_hours", flat)

    def test_numeric_scalars_are_normalised(self):
        # 1, "1", and "1.0" are the same declared number.
        self.assertEqual(flatten_declared({"a": 1, "b": "1"}), flatten_declared({"a": "1.0", "b": 1}))
        self.assertNotEqual(flatten_declared({"a": 1}), flatten_declared({"a": 2}))

    def test_booleans_and_null_are_normalised(self):
        self.assertEqual(flatten_declared({"a": True}), flatten_declared({"a": "true"}))
        self.assertEqual(flatten_declared({"a": None}), flatten_declared({"a": "null"}))

    def test_scenario_id_and_description_are_not_declared_assumptions(self):
        flat = flatten_declared(template("flat-fee-low-volume"))
        self.assertNotIn("scenario_id", flat)
        self.assertNotIn("description", flat)


class ScenarioDiffTests(unittest.TestCase):
    def _base(self):
        return template("flat-fee-low-volume")

    def test_no_change_is_reported_honestly(self):
        report = diff_scenarios(self._base(), self._base())
        self.assertEqual(report["attribution"]["status"], "no_declared_change")
        self.assertEqual(report["assumption_changes"], [])
        self.assertEqual(report["output_changes"], [])

    def test_single_change_is_attributed(self):
        changed = self._base()
        changed["routes"][1]["fixed_fee_send"] = "4.00"
        report = diff_scenarios(self._base(), changed)
        self.assertEqual(report["attribution"]["status"], "single_declared_change")
        self.assertEqual(report["attribution"]["changed_assumption"], "routes.route_id=slow-cheap.fixed_fee_send")

    def test_hand_calculated_output_deltas(self):
        changed = self._base()
        changed["routes"][1]["fixed_fee_send"] = "4.00"
        report = diff_scenarios(self._base(), changed)
        rows = {(item["route_id"], item["metric"]): item for item in report["output_changes"]}
        # percentage fee is 500 * 5/10000 = 0.25, so the explicit fee moves by exactly 3.00
        self.assertEqual(rows[("slow-cheap", "explicit_fee_send")]["delta"], "3")
        # recipient = (500 - fee - 0.25) * 1.75 * (1 - 50/10000)
        self.assertEqual(rows[("slow-cheap", "recipient_amount")]["before"], "868.45")
        self.assertEqual(rows[("slow-cheap", "recipient_amount")]["after"], "863.22")
        self.assertEqual(rows[("slow-cheap", "recipient_amount")]["delta"], "-5.23")

    def test_multiple_changes_are_never_attributed(self):
        changed = self._base()
        changed["routes"][1]["fixed_fee_send"] = "4.00"
        changed["transaction"]["deadline_hours"] = "8"
        report = diff_scenarios(self._base(), changed)
        self.assertEqual(report["attribution"]["status"], "multiple_declared_changes")
        self.assertEqual(report["attribution"]["changed_assumption_count"], 2)
        self.assertIn("does not apportion", report["attribution"]["note"])

    def test_added_and_removed_assumptions_are_distinguished(self):
        changed = self._base()
        changed.pop("objective")
        report = diff_scenarios(self._base(), changed)
        kinds = {item["change"] for item in report["assumption_changes"]}
        self.assertIn("removed", kinds)

    def test_added_and_removed_routes_are_reported(self):
        changed = self._base()
        changed["routes"] = changed["routes"][:1]
        report = diff_scenarios(self._base(), changed)
        self.assertIn(
            ("slow-cheap", "route", "removed"),
            [(item["route_id"], item["metric"], item["change"]) for item in report["output_changes"]],
        )

    def test_reordered_routes_produce_no_assumption_change(self):
        changed = self._base()
        changed["routes"] = list(reversed(changed["routes"]))
        report = diff_scenarios(self._base(), changed)
        self.assertEqual(report["attribution"]["status"], "no_declared_change")

    def test_rendered_forms_are_deterministic_and_explain_themselves(self):
        changed = self._base()
        changed["routes"][1]["fixed_fee_send"] = "4.00"
        report = diff_scenarios(self._base(), changed)
        markdown = render_report(report, "markdown")
        self.assertIn("## Changed declared assumptions", markdown)
        self.assertIn("## Attribution", markdown)
        self.assertEqual(render_report(report, "json"), render_report(report, "json"))
        csv_text = render_report(report, "csv")
        self.assertIn("routes.route_id=slow-cheap.fixed_fee_send", csv_text)


class RevisionTests(unittest.TestCase):
    def _folder(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: _remove_tree(directory))
        return Path(directory)

    def test_revisions_are_numbered_and_sorted(self):
        folder = self._folder()
        first = save_revision(folder, template("flat-fee-low-volume"))
        second = save_revision(folder, template("flat-fee-low-volume"))
        self.assertEqual(first.name, "fictional-flat-fee-low-volume-r0001.json")
        self.assertEqual(second.name, "fictional-flat-fee-low-volume-r0002.json")
        self.assertEqual([item["name"] for item in list_revisions(folder)], [first.name, second.name])

    def test_revisions_are_only_written_when_the_document_is_valid(self):
        folder = self._folder()
        broken = template("flat-fee-low-volume")
        broken["routes"][0]["outcomes"][0]["probability"] = "0.5"
        with self.assertRaises(InputError):
            save_revision(folder, broken)
        self.assertEqual(list_revisions(folder), [])

    def test_revision_folder_must_exist(self):
        with self.assertRaises(RevisionError):
            save_revision(Path("/definitely/not/a/folder"), template("flat-fee-low-volume"))

    def test_next_revision_number_is_per_scenario(self):
        folder = self._folder()
        save_revision(folder, template("flat-fee-low-volume"))
        self.assertEqual(next_revision_number(folder, "fictional-flat-fee-low-volume"), 2)
        self.assertEqual(next_revision_number(folder, "other-scenario"), 1)
        self.assertEqual(
            revision_path(folder, "other-scenario", 1).name, "other-scenario-r0001.json"
        )

    def test_unrelated_json_files_are_ignored(self):
        folder = self._folder()
        (folder / "notes.json").write_text("{}", encoding="utf-8")
        save_revision(folder, template("flat-fee-low-volume"))
        self.assertEqual(len(list_revisions(folder)), 1)

    def test_a_saved_revision_round_trips_through_a_diff(self):
        folder = self._folder()
        before = save_revision(folder, template("flat-fee-low-volume"))
        changed = template("flat-fee-low-volume")
        changed["routes"][1]["fixed_fee_send"] = "4.00"
        after = save_revision(folder, changed)
        from corridor_lab.diff import diff_scenario_files

        report = diff_scenario_files(before, after)
        self.assertEqual(report["attribution"]["status"], "single_declared_change")


def _wrap(transaction: dict) -> dict:
    """Wrap a fragment in the smallest valid v1 scenario."""
    document = template("flat-fee-low-volume")
    document["transaction"].update(transaction)
    return document


def _remove_tree(directory: str) -> None:
    import shutil

    shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
