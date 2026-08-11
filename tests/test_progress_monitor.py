from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import progress_monitor  # noqa: E402


class FakeContext:
    def __init__(self, override_result: bool = True) -> None:
        self.override: dict | None = None
        self.override_result = override_result

    def override_pipeline(self, override: dict) -> bool:
        self.override = override
        return self.override_result


class ProgressMonitorTest(unittest.TestCase):
    @patch("progress_monitor.telegram_bot.start", return_value=True)
    def test_starts_monitor_and_finishes_successfully(self, start) -> None:
        context = FakeContext(override_result=False)
        result = progress_monitor.ProgressMonitorStart().run(context, object())
        self.assertTrue(result.success)
        start.assert_called_once_with()
        content = context.override["ProgressMonitorLog"]["focus"][
            "Node.Action.Succeeded"
        ]["content"]
        self.assertEqual(content, "[进度监控] Telegram 监听已启动")

    @patch("progress_monitor.telegram_bot.start", return_value=False)
    def test_missing_config_does_not_block_following_task(self, start) -> None:
        context = FakeContext()
        result = progress_monitor.ProgressMonitorStart().run(context, object())
        self.assertTrue(result.success)
        content = context.override["ProgressMonitorLog"]["focus"][
            "Node.Action.Succeeded"
        ]["content"]
        self.assertIn("已跳过", content)

    @patch("progress_monitor.telegram_bot.start", side_effect=ValueError("bad config"))
    def test_invalid_config_does_not_block_following_task(self, start) -> None:
        result = progress_monitor.ProgressMonitorStart().run(FakeContext(), object())
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
