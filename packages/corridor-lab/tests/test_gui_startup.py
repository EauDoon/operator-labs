import unittest
from io import StringIO
from unittest.mock import patch

from corridor_lab import gui


class StartupGuiTests(unittest.TestCase):
    def test_missing_tk_with_absent_stream_uses_generic_fallback(self):
        with patch.object(gui, "_load_tk_modules", side_effect=ImportError), patch.object(
            gui, "_show_windows_message"
        ) as fallback, patch.object(gui.sys, "stderr", None):
            self.assertEqual(gui.launch_gui(), 2)
        fallback.assert_called_once_with(gui.STARTUP_FAILURE_MESSAGE)

    def test_tcl_error_with_absent_stream_uses_generic_fallback(self):
        class FakeTclError(Exception):
            pass

        class FakeTk:
            TclError = FakeTclError

            @staticmethod
            def Tk():
                raise FakeTclError()

        with patch.object(gui, "_load_tk_modules", return_value=(FakeTk, None, None, None, None)), patch.object(
            gui, "_show_windows_message"
        ) as fallback, patch.object(gui.sys, "stderr", None):
            self.assertEqual(gui.launch_gui(), 2)
        fallback.assert_called_once_with(gui.STARTUP_FAILURE_MESSAGE)

    def test_startup_console_message_is_generic(self):
        stderr = StringIO()
        with patch.object(gui, "_load_tk_modules", side_effect=ImportError), patch.object(
            gui, "_show_windows_message"
        ) as fallback, patch.object(gui.sys, "stderr", stderr):
            self.assertEqual(gui.launch_gui(), 2)
        self.assertEqual(stderr.getvalue(), f"error: {gui.STARTUP_FAILURE_MESSAGE}\n")
        fallback.assert_not_called()

    def test_smoke_test_tolerates_pythonw_style_stdout_none(self):
        with patch.object(gui.sys, "stdout", None):
            self.assertEqual(gui.run_smoke_test(), 0)
