"""Write the actual normal-endless round number into the MXU task log."""

from __future__ import annotations

import json

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

import progress_state
import telegram_bot


@AgentServer.custom_action("normal_endless_log_round")
class NormalEndlessRoundLogger(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("NormalEndlessRestartQuota"))
        completion = progress_state.complete_round(current, total, "普通扼守")
        content = _finite_round_content("普通扼守", completion)
        _notify_early_completion(completion)

        succeeded = context.override_pipeline(
            {
                "NormalEndlessRoundLog": {
                    "focus": {
                        "Node.Action.Succeeded": {
                            "content": content,
                            "display": ["log"],
                        }
                    }
                }
            }
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("normal_endless_decide_restart")
class NormalEndlessRoundDecision(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("NormalEndlessRestartQuota"))
        next_node = (
            "NormalEndlessRestartByClick"
            if current < total
            else "NormalEndlessFinished"
        )
        succeeded = context.override_pipeline(
            {"NormalEndlessRoundDecision": {"next": [next_node]}}
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("normal_expel_log_round")
class NormalExpelRoundLogger(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("NormalExpelRoundQuota"))
        progress_state.complete_round(current, total, "普通驱离")
        content = f"[普通驱离] 已完成第 {current} / {total} 轮"

        succeeded = context.override_pipeline(
            {
                "NormalExpelRoundLog": {
                    "focus": {
                        "Node.Action.Succeeded": {
                            "content": content,
                            "display": ["log"],
                        }
                    }
                }
            }
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("normal_expel_decide_restart")
class NormalExpelRoundDecision(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("NormalExpelRoundQuota"))
        next_node = (
            "NormalEndlessRestartByClick"
            if current < total
            else "NormalExpelFinished"
        )
        succeeded = context.override_pipeline(
            {"NormalExpelRoundDecision": {"next": [next_node]}}
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("cipher_expel_log_round")
class CipherExpelRoundLogger(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("CipherExpelRoundQuota"))
        progress_state.complete_round(current, total, "密函驱离")
        content = f"[密函驱离] 已完成第 {current} / {total} 轮"

        succeeded = context.override_pipeline(
            {
                "CipherExpelRoundLog": {
                    "focus": {
                        "Node.Action.Succeeded": {
                            "content": content,
                            "display": ["log"],
                        }
                    }
                }
            }
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("cipher_expel_decide_restart")
class CipherExpelRoundDecision(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("CipherExpelRoundQuota"))
        next_node = (
            "CipherExpelAgainByClick"
            if current < total
            else "CipherExpelFinished"
        )
        succeeded = context.override_pipeline(
            {"CipherExpelRoundDecision": {"next": [next_node]}}
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("coin_afk_log_round")
class CoinAFKRoundLogger(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("CoinAFKRoundQuota"))
        completion = progress_state.complete_round(current, total, "皎皎币挂机")
        content = _finite_round_content("皎皎币挂机", completion)
        _notify_early_completion(completion)
        succeeded = context.override_pipeline(
            {
                "CoinAFKRoundLog": {
                    "focus": {
                        "Node.Action.Succeeded": {
                            "content": content,
                            "display": ["log"],
                        }
                    }
                }
            }
        )
        return CustomAction.RunResult(success=succeeded)


@AgentServer.custom_action("coin_afk_decide_restart")
class CoinAFKRoundDecision(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("CoinAFKRoundQuota"))
        next_node = "CoinAFKRestartAgain" if current < total else "CoinAFKFinished"
        succeeded = context.override_pipeline(
            {"CoinAFKRoundDecision": {"next": [next_node]}}
        )
        return CustomAction.RunResult(success=succeeded)


def _parse_params(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _finite_round_content(
    mode: str, completion: progress_state.RoundCompletion
) -> str:
    if completion.early:
        return (
            f"[{mode}] 第 {completion.current} / {completion.total} 次副本提前结束，"
            f"实际局内进度 {completion.stage_count} / {completion.stage_total}，已计入完成"
        )
    if completion.stage_tracking_active:
        return f"[{mode}] 已完成第 {completion.current} / {completion.total} 个 99 轮副本"
    return (
        f"[{mode}] 已完成第 {completion.current} / {completion.total} 次副本"
        "（任务从结算页接管，局内进度未观测）"
    )


def _notify_early_completion(completion: progress_state.RoundCompletion) -> None:
    if completion.should_notify_early:
        telegram_bot.notify_early_completion(
            completion.current,
            completion.total,
            completion.stage_count,
            completion.stage_total,
        )
