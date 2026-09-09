import tempfile
import unittest
from pathlib import Path
from helpers import scenario
from corridor_lab.starter import write_starter
from corridor_lab.scenario import load_scenario
from corridor_lab.comparison import evaluate_scenario

class StarterTests(unittest.TestCase):
    def test_self_contained_reproducible_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a.json", Path(directory) / "b.json"
            write_starter(a)
            write_starter(b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(len(evaluate_scenario(load_scenario(a))["routes"]), 2)
            original = a.read_bytes()
            with self.assertRaises(FileExistsError):
                write_starter(a)
            self.assertEqual(a.read_bytes(), original)
