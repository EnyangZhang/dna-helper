from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import round_logger  # noqa: E402


class CoinAFKRoundTest(unittest.TestCase):
    def test_normal_hold_uses_same_early_completion_recovery(self) -> None:
        context = Mock()
        context.get_hit_count.return_value = 2
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 4})
        completion = round_logger.progress_state.RoundCompletion(
            current=2,
            total=4,
            stage_count=37,
            stage_total=99,
            stage_tracking_active=True,
            early=True,
            should_notify_early=True,
        )

        with (
            patch.object(
                round_logger.progress_state,
                "complete_round",
                return_value=completion,
            ) as complete,
            patch.object(
                round_logger.telegram_bot, "notify_early_completion"
            ) as notify,
        ):
            result = round_logger.NormalEndlessRoundLogger().run(context, argv)

        self.assertTrue(result.success)
        complete.assert_called_once_with(2, 4, "普通扼守")
        notify.assert_called_once_with(2, 4, 37, 99)
        content = context.override_pipeline.call_args.args[0]["NormalEndlessRoundLog"][
            "focus"
        ]["Node.Action.Succeeded"]["content"]
        self.assertEqual(
            content,
            "[普通扼守] 第 2 / 4 次副本提前结束，实际局内进度 37 / 99，已计入完成",
        )

    def test_completed_again_records_outer_round_and_updates_log(self) -> None:
        context = Mock()
        context.get_hit_count.return_value = 2
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 3})

        completion = round_logger.progress_state.RoundCompletion(
            current=2,
            total=3,
            stage_count=99,
            stage_total=99,
            stage_tracking_active=True,
            early=False,
            should_notify_early=False,
        )
        with patch.object(
            round_logger.progress_state, "complete_round", return_value=completion
        ) as complete:
            result = round_logger.CoinAFKRoundLogger().run(context, argv)

        self.assertTrue(result.success)
        complete.assert_called_once_with(2, 3, "皎皎币挂机")
        override = context.override_pipeline.call_args.args[0]
        content = override["CoinAFKRoundLog"]["focus"]["Node.Action.Succeeded"][
            "content"
        ]
        self.assertEqual(content, "[皎皎币挂机] 已完成第 2 / 3 个 99 轮副本")

    def test_early_completion_preserves_progress_and_notifies_once(self) -> None:
        context = Mock()
        context.get_hit_count.return_value = 3
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 10})
        completion = round_logger.progress_state.RoundCompletion(
            current=3,
            total=10,
            stage_count=15,
            stage_total=99,
            stage_tracking_active=True,
            early=True,
            should_notify_early=True,
        )

        with (
            patch.object(
                round_logger.progress_state,
                "complete_round",
                return_value=completion,
            ),
            patch.object(
                round_logger.telegram_bot, "notify_early_completion"
            ) as notify,
        ):
            result = round_logger.CoinAFKRoundLogger().run(context, argv)

        self.assertTrue(result.success)
        notify.assert_called_once_with(3, 10, 15, 99)
        content = context.override_pipeline.call_args.args[0]["CoinAFKRoundLog"][
            "focus"
        ]["Node.Action.Succeeded"]["content"]
        self.assertEqual(
            content,
            "[皎皎币挂机] 第 3 / 10 次副本提前结束，实际局内进度 15 / 99，已计入完成",
        )

    def test_round_decision_restarts_only_before_total(self) -> None:
        context = Mock()
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 3})

        context.get_hit_count.return_value = 2
        result = round_logger.CoinAFKRoundDecision().run(context, argv)
        self.assertTrue(result.success)
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {"CoinAFKRoundDecision": {"next": ["CoinAFKRestartAgain"]}},
        )

        context.get_hit_count.return_value = 3
        result = round_logger.CoinAFKRoundDecision().run(context, argv)
        self.assertTrue(result.success)
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {"CoinAFKRoundDecision": {"next": ["CoinAFKFinished"]}},
        )


if __name__ == "__main__":
    unittest.main()
