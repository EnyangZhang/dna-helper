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


class MediationAFKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = json.loads(
            (
                ROOT / "assets/resource/base/pipeline/MediationAFK.json"
            ).read_text(encoding="utf-8")
        )

    def test_entry_classifies_again_space_start_and_combat_hud(self) -> None:
        self.assertEqual(
            self.pipeline["MediationAFKEntry"]["next"],
            ["MediationAFKInitialMonitor"],
        )
        self.assertEqual(
            self.pipeline["MediationAFKInitialMonitor"]["next"],
            [
                "MediationAFKCompletedAgain",
                "MediationAFKSpaceStart",
                "MediationAFKCombatHudFrame1",
                "MediationAFKInitialMonitor",
            ],
        )

    def test_hud_confirmation_runs_recorded_input_then_only_monitors_settlement(self) -> None:
        self.assertEqual(
            self.pipeline["MediationAFKCombatHudReady"]["next"],
            ["MediationAFKCombatSequence"],
        )
        action = self.pipeline["MediationAFKCombatSequence"]["action"]["param"]
        self.assertEqual(self.pipeline["MediationAFKCombatSequence"]["pre_delay"], 3000)
        self.assertEqual(action["custom_action"], "focus_guard_action")
        self.assertEqual(
            action["custom_action_param"],
            {
                "kind": "input_sequence",
                "steps": [
                    {"key_down": 87},
                    {"delay_ms": 1300},
                    {"key_up": 87},
                    {"mouse_down": "left"},
                    {"delay_ms": 250},
                    {"mouse_up": "left"},
                    {"delay_ms": 300},
                    {"key_press": 70},
                    {"delay_ms": 300},
                    {"key_press": 70},
                    {"delay_ms": 300},
                    {"key_press": 70},
                    {"delay_ms": 300},
                    {"key_press": 70},
                    {"delay_ms": 300},
                    {"mouse_move": [0, -130]},
                    {"mouse_down": "right"},
                    {"delay_ms": 800},
                    {"mouse_up": "right"},
                    {"delay_ms": 300},
                    {"key_press": 90},
                ],
                "restore_delay_ms": 500,
            },
        )
        self.assertEqual(
            self.pipeline["MediationAFKCombatSequence"]["focus"]
            ["Node.Action.Succeeded"]["content"],
            "[调停挂机] 局内角色操作已完成：W↓ → 1300ms → W↑ → "
            "左键↓ → 250ms → 左键↑ → 300ms → F → 300ms → F → 300ms → "
            "F → 300ms → F → 300ms → 鼠标1秒↑130px → 右键↓ → 800ms → "
            "右键↑ → 300ms → Z",
        )
        self.assertEqual(
            self.pipeline["MediationAFKInsideMonitor"]["next"],
            [
                "MediationAFKInsideGate",
                "MediationAFKCompletedAgain",
                "MediationAFKInsideMonitor",
            ],
        )
        self.assertFalse(
            any(
                word in node_name
                for node_name in self.pipeline
                for word in ("ContinueChallenge", "ConfirmChoice", "TargetMap")
            )
        )

    def test_round_logger_records_completed_dungeon_without_stage_semantics(self) -> None:
        context = Mock()
        context.get_hit_count.return_value = 2
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 3})

        with patch.object(round_logger.progress_state, "complete_round") as complete:
            result = round_logger.MediationAFKRoundLogger().run(context, argv)

        self.assertTrue(result.success)
        complete.assert_called_once_with(2, 3, "调停挂机")
        content = context.override_pipeline.call_args.args[0][
            "MediationAFKRoundLog"
        ]["focus"]["Node.Action.Succeeded"]["content"]
        self.assertEqual(content, "[调停挂机] 已完成第 2 / 3 次副本")

    def test_round_decision_restarts_only_before_total(self) -> None:
        context = Mock()
        context.override_pipeline.return_value = True
        argv = SimpleNamespace(custom_action_param={"total": 3})

        context.get_hit_count.return_value = 2
        self.assertTrue(round_logger.MediationAFKRoundDecision().run(context, argv).success)
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {
                "MediationAFKRoundDecision": {
                    "next": ["MediationAFKRestartAgain"]
                }
            },
        )

        context.get_hit_count.return_value = 3
        self.assertTrue(round_logger.MediationAFKRoundDecision().run(context, argv).success)
        self.assertEqual(
            context.override_pipeline.call_args.args[0],
            {"MediationAFKRoundDecision": {"next": ["MediationAFKFinished"]}},
        )


if __name__ == "__main__":
    unittest.main()
