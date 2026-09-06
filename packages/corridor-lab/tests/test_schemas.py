"""Keep the published JSON schemas and the strict parser in agreement.

These checks use only the standard library so they run in the same environment
as the rest of the suite. They assert that the schema files describe exactly the
same field sets and contract versions that ``corridor_lab`` accepts, so a schema
edit or a parser edit cannot silently drift apart.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from corridor_lab.route import (  # noqa: E402
    ROUTE_CONTRACT_VERSION,
    ROUTE_CONTRACT_VERSION_V2,
    parse_route,
)
from corridor_lab.scenario import (  # noqa: E402
    SCENARIO_CONTRACT_VERSION,
    SCENARIO_CONTRACT_VERSION_V2,
    parse_scenario,
)

SCHEMAS = ROOT / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


class SchemaAgreementTests(unittest.TestCase):
    def test_route_v1_schema_matches_the_v1_parser(self):
        schema = _load("route.schema.json")
        self.assertEqual(schema["properties"]["contract_version"]["const"], ROUTE_CONTRACT_VERSION)
        self.assertEqual(set(schema["required"]), set(_parser_required_route(ROUTE_CONTRACT_VERSION)))
        self.assertEqual(set(schema["properties"]), set(_parser_known_route(ROUTE_CONTRACT_VERSION)))

    def test_route_v2_schema_matches_the_v2_parser(self):
        schema = _load("route.schema.v2.json")
        self.assertEqual(schema["properties"]["contract_version"]["const"], ROUTE_CONTRACT_VERSION_V2)
        known = set(_parser_known_route(ROUTE_CONTRACT_VERSION_V2))
        self.assertEqual(set(schema["properties"]), known)
        # The v2 parser requires these unconditionally.
        self.assertTrue(set(schema["required"]).issubset(known))
        for name in ("fx_rate", "fx_spread_bps", "liquidity", "outcomes"):
            self.assertIn(name, schema["required"])

    def test_scenario_v1_schema_matches_the_v1_parser(self):
        schema = _load("scenario.schema.json")
        self.assertEqual(schema["properties"]["contract_version"]["const"], SCENARIO_CONTRACT_VERSION)
        self.assertEqual(set(schema["properties"]), set(_parser_known_scenario(SCENARIO_CONTRACT_VERSION)))

    def test_scenario_v2_schema_matches_the_v2_parser(self):
        schema = _load("scenario.schema.v2.json")
        self.assertEqual(schema["properties"]["contract_version"]["const"], SCENARIO_CONTRACT_VERSION_V2)
        self.assertEqual(set(schema["properties"]), set(_parser_known_scenario(SCENARIO_CONTRACT_VERSION_V2)))
        self.assertIn("workload_scenarios", schema["properties"])

    def test_v2_scenario_schema_references_both_route_schemas(self):
        schema = _load("scenario.schema.v2.json")
        refs = sorted(item["$ref"] for item in schema["properties"]["routes"]["items"]["oneOf"])
        self.assertEqual(refs, ["route.schema.json", "route.schema.v2.json"])

    def test_every_documented_enum_matches_the_parser(self):
        route_schema = _load("route.schema.v2.json")
        self.assertEqual(
            route_schema["properties"]["fee_schedule"]["properties"]["basis"]["enum"],
            ["marginal", "whole_band"],
        )
        self.assertEqual(
            route_schema["properties"]["fee_schedule"]["properties"]["period_charges"]["items"][
                "properties"
            ]["amortization_over"]["enum"],
            ["declared_transactions", "scenario_volume"],
        )

    def test_bundled_examples_use_only_declared_scenario_fields(self):
        for path in sorted((ROOT / "examples").glob("*/scenario.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data["contract_version"]
            name = {
                SCENARIO_CONTRACT_VERSION: "scenario.schema.json",
                SCENARIO_CONTRACT_VERSION_V2: "scenario.schema.v2.json",
            }[version]
            allowed = set(_load(name)["properties"])
            self.assertLessEqual(set(data), allowed, f"{path.name} has undeclared fields")


def _parser_required_route(version: str) -> set[str]:
    """Probe the parser for its unconditional required fields."""
    base = {
        "contract_version": version,
        "route_id": "r",
        "label": "l",
        "fictional": True,
        "fx_rate": "1",
        "fx_spread_bps": "0",
        "liquidity": {
            "prefunding_amount_send": "0",
            "annual_cost_of_capital_bps": "0",
            "holding_days": "0",
        },
        "outcomes": [
            {
                "outcome_id": "o",
                "probability": "1",
                "completion": "success",
                "delay_hours": "0",
                "recovery_amount_send": "0",
                "recovery_delay_hours": "0",
            }
        ],
    }
    if version == ROUTE_CONTRACT_VERSION:
        base["fixed_fee_send"] = "0"
        base["percent_fee_bps"] = "0"
    parse_route(dict(base))
    required: set[str] = set()
    for field in list(base):
        candidate = {key: value for key, value in base.items() if key != field}
        try:
            parse_route(dict(candidate))
        except Exception:
            required.add(field)
    return required


def _parser_known_route(version: str) -> set[str]:
    return set(_ROUTE_FIELDS[version])


def _parser_known_scenario(version: str) -> set[str]:
    return set(_SCENARIO_FIELDS[version])


_ROUTE_FIELDS = {
    ROUTE_CONTRACT_VERSION: {
        "contract_version",
        "route_id",
        "label",
        "fictional",
        "fx_rate",
        "fixed_fee_send",
        "percent_fee_bps",
        "fx_spread_bps",
        "liquidity",
        "outcomes",
    },
    ROUTE_CONTRACT_VERSION_V2: {
        "contract_version",
        "route_id",
        "label",
        "fictional",
        "fx_rate",
        "fixed_fee_send",
        "percent_fee_bps",
        "fx_spread_bps",
        "fee_schedule",
        "liquidity",
        "outcomes",
    },
}

_SCENARIO_FIELDS = {
    SCENARIO_CONTRACT_VERSION: {
        "contract_version",
        "scenario_id",
        "description",
        "fictional",
        "transaction",
        "routes",
        "objective",
    },
    SCENARIO_CONTRACT_VERSION_V2: {
        "contract_version",
        "scenario_id",
        "description",
        "fictional",
        "transaction",
        "routes",
        "objective",
        "workload_scenarios",
    },
}


class ParserFieldProbeTests(unittest.TestCase):
    """The hand-maintained field tables above must match the parser exactly."""

    def test_route_field_tables_match_the_parser(self):
        for version, fields in _ROUTE_FIELDS.items():
            document = {
                "contract_version": version,
                "route_id": "r",
                "label": "l",
                "fictional": True,
                "fx_rate": "1",
                "fx_spread_bps": "0",
                "liquidity": {
                    "prefunding_amount_send": "0",
                    "annual_cost_of_capital_bps": "0",
                    "holding_days": "0",
                },
                "outcomes": [
                    {
                        "outcome_id": "o",
                        "probability": "1",
                        "completion": "success",
                        "delay_hours": "0",
                        "recovery_amount_send": "0",
                        "recovery_delay_hours": "0",
                    }
                ],
            }
            if version == ROUTE_CONTRACT_VERSION:
                document["fixed_fee_send"] = "0"
                document["percent_fee_bps"] = "0"
            else:
                document["fee_schedule"] = {
                    "basis": "whole_band",
                    "tiers": [
                        {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "0"}
                    ],
                }
            probe = dict(document)
            probe["unknown-field"] = 1
            with self.assertRaisesRegex(Exception, r"unsupported field\(s\): unknown-field"):
                parse_route(probe)
            optional: set[str] = set()
            if version == ROUTE_CONTRACT_VERSION_V2:
                optional = {"fixed_fee_send", "percent_fee_bps"}
            self.assertEqual(fields, set(document) | optional)

    def test_scenario_field_tables_match_the_parser(self):
        for version, fields in _SCENARIO_FIELDS.items():
            document = {
                "contract_version": version,
                "scenario_id": "s",
                "description": "d",
                "fictional": True,
                "transaction": {
                    "send_amount": "1",
                    "send_currency": "A",
                    "send_precision": 2,
                    "receive_currency": "B",
                    "receive_precision": 2,
                    "rounding": "ROUND_HALF_UP",
                    "deadline_hours": "1",
                    "volume_per_period": "1",
                },
            }
            parse_scenario(dict(document))
            probe = dict(document)
            probe["unknown-field"] = 1
            with self.assertRaisesRegex(Exception, r"unsupported field\(s\): unknown-field"):
                parse_scenario(probe)
            optional = {"routes", "objective"}
            if version == SCENARIO_CONTRACT_VERSION_V2:
                optional |= {"workload_scenarios"}
            self.assertEqual(fields, set(document) | optional)


if __name__ == "__main__":
    unittest.main()
