"""Write the actual normal-endless round number into the MXU task log."""

from __future__ import annotations

import json

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

import progress_state


@AgentServer.custom_action("normal_endless_log_round")
class NormalEndlessRoundLogger(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        total = max(1, int(params.get("total", 1)))
        current = max(1, context.get_hit_count("NormalEndlessRestartQuota"))
        progress_state.complete_round(current, total, "普通扼守")
        content = f"[普通扼守] 已完成第 {current} / {total} 轮（每轮 99 局）"

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
