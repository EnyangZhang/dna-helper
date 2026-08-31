from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import round_logger  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent


class MoonHunterAFKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = json.loads(
            (
                ROOT / "assets/resource/base/pipeline/MoonHunterAFK.json"
            ).read_text(encoding="utf-8")
        )

    def test_entry_classifies_restart_and_combat_hud_only(self) -> None:
        self.assertEqual(
            self.pipeline["MoonHunterAFKInitialMonitor"]["next"],
            [
                "MoonHunterAFKCompletedRestart",
                "MoonHunterAFKCombatHudFrame1",
                "MoonHunterAFKInitialMonitor",
            ],
        )
        self.assertEqual(
            self.pipeline["MoonHunterAFKCompletedRestart"]["recognition"]["param"],
            {
                "template": "MoonHunterAFK/restart.png",
                "roi": [420, 580, 250, 90],
                "threshold": 0.8,
            },
        )

    def test_hud_confirmation_runs_opening_then_repeats_e_until_restart(self) -> None:
        self.assertEqual(
            self.pipeline["MoonHunterAFKCombatHudReady"]["next"],
            ["MoonHunterAFKCombatSequence"],
        )
        sequence = self.pipeline["MoonHunterAFKCombatSequence"]
        self.assertEqual(sequence["pre_delay"], 3000)
        self.assertEqual(
            sequence["action"]["param"],
            {
                "custom_action": "focus_guard_action",
                "custom_action_param": {
                    "kind": "input_sequence",
                    "steps": [
                        {"mouse_down": "left"},
                        {"delay_ms": 300},
                        {"mouse_up": "left"},
                        {"delay_ms": 300},
                        {"mouse_down": "left"},
                        {"delay_ms": 300},
                        {"mouse_up": "left"},
                        {"delay_ms": 300},
                        {"mouse_down": "left"},
                        {"delay_ms": 300},
                        {"mouse_up": "left"},
                        {"delay_ms": 300},
                        {"delay_ms": 300},
                        {"key_press": 81},
                        {"delay_ms": 3500},
                    ],
                    "skill_input_group": True,
                },
            },
        )
        self.assertEqual(
            self.pipeline["MoonHunterAFKInsideMonitor"]["next"],
            [
                "MoonHunterAFKCompletedRestart",
                "MoonHunterAFKPressE",
            ],
        )
        self.assertEqual(
            self.pipeline["MoonHunterAFKPressE"]["action"]["param"],
            {
                "custom_action": "focus_guard_action",
                "custom_action_param": {
                    "kind": "key",
                    "key": 69,
                    "repeat": 1,
                    "skill_input_group": True,
                    "track_e_sequence": False,
                },
            },
        )
        self.assertEqual(self.pipeline["MoonHunterAFKPressE"]["post_delay"], 300)
        self.assertEqual(
            self.pipeline["MoonHunterAFKCompletedRestart"]["action"],
            {
                "type": "Custom",
                "param": {
                    "custom_action": "skill_input_group_complete",
                    "custom_action_param": {"restore_delay_ms": 100},
                },
            },
        )

    def test_restart_uses_fast_click_chain_and_direct_combat_reentry(self) -> None:
        for first in ("MoonHunterAFKRestart", "MoonHunterAFKRestartRetry"):
            self.assertEqual(
                self.pipeline[first]["action"],
                {"type": "Click", "param": {"target": [540, 630]}},
            )
            self.assertEqual(self.pipeline[first]["post_delay"], 50)
            self.assertEqual(
                self.pipeline[first]["next"], ["MoonHunterAFKRestartClick2"]
            )
        self.assertEqual(
            self.pipeline["MoonHunterAFKRestartMonitor"]["next"],
            [
                "MoonHunterAFKRestartRetry",
                "MoonHunterAFKCombatHudFrame1",
                "MoonHunterAFKRestartMonitor",
            ],
        )

    def test_round_logger_and_decision_use_9999_capable_outer_rounds(self) -> None:
        context = Mock()
        context.override_pipeline.return_value = True
        context.get_hit_count.return_value = 2
        argv = SimpleNamespace(custom_action_param={"total": 9999})

        with patch.object(round_logger.progress_state, "complete_round") as complete:
            result = round_logger.MoonHunterAFKRoundLogger().run(context, argv)

        self.assertTrue(result.success)
        complete.assert_called_once_with(2, 9999, "狩月人之阶挂机")
        content = context.override_pipeline.call_args.args[0][
            "MoonHunterAFKRoundLog"
        ]["focus"]["Node.Action.Succeeded"]["content"]
        self.assertEqual(content, "[狩月人之阶挂机] 已完成第 2 / 9999 次副本")

        self.assertTrue(
            round_logger.MoonHunterAFKRoundDecision().run(context, argv).success
        )
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {"MoonHunterAFKRoundDecision": {"next": ["MoonHunterAFKRestart"]}},
        )
        context.get_hit_count.return_value = 9999
        self.assertTrue(
            round_logger.MoonHunterAFKRoundDecision().run(context, argv).success
        )
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {"MoonHunterAFKRoundDecision": {"next": ["MoonHunterAFKFinished"]}},
        )


if __name__ == "__main__":
    unittest.main()
