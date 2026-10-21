from __future__ import annotations

import json
import queue
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from test_theatre_afk import PIPELINE, TASK, TheatreGraphRunner, selected_pipeline

import focus_restore
import progress_state
import telegram_bot


MODE = "沉浸式戏剧挂机"


class ProgressGraphRunner(TheatreGraphRunner):
    """Execute real progress hooks on the offline graph, never game inputs."""

    def step(self, **observations):
        super().step(**observations)
        action = self.pipeline[self.current]["action"]
        param = action.get("param", {})
        if param.get("custom_action") == "progress_dungeon_entered":
            result = focus_restore.ProgressDungeonEntered().run(None, SimpleNamespace())
            if not result.success:
                raise AssertionError("HUD progress hook failed")
        elif param.get("custom_action") == "focus_guard_finalize":
            focus_restore._apply_progress_event(param.get("custom_action_param", {}))


class TheatreProgressTest(unittest.TestCase):
    def setUp(self):
        self.original_state = progress_state.snapshot()
        self.original_clock = progress_state._last_stage_increment_monotonic
        for item in (
            patch.object(progress_state, "_persist_locked"),
            patch.object(telegram_bot, "_config", {"bot_token": "test", "allowed_chat_id": 123}),
            patch.object(telegram_bot, "_stop_event", threading.Event()),
            patch.object(telegram_bot, "_outbound", queue.Queue()),
        ):
            item.start()
            self.addCleanup(item.stop)
        sender = patch.object(telegram_bot, "_send_final_message_async")
        self.sender = sender.start()
        self.addCleanup(sender.stop)
        logger = patch.object(focus_restore, "_safe_user_log")
        self.logger = logger.start()
        self.addCleanup(logger.stop)
        self.pipeline = json.loads(PIPELINE.read_text(encoding="utf-8"))
        self.task = json.loads(TASK.read_text(encoding="utf-8"))
        progress_state.start_task(MODE, 0, 0, task_id=401)

    def tearDown(self):
        with progress_state._lock:
            progress_state._state.clear()
            progress_state._state.update(self.original_state)
            progress_state._last_stage_increment_monotonic = self.original_clock

    def complete(self):
        focus_restore._apply_progress_event({"progress_event": "theatre_round_completed"})

    def test_both_profiles_dedupe_residual_go_and_require_three_hud_frames(self):
        for profile in ("CoinDefault", "YiweiNoE"):
            with self.subTest(profile=profile):
                progress_state.start_task(MODE, 0, 0)
                self.logger.reset_mock()
                runner = ProgressGraphRunner(selected_pipeline(self.pipeline, self.task, profile))
                runner.enter_first_dungeon()
                self.assertTrue(progress_state.snapshot()["theatre_round_armed"])
                self.assertEqual(progress_state.snapshot()["completed_rounds"], 0)
                for dungeon in range(1, 4):
                    for _ in range(4):
                        runner.click_go()
                        state = progress_state.snapshot()
                        self.assertEqual(state["completed_rounds"], dungeon)
                        self.assertEqual(state["status"], "waiting_next_round")
                        self.assertFalse(state["theatre_round_armed"])
                    for _ in range(20):
                        runner.step()  # Unknown intermediate page: no input or rearm.
                    runner.step(hud=True)
                    runner.step(hud=True)
                    runner.step(hud=False)
                    self.assertFalse(progress_state.snapshot()["theatre_round_armed"])
                    self.assertEqual(runner.openings, dungeon)
                    for _ in range(6):
                        runner.step(hud=True)
                    self.assertTrue(progress_state.snapshot()["theatre_round_armed"])
                    self.assertEqual(runner.openings, dungeon + 1)
                self.assertEqual(self.logger.call_count, 3)
                self.assertIn("已完成第 3 次副本", self.logger.call_args.args[0])
                self.sender.assert_not_called()

    def test_hud_loss_recovery_and_scene_changes_do_not_count_or_reopen(self):
        for profile in ("CoinDefault", "YiweiNoE"):
            runner = ProgressGraphRunner(selected_pipeline(self.pipeline, self.task, profile))
            runner.enter_first_dungeon()
            for scene in (2, 3, 4, 5):
                for index in range(20):
                    runner.step(hud=index % 2 == 0, scene=scene)
            self.assertEqual(runner.openings, 1)
            self.assertEqual(progress_state.snapshot()["completed_rounds"], 0)
            self.assertTrue(progress_state.snapshot()["theatre_round_armed"])
        self.sender.assert_not_called()
        self.logger.assert_not_called()

    def test_notify_only_once_at_each_50_with_no_quota_or_completion(self):
        for current in range(1, 124):
            self.assertTrue(progress_state.mark_dungeon_entered())
            self.complete()
            self.complete()
            self.assertEqual(progress_state.snapshot()["completed_rounds"], current)
        calls = self.sender.call_args_list
        self.assertEqual(len(calls), 2)
        for call, count in zip(calls, (50, 100)):
            self.assertIn(f"局外副本轮次（已完成）：{count}", call.args[1])
            self.assertIn(MODE, call.args[1])
            self.assertNotIn("/ 0", call.args[1])
            self.assertNotIn("任务已完成", call.args[1])
        state = progress_state.snapshot()
        self.assertEqual((state["total_rounds"], state["stage_total"], state["stage_count"]), (0, 0, 0))
        self.assertEqual(state["status"], "waiting_next_round")
        self.assertEqual(self.logger.call_count, 123)
        status = progress_state.format_status()
        self.assertIn("局外副本轮次（已完成）：123", status)
        self.assertNotIn("局内轮次", status)
        self.assertNotIn("/ 0", status)

    def test_go_before_confirmed_entry_is_not_counted(self):
        self.complete()
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 0)
        self.logger.assert_not_called()

    def test_concurrent_duplicate_finalizers_count_only_once(self):
        progress_state.mark_dungeon_entered()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: progress_state.record_theatre_round_completed(), range(32)))
        self.assertEqual(results.count(1), 1)
        self.assertEqual(results.count(None), 31)
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 1)

    def test_real_finalize_closes_group_and_counts_but_residual_only_restores(self):
        progress_state.mark_dungeon_entered()
        group = focus_restore._SkillInputGroup(202, 101, (300, 400), False)
        params = self.pipeline["TheatreAFKGoClick3Finalize"]["action"]["param"]["custom_action_param"]
        argv = SimpleNamespace(custom_action_param=params, task_detail=SimpleNamespace(task_id=401))
        context = SimpleNamespace(tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": 202})))
        with (
            patch.object(focus_restore, "_skill_input_groups", {401: group}),
            patch.object(focus_restore.time, "sleep"),
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
            patch.object(focus_restore, "_foreground_window", return_value=202),
            patch.object(focus_restore, "_remember_restore_target", return_value=(101, (300, 400))),
        ):
            for _ in range(2):
                self.assertTrue(focus_restore.FocusGuardFinalize().run(context, argv).success)
            self.assertFalse(focus_restore._skill_input_groups)
            self.assertEqual(restore.call_count, 2)
            restore.assert_called_with(101, (300, 400))
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 1)
        self.logger.assert_called_once()

    def test_task_identity_preserves_count_and_new_task_resets_it(self):
        progress_state.mark_dungeon_entered()
        self.complete()
        self.assertFalse(progress_state.start_task(MODE, 0, 0, task_id=401))
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 1)
        self.assertFalse(progress_state.snapshot()["theatre_round_armed"])
        self.assertTrue(progress_state.start_task(MODE, 0, 0, task_id=402))
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 0)
        progress_state.mark_dungeon_entered()
        progress_state.reset()
        self.assertFalse(progress_state.snapshot()["theatre_round_armed"])

    def test_disabled_or_disconnected_monitor_does_not_stop_counting_or_buffer(self):
        for config, stopped in ((None, False), ({"bot_token": "test"}, True)):
            with patch.object(telegram_bot, "_config", config):
                telegram_bot._stop_event.set() if stopped else telegram_bot._stop_event.clear()
                for _ in range(50):
                    progress_state.mark_dungeon_entered()
                    self.complete()
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 100)
        self.sender.assert_not_called()
        self.assertTrue(telegram_bot._outbound.empty())

    def test_other_modes_cannot_accept_theatre_completion(self):
        for mode in ("普通扼守", "普通驱离", "密函驱离", "皎皎币挂机", "调停挂机", "狩月人之阶挂机", "钓鱼挂机", "密函无尽", "普通无尽"):
            with self.subTest(mode=mode):
                progress_state.start_task(mode, 100, 0)
                progress_state.mark_dungeon_entered()
                before = progress_state.snapshot()
                self.complete()
                self.assertEqual(progress_state.snapshot(), before)
        self.logger.assert_not_called()
        self.sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
