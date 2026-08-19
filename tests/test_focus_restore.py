from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import focus_restore  # noqa: E402


class FocusRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_hwnd = focus_restore._fallback_hwnd
        self.original_cursor = focus_restore._fallback_cursor_position
        self.original_restore_state = focus_restore._restore_in_progress
        self.original_hybrid_ready_hwnd = focus_restore._hybrid_skill_ready_hwnd
        focus_restore._fallback_hwnd = 0
        focus_restore._fallback_cursor_position = None
        focus_restore._restore_in_progress = False
        focus_restore._hybrid_skill_ready_hwnd = 0

    def tearDown(self) -> None:
        focus_restore._fallback_hwnd = self.original_hwnd
        focus_restore._fallback_cursor_position = self.original_cursor
        focus_restore._restore_in_progress = self.original_restore_state
        focus_restore._hybrid_skill_ready_hwnd = self.original_hybrid_ready_hwnd

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

    def test_skill_activation_helper_only_activates_game(self) -> None:
        with (
            patch.object(focus_restore._user32, "IsWindow", return_value=True),
            patch.object(focus_restore, "_foreground_window", return_value=101),
            patch.object(focus_restore, "_restore_window", return_value=True) as activate,
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
            patch.object(focus_restore.time, "sleep") as sleep,
        ):
            activated = focus_restore._activate_game_for_skill(202)

        self.assertTrue(activated)
        activate.assert_called_once_with(202)
        sleep.assert_called_once_with(focus_restore._SKILL_FOREGROUND_SETTLE_SECONDS)
        restore.assert_not_called()

    def test_hybrid_skill_uses_foreground_with_restore_then_background(self) -> None:
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})),
            run_action=Mock(return_value=SimpleNamespace(success=True)),
        )
        argv = SimpleNamespace(
            custom_action_param={"kind": "key", "key": 81, "repeat": 1},
            task_detail=SimpleNamespace(task_id=1),
            node_name="LisePressQ",
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(focus_restore, "_activate_game_for_skill", return_value=True),
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
            patch.object(focus_restore, "_send_background_key", return_value=True) as send,
        ):
            first = focus_restore.HybridSkillAction().run(context, argv)
            second = focus_restore.HybridSkillAction().run(context, argv)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        context.run_action.assert_called_once_with("FocusGuardQKeyProxy")
        restore.assert_called_once_with(101, (300, 400))
        send.assert_called_once_with(202, 81)
        self.assertTrue(focus_restore._is_hybrid_skill_ready(202))

    def test_hybrid_background_failure_falls_back_to_foreground_with_restore(self) -> None:
        focus_restore._mark_hybrid_skill_ready(202)
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})),
            run_action=Mock(return_value=SimpleNamespace(success=True)),
        )
        argv = SimpleNamespace(
            custom_action_param={"kind": "key", "key": 81, "repeat": 1},
            task_detail=SimpleNamespace(task_id=1),
            node_name="LisePressQ",
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(focus_restore, "_activate_game_for_skill", return_value=True),
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
            patch.object(focus_restore, "_send_background_key", return_value=False),
        ):
            result = focus_restore.HybridSkillAction().run(context, argv)

        self.assertTrue(result.success)
        context.run_action.assert_called_once_with("FocusGuardQKeyProxy")
        restore.assert_called_once_with(101, (300, 400))
        self.assertTrue(focus_restore._is_hybrid_skill_ready(202))

    def test_normal_key_run_still_restores_focus(self) -> None:
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})),
            run_action=Mock(return_value=SimpleNamespace(success=True)),
        )
        argv = SimpleNamespace(
            custom_action_param={"kind": "key", "key": 81, "repeat": 1},
            task_detail=SimpleNamespace(task_id=1),
            node_name="LisePressQ",
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(focus_restore.time, "sleep"),
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
        ):
            result = focus_restore.FocusGuardAction().run(context, argv)

        self.assertTrue(result.success)
        context.run_action.assert_called_once_with("FocusGuardQKeyProxy")
        restore.assert_called_once_with(101, (300, 400))


if __name__ == "__main__":
    unittest.main()
