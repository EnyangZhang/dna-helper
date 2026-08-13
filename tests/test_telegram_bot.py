from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import telegram_bot  # noqa: E402


class TelegramBotTest(unittest.TestCase):
    def tearDown(self) -> None:
        telegram_bot._config = None
        telegram_bot._stop_event.clear()

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

    @patch("telegram_bot.progress_state.snapshot", return_value={"mode": "普通驱离"})
    def test_task_completion_message_uses_current_mode(self, snapshot) -> None:
        self.assertEqual(
            telegram_bot.format_task_completed_message(),
            "DNA Helper 任务已完成\n任务：普通无尽加速\n模式：驱离",
        )
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

    @patch("telegram_bot._send_message", side_effect=OSError("offline"))
    def test_final_message_network_failure_is_non_blocking(self, send_message) -> None:
        telegram_bot._send_final_message(
            {"bot_token": "token", "allowed_chat_id": 123},
            "任务完成消息",
        )
        send_message.assert_called_once_with("token", 123, "任务完成消息")

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
        telegram_bot._auto_status_loop(stop_event)

        self.assertEqual(
            stop_event.assert_interval, telegram_bot._AUTO_STATUS_INTERVAL_SECONDS
        )
        self.assertEqual(telegram_bot._AUTO_STATUS_INTERVAL_SECONDS, 1800)
        format_status.assert_called_once_with()
        put.assert_called_once_with("当前状态")


if __name__ == "__main__":
    unittest.main()
