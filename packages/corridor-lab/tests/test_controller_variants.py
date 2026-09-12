import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from corridor_lab.cli import main as cli_main
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.projects import PROJECT_MANIFEST_NAME
from helpers import route, scenario


def make_variant_project(root: Path) -> Path:
    """Create a project with a derived variant; root IS the project directory."""
    project_root = root
    project_root.mkdir(parents=True, exist_ok=True)
    inputs = project_root / "inputs"
    inputs.mkdir()
    (inputs / "scenario.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
    with redirect_stdout(StringIO()):
        assert cli_main(["project", "create", "--directory", str(project_root), "--project-id", "fictional-variants",
                         "--scenario", str(inputs / "scenario.json"),
                         "--experiment", "deadline-sweep:transaction-sweep:parameter=deadline_hours;values=1,2,8"]) == 0
        assert cli_main(["project", "add-variant", str(project_root), "--variant", "tight",
                         "--changes", "transaction.deadline_hours=1"]) == 0
    return project_root / PROJECT_MANIFEST_NAME


class ControllerVariantTests(unittest.TestCase):
    def test_open_project_loads_variants_and_applies_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_variant_project(Path(temporary))
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            self.assertEqual(controller.variant_names(), ("tight",))
            applied = controller.apply_variant("tight")
            self.assertIsNone(applied.error)
            self.assertEqual(controller.transaction_fields()["deadline_hours"], "1")
            self.assertTrue(controller.scenario_unsaved)
            self.assertEqual(controller.active_variant, "tight")
            self.assertIsNone(controller.last_report)
            self.assertIsNone(controller.compare().error)

    def test_variant_diff_and_comparison_match_the_cli(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            project_root = Path(temporary) / "project"
            manifest_path = make_variant_project(project_root)
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            diff = controller.show_variant_diff("tight")
            self.assertIsNone(diff.error)
            comparison = controller.compare_variants()
            self.assertIsNone(comparison.error)
            cli_diff = Path(temporary) / "diff.json"
            cli_comparison = Path(temporary) / "comparison.json"
            self.assertEqual(cli_main(["project", "show-variant", str(project_root), "--variant", "tight", "--format", "json", "--output", str(cli_diff)]), 0)
            self.assertEqual(cli_main(["project", "compare-variants", str(project_root), "--format", "json", "--output", str(cli_comparison)]), 0)
            self.assertEqual(diff.report, json.loads(cli_diff.read_text(encoding="utf-8")))
            self.assertEqual(comparison.report, json.loads(cli_comparison.read_text(encoding="utf-8")))

    def test_staged_variant_persists_through_save_project(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            source_root = Path(temporary) / "source"
            manifest_path = make_variant_project(source_root)
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            self.assertIsNone(controller.add_variant("wide", {"transaction": {"volume_per_period": "500"}}).error)
            self.assertEqual(controller.variant_names(), ("tight", "wide"))
            destination = Path(temporary) / "saved"
            destination.mkdir()
            self.assertIsNone(controller.save_project(destination, "fictional-saved-variants").error)
            fresh = CorridorGuiController()
            self.assertIsNone(fresh.open_project(destination / PROJECT_MANIFEST_NAME).error)
            self.assertEqual(fresh.variant_names(), ("tight", "wide"))
            self.assertIsNone(fresh.apply_variant("wide").error)
            self.assertEqual(fresh.transaction_fields()["volume_per_period"], "500")

    def test_rejected_variant_change_leaves_state_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_variant_project(Path(temporary))
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            rejected = controller.add_variant("bad", {"transaction": {"deadline_hours": "-3"}})
            self.assertIsNotNone(rejected.error)
            self.assertEqual(controller.variant_names(), ("tight",))
            self.assertEqual(controller.transaction_fields()["deadline_hours"], "3")

    def test_compare_variants_explains_unknown_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_variant_project(Path(temporary))
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            result = controller.compare_variants(("ghost",))
            self.assertIsNotNone(result.error)
            self.assertIn("ghost", result.error)


if __name__ == "__main__":
    unittest.main()
