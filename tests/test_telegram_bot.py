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


if __name__ == "__main__":
    unittest.main()
