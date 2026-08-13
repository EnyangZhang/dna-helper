"""Register the UI task that starts Telegram progress monitoring."""

from __future__ import annotations

import re
import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink

import telegram_bot


_GAME_TASK_ENTRIES = {"RewardConfirmEntry", "NormalEndlessEntry"}
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MXU_LOG_PATH = _PROJECT_ROOT / "debug" / "mxu-tauri.log"
_QUEUE_LOG_WAIT_SECONDS = 0.5
_QUEUE_LOG_RETRY_SECONDS = 0.05
_QUEUE_LOG_TAIL_BYTES = 2 * 1024 * 1024
_POSTED_TASK_PATTERN = re.compile(
    rb"Calling post_task: entry=([^,\r\n]+), override=.*?"
    rb"post_task returned task_id: (\d+)",
    re.DOTALL,
)


def _has_queued_game_task_from_log(current_task_id: int) -> bool:
    """Read MXU's completed task submissions without probing invalid Maa IDs."""

    deadline = time.monotonic() + _QUEUE_LOG_WAIT_SECONDS
    while True:
        try:
            with _MXU_LOG_PATH.open("rb") as log_file:
                log_file.seek(0, 2)
                size = log_file.tell()
                log_file.seek(max(0, size - _QUEUE_LOG_TAIL_BYTES))
                content = log_file.read()
            posted = [
                (match.group(1).decode("utf-8", errors="replace"), int(match.group(2)))
                for match in _POSTED_TASK_PATTERN.finditer(content)
            ]
            current_index = max(
                (
                    index
                    for index, (_, task_id) in enumerate(posted)
                    if task_id == current_task_id
                ),
                default=None,
            )
            if current_index is not None and any(
                entry in _GAME_TASK_ENTRIES
                for entry, _ in posted[current_index + 1 :]
            ):
                return True
        except (OSError, TypeError, ValueError):
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(_QUEUE_LOG_RETRY_SECONDS)


@AgentServer.tasker_sink()
class ProgressMonitorLifecycle(TaskerEventSink):
    """Report natural completion, then stop Telegram with the UI task."""

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ) -> None:
        if detail.entry not in _GAME_TASK_ENTRIES:
            if (
                detail.entry == "ProgressMonitorEntry"
                and noti_type == NotificationType.Failed
            ):
                if telegram_bot.stop():
                    print(
                        "[进度监控] 独立监控已由 UI 停止，Telegram 监听已停止",
                        flush=True,
                    )
            return
        if noti_type not in {NotificationType.Succeeded, NotificationType.Failed}:
            return
        final_message = (
            telegram_bot.format_task_completed_message()
            if noti_type == NotificationType.Succeeded
            else None
        )
        if telegram_bot.stop(final_message=final_message):
            print("[进度监控] UI 任务已结束，Telegram 监听已停止", flush=True)


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
            queued_game_task = _has_queued_game_task_from_log(
                argv.task_detail.task_id
            )
        except (AttributeError, TypeError, ValueError):
            queued_game_task = False
        if enabled and not queued_game_task:
            telegram_bot.notify_monitor_started()
        monitor_log_override = {
            "focus": {
                "Node.Action.Succeeded": {
                    "content": content,
                    "display": ["log"],
                }
            }
        }
        if queued_game_task:
            monitor_log_override["next"] = []
        try:
            context.override_pipeline(
                {
                    "ProgressMonitorLog": monitor_log_override
                }
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return CustomAction.RunResult(success=True)
