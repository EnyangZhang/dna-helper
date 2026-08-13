from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import progress_monitor  # noqa: E402
from maa.event_sink import NotificationType  # noqa: E402


class FakeContext:
    def __init__(self, override_result: bool = True) -> None:
        self.override: dict | None = None
        self.override_result = override_result

    def override_pipeline(self, override: dict) -> bool:
        self.override = override
        return self.override_result


def make_argv(task_id: int = 100) -> SimpleNamespace:
    return SimpleNamespace(task_detail=SimpleNamespace(task_id=task_id))


class ProgressMonitorTest(unittest.TestCase):
    def test_queue_detection_reads_existing_mxu_submission_map(self) -> None:
        content = (
            b"Calling post_task: entry=ProgressMonitorEntry, override=[]\n"
            b"post_task returned task_id: 200000003\n"
            b"Calling post_task: entry=NormalEndlessEntry, override=[]\n"
            b"post_task returned task_id: 200000004\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "mxu-tauri.log"
            log_path.write_bytes(content)
            with (
                patch("progress_monitor._MXU_LOG_PATH", log_path),
                patch("progress_monitor._QUEUE_LOG_WAIT_SECONDS", 0),
            ):
                self.assertTrue(
                    progress_monitor._has_queued_game_task_from_log(200000003)
                )
                self.assertFalse(
                    progress_monitor._has_queued_game_task_from_log(200000004)
                )

    @patch("progress_monitor._has_queued_game_task_from_log", return_value=False)
    @patch("progress_monitor.telegram_bot.notify_monitor_started")
    @patch("progress_monitor.telegram_bot.start", return_value=True)
    def test_standalone_monitor_starts_and_notifies_phone(
        self, start, notify, has_game
    ) -> None:
        context = FakeContext(override_result=False)
        result = progress_monitor.ProgressMonitorStart().run(context, make_argv())
        self.assertTrue(result.success)
        start.assert_called_once_with()
        notify.assert_called_once_with()
        has_game.assert_called_once_with(100)
        content = context.override["ProgressMonitorLog"]["focus"][
            "Node.Action.Succeeded"
        ]["content"]
        self.assertEqual(content, "[进度监控] Telegram 监听已启动")
        self.assertNotIn("next", context.override["ProgressMonitorLog"])

    @patch("progress_monitor.telegram_bot.start", return_value=False)
    def test_missing_config_does_not_block_following_task(self, start) -> None:
        context = FakeContext()
        result = progress_monitor.ProgressMonitorStart().run(context, make_argv())
        self.assertTrue(result.success)
        content = context.override["ProgressMonitorLog"]["focus"][
            "Node.Action.Succeeded"
        ]["content"]
        self.assertIn("已跳过", content)

    @patch("progress_monitor.telegram_bot.start", side_effect=ValueError("bad config"))
    def test_invalid_config_does_not_block_following_task(self, start) -> None:
        result = progress_monitor.ProgressMonitorStart().run(FakeContext(), make_argv())
        self.assertTrue(result.success)

    @patch("progress_monitor._has_queued_game_task_from_log", return_value=True)
    @patch("progress_monitor.telegram_bot.notify_monitor_started")
    @patch("progress_monitor.telegram_bot.start", return_value=True)
    def test_queued_game_task_does_not_send_idle_notification(
        self, start, notify, has_game
    ) -> None:
        context = FakeContext()
        result = progress_monitor.ProgressMonitorStart().run(context, make_argv())
        self.assertTrue(result.success)
        notify.assert_not_called()
        self.assertEqual(context.override["ProgressMonitorLog"]["next"], [])
        has_game.assert_called_once_with(100)

    @patch("progress_monitor.telegram_bot.stop")
    def test_ui_stop_event_stops_monitor(self, stop) -> None:
        detail = SimpleNamespace(entry="NormalEndlessEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Failed, detail
        )
        stop.assert_called_once_with(final_message=None)

    @patch(
        "progress_monitor.telegram_bot.format_task_completed_message",
        return_value="任务完成消息",
    )
    @patch("progress_monitor.telegram_bot.stop")
    def test_natural_game_completion_notifies_then_stops(
        self, stop, format_completed
    ) -> None:
        detail = SimpleNamespace(entry="RewardConfirmEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Succeeded, detail
        )
        format_completed.assert_called_once_with()
        stop.assert_called_once_with(final_message="任务完成消息")

    @patch("progress_monitor.telegram_bot.stop")
    def test_monitor_bootstrap_completion_does_not_stop_monitor(self, stop) -> None:
        detail = SimpleNamespace(entry="ProgressMonitorEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Succeeded, detail
        )
        stop.assert_not_called()

    @patch("progress_monitor.telegram_bot.stop")
    def test_standalone_monitor_ui_stop_closes_monitor(self, stop) -> None:
        detail = SimpleNamespace(entry="ProgressMonitorEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Failed, detail
        )
        stop.assert_called_once_with()

    @patch("progress_monitor.telegram_bot.stop")
    def test_game_start_event_does_not_stop_monitor(self, stop) -> None:
        detail = SimpleNamespace(entry="RewardConfirmEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Starting, detail
        )
        stop.assert_not_called()

    @patch("builtins.print")
    @patch("progress_monitor.telegram_bot.stop", return_value=False)
    def test_inactive_monitor_does_not_log_stopped(self, stop, print_mock) -> None:
        detail = SimpleNamespace(entry="NormalEndlessEntry")
        progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
            None, NotificationType.Failed, detail
        )
        stop.assert_called_once_with(final_message=None)
        print_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
