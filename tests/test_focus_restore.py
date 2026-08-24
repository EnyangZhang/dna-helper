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
        self.original_fishing_ready_hwnd = focus_restore._hybrid_fishing_ready_hwnd
        focus_restore._fallback_hwnd = 0
        focus_restore._fallback_cursor_position = None
        focus_restore._restore_in_progress = False
        focus_restore._hybrid_skill_ready_hwnd = 0
        focus_restore._hybrid_fishing_ready_hwnd = 0

    def tearDown(self) -> None:
        focus_restore._fallback_hwnd = self.original_hwnd
        focus_restore._fallback_cursor_position = self.original_cursor
        focus_restore._restore_in_progress = self.original_restore_state
        focus_restore._hybrid_skill_ready_hwnd = self.original_hybrid_ready_hwnd
        focus_restore._hybrid_fishing_ready_hwnd = self.original_fishing_ready_hwnd

    def test_confirmed_combat_hud_marks_dungeon_entered(self) -> None:
        with patch.object(
            focus_restore.progress_state, "mark_dungeon_entered", return_value=True
        ) as mark_entered:
            result = focus_restore.ProgressDungeonEntered().run(Mock(), Mock())

        self.assertTrue(result.success)
        mark_entered.assert_called_once_with()

    def test_native_click_finalizer_restores_without_sending_mouse_input(self) -> None:
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})),
            run_action=Mock(),
        )
        argv = SimpleNamespace(
            custom_action_param={
                "restore_delay_ms": 100,
                "progress_event": "continue_challenge",
            }
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(focus_restore, "_foreground_window", return_value=202),
            patch.object(focus_restore.time, "sleep") as sleep,
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
            patch.object(focus_restore, "_apply_progress_event") as progress,
        ):
            result = focus_restore.FocusGuardFinalize().run(context, argv)

        self.assertTrue(result.success)
        context.run_action.assert_not_called()
        sleep.assert_called_once_with(0.1)
        restore.assert_called_once_with(101, (300, 400))
        progress.assert_called_once_with(argv.custom_action_param)

    def test_focus_guard_action_rejects_agent_mouse_input(self) -> None:
        result = focus_restore.FocusGuardAction().run(
            Mock(),
            SimpleNamespace(
                custom_action_param={"kind": "click", "target": [900, 500]},
                task_detail=SimpleNamespace(task_id=1),
                node_name="legacy-click",
            ),
        )

        self.assertFalse(result.success)

    def test_remembers_window_and_multimonitor_cursor_position(self) -> None:
        with (
            patch.object(focus_restore, "_is_restore_target", return_value=True),
            patch.object(focus_restore, "_cursor_position", return_value=(-420, 815)),
        ):
            target = focus_restore._remember_restore_target(101, 202)

        self.assertEqual(target, (101, (-420, 815)))

    def test_task_start_clears_stale_target_when_game_is_already_focused(self) -> None:
        focus_restore._fallback_hwnd = 101
        focus_restore._fallback_cursor_position = (300, 400)

        target = focus_restore._initialize_restore_target(202, 202)

        self.assertEqual(target, 0)
        self.assertEqual(focus_restore._fallback_hwnd, 0)
        self.assertIsNone(focus_restore._fallback_cursor_position)

    def test_key_input_does_not_restore_stale_window_when_game_is_focused(self) -> None:
        focus_restore._fallback_hwnd = 101
        focus_restore._fallback_cursor_position = (300, 400)
        with patch.object(focus_restore._user32, "IsWindow", return_value=True), patch.object(
            focus_restore._user32, "IsWindowVisible", return_value=True
        ):
            target = focus_restore._remember_restore_target(
                202, 202, keep_game_focused=True
            )

        self.assertEqual(target, (0, None))
        self.assertEqual(focus_restore._fallback_hwnd, 101)

    def test_native_click_finalize_can_still_use_saved_non_game_target(self) -> None:
        focus_restore._fallback_hwnd = 101
        focus_restore._fallback_cursor_position = (300, 400)
        with patch.object(focus_restore._user32, "IsWindow", return_value=True), patch.object(
            focus_restore._user32, "IsWindowVisible", return_value=True
        ):
            target = focus_restore._remember_restore_target(202, 202)

        self.assertEqual(target, (101, (300, 400)))

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

    def test_hybrid_skill_keeps_first_dungeon_foreground_then_uses_background(self) -> None:
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
            boundary = focus_restore.HybridSkillDungeonComplete().run(context, argv)
            third = focus_restore.HybridSkillAction().run(context, argv)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertTrue(boundary.success)
        self.assertTrue(third.success)
        self.assertEqual(context.run_action.call_count, 2)
        context.run_action.assert_called_with("FocusGuardQKeyProxy")
        self.assertEqual(restore.call_count, 2)
        restore.assert_called_with(101, (300, 400))
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

    def test_fishing_hybrid_uses_first_foreground_then_background(self) -> None:
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})),
            run_action=Mock(return_value=SimpleNamespace(success=True)),
        )
        argv = SimpleNamespace(
            custom_action_param={"kind": "key", "key": 32, "repeat": 1},
            task_detail=SimpleNamespace(task_id=1),
            node_name="FishingPromptDetected",
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
            first = focus_restore.HybridFishingAction().run(context, argv)
            e_argv = SimpleNamespace(
                custom_action_param={
                    "kind": "key",
                    "key": 69,
                    "repeat": 1,
                    "proxy_node": "FishingEKeyProxy",
                    "track_e_sequence": False,
                },
                task_detail=SimpleNamespace(task_id=1),
                node_name="FishingEPromptDetected",
            )
            second = focus_restore.HybridFishingAction().run(context, e_argv)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(
            context.run_action.call_args_list,
            [
                unittest.mock.call("FishingSpaceKeyProxy"),
            ],
        )
        restore.assert_called_once_with(101, (300, 400))
        send.assert_called_once_with(202, 69)

    def test_fishing_space_log_does_not_increment_or_show_progress(self) -> None:
        with (
            patch.object(
                focus_restore.progress_state,
                "snapshot",
                return_value={
                    "stage_count": 2,
                    "total_rounds": 100,
                    "status": "running",
                },
            ),
            patch("builtins.print") as log,
        ):
            focus_restore._log_fishing_action(
                {"fishing_log_key": "Space"}, background=True
            )

        log.assert_called_once_with(
            "[挂机钓鱼] Space 已发送（后台）",
            flush=True,
        )

    def test_fishing_completion_log_includes_final_progress(self) -> None:
        with (
            patch.object(
                focus_restore.progress_state,
                "snapshot",
                return_value={
                    "stage_count": 100,
                    "total_rounds": 100,
                    "status": "completed",
                },
            ),
            patch("builtins.print") as log,
        ):
            focus_restore._log_fishing_action(
                {
                    "fishing_log_key": "Esc",
                    "progress_event": "fishing_caught",
                },
                background=False,
            )

        self.assertEqual(
            log.call_args_list,
            [
                unittest.mock.call(
                    "[挂机钓鱼] Esc 已发送（前台），钓鱼数量：100 / 100",
                    flush=True,
                ),
                unittest.mock.call(
                    "[挂机钓鱼] 已达到设定数量：100 / 100，任务完成",
                    flush=True,
                ),
            ],
        )

    def test_fishing_e_log_does_not_include_progress(self) -> None:
        with patch("builtins.print") as log:
            focus_restore._log_fishing_action(
                {"fishing_log_key": "E"}, background=True
            )

        log.assert_called_once_with("[挂机钓鱼] E 已发送（后台）", flush=True)

    def test_fishing_log_failure_does_not_fail_the_action_path(self) -> None:
        with patch("builtins.print", side_effect=OSError("closed")):
            focus_restore._log_fishing_action(
                {"fishing_log_key": "Esc"}, background=False
            )

    def test_key_hold_releases_s_after_one_second_and_restores_focus(self) -> None:
        key_down_job = Mock()
        key_down_job.wait.return_value = key_down_job
        key_down_job.succeeded = True
        key_up_job = Mock()
        key_up_job.wait.return_value = key_up_job
        key_up_job.succeeded = True
        controller = SimpleNamespace(
            info={"hwnd": 202},
            post_key_down=Mock(return_value=key_down_job),
            post_key_up=Mock(return_value=key_up_job),
        )
        context = SimpleNamespace(tasker=SimpleNamespace(controller=controller))
        argv = SimpleNamespace(
            custom_action_param={
                "kind": "key_hold",
                "key": 83,
                "hold_ms": 1000,
            },
            task_detail=SimpleNamespace(task_id=1),
            node_name="CoinAFKMoveBackward",
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(focus_restore.time, "sleep") as sleep,
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
        ):
            result = focus_restore.FocusGuardAction().run(context, argv)

        self.assertTrue(result.success)
        controller.post_key_down.assert_called_once_with(83)
        controller.post_key_up.assert_called_once_with(83)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 0.1])
        restore.assert_called_once_with(101, (300, 400))

    def test_coin_afk_key_sequence_preserves_order_and_restores_once(self) -> None:
        events = []
        key_job = Mock()
        key_job.wait.return_value = key_job
        key_job.succeeded = True

        def post_key_down(key: int):
            events.append(("down", key))
            return key_job

        def post_key_up(key: int):
            events.append(("up", key))
            return key_job

        def run_action(node_name: str):
            events.append(("action", node_name))
            return SimpleNamespace(success=True)

        controller = SimpleNamespace(
            info={"hwnd": 202},
            post_key_down=Mock(side_effect=post_key_down),
            post_key_up=Mock(side_effect=post_key_up),
        )
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=controller),
            run_action=Mock(side_effect=run_action),
        )
        argv = SimpleNamespace(
            custom_action_param={
                "kind": "key_sequence",
                "steps": [
                    {"delay_ms": 3000},
                    {"key": 69},
                    {"delay_ms": 300},
                    {"key": 69},
                    {"delay_ms": 300},
                    {"key": 83, "hold_ms": 600},
                    {"key": 81},
                    {"delay_ms": 3500},
                    {"key": 83, "hold_ms": 5000},
                    {"key": 68, "hold_ms": 100},
                ],
                "restore_delay_ms": 100,
            },
            task_detail=SimpleNamespace(task_id=1),
            node_name="CoinAFKMoveBackward",
        )
        with (
            patch.object(
                focus_restore,
                "_remember_restore_target",
                return_value=(101, (300, 400)),
            ),
            patch.object(
                focus_restore.time,
                "sleep",
                side_effect=lambda seconds: events.append(("sleep", seconds)),
            ),
            patch.object(
                focus_restore,
                "_restore_window_and_cursor",
                side_effect=lambda *_: events.append(("restore", None)),
            ),
        ):
            result = focus_restore.FocusGuardAction().run(context, argv)

        self.assertTrue(result.success)
        self.assertEqual(
            events,
            [
                ("sleep", 3.0),
                ("action", "FocusGuardEKeyProxy"),
                ("sleep", 0.3),
                ("action", "FocusGuardEKeyProxy"),
                ("sleep", 0.3),
                ("down", 83),
                ("sleep", 0.6),
                ("up", 83),
                ("action", "FocusGuardQKeyProxy"),
                ("sleep", 3.5),
                ("down", 83),
                ("sleep", 5.0),
                ("up", 83),
                ("down", 68),
                ("sleep", 0.1),
                ("up", 68),
                ("sleep", 0.1),
                ("restore", None),
            ],
        )

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
