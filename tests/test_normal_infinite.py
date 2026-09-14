from __future__ import annotations

import copy
import json
import queue
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

import progress_monitor  # noqa: E402
import telegram_bot  # noqa: E402
from maa.event_sink import NotificationType  # noqa: E402


STOP = "NormalInfiniteAgainDetected"
WAIT_PHASES = {
    "NormalEndlessEntry": ["NormalEndlessMonitor"],
    "NormalEndlessMonitor": [
        "NormalEndlessContinueChallenge", "NormalEndlessConfirmChoice", "NormalEndlessIdle"
    ],
    "NormalEndlessContinueChallengeClick3Finalize": ["NormalContinueTransition"],
    "NormalContinueTransition": ["NormalEndlessConfirmChoice", "NormalEndlessMonitor"],
    "NormalEndlessConfirmChoiceClick3Finalize": ["NormalEndlessMonitor"],
    "NormalEndlessIdle": ["NormalEndlessMonitor"],
}


def merge(target: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def reachable(pipeline: dict, entry: str) -> set[str]:
    visited = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in visited or not pipeline[name].get("enabled", True):
            continue
        visited.add(name)
        for field in ("next", "on_error"):
            pending.extend(pipeline[name].get(field, []))
    return visited


class NormalInfiniteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = {}
        for path in (ROOT / "assets/resource/base/pipeline").glob("*.json"):
            cls.base.update(json.loads(path.read_text(encoding="utf-8")))
        task = json.loads(
            (ROOT / "assets/resource/tasks/NormalEndlessBoost.json").read_text(encoding="utf-8")
        )
        cls.cases = {case["name"]: case for case in task["option"]["NormalMode"]["cases"]}
        cls.infinite = copy.deepcopy(cls.base)
        merge(cls.infinite, cls.cases["Infinite"]["pipeline_override"])

    def test_every_wait_phase_prioritizes_again_and_preserves_fallbacks(self) -> None:
        for name, fallbacks in WAIT_PHASES.items():
            with self.subTest(phase=name):
                self.assertEqual(self.infinite[name]["next"], [STOP, *fallbacks])
                # Each immediate fallback is DirectHit; stop recognition must precede it.
                self.assertEqual(self.infinite[name]["rate_limit"], 0)
                self.assertEqual(self.infinite[name]["pre_delay"], 0)
                self.assertEqual(self.infinite[name]["post_delay"], 50 if name.endswith("Idle") else 0)

    def test_again_is_a_zero_delay_terminal_without_click_or_counter_event(self) -> None:
        stop = self.infinite[STOP]
        self.assertTrue(stop["enabled"])
        self.assertEqual(stop["recognition"], self.base["CipherEndlessAgainDetected"]["recognition"])
        self.assertEqual(stop["action"], {"type": "StopTask"})
        self.assertEqual([stop[field] for field in ("rate_limit", "pre_delay", "post_delay")], [0, 0, 0])
        self.assertEqual(reachable(self.infinite, STOP), {STOP})
        self.assertNotIn("next", stop)
        self.assertNotIn("on_error", stop)

    def test_infinite_reachable_graph_excludes_quota_restart_hud_and_skill_routes(self) -> None:
        expected = set(WAIT_PHASES) | {STOP}
        for prefix in ("NormalEndlessContinueChallenge", "NormalEndlessConfirmChoice"):
            expected.update((prefix, prefix + "Click2", prefix + "Click3"))
        self.assertEqual(reachable(self.infinite, "NormalEndlessEntry"), expected)

    def test_click_triples_focus_finalizers_and_progress_events_are_unchanged(self) -> None:
        for prefix, target, event in (
            ("NormalEndlessContinueChallenge", [900, 500], "continue_challenge"),
            ("NormalEndlessConfirmChoice", [640, 505], None),
        ):
            names = (prefix, prefix + "Click2", prefix + "Click3")
            for index, name in enumerate(names):
                with self.subTest(node=name):
                    node = self.infinite[name]
                    self.assertEqual(node, self.base[name])
                    self.assertEqual(node["recognition"]["type"], "TemplateMatch" if index == 0 else "DirectHit")
                    self.assertEqual(node["action"], {"type": "Click", "param": {"target": target}})
                    self.assertEqual(node["post_delay"], 50 if index < 2 else 0)
                    self.assertEqual(node["next"], [names[index + 1] if index < 2 else prefix + "Click3Finalize"])
            finalizer = self.infinite[prefix + "Click3Finalize"]
            self.assertEqual(finalizer["action"], self.base[prefix + "Click3Finalize"]["action"])
            params = finalizer["action"]["param"]
            self.assertEqual(params["custom_action"], "focus_guard_finalize")
            self.assertEqual(params["custom_action_param"].get("progress_event"), event)
        self.assertEqual(
            self.infinite["NormalEndlessEntry"]["action"]["param"]["custom_action_param"],
            {"progress_mode": "普通无尽", "progress_total": 0, "progress_stage_total": 0},
        )

    def test_stop_is_disabled_and_unreferenced_outside_infinite_mode(self) -> None:
        self.assertFalse(self.base[STOP]["enabled"])
        for name, node in self.base.items():
            with self.subTest(base_node=name):
                self.assertNotIn(STOP, json.dumps(node))
        for mode in ("Endless", "Expel"):
            pipeline = copy.deepcopy(self.base)
            merge(pipeline, self.cases[mode]["pipeline_override"])
            self.assertNotIn(STOP, reachable(pipeline, "NormalEndlessEntry"))
            self.assertEqual(pipeline["NormalEndlessAgainDetected"]["action"]["type"], "DoNothing")
            self.assertEqual(
                pipeline["NormalEndlessAgainDetected"]["next"],
                ["NormalEndlessRestartQuota" if mode == "Endless" else "NormalExpelRoundQuota"],
            )
        # Check all task and nested option overrides, not only default mode graphs.
        for path in (ROOT / "assets/resource/tasks").rglob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "NormalEndlessBoost.json":
                for case in data["option"]["NormalMode"]["cases"]:
                    if case["name"] == "Infinite":
                        case.pop("pipeline_override")
            with self.subTest(task_file=path.name):
                self.assertNotIn(STOP, json.dumps(data))

    def test_success_uses_existing_completion_sender_once_and_stops_monitor(self) -> None:
        state = {"mode": "普通无尽", "stage_count": 99, "completed_rounds": 0}
        stop_event = threading.Event()
        with (
            patch.object(telegram_bot, "_config", {"token": "test", "chat_id": 123}),
            patch.object(telegram_bot, "_stop_event", stop_event),
            patch.object(telegram_bot, "_owner_id", None),
            patch.object(telegram_bot, "_outbound", queue.Queue()),
            patch.object(telegram_bot, "_send_final_message_async") as send,
            patch.object(telegram_bot.progress_state, "snapshot", return_value=state),
            patch.object(telegram_bot.progress_state, "reset") as reset,
            patch("builtins.print"),
        ):
            lifecycle = progress_monitor.ProgressMonitorLifecycle()
            detail = SimpleNamespace(entry="NormalEndlessEntry")
            lifecycle.on_tasker_task(None, NotificationType.Succeeded, detail)
            self.assertTrue(stop_event.is_set())
            self.assertIsNone(telegram_bot._config)
            send.assert_called_once_with(
                {"token": "test", "chat_id": 123},
                "DNA Helper 任务已完成\n任务：普通无尽加速\n模式：无尽",
            )
            reset.assert_called_once_with()
            lifecycle.on_tasker_task(None, NotificationType.Succeeded, detail)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(state, {"mode": "普通无尽", "stage_count": 99, "completed_rounds": 0})

    def test_no_monitor_or_failed_task_does_not_send_completion(self) -> None:
        for active, notification in (
            (False, NotificationType.Succeeded),
            (True, NotificationType.Failed),
        ):
            with (
                self.subTest(active=active, notification=notification),
                patch.object(telegram_bot, "_config", {"token": "test"} if active else None),
                patch.object(telegram_bot, "_stop_event", threading.Event()),
                patch.object(telegram_bot, "_owner_id", None),
                patch.object(telegram_bot, "_outbound", queue.Queue()),
                patch.object(telegram_bot, "_send_final_message_async") as send,
                patch.object(telegram_bot.progress_state, "snapshot", return_value={"mode": "普通无尽"}),
                patch.object(telegram_bot.progress_state, "reset"),
                patch("builtins.print"),
            ):
                progress_monitor.ProgressMonitorLifecycle().on_tasker_task(
                    None, notification, SimpleNamespace(entry="NormalEndlessEntry")
                )
                send.assert_not_called()
                self.assertTrue(telegram_bot._stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
