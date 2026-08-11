"""Register the one-shot UI task that starts Telegram progress monitoring."""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

import telegram_bot


@AgentServer.custom_action("progress_monitor_start")
class ProgressMonitorStart(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        try:
            enabled = telegram_bot.start()
        except (OSError, RuntimeError, TypeError, ValueError):
            enabled = False
        content = (
            "[进度监控] Telegram 监听已启动"
            if enabled
            else "[进度监控] 未找到有效 Telegram 配置，已跳过"
        )
        try:
            context.override_pipeline(
                {
                    "ProgressMonitorLog": {
                        "focus": {
                            "Node.Action.Succeeded": {
                                "content": content,
                                "display": ["log"],
                            }
                        }
                    }
                }
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return CustomAction.RunResult(success=True)
