from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import parent_watchdog  # noqa: E402


class ParentWatchdogTest(unittest.TestCase):
    def test_parent_exit_runs_callback_and_closes_handle(self) -> None:
        callback_called = threading.Event()
        kernel32 = Mock()
        kernel32.OpenProcess.return_value = 123
        kernel32.WaitForSingleObject.return_value = parent_watchdog._WAIT_OBJECT_0

        with patch.object(parent_watchdog, "_kernel32", kernel32):
            thread = parent_watchdog.start_parent_watchdog(
                callback_called.set,
                parent_pid=456,
            )
            self.assertIsNotNone(thread)
            thread.join(timeout=1)

        self.assertTrue(callback_called.is_set())
        kernel32.OpenProcess.assert_called_once_with(
            parent_watchdog._SYNCHRONIZE,
            False,
            456,
        )
        kernel32.WaitForSingleObject.assert_called_once_with(
            123,
            parent_watchdog._INFINITE,
        )
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_open_failure_does_not_start_thread_or_callback(self) -> None:
        callback = Mock()
        kernel32 = Mock()
        kernel32.OpenProcess.return_value = 0

        with (
            patch.object(parent_watchdog, "_kernel32", kernel32),
            patch.object(parent_watchdog.ctypes, "get_last_error", return_value=5),
        ):
            thread = parent_watchdog.start_parent_watchdog(callback, parent_pid=456)

        self.assertIsNone(thread)
        callback.assert_not_called()
        kernel32.WaitForSingleObject.assert_not_called()
        kernel32.CloseHandle.assert_not_called()

    def test_invalid_parent_pid_is_rejected(self) -> None:
        callback = Mock()
        kernel32 = Mock()

        with patch.object(parent_watchdog, "_kernel32", kernel32):
            thread = parent_watchdog.start_parent_watchdog(callback, parent_pid=0)

        self.assertIsNone(thread)
        callback.assert_not_called()
        kernel32.OpenProcess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
