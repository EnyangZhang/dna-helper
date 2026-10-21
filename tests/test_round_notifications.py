from __future__ import annotations

import queue
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import focus_restore  # noqa: E402
import progress_state  # noqa: E402
import round_logger  # noqa: E402
import telegram_bot  # noqa: E402


class RoundNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state = progress_state.snapshot()
        self.original_clock = progress_state._last_stage_increment_monotonic
        self.patches = [
            patch.object(progress_state, "_persist_locked"),
            patch.object(telegram_bot, "_config", {"bot_token": "test", "allowed_chat_id": 123}),
            patch.object(telegram_bot, "_stop_event", threading.Event()),
            patch.object(telegram_bot, "_owner_id", None),
            patch.object(telegram_bot, "_outbound", queue.Queue()),
            patch.object(telegram_bot, "_send_final_message_async"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self) -> None:
        with progress_state._lock:
            progress_state._state.clear()
            progress_state._state.update(self.original_state)
            progress_state._last_stage_increment_monotonic = self.original_clock

    def test_all_six_outer_round_loggers_respect_their_notification_interval(self) -> None:
        for mode, logger in (
            ("普通扼守", round_logger.NormalEndlessRoundLogger),
            ("普通驱离", round_logger.NormalExpelRoundLogger),
            ("密函驱离", round_logger.CipherExpelRoundLogger),
            ("皎皎币挂机", round_logger.CoinAFKRoundLogger),
            ("调停挂机", round_logger.MediationAFKRoundLogger),
            ("狩月人之阶挂机", round_logger.MoonHunterAFKRoundLogger),
        ):
            with self.subTest(mode=mode):
                progress_state.start_task(mode, 2, 0)
                telegram_bot._send_final_message_async.reset_mock()
                context = Mock()
                context.get_hit_count.side_effect = [1, 1, 2, 2]
                context.override_pipeline.return_value = True
                for _ in range(4):
                    self.assertTrue(logger().run(
                        context, SimpleNamespace(custom_action_param={"total": 2})
                    ).success)
                calls = telegram_bot._send_final_message_async.call_args_list
                if mode in {"普通驱离", "密函驱离", "调停挂机", "狩月人之阶挂机"}:
                    self.assertEqual(len(calls), 0)
                else:
                    self.assertEqual(len(calls), 2)
                    self.assertIn("局外副本轮次（已完成）：1 / 2", calls[0].args[1])
                    self.assertIn("局外副本轮次（已完成）：2 / 2", calls[1].args[1])
                    task_label, mode_label = telegram_bot._TASK_LABELS[mode]
                    self.assertIn(f"任务：{task_label}\n模式：{mode_label}", calls[1].args[1])
                self.assertEqual(progress_state.snapshot()["status"], "completed")

    def test_early_completion_is_one_combined_notice_not_two(self) -> None:
        progress_state.start_task("皎皎币挂机", 2, 99)
        progress_state.mark_dungeon_entered()
        for _ in range(14):
            progress_state.increment_stage()
        context = Mock()
        context.get_hit_count.return_value = 1
        context.override_pipeline.return_value = True
        for _ in range(2):
            round_logger.CoinAFKRoundLogger().run(
                context, SimpleNamespace(custom_action_param={"total": 2})
            )
        telegram_bot._send_final_message_async.assert_called_once()
        message = telegram_bot._send_final_message_async.call_args.args[1]
        self.assertIn("第 1 / 2 次副本提前结束", message)
        self.assertIn("实际局内进度 15 / 99", message)
        self.assertEqual(progress_state.snapshot()["stage_count"], 15)

    def test_final_round_notice_survives_natural_completion_queue_cleanup(self) -> None:
        progress_state.start_task("普通扼守", 1, 0)
        completion = progress_state.complete_round(1, 1, "普通扼守")
        round_logger._notify_round_completion("普通扼守", completion)
        final_message = telegram_bot.format_task_completed_message()
        self.assertTrue(telegram_bot.stop(final_message, reset_progress=False))
        calls = telegram_bot._send_final_message_async.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].args[1].startswith("DNA Helper 进度更新\n"))
        self.assertNotIn("副本已完成", calls[0].args[1])
        self.assertIn("局外副本轮次（已完成）：1 / 1", calls[0].args[1])
        self.assertIn("任务已完成", calls[1].args[1])
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 1)

    def test_50_interval_loggers_only_notify_at_50_and_100_without_duplicates(self) -> None:
        for mode, logger in (
            ("普通驱离", round_logger.NormalExpelRoundLogger),
            ("密函驱离", round_logger.CipherExpelRoundLogger),
            ("调停挂机", round_logger.MediationAFKRoundLogger),
            ("狩月人之阶挂机", round_logger.MoonHunterAFKRoundLogger),
        ):
            with self.subTest(mode=mode):
                progress_state.start_task(mode, 123, 0)
                telegram_bot._send_final_message_async.reset_mock()
                context = Mock()
                context.override_pipeline.return_value = True
                for current in range(1, 124):
                    context.get_hit_count.return_value = current
                    for _ in range(2):
                        self.assertTrue(logger().run(
                            context, SimpleNamespace(custom_action_param={"total": 123})
                        ).success)
                calls = telegram_bot._send_final_message_async.call_args_list
                self.assertEqual(len(calls), 2)
                for call, count in zip(calls, (50, 100)):
                    self.assertIn(f"局外副本轮次（已完成）：{count} / 123", call.args[1])
                    label, mode_label = telegram_bot._TASK_LABELS[mode]
                    self.assertIn(f"任务：{label}\n模式：{mode_label}", call.args[1])
                state = progress_state.snapshot()
                self.assertEqual(state["completed_rounds"], 123)
                self.assertEqual(state["status"], "completed")

    def test_50_interval_task_completion_still_sends_at_all_targets(self) -> None:
        for mode in ("普通驱离", "密函驱离", "调停挂机", "狩月人之阶挂机"):
            for total in (1, 49, 50, 51, 100, 123):
                with self.subTest(mode=mode, total=total):
                    telegram_bot._config = {"bot_token": "test", "allowed_chat_id": 123}
                    telegram_bot._stop_event = threading.Event()
                    telegram_bot._send_final_message_async.reset_mock()
                    progress_state.start_task(mode, total, 0)
                    result = progress_state.complete_round(total, total, mode)
                    round_logger._notify_round_completion(mode, result)
                    self.assertTrue(telegram_bot.stop(
                        telegram_bot.format_task_completed_message(), reset_progress=False
                    ))
                    calls = telegram_bot._send_final_message_async.call_args_list
                    self.assertEqual(len(calls), 2 if total % 50 == 0 else 1)
                    self.assertIn("任务已完成", calls[-1].args[1])
                    self.assertIn(f"模式：{telegram_bot._TASK_LABELS[mode][1]}", calls[-1].args[1])
                    self.assertEqual(progress_state.snapshot()["completed_rounds"], total)

    def test_fishing_only_pushes_at_50_and_100_then_keeps_completion_message(self) -> None:
        progress_state.start_task("钓鱼挂机", 120, 0)
        for _ in range(120):
            focus_restore._apply_progress_event({"progress_event": "fishing_caught"})
        self.assertTrue(telegram_bot._outbound.empty())
        calls = telegram_bot._send_final_message_async.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("钓鱼数量：50 / 120", calls[0].args[1])
        self.assertIn("钓鱼数量：100 / 120", calls[1].args[1])
        self.assertEqual(progress_state.snapshot()["stage_count"], 120)
        self.assertIn("钓鱼数量：120 / 120", progress_state.format_status())
        self.assertTrue(telegram_bot.stop(
            telegram_bot.format_task_completed_message(), reset_progress=False
        ))
        self.assertEqual(telegram_bot._send_final_message_async.call_count, 3)
        self.assertIn("任务已完成", telegram_bot._send_final_message_async.call_args.args[1])
        self.assertIn("钓鱼挂机", telegram_bot._send_final_message_async.call_args.args[1])

    def test_fishing_target_multiple_keeps_milestone_and_original_final_notice(self) -> None:
        for target in (1, 49, 50, 51, 100, 120, 150):
            with self.subTest(target=target):
                telegram_bot._config = {"bot_token": "test", "allowed_chat_id": 123}
                telegram_bot._stop_event = threading.Event()
                telegram_bot._send_final_message_async.reset_mock()
                progress_state.start_task("钓鱼挂机", target, 0)
                for _ in range(target + 2):
                    focus_restore._apply_progress_event({"progress_event": "fishing_caught"})
                self.assertEqual(progress_state.snapshot()["stage_count"], target)
                calls = telegram_bot._send_final_message_async.call_args_list
                self.assertEqual(len(calls), target // 50)
                for call, count in zip(calls, range(50, target + 1, 50)):
                    self.assertIn(f"钓鱼数量：{count} / {target}", call.args[1])
                final = telegram_bot.format_task_completed_message()
                self.assertEqual(final, "DNA Helper 任务已完成\n任务：钓鱼挂机\n模式：钓鱼挂机")
                self.assertTrue(telegram_bot.stop(final, reset_progress=False))
                self.assertEqual(telegram_bot._send_final_message_async.call_count, target // 50 + 1)
                self.assertEqual(telegram_bot._send_final_message_async.call_args.args[1], final)

    def test_fishing_pool_empty_keeps_original_notice_and_does_not_replay_milestone(self) -> None:
        progress_state.start_task("钓鱼挂机", 120, 0)
        for _ in range(50):
            focus_restore._apply_progress_event({"progress_event": "fishing_caught"})
        self.assertTrue(progress_state.mark_fishing_pool_empty())
        focus_restore._apply_progress_event({"progress_event": "fishing_caught"})
        telegram_bot._send_final_message_async.assert_called_once()
        self.assertEqual(telegram_bot.format_task_completed_message(), "鱼池已空。")
        self.assertTrue(telegram_bot.stop("鱼池已空。", reset_progress=False))
        calls = telegram_bot._send_final_message_async.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].args[1], "鱼池已空。")
        self.assertEqual(progress_state.snapshot()["stage_count"], 50)

    def test_fishing_milestones_are_silent_without_monitor_or_after_disconnect(self) -> None:
        for disabled in ("no_config", "stopped"):
            with self.subTest(disabled=disabled):
                telegram_bot._config = None if disabled == "no_config" else {"bot_token": "test"}
                telegram_bot._stop_event = threading.Event()
                if disabled == "stopped":
                    telegram_bot._stop_event.set()
                progress_state.start_task("钓鱼挂机", 120, 0)
                for _ in range(100):
                    focus_restore._apply_progress_event({"progress_event": "fishing_caught"})
                self.assertEqual(progress_state.snapshot()["stage_count"], 100)
                telegram_bot._send_final_message_async.assert_not_called()

    def test_fishing_milestones_do_not_accept_other_task_counters(self) -> None:
        for mode in ("普通扼守", "普通驱离", "密函无尽", "沉浸式戏剧挂机"):
            with patch.object(progress_state, "snapshot", return_value={"mode": mode, "stage_count": 50}):
                self.assertFalse(telegram_bot.notify_fishing_milestone())
        telegram_bot._send_final_message_async.assert_not_called()

    def test_actual_progress_events_only_notify_at_50_not_99_or_100(self) -> None:
        for mode, event, stage_total in (
            ("普通无尽", "continue_challenge", 0),
            ("密函无尽", "cipher_cycle_completed", 0),
            ("普通扼守", "continue_challenge", 99),
            ("皎皎币挂机", "continue_challenge", 99),
        ):
            with self.subTest(mode=mode):
                progress_state.start_task(mode, 2 if stage_total else 0, stage_total)
                if stage_total:
                    progress_state.mark_dungeon_entered()
                telegram_bot._outbound = queue.Queue()
                with patch.object(progress_state.time, "monotonic", side_effect=(i * 6 for i in range(1, 121))):
                    for _ in range(120):
                        focus_restore._apply_progress_event({"progress_event": event})
                self.assertEqual(telegram_bot._outbound.qsize(), 1)
                message = telegram_bot._outbound.get_nowait()
                self.assertIn("局内轮次：50", message)
                self.assertNotIn("99 轮已完成", message)
                if stage_total:
                    self.assertIn("局外副本轮次（已完成）：0 / 2", message)

    def test_disabled_or_disconnected_monitor_never_sends_round_notifications(self) -> None:
        for disabled in ("no_config", "stopped"):
            with self.subTest(disabled=disabled):
                telegram_bot._config = None if disabled == "no_config" else {"bot_token": "test"}
                telegram_bot._stop_event = threading.Event()
                if disabled == "stopped":
                    telegram_bot._stop_event.set()
                progress_state.start_task("普通扼守", 1, 99)
                for _ in range(49):
                    progress_state.increment_stage()
                self.assertFalse(telegram_bot.notify_stage_milestone())
                completion = progress_state.complete_round(1, 1)
                round_logger._notify_round_completion("普通扼守", completion)
                self.assertTrue(telegram_bot._outbound.empty())
                telegram_bot._send_final_message_async.assert_not_called()
                self.assertEqual(progress_state.snapshot()["stage_count"], 50)

    def test_fishing_and_theatre_do_not_gain_fake_dungeon_milestones(self) -> None:
        for mode in ("钓鱼挂机", "沉浸式戏剧挂机", "调停挂机", "普通驱离"):
            with patch.object(progress_state, "snapshot", return_value={"mode": mode, "stage_count": 50}):
                self.assertFalse(telegram_bot.notify_stage_milestone())
        self.assertTrue(telegram_bot._outbound.empty())

    def test_concurrent_duplicate_round_events_claim_only_one_notification(self) -> None:
        progress_state.start_task("普通驱离", 2, 0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            completions = list(pool.map(lambda _: progress_state.complete_round(1, 2), range(20)))
        self.assertEqual(sum(result.should_notify for result in completions), 1)
        self.assertEqual(progress_state.snapshot()["completed_rounds"], 1)


if __name__ == "__main__":
    unittest.main()
