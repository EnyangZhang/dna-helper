from __future__ import annotations

import sys
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import telegram_bot  # noqa: E402


class TelegramBotTest(unittest.TestCase):
    def tearDown(self) -> None:
        telegram_bot._config = None
        telegram_bot._stop_event.clear()
        telegram_bot._owner_id = None

    @patch("telegram_bot._send_message")
    @patch("telegram_bot.progress_state.format_status", return_value="当前状态")
    def test_authorized_status_query(self, format_status, send_message) -> None:
        telegram_bot._handle_update(
            "token", 123, {"message": {"chat": {"id": 123}, "text": "/status"}}
        )
        format_status.assert_called_once_with()
        send_message.assert_called_once_with("token", 123, "当前状态")

    @patch("telegram_bot._send_message")
    def test_unauthorized_chat_is_ignored(self, send_message) -> None:
        telegram_bot._handle_update(
            "token", 123, {"message": {"chat": {"id": 456}, "text": "进度"}}
        )
        send_message.assert_not_called()

    def test_authorized_disconnect_consumes_update_then_stops_only_telegram(self) -> None:
        events: list[str] = []
        with (
            patch.object(
                telegram_bot,
                "_send_message",
                side_effect=lambda *_args: events.append("ack"),
            ) as send_message,
            patch.object(
                telegram_bot,
                "_acknowledge_disconnect_update",
                side_effect=lambda *_args: events.append("consume"),
            ) as acknowledge,
            patch.object(
                telegram_bot.process_registry,
                "publish_monitor_disconnect",
                side_effect=lambda *_args: events.append("broadcast"),
            ) as broadcast,
            patch.object(
                telegram_bot,
                "stop",
                side_effect=lambda **_kwargs: events.append("telegram-stop") or True,
            ) as stop,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            telegram_bot._handle_update(
                "token",
                123,
                {
                    "update_id": 900,
                    "message": {"chat": {"id": 123}, "text": "disconnect"},
                },
            )

        self.assertEqual(events, ["ack", "consume", "broadcast", "telegram-stop"])
        send_message.assert_called_once_with(
            "token",
            123,
            "DNA Helper 已收到 disconnect。\n正在关闭本机全部监控通讯；当前游戏任务和窗口不会关闭。",
        )
        acknowledge.assert_called_once_with("token", 900)
        broadcast.assert_called_once_with("telegram")
        stop.assert_called_once_with(reset_progress=False)
        self.assertIn(
            "disconnect 已执行，本机全部监控通讯已关闭；当前任务继续运行",
            output.getvalue(),
        )

    def test_disconnect_supports_slash_and_bot_suffix(self) -> None:
        with (
            patch.object(telegram_bot, "_send_message") as send_message,
            patch.object(telegram_bot, "_acknowledge_disconnect_update"),
            patch.object(telegram_bot.process_registry, "publish_monitor_disconnect"),
            patch.object(telegram_bot, "stop"),
        ):
            telegram_bot._handle_update(
                "token",
                123,
                {
                    "message": {
                        "chat": {"id": 123},
                        "text": "/disconnect@DNAHelperBot",
                    }
                },
            )

        send_message.assert_called_once()

    def test_disconnect_still_stops_when_acknowledgement_fails(self) -> None:
        with (
            patch.object(telegram_bot, "_send_message", side_effect=OSError("offline")),
            patch.object(telegram_bot, "_acknowledge_disconnect_update"),
            patch.object(telegram_bot.process_registry, "publish_monitor_disconnect"),
            patch.object(telegram_bot, "stop"),
        ):
            with self.assertRaises(OSError):
                telegram_bot._handle_update(
                    "token",
                    123,
                    {"message": {"chat": {"id": 123}, "text": "disconnect"}},
                )

    @patch("telegram_bot._api_call")
    def test_disconnect_update_is_consumed_before_shutdown(self, api_call) -> None:
        telegram_bot._acknowledge_disconnect_update("token", 900)

        api_call.assert_called_once_with(
            "token", "getUpdates", {"offset": 901, "timeout": 0}, timeout=5
        )

    @patch.object(telegram_bot._outbound, "put")
    def test_task_start_notification_is_queued_once_enabled(self, put) -> None:
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}
        self.assertTrue(telegram_bot.notify_task_started("普通扼守"))
        put.assert_called_once_with(
            "DNA Helper 任务已启动\n任务：普通无尽加速\n模式：扼守"
        )

    @patch.object(telegram_bot._outbound, "put")
    def test_task_start_notification_is_disabled_without_config(self, put) -> None:
        telegram_bot._config = None
        self.assertFalse(telegram_bot.notify_task_started("密函无尽"))
        put.assert_not_called()

    @patch.object(telegram_bot._outbound, "put")
    @patch("telegram_bot.progress_state.snapshot", return_value={"mode": "密函无尽"})
    def test_infinite_99_completion_is_queued(self, snapshot, put) -> None:
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}

        self.assertTrue(telegram_bot.notify_infinite_99_completed())

        snapshot.assert_called_once_with()
        put.assert_called_once_with(
            "DNA Helper 局内 99 轮已完成\n任务：密函无尽加速\n模式：无尽"
        )

    @patch.object(telegram_bot._outbound, "put")
    @patch("telegram_bot.progress_state.snapshot", return_value={"mode": "普通扼守"})
    def test_finite_mode_does_not_send_infinite_milestone(self, snapshot, put) -> None:
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}

        self.assertFalse(telegram_bot.notify_infinite_99_completed())

        snapshot.assert_called_once_with()
        put.assert_not_called()

    @patch("telegram_bot._send_final_message_async")
    def test_early_completion_uses_reliable_one_shot_sender(self, send_final) -> None:
        telegram_bot._config = {
            "bot_token": "token",
            "allowed_chat_id": 123,
            "poll_timeout_seconds": 25,
        }

        self.assertTrue(telegram_bot.notify_early_completion(3, 10, 15, 99))

        send_final.assert_called_once_with(
            {
                "bot_token": "token",
                "allowed_chat_id": 123,
                "poll_timeout_seconds": 25,
            },
            "第 3 / 10 次副本提前结束，实际局内进度 15 / 99，已计入完成并继续下一次。",
        )

    @patch("telegram_bot._send_final_message_async")
    def test_early_completion_at_limit_does_not_claim_restart(self, send_final) -> None:
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}

        self.assertTrue(telegram_bot.notify_early_completion(10, 10, 15, 99))

        send_final.assert_called_once_with(
            {"bot_token": "token", "allowed_chat_id": 123},
            "第 10 / 10 次副本提前结束，实际局内进度 15 / 99，已计入完成并达到设定次数。",
        )

    @patch("telegram_bot.progress_state.snapshot", return_value={"mode": "普通驱离"})
    def test_task_completion_message_uses_current_mode(self, snapshot) -> None:
        self.assertEqual(
            telegram_bot.format_task_completed_message(),
            "DNA Helper 任务已完成\n任务：普通无尽加速\n模式：驱离",
        )
        snapshot.assert_called_once_with()

    @patch("telegram_bot.progress_state.snapshot", return_value={"mode": "皎皎币挂机"})
    def test_coin_afk_completion_uses_formal_task_label(self, snapshot) -> None:
        self.assertEqual(
            telegram_bot.format_task_completed_message(),
            "DNA Helper 任务已完成\n任务：皎皎币挂机\n模式：自动循环",
        )
        snapshot.assert_called_once_with()

    @patch(
        "telegram_bot.progress_state.snapshot",
        return_value={
            "mode": "挂机钓鱼",
            "completion_reason": "fishing_pool_empty",
        },
    )
    def test_fishing_pool_empty_uses_specific_completion_message(self, snapshot) -> None:
        self.assertEqual(telegram_bot.format_task_completed_message(), "鱼池已空。")
        snapshot.assert_called_once_with()

    @patch.object(telegram_bot._outbound, "put")
    def test_standalone_monitor_start_notification_is_queued(self, put) -> None:
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}
        self.assertTrue(telegram_bot.notify_monitor_started())
        put.assert_called_once_with("DNA Helper 监控已开启\n无任务")

    def test_stop_reports_only_an_active_monitor(self) -> None:
        self.assertFalse(telegram_bot.stop())
        telegram_bot._stop_event.clear()
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}
        self.assertTrue(telegram_bot.stop())
        self.assertFalse(telegram_bot.stop())

    @patch("telegram_bot._send_final_message_async")
    def test_stop_sends_final_message_outside_cleared_queue(self, send_final) -> None:
        telegram_bot._stop_event.clear()
        telegram_bot._config = {
            "bot_token": "token",
            "allowed_chat_id": 123,
            "poll_timeout_seconds": 25,
        }

        self.assertTrue(telegram_bot.stop(final_message="任务完成消息"))

        send_final.assert_called_once_with(
            {
                "bot_token": "token",
                "allowed_chat_id": 123,
                "poll_timeout_seconds": 25,
            },
            "任务完成消息",
        )

    @patch("telegram_bot.progress_state.reset")
    def test_stop_clears_progress_state(self, reset_state) -> None:
        telegram_bot._stop_event.clear()
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}
        telegram_bot.stop()
        reset_state.assert_called_once_with()

    @patch("telegram_bot.progress_state.reset")
    def test_disconnect_stop_preserves_running_task_progress(self, reset_state) -> None:
        telegram_bot._stop_event.clear()
        telegram_bot._config = {"bot_token": "token", "allowed_chat_id": 123}

        telegram_bot.stop(reset_progress=False)

        reset_state.assert_not_called()

    @patch("telegram_bot._send_message", side_effect=OSError("https://api.telegram.org/botbotSECRET/sendMessage"))
    def test_final_message_network_failure_is_non_blocking(self, send_message) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            telegram_bot._send_final_message(
                {"bot_token": "token", "allowed_chat_id": 123},
                "任务完成消息",
            )
        send_message.assert_called_once_with("token", 123, "任务完成消息")
        self.assertNotIn("botSECRET", output.getvalue())

    @patch("telegram_bot._api_call", side_effect=OSError("botSECRET leaked"))
    def test_poll_network_failure_log_excludes_exception_text(self, api_call) -> None:
        class StopAfterFailure:
            def __init__(self) -> None:
                self.calls = 0

            def is_set(self) -> bool:
                return self.calls > 0

            def wait(self, _seconds: int) -> bool:
                self.calls += 1
                return True

        stop_event = StopAfterFailure()
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            telegram_bot._poll_loop(
                {"bot_token": "token", "allowed_chat_id": 123, "poll_timeout_seconds": 5},
                stop_event,
                "owner-a",
            )
        api_call.assert_called_once()
        self.assertNotIn("botSECRET", output.getvalue())

    def test_poll_discards_pending_updates_before_processing_new_messages(self) -> None:
        class StopAfterSecondCall:
            stopped = False

            def is_set(self) -> bool:
                return self.stopped

            def wait(self, _seconds: int) -> bool:
                self.stopped = True
                return True

        stop_event = StopAfterSecondCall()
        responses = [
            {
                "result": [
                    {
                        "update_id": 900,
                        "message": {"chat": {"id": 123}, "text": "disconnect"},
                    }
                ]
            },
            {"result": []},
        ]

        def api_call(_token, _method, params, _timeout):
            response = responses.pop(0)
            if not responses:
                stop_event.stopped = True
            return response

        with (
            patch.object(telegram_bot, "_api_call", side_effect=api_call) as call,
            patch.object(telegram_bot, "_handle_update") as handle_update,
        ):
            telegram_bot._poll_loop(
                {"bot_token": "token", "allowed_chat_id": 123, "poll_timeout_seconds": 5},
                stop_event,
                "owner-a",
            )

        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[0].args[2]["timeout"], 0)
        self.assertEqual(call.call_args_list[1].args[2]["offset"], 901)
        handle_update.assert_not_called()

    def test_owner_record_rejects_non_normal_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "telegram-owner.json"
            with patch.object(telegram_bot, "_LOCK_PATH", lock_path), patch.object(
                telegram_bot.process_registry, "_is_normal_file_target", return_value=False
            ):
                self.assertIsNone(telegram_bot._read_owner_record())

    @patch.object(telegram_bot._outbound, "put")
    @patch("telegram_bot.progress_state.format_status", return_value="当前状态")
    def test_auto_status_is_queued_every_thirty_minutes(
        self, format_status, put
    ) -> None:
        class StopAfterSecondWait:
            def __init__(self) -> None:
                self.wait_count = 0

            def wait(self, seconds: int) -> bool:
                self.wait_count += 1
                self.assert_interval = seconds
                return self.wait_count >= 2

        stop_event = StopAfterSecondWait()
        telegram_bot._auto_status_loop(stop_event, "owner-a")

        self.assertEqual(
            stop_event.assert_interval, telegram_bot._AUTO_STATUS_INTERVAL_SECONDS
        )
        self.assertEqual(telegram_bot._AUTO_STATUS_INTERVAL_SECONDS, 1800)
        format_status.assert_called_once_with()
        put.assert_called_once_with("当前状态")

    @patch("telegram_bot._refresh_ownership", side_effect=[False, False, True, False, False, False])
    @patch("telegram_bot.process_registry.read_monitor_disconnect_generation", return_value=None)
    def test_ownership_watchdog_tolerates_transient_failures(
        self, _read_signal, refresh
    ) -> None:
        class ImmediateWait:
            def __init__(self) -> None:
                self.stopped = False

            def wait(self, seconds: int) -> bool:
                self.assert_interval = seconds
                return self.stopped

            def set(self) -> None:
                self.stopped = True

        stop_event = ImmediateWait()
        stop = Mock(side_effect=lambda **_kwargs: stop_event.set())
        with (
            patch("sys.stdout", new_callable=io.StringIO) as output,
            patch.object(telegram_bot, "stop", stop),
        ):
            telegram_bot._ownership_watchdog(stop_event, "owner-a")

        self.assertTrue(stop_event.stopped)
        self.assertEqual(stop_event.assert_interval, telegram_bot._OWNERSHIP_WATCHDOG_SECONDS)
        self.assertEqual(refresh.call_count, 6)
        self.assertIn("连续失去监听权", output.getvalue())
        self.assertIn("仅停止当前实例通讯", output.getvalue())
        stop.assert_called_once_with(reset_progress=False)

    @patch("telegram_bot._refresh_ownership", side_effect=[False, False, False])
    @patch("telegram_bot.process_registry.read_monitor_disconnect_generation", return_value=None)
    def test_ownership_loss_stop_failure_never_requests_agent_shutdown(
        self, _read_signal, refresh
    ) -> None:
        class ImmediateWait:
            stopped = False

            def wait(self, _seconds: int) -> bool:
                return self.stopped

            def set(self) -> None:
                self.stopped = True

        stop_event = ImmediateWait()
        stop = Mock(side_effect=RuntimeError("stop failed"))
        with (
            patch("sys.stdout", new_callable=io.StringIO) as output,
            patch.object(telegram_bot, "stop", stop),
        ):
            telegram_bot._ownership_watchdog(stop_event, "owner-a")

        self.assertTrue(stop_event.stopped)
        stop.assert_called_once_with(reset_progress=False)
        self.assertIn("停止当前实例通讯失败", output.getvalue())

    def test_global_disconnect_signal_stops_only_telegram_and_preserves_progress(self) -> None:
        class StopAfterOneWait:
            def wait(self, _seconds: int) -> bool:
                return False

        stop = Mock()
        with (
            patch.object(
                telegram_bot.process_registry,
                "read_monitor_disconnect_generation",
                return_value="new-generation",
            ),
            patch.object(telegram_bot, "stop", stop),
            patch.object(telegram_bot, "_refresh_ownership") as refresh,
        ):
            telegram_bot._ownership_watchdog(
                StopAfterOneWait(), "owner-a", "startup-generation"
            )

        stop.assert_called_once_with(reset_progress=False)
        refresh.assert_not_called()

    def test_existing_disconnect_signal_is_only_a_startup_baseline(self) -> None:
        class StopAfterSecondWait:
            def __init__(self) -> None:
                self.wait_count = 0

            def wait(self, _seconds: int) -> bool:
                self.wait_count += 1
                return self.wait_count >= 2

        stop = Mock()
        with (
            patch.object(
                telegram_bot.process_registry,
                "read_monitor_disconnect_generation",
                return_value="startup-generation",
            ),
            patch.object(telegram_bot, "stop", stop),
            patch.object(telegram_bot, "_refresh_ownership", return_value=True),
        ):
            telegram_bot._ownership_watchdog(
                StopAfterSecondWait(), "owner-a", "startup-generation"
            )

        stop.assert_not_called()

    @patch("telegram_bot._is_owner", side_effect=AssertionError("worker must not read owner file"))
    @patch("telegram_bot._refresh_ownership", side_effect=AssertionError("worker must not refresh owner file"))
    @patch.object(telegram_bot._outbound, "put")
    @patch("telegram_bot.progress_state.format_status", return_value="当前状态")
    def test_auto_status_worker_does_not_touch_owner_file(
        self, format_status, put, refresh, is_owner
    ) -> None:
        class StopAfterSecondWait:
            def __init__(self) -> None:
                self.wait_count = 0

            def wait(self, _seconds: int) -> bool:
                self.wait_count += 1
                return self.wait_count >= 2

        telegram_bot._auto_status_loop(StopAfterSecondWait(), "owner-a")

        format_status.assert_called_once_with()
        put.assert_called_once_with("当前状态")
        refresh.assert_not_called()
        is_owner.assert_not_called()

    @patch("telegram_bot._is_owner", side_effect=AssertionError("worker must not read owner file"))
    @patch("telegram_bot._refresh_ownership", side_effect=AssertionError("worker must not refresh owner file"))
    @patch.object(telegram_bot._outbound, "task_done")
    @patch.object(telegram_bot._outbound, "get", return_value="当前状态")
    @patch("telegram_bot._send_message")
    def test_sender_does_not_touch_owner_file(
        self, send_message, get, task_done, refresh, is_owner
    ) -> None:
        class StopAfterSend:
            def __init__(self) -> None:
                self.stopped = False

            def is_set(self) -> bool:
                return self.stopped

            def wait(self, _seconds: int) -> bool:
                return self.stopped

        stop_event = StopAfterSend()
        send_message.side_effect = lambda *_args: setattr(stop_event, "stopped", True)

        telegram_bot._send_loop(
            {"bot_token": "token", "allowed_chat_id": 123},
            stop_event,
            "owner-a",
        )

        get.assert_called_once_with(timeout=0.5)
        send_message.assert_called_once_with("token", 123, "当前状态")
        task_done.assert_called_once_with()
        refresh.assert_not_called()
        is_owner.assert_not_called()

    def test_single_instance_lock_prevents_non_owner_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "telegram-owner.json"
            with patch.object(telegram_bot, "_LOCK_PATH", lock_path):
                self.assertFalse(telegram_bot._is_owner("owner-a"))
                self.assertTrue(telegram_bot._acquire_ownership("owner-a"))
                self.assertTrue(telegram_bot._is_owner("owner-a"))
                self.assertFalse(telegram_bot._is_owner("owner-b"))
                self.assertTrue(telegram_bot._acquire_ownership("owner-b"))
                self.assertFalse(telegram_bot._is_owner("owner-a"))
                self.assertTrue(telegram_bot._is_owner("owner-b"))
                telegram_bot._release_ownership("owner-a")
                self.assertTrue(telegram_bot._is_owner("owner-b"))
                telegram_bot._release_ownership("owner-b")
                self.assertFalse(lock_path.exists())

    def test_lock_refresh_failure_when_expired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "telegram-owner.json"
            with patch.object(telegram_bot, "_LOCK_PATH", lock_path):
                with patch.object(telegram_bot.time, "time", return_value=1000):
                    self.assertTrue(telegram_bot._acquire_ownership("owner-a"))
                self.assertTrue(telegram_bot._is_owner("owner-a", now=1000))
                self.assertFalse(telegram_bot._is_owner("owner-a", now=1000 + 100))
                self.assertTrue(telegram_bot._acquire_ownership("owner-b"))
                self.assertTrue(telegram_bot._is_owner("owner-b"))
                self.assertFalse(telegram_bot._is_owner("owner-a"))
                self.assertTrue(lock_path.exists())

if __name__ == "__main__":
    unittest.main()
