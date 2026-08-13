from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import focus_restore  # noqa: E402


class FocusRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_hwnd = focus_restore._fallback_hwnd
        self.original_cursor = focus_restore._fallback_cursor_position
        self.original_restore_state = focus_restore._restore_in_progress
        focus_restore._fallback_hwnd = 0
        focus_restore._fallback_cursor_position = None
        focus_restore._restore_in_progress = False

    def tearDown(self) -> None:
        focus_restore._fallback_hwnd = self.original_hwnd
        focus_restore._fallback_cursor_position = self.original_cursor
        focus_restore._restore_in_progress = self.original_restore_state

    def test_remembers_window_and_multimonitor_cursor_position(self) -> None:
        with (
            patch.object(focus_restore, "_is_restore_target", return_value=True),
            patch.object(focus_restore, "_cursor_position", return_value=(-420, 815)),
        ):
            target = focus_restore._remember_restore_target(101, 202)

        self.assertEqual(target, (101, (-420, 815)))

    def test_watcher_does_not_overwrite_snapshot_during_restore(self) -> None:
        focus_restore._fallback_hwnd = 101
        focus_restore._fallback_cursor_position = (300, 400)
        focus_restore._restore_in_progress = True

        with (
            patch.object(focus_restore, "_is_restore_target", return_value=True),
            patch.object(focus_restore, "_cursor_position", return_value=(900, 500)),
        ):
            target = focus_restore._remember_restore_target(303, 202)

        self.assertEqual(target, (101, (300, 400)))

    def test_restores_cursor_after_clip_release_and_window_restore(self) -> None:
        calls: list[object] = []

        with (
            patch.object(
                focus_restore,
                "_release_cursor_clip",
                side_effect=lambda: calls.append("release"),
            ),
            patch.object(
                focus_restore,
                "_restore_window",
                side_effect=lambda hwnd: calls.append(("window", hwnd)) or True,
            ),
            patch.object(
                focus_restore,
                "_restore_cursor",
                side_effect=lambda position: calls.append(("cursor", position)) or True,
            ),
        ):
            restored = focus_restore._restore_window_and_cursor(101, (-20, 700))

        self.assertTrue(restored)
        self.assertEqual(
            calls,
            ["release", ("window", 101), ("cursor", (-20, 700))],
        )
        self.assertFalse(focus_restore._restore_in_progress)

    def test_does_not_move_cursor_when_window_restore_fails(self) -> None:
        with (
            patch.object(focus_restore, "_release_cursor_clip"),
            patch.object(focus_restore, "_restore_window", return_value=False),
            patch.object(focus_restore, "_restore_cursor") as restore_cursor,
        ):
            restored = focus_restore._restore_window_and_cursor(101, (300, 400))

        self.assertFalse(restored)
        restore_cursor.assert_not_called()
        self.assertFalse(focus_restore._restore_in_progress)


if __name__ == "__main__":
    unittest.main()
