import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.report import Violation, build_report, render_junit, render_sarif


class CiArtifactTests(unittest.TestCase):
    def test_pointer_diagnostics_uri_encoding_and_path_opt_in(self):
        report = build_report("tracecanary/v1", "regression", [Violation("TC001", "/resourceSpans/0", "synthetic canary survived export")], mode="batch")
        batch = {"status": "regression", "items": [{"id": "item-0001", "status": "regression", "report": report, "path": "nested/a #?.json"}]}
        result = json.loads(render_sarif(batch))["runs"][0]["results"][0]
        self.assertEqual(result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "nested/a%20%23%3F.json")
        self.assertEqual(result["properties"]["jsonPointer"], "/resourceSpans/0")
        root = ET.fromstring(render_junit(batch))
        self.assertEqual(root.find("testcase").get("file"), "nested/a #?.json")
        self.assertIn("TC001", root.find("testcase/failure").text)
        del batch["items"][0]["path"]
        self.assertNotIn("nested", render_sarif(batch) + render_junit(batch))

    def test_xml_controls_do_not_break_artifacts(self):
        report = build_report("tracecanary/v1", "unresolved", [Violation("TC006", "", "bad")], mode="batch")
        batch = {"items": [{"id": "item-0001", "path": "bad\x01name.json", "status": "unresolved", "report": report}]}
        root = ET.fromstring(render_junit(batch))
        self.assertEqual(root.get("errors"), "1")
        self.assertIn("TC006", root.find("testcase/error").text)
