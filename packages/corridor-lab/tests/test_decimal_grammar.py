"""Decimal strings use a plain ASCII grammar and never guess at the intent."""
import contextlib
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from helpers import route, scenario
from corridor_lab.canonical import InputError, require_decimal
from corridor_lab.cli import main
from corridor_lab.scenario import parse_scenario


class DecimalGrammarTests(unittest.TestCase):
    def test_python_only_spellings_are_rejected(self):
        for text in ("1_000", " 5", "5 ", "\n7", "１２", "١٢", "1e1_0", ""):
            with self.subTest(text=text), self.assertRaises(InputError) as caught:
                require_decimal(text, "amount")
            self.assertIn("amount is not a valid decimal", str(caught.exception))

    def test_plain_decimal_spellings_still_parse(self):
        for text, expected in (("1000.00", "1000.00"), ("+5", "5"), ("5.", "5"), (".5", "0.5"),
                               ("1e3", "1000"), ("1E-12", "0.000000000001"), ("-0", "0")):
            with self.subTest(text=text):
                self.assertEqual(require_decimal(text, "amount"), Decimal(expected))
        self.assertEqual(require_decimal(7, "amount"), Decimal(7))
        self.assertEqual(require_decimal(Decimal("7.5"), "amount"), Decimal("7.5"))

    def test_non_finite_strings_keep_the_finite_diagnostic(self):
        for text in ("NaN", "Infinity", "-inf"):
            with self.subTest(text=text), self.assertRaises(InputError) as caught:
                require_decimal(text, "amount")
            self.assertIn("must be finite", str(caught.exception))

    def test_scenario_amount_with_digit_separator_is_not_read_as_a_larger_amount(self):
        document = scenario([route()])
        document["transaction"]["send_amount"] = "1_000"
        with self.assertRaises(InputError):
            parse_scenario(document)

    def test_cli_values_with_digit_separator_exit_2(self):
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(scenario([route()])), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(error):
                status = main(["sensitivity", str(path), "--parameter", "fx_rate", "--values", "1_0"])
        self.assertEqual(status, 2)
        self.assertIn("--values value is not a valid decimal", error.getvalue())


if __name__ == "__main__":
    unittest.main()
