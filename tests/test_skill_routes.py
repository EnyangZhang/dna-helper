from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def option_case(option: dict, name: str) -> dict:
    return next(case for case in option.get("cases", []) if case.get("name") == name)


class SkillRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        normal = json.loads(
            (ROOT / "assets/resource/tasks/NormalEndlessBoost.json").read_text(
                encoding="utf-8"
            )
        )
        cipher_skill = json.loads(
            (ROOT / "assets/resource/tasks/LiseExpelSkillCast.json").read_text(
                encoding="utf-8"
            )
        )
        cls.normal_options = normal["option"]
        cls.cipher_skill_options = cipher_skill["option"]

    def test_normal_expel_high_platform_bypasses_disabled_delay(self) -> None:
        high_platform = self.normal_options["NormalLiseHighPlatformOnly"]
        enabled = option_case(high_platform, "Yes")["pipeline_override"]
        disabled = option_case(high_platform, "No")["pipeline_override"]

        self.assertFalse(enabled["LiseCombatLoadDelay"]["enabled"])
        for hud_node in ("NormalOutsideCombatHudReady", "NormalRestartCombatHudReady"):
            self.assertEqual(enabled[hud_node]["next"], ["NormalExpelCombatEntry"])
            self.assertEqual(disabled[hud_node]["next"], ["LiseCombatLoadDelay"])

    def test_cipher_high_platform_keeps_combat_entry_fallback(self) -> None:
        high_platform = self.cipher_skill_options["LiseHighPlatformOnly"]
        enabled = option_case(high_platform, "Yes")["pipeline_override"]

        self.assertFalse(enabled["LiseCombatLoadDelay"]["enabled"])
        self.assertEqual(
            enabled["CipherExpelCombatEntry"]["next"],
            ["RewardConfirmByClick", "LiseHighPlatformWindowStart"],
        )


if __name__ == "__main__":
    unittest.main()
