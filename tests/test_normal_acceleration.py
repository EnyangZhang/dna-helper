from __future__ import annotations

import copy
import itertools
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPTION = "NormalEnableAcceleration"
ENTRIES = {
    "NormalEndlessContinueChallenge",
    "NormalEndlessConfirmChoice",
    "NormalHoldPostSkillContinueChallenge",
    "NormalHoldPostSkillConfirmChoice",
}


def merge(target: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def reachable(pipeline: dict, entry: str, boundaries: set[str] | None = None) -> set[str]:
    visited = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in visited or not pipeline[name].get("enabled", True):
            continue
        visited.add(name)
        if boundaries and name in boundaries:
            continue
        for field in ("next", "on_error"):
            pending.extend(pipeline[name].get(field, []))
    return visited


class NormalAccelerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = {}
        for path in (ROOT / "assets/resource/base/pipeline").glob("*.json"):
            cls.base.update(json.loads(path.read_text(encoding="utf-8")))
        cls.task = json.loads(
            (ROOT / "assets/resource/tasks/NormalEndlessBoost.json").read_text(encoding="utf-8")
        )
        cls.options = {}
        for path in (ROOT / "assets/resource/tasks").rglob("*.json"):
            cls.options.update(json.loads(path.read_text(encoding="utf-8")).get("option", {}))
        cls.switch = cls.options[OPTION]

    def apply_option(self, pipeline: dict, name: str, choices: dict) -> None:
        option = self.options[name]
        merge(pipeline, option.get("pipeline_override", {}))
        if option["type"] == "input":
            return
        selected = choices.get(name, option.get("default_case"))
        case = next(case for case in option["cases"] if case["name"] == selected)
        merge(pipeline, case.get("pipeline_override", {}))
        for child in case.get("option", []):
            self.apply_option(pipeline, child, choices)

    def configured(self, mode: str, *, acceleration: str | None, **choices) -> dict:
        pipeline = copy.deepcopy(self.base)
        choices["NormalMode"] = mode
        if acceleration is not None:
            choices[OPTION] = acceleration
        self.apply_option(pipeline, "NormalMode", choices)
        if acceleration is not None:
            self.apply_option(pipeline, OPTION, choices)
        return pipeline

    def test_switch_is_shared_default_on_and_only_gates_four_inside_entries(self) -> None:
        self.assertEqual(self.task["task"][0]["option"], ["NormalMode", OPTION])
        self.assertEqual(self.switch["type"], "switch")
        self.assertEqual(self.switch["label"], "开启局内加速")
        self.assertEqual(self.switch["default_case"], "Yes")
        self.assertTrue(self.switch["description"])
        for case in self.switch["cases"]:
            self.assertNotIn("option", case)
            self.assertEqual(
                case["pipeline_override"],
                {name: {"enabled": case["name"] == "Yes"} for name in ENTRIES},
            )

    def test_mode_skill_high_platform_and_key_order_do_not_override_switch(self) -> None:
        # Resolve actual nested task options, not only top-level mode overrides.
        for mode, (skills, high, e, q, q_first) in itertools.product(
            ("Endless", "Infinite", "Expel"),
            itertools.product(("No", "Yes"), repeat=5),
        ):
            choices = {
                "NormalHoldEnableSkills": skills, "NormalExpelEnableSkills": skills,
                "NormalLiseHighPlatformOnly": high, "NormalHoldEnableE": e,
                "LiseEnableE": e, "NormalHoldEnableQ": q, "LiseEnableQ": q,
                "LiseEnableQOnly": q, "NormalHoldQBeforeE": q_first,
                "LiseQBeforeE": q_first,
            }
            with self.subTest(mode=mode, skills=skills, high=high, e=e, q=q, q_first=q_first):
                baseline = self.configured(mode, acceleration=None, **choices)
                enabled = self.configured(mode, acceleration="Yes", **choices)
                disabled = self.configured(mode, acceleration="No", **choices)
                for name in ENTRIES:
                    self.assertTrue(enabled[name]["enabled"])
                    self.assertFalse(disabled[name]["enabled"])
                    # Remove only the switch-controlled field; every other byte of
                    # the resolved skill/HUD/restart/timing/progress contract stays.
                    for pipeline in (baseline, enabled, disabled):
                        pipeline[name].pop("enabled", None)
                self.assertEqual(enabled, baseline)
                self.assertEqual(disabled, baseline)

    def test_disabled_entries_make_every_inside_click_and_event_unreachable(self) -> None:
        for mode, skills in itertools.product(("Endless", "Infinite", "Expel"), ("No", "Yes")):
            pipeline = self.configured(
                mode, acceleration="No", NormalHoldEnableSkills=skills,
                NormalExpelEnableSkills=skills,
            )
            nodes = reachable(pipeline, "NormalEndlessEntry")
            for prefix in ENTRIES:
                with self.subTest(mode=mode, skills=skills, prefix=prefix):
                    self.assertTrue(nodes.isdisjoint({
                        prefix, prefix + "Click2", prefix + "Click3",
                        prefix + "Click3Finalize",
                    }))
            if mode == "Infinite":
                self.assertEqual(nodes, {
                    "NormalEndlessEntry", "NormalEndlessMonitor",
                    "NormalEndlessIdle", "NormalInfiniteAgainDetected",
                })
            else:
                self.assertIn("NormalEndlessStartChallengeByClick", nodes)
                self.assertIn("NormalEndlessAgainDetected", nodes)
                self.assertIn("NormalEndlessWaitStartChallenge", nodes)
                if skills == "Yes":
                    self.assertIn("LiseSkillOrderEntry", nodes)

    def test_switch_does_not_hide_skills_or_change_skill_lock_on_hud_recovery(self) -> None:
        boundaries = {"NormalEndlessAgainDetected", "NormalEndlessStartChallengeByClick"}
        for mode, monitor in (
            ("Endless", "NormalHoldPostSkillIdle"),
            ("Expel", "NormalExpelPostSkillInsideIdle"),
        ):
            for acceleration in ("No", "Yes"):
                pipeline = self.configured(
                    mode, acceleration=acceleration, NormalHoldEnableSkills="Yes",
                    NormalExpelEnableSkills="Yes",
                )
                self.assertEqual(pipeline["LiseSkillCastEnd"]["next"], [monitor])
                post_skill = reachable(pipeline, monitor, boundaries)
                self.assertNotIn("LiseSkillOrderEntry", post_skill)
                self.assertNotIn("LiseCombatLoadDelay", post_skill)
                self.assertTrue(boundaries <= post_skill)

    def test_disabled_candidates_fall_back_without_input_or_failed_chain(self) -> None:
        pipeline = self.configured("Endless", acceleration="No", NormalHoldEnableSkills="Yes")

        def choose(parent: str, hits: set[str]) -> str:
            return next(
                name for name in pipeline[parent]["next"]
                if pipeline[name].get("enabled", True)
                and (name in hits or pipeline[name]["recognition"]["type"] == "DirectHit")
            )

        # Even when both buttons are visible, disabled candidates are skipped.
        self.assertEqual(choose("NormalEndlessCombatEntry", ENTRIES), "LiseSkillOrderEntry")
        self.assertEqual(choose("NormalHoldPostSkillMonitor", ENTRIES), "NormalHoldPostSkillIdle")
        self.assertEqual(choose("NormalHoldPostSkillIdle", ENTRIES), "NormalHoldPostSkillIdle")
        self.assertEqual(
            choose("NormalHoldPostSkillIdle", ENTRIES | {"NormalEndlessAgainDetected"}),
            "NormalEndlessAgainDetected",
        )
        for name in ("NormalEndlessIdle", "NormalHoldPostSkillIdle", "NormalExpelInsideIdle"):
            self.assertEqual(pipeline[name]["post_delay"], 50)

    def test_reenabling_restores_original_triples_and_progress_events(self) -> None:
        for mode in ("Endless", "Infinite", "Expel"):
            pipeline = self.configured(mode, acceleration="No", NormalHoldEnableSkills="Yes")
            self.apply_option(pipeline, OPTION, {OPTION: "Yes"})
            fresh = self.configured(mode, acceleration="Yes", NormalHoldEnableSkills="Yes")
            self.assertEqual(pipeline, fresh)
            for prefix in ENTRIES:
                for index, name in enumerate((prefix, prefix + "Click2", prefix + "Click3")):
                    self.assertEqual(pipeline[name]["action"]["type"], "Click")
                    self.assertEqual(pipeline[name]["post_delay"], 50 if index < 2 else 0)
                finalizer = pipeline[prefix + "Click3Finalize"]["action"]["param"]
                self.assertEqual(finalizer["custom_action"], "focus_guard_finalize")
                self.assertEqual(
                    finalizer["custom_action_param"].get("progress_event"),
                    "continue_challenge" if "ContinueChallenge" in prefix else None,
                )

    def test_other_tasks_cannot_select_switch_and_normal_options_cannot_bypass_it(self) -> None:
        for path in (ROOT / "assets/resource/tasks").rglob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.name != "NormalEndlessBoost.json":
                self.assertNotIn(OPTION, json.dumps(data))
        for name, option in self.options.items():
            if name == OPTION:
                continue
            for override in [option.get("pipeline_override", {}), *(
                case.get("pipeline_override", {}) for case in option.get("cases", [])
            )]:
                for node in ENTRIES:
                    self.assertNotIn("enabled", override.get(node, {}), (name, node))


if __name__ == "__main__":
    unittest.main()
