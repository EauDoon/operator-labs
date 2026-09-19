import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from corridor_lab.canonical import InputError
from corridor_lab.cli import main as cli_main
from corridor_lab.projects import PROJECT_MANIFEST_NAME
from corridor_lab.scenario import parse_scenario
from corridor_lab.variants import (
    apply_variant,
    apply_variant_chain,
    chain_changes,
    parse_derived_variant,
    parse_variant_changes_argument,
    validate_variant_graph,
    variant_changes,
    variant_comparison,
    variant_diff_report,
)
from helpers import route, scenario


class VariantLibraryTests(unittest.TestCase):
    def setUp(self):
        self.base = scenario(routes=[route("fictional-route-one"), route("fictional-route-two")])

    def test_variant_applies_only_declared_changes(self):
        variant = parse_derived_variant("tight", {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}})
        parsed = parse_scenario(apply_variant(variant, self.base))
        self.assertEqual(parsed.transaction.deadline_hours, __import__("decimal").Decimal("1"))
        self.assertEqual(parsed.transaction.send_amount, __import__("decimal").Decimal("100.00"))
        self.assertEqual(parsed.routes[0].fixed_fee_send, __import__("decimal").Decimal("1.00"))
        self.assertEqual(parsed.routes[1].route_id, "fictional-route-two")

    def test_route_changes_preserve_unchanged_fields(self):
        variant = parse_derived_variant("fee", {"base": "scenario", "changes": {
            "transaction": {},
            "routes": {"fictional-route-one": {"fixed_fee_send": "2.50", "liquidity.holding_days": "2"}}}})
        parsed = parse_scenario(apply_variant(variant, self.base))
        changed = next(item for item in parsed.routes if item.route_id == "fictional-route-one")
        untouched = next(item for item in parsed.routes if item.route_id == "fictional-route-two")
        self.assertEqual(changed.fixed_fee_send, __import__("decimal").Decimal("2.50"))
        self.assertEqual(changed.liquidity.holding_days, __import__("decimal").Decimal("2"))
        self.assertEqual(changed.fx_rate, untouched.fx_rate)
        self.assertEqual(untouched.fixed_fee_send, __import__("decimal").Decimal("1.00"))

    def test_unknown_fields_and_routes_fail_closed(self):
        with self.assertRaisesRegex(InputError, "must be one of"):
            parse_derived_variant("bad", {"base": "scenario", "changes": {"transaction": {"send_currency": "XYZ"}}})
        with self.assertRaisesRegex(InputError, "has no route"):
            variant = parse_derived_variant("bad", {"base": "scenario", "changes": {"routes": {"missing-route": {"fixed_fee_send": "2"}}}})
            apply_variant(variant, self.base)
        with self.assertRaisesRegex(InputError, "between 1 and"):
            parse_derived_variant("empty", {"base": "scenario", "changes": {"transaction": {}, "routes": {}}})

    def test_materializing_a_variant_never_mutates_the_declared_base(self):
        import copy as copy_module

        snapshot = copy_module.deepcopy(self.base)
        variant = parse_derived_variant("fee", {"base": "scenario", "changes": {
            "transaction": {},
            "routes": {"fictional-route-one": {"fixed_fee_send": "9.00", "liquidity.holding_days": "4"}}}})
        apply_variant(variant, self.base)
        self.assertEqual(self.base, snapshot)
        apply_variant(variant, self.base)
        self.assertEqual(self.base, snapshot)

    def test_assumption_diff_lists_exactly_the_changes(self):
        variant = parse_derived_variant("tight", {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}})
        rows = variant_changes(variant, self.base)
        self.assertEqual(rows, [{"section": "transaction", "field": "deadline_hours", "base": "3", "variant": "1"}])
        diff = variant_diff_report({"tight": variant}, "tight", self.base, "fictional-test-scenario")
        self.assertEqual(diff["report_version"], "corridor-lab.analysis/v1")
        self.assertEqual(diff["analysis"], "variant-assumption-diff")

    def test_argument_parser_builds_the_same_variant(self):
        transaction, routes = parse_variant_changes_argument("transaction.deadline_hours=2;route.fictional-route-one.fixed_fee_send=2.00")
        variant = parse_derived_variant("mixed", {"base": "scenario", "changes": {"transaction": transaction, "routes": routes}})
        self.assertEqual(variant.transaction, {"deadline_hours": "2"})
        self.assertEqual(variant.routes, {"fictional-route-one": {"fixed_fee_send": "2.00"}})
        with self.assertRaisesRegex(InputError, "must start with"):
            parse_variant_changes_argument("fee=2")

    def test_comparison_covers_routes_and_metrics_with_explicit_units(self):
        variant = parse_derived_variant("tight", {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}})
        report = variant_comparison(self.base, {"tight": variant}, "fictional-project")
        variants = {row["variant"] for row in report["rows"]}
        self.assertEqual(variants, {"scenario", "tight"})
        metrics = {row["metric"] for row in report["rows"]}
        self.assertEqual(metrics, {"expected_recipient_amount", "expected_sender_cost", "probability_by_deadline", "tail_completion_time_hours"})
        units = {row["unit"] for row in report["rows"]}
        self.assertEqual(units, {"amount RCV", "cost SND", "probability", "hours"})
        self.assertIn("not a statistically representative distribution", report["scope"])

    def test_comparison_surfaces_guardrail_satisfaction_when_declared(self):
        objective = {"metric": "maximize_expected_recipient_amount", "guardrails": {"minimum_probability_by_deadline": "0.80", "maximum_tail_hours": "24"}}
        base = scenario(routes=[route("fictional-route-one")], objective=objective)
        variant = parse_derived_variant("impossible", {"base": "scenario", "changes": {"transaction": {"deadline_hours": "0.01"}}})
        report = variant_comparison(base, {"impossible": variant}, "fictional-project")
        pass_rows = [row for row in report["rows"] if row["metric"] == "objective_guardrail_pass"]
        self.assertEqual({row["value"] for row in pass_rows}, {"true", "false"})


class VariantCliTests(unittest.TestCase):
    def test_add_show_compare_and_run_variants(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            project_root = root / "project"
            project_root.mkdir()
            inputs = project_root / "inputs"
            inputs.mkdir()
            (inputs / "scenario.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            self.assertEqual(cli_main(["project", "create", "--directory", str(project_root), "--project-id", "fictional-variants",
                                       "--scenario", str(inputs / "scenario.json"),
                                       "--experiment", "deadline-sweep:transaction-sweep:parameter=deadline_hours;values=1,2,8"]), 0)
            self.assertEqual(cli_main(["project", "add-variant", str(project_root), "--variant", "tight",
                                       "--changes", "transaction.deadline_hours=1;route.fictional-embedded.fixed_fee_send=2.00"]), 0)
            manifest = json.loads((project_root / PROJECT_MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["variants"]["tight"]["changes"]["transaction"], {"deadline_hours": "1"})
            self.assertEqual(cli_main(["project", "add-variant", str(project_root), "--variant", "tight",
                                       "--changes", "transaction.deadline_hours=2"]), 2)
            # show-variant prints the assumption diff
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli_main(["project", "show-variant", str(project_root), "--variant", "tight"]), 0)
            self.assertIn("variant-assumption-diff", out.getvalue())
            self.assertIn("fictional-embedded", out.getvalue())
            # compare-variants with protection
            comparison = root / "comparison.csv"
            self.assertEqual(cli_main(["project", "compare-variants", str(project_root), "--format", "csv", "--output", str(comparison)]), 0)
            self.assertIn("variant,", comparison.read_text(encoding="utf-8"))
            self.assertEqual(cli_main(["project", "compare-variants", str(project_root), "--output", str(inputs / "scenario.json")]), 2)
            # run-variants across the saved experiment
            runs = root / "runs.json"
            self.assertEqual(cli_main(["project", "run-variants", str(project_root), "--experiment", "deadline-sweep", "--output", str(runs)]), 0)
            combined = json.loads(runs.read_text(encoding="utf-8"))
            self.assertEqual([item["variant"] for item in combined["items"]], ["tight"])
            self.assertEqual(combined["items"][0]["report"]["report_version"], "corridor-lab.transaction-sweep/v1")
            self.assertEqual(combined["items"][0]["report"]["parameter"], "deadline_hours")
            self.assertEqual(combined["items"][0]["report"]["rows"][0]["value"], "1")

    def test_run_variants_rejects_unknown_names_and_keeps_protection(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            project_root = root / "project"
            project_root.mkdir()
            (project_root / "inputs").mkdir()
            (project_root / "inputs" / "scenario.json").write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            self.assertEqual(cli_main(["project", "create", "--directory", str(project_root), "--project-id", "fictional",
                                       "--scenario", str(project_root / "inputs" / "scenario.json")]), 0)
            self.assertEqual(cli_main(["project", "run-variants", str(project_root), "--experiment", "nope"]), 2)
            self.assertEqual(cli_main(["project", "compare-variants", str(project_root), "--variant", "ghost"]), 2)


if __name__ == "__main__":
    unittest.main()


class ChainedVariantTests(unittest.TestCase):
    def setUp(self):
        self.base = scenario(routes=[route("fictional-route-one")])

    def _variants(self):
        tight = parse_derived_variant("tight", {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}})
        fee = parse_derived_variant("tight-plus-fee", {"base": "tight", "changes": {"routes": {"fictional-route-one": {"fixed_fee_send": "5.00"}}}})
        return {"tight": tight, "tight-plus-fee": fee}

    def test_chain_materializes_in_dependency_order(self):
        variants = self._variants()
        parsed = parse_scenario(apply_variant_chain(variants, "tight-plus-fee", self.base))
        self.assertEqual(parsed.transaction.deadline_hours, __import__("decimal").Decimal("1"))
        self.assertEqual(parsed.routes[0].fixed_fee_send, __import__("decimal").Decimal("5.00"))
        # the intermediate state is preserved: tight alone changes only the deadline
        tight = parse_scenario(apply_variant_chain(variants, "tight", self.base))
        self.assertEqual(tight.routes[0].fixed_fee_send, __import__("decimal").Decimal("1.00"))

    def test_chain_diff_is_cumulative_with_declared_base_values(self):
        rows = chain_changes(self._variants(), "tight-plus-fee", self.base)
        by_field = {row["field"]: row for row in rows}
        self.assertEqual(by_field["deadline_hours"]["base"], "3")
        self.assertEqual(by_field["deadline_hours"]["variant"], "1")
        self.assertEqual(by_field["fixed_fee_send"]["base"], "1")
        self.assertEqual(by_field["fixed_fee_send"]["variant"], "5.00")
        diff = variant_diff_report(self._variants(), "tight-plus-fee", self.base, "fictional-test-scenario")
        self.assertEqual(diff["rows"], rows)

    def test_cycles_missing_bases_and_self_reference_fail_closed(self):
        cyclic = self._variants()
        cyclic["tight"] = parse_derived_variant("tight", {"base": "tight-plus-fee", "changes": {"transaction": {"deadline_hours": "1"}}})
        with self.assertRaisesRegex(InputError, "cycle"):
            validate_variant_graph(cyclic)
        missing = {"orphan": parse_derived_variant("orphan", {"base": "ghost", "changes": {"transaction": {"deadline_hours": "1"}}})}
        with self.assertRaisesRegex(InputError, "unknown variant"):
            validate_variant_graph(missing)
        self_derived = {"loop": parse_derived_variant("loop", {"base": "loop", "changes": {"transaction": {"deadline_hours": "1"}}})}
        with self.assertRaisesRegex(InputError, "cannot derive from itself"):
            validate_variant_graph(self_derived)

    def test_manifest_parses_chained_variants_and_rejects_cycles(self):
        from corridor_lab.projects import parse_manifest

        manifest = {
            "project_version": "corridor-lab.project/v1",
            "project_id": "fictional-chained",
            "scenario": {"path": "inputs/scenario.json", "sha256": "a" * 64, "folder": False},
            "experiments": [],
            "variants": {
                "tight": {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}},
                "tight-plus-fee": {"base": "tight", "changes": {"routes": {"fictional-route-one": {"fixed_fee_send": "5.00"}}}},
            },
        }
        parsed = parse_manifest(manifest)
        self.assertEqual(parsed.derived_variants["tight-plus-fee"].base, "tight")
        cyclic = json.loads(json.dumps(manifest))
        cyclic["variants"]["tight"]["base"] = "tight-plus-fee"
        with self.assertRaisesRegex(InputError, "cycle"):
            parse_manifest(cyclic)

    def test_cli_supports_chained_bases_and_cumulative_diffs(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            project_root = root / "project"
            project_root.mkdir()
            inputs = project_root / "inputs"
            inputs.mkdir()
            (inputs / "scenario.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            self.assertEqual(cli_main(["project", "create", "--directory", str(project_root), "--project-id", "fictional-chained",
                                       "--scenario", str(inputs / "scenario.json")]), 0)
            self.assertEqual(cli_main(["project", "add-variant", str(project_root), "--variant", "tight",
                                       "--changes", "transaction.deadline_hours=1"]), 0)
            self.assertEqual(cli_main(["project", "add-variant", str(project_root), "--variant", "tight-plus-fee",
                                       "--base", "tight", "--changes", "route.fictional-embedded.fixed_fee_send=5.00"]), 0)
            manifest = json.loads((project_root / PROJECT_MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["variants"]["tight-plus-fee"]["base"], "tight")
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli_main(["project", "show-variant", str(project_root), "--variant", "tight-plus-fee"]), 0)
            self.assertIn("5.00", out.getvalue())
            self.assertIn("| 1 |", out.getvalue())
            # chained materialization flows through run-variants
            runs = root / "runs.json"
            self.assertEqual(cli_main(["project", "run-variants", str(project_root), "--experiment", "none"],) == 2, True)
            self.assertEqual(cli_main(["project", "compare-variants", str(project_root), "--format", "csv", "--output", str(root / "cmp.csv")]), 0)
            comparison = (root / "cmp.csv").read_text(encoding="utf-8")
            self.assertIn("tight-plus-fee", comparison)
