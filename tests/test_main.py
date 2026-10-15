import argparse
import unittest
from unittest.mock import patch

from main import bounded_number, main


class TestCommandLine(unittest.TestCase):
    def test_invalid_numeric_arguments_are_rejected(self):
        for field, value in (
            ("sensitivity", "nan"),
            ("sensitivity", "inf"),
            ("smoothing_factor", ".99"),
            ("camera_index", "-1"),
            ("camera_index", "0.5"),
        ):
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(argparse.ArgumentTypeError),
            ):
                bounded_number(field, field == "camera_index")(value)

    def test_help_does_not_start_gui(self):
        with (
            patch("sys.argv", ["main.py", "--help"]),
            patch("builtins.print"),
            self.assertRaises(SystemExit) as result,
        ):
            main()
        self.assertEqual(result.exception.code, 0)
