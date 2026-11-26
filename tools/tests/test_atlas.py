"""Keep source links and the hand-curated import map tied to the shipped modules."""

import ast
from html.parser import HTMLParser
from pathlib import Path
import unittest


ATLAS = Path(__file__).resolve().parents[2] / "docs" / "atlas"


class ModuleDirectory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.module = None
        self.sources = {}
        self.edges = []
        self.files = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "data-point" in attrs:
            self.module = attrs["id"]
        if tag not in {"a", "script", "link"}:
            return
        path = attrs.get("href") or attrs.get("src")
        if not path:
            return
        if path.startswith("#"):
            if self.module:
                self.edges.append((self.module, path[1:]))
        else:
            target = ATLAS / path
            self.files.append(target)
            if attrs.get("class") == "source":
                self.sources[self.module] = target

    def handle_endtag(self, tag):
        if tag == "li":
            self.module = None


class AtlasTest(unittest.TestCase):
    def test_local_files_and_selected_imports(self):
        directory = ModuleDirectory()
        directory.feed((ATLAS / "index.html").read_text(encoding="utf-8"))
        self.assertGreater(len(directory.sources), 0)
        self.assertGreater(len(directory.edges), 0)
        for target in directory.files:
            with self.subTest(file=target):
                self.assertTrue(target.is_file())
        for origin, destination in directory.edges:
            with self.subTest(origin=origin, destination=destination):
                source = directory.sources[origin]
                target = directory.sources[destination]
                self.assertEqual(source.parent, target.parent)
                tree = ast.parse(source.read_text(encoding="utf-8"))
                imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
                self.assertTrue(target.stem in imports or f"{target.parent.name}.{target.stem}" in imports)
