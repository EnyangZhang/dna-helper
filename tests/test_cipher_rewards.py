from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import cipher_rewards as rewards


def merge(target, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def reachable(pipeline, entry):
    visited, pending = set(), [entry]
    while pending:
        name = pending.pop()
        if name in visited or not pipeline[name].get("enabled", True):
            continue
        visited.add(name)
        for field in ("next", "on_error"):
            pending.extend(pipeline[name].get(field, []))
    return visited


class CipherRewardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = cv2.imread(str(ROOT / "tests/fixtures/cipher_reward_choice.png"))
        cls.pipeline = {}
        for path in (ROOT / "assets/resource/base/pipeline").glob("*.json"):
            cls.pipeline.update(json.loads(path.read_text(encoding="utf-8")))
        cls.task = json.loads((ROOT / "assets/resource/tasks/CipherEndlessBoost.json").read_text(encoding="utf-8"))

    def choose(self, image, slot):
        """Synthetic selection UI, using the supplied real checked/unchecked strips."""
        image = image.copy()
        checked = self.original[500:538, 408:504].copy()
        unchecked = self.original[500:538, 592:688].copy()
        for cx in rewards.SLOT_CENTERS:
            image[500:538, cx - 48:cx + 48] = unchecked
        if slot:
            cx = rewards.SLOT_CENTERS[slot - 1]
            image[500:538, cx - 48:cx + 48] = checked
        return image

    def red_at(self, slot):
        image = self.original.copy()
        if slot != 2:
            cx = rewards.SLOT_CENTERS[slot - 1]
            old = image[352:430, cx - 38:cx + 38].copy()
            image[352:430, cx - 38:cx + 38] = self.original[352:430, 602:678]
            image[352:430, 602:678] = old
        return image

    def without_red(self):
        image = self.original.copy()
        image[352:430, 602:678] = self.original[352:430, 785:861]
        return image

    def test_supplied_image_requires_middle_selection_before_confirmation(self):
        page = rewards.inspect_reward_page(self.original)
        self.assertEqual(page["red_slots"], [2])
        self.assertEqual(page["selected_slots"], [1])
        self.assertIsNone(rewards.recognize_reward(self.original, "ready")[0])
        box, _ = rewards.recognize_reward(self.original, "select", 2)
        self.assertEqual(box, (635, 514, 10, 10))

    def test_target_can_occupy_any_slot_and_selected_state_is_verified(self):
        for slot in (1, 2, 3):
            with self.subTest(slot=slot):
                image = self.choose(self.red_at(slot), 1 if slot != 1 else 3)
                self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [slot])
                self.assertIsNone(rewards.recognize_reward(image, "ready")[0])
                for candidate in (1, 2, 3):
                    box, _ = rewards.recognize_reward(image, "select", candidate)
                    self.assertEqual(box is not None, candidate == slot)
                selected = self.choose(image, slot)
                self.assertIsNotNone(rewards.recognize_reward(selected, "ready")[0])
                self.assertIsNone(rewards.recognize_reward(selected, "select", slot)[0])

    def test_no_red_preserves_any_currently_selected_default(self):
        for slot in (1, 2, 3):
            image = self.choose(self.without_red(), slot)
            self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [])
            self.assertIsNotNone(rewards.recognize_reward(image, "ready")[0])
            self.assertTrue(all(rewards.recognize_reward(image, "select", i)[0] is None for i in (1, 2, 3)))

    def test_partial_page_or_missing_selected_indicator_does_not_confirm(self):
        for slot, cx in enumerate(rewards.SLOT_CENTERS, 1):
            image = self.original.copy()
            image[270:312, cx - 22:cx + 22] = 0
            with self.subTest(missing_header=slot):
                self.assertIsNone(rewards.inspect_reward_page(image))
        for roi in ((590, 155, 105, 35), (500, 520, 300, 130)):
            image = self.original.copy()
            x, y, w, h = roi
            image[y:y + h, x:x + w] = 0
            self.assertIsNone(rewards.inspect_reward_page(image))
        self.assertIsNone(rewards.recognize_reward(self.choose(self.without_red(), None), "ready")[0])

    def test_missing_templates_and_invalid_frames_fail_closed(self):
        with patch.object(rewards, "_templates", return_value={}):
            self.assertIsNone(rewards.inspect_reward_page(self.original))
        for image in (None, np.zeros((720, 1280), np.uint8), np.zeros((720, 1280, 3), np.float32), np.zeros((1080, 1920, 3), np.uint8)):
            self.assertIsNone(rewards.inspect_reward_page(image))

    def test_background_changes_do_not_change_icon_selection(self):
        # Replace only the surrounding scene; preserve the actual UI regions.
        for value in (0, 240):
            image = np.full_like(self.original, value)
            for x, y, w, h in ((375, 260, 530, 280), (590, 155, 105, 35), (500, 590, 300, 60)):
                image[y:y+h, x:x+w] = self.original[y:y+h, x:x+w]
            self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [2])

    def test_red_outside_cards_and_ambiguous_targets_never_select_arbitrarily(self):
        image = self.without_red()
        image[100:178, 100:176] = self.original[352:430, 602:678]
        self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [])
        image = self.original.copy()
        image[352:430, 418:494] = self.original[352:430, 602:678]
        self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [1, 2])
        self.assertIsNone(rewards.recognize_reward(image, "ready")[0])
        for slot in (1, 2, 3):
            self.assertIsNone(rewards.recognize_reward(image, "select", slot)[0])

    def test_all_four_triples_are_native_50ms_with_input_free_finalize(self):
        for prefix, target in [(f"CipherEndlessRewardSelect{i}", [cx, 519]) for i, cx in enumerate(rewards.SLOT_CENTERS, 1)] + [("CipherEndlessRewardConfirm", [620, 607])]:
            names = [prefix, prefix + "Click2", prefix + "Click3"]
            for index, name in enumerate(names):
                node = self.pipeline[name]
                self.assertEqual(node["action"], {"type": "Click", "param": {"target": target}})
                self.assertEqual([node[k] for k in ("rate_limit", "pre_delay", "post_delay")], [0, 0, 50 if index < 2 else 0])
                self.assertEqual(node["next"], [names[index + 1] if index < 2 else name + "Finalize"])
                if index:
                    self.assertEqual(node["recognition"], {"type": "DirectHit"})
            finalize = self.pipeline[prefix + "Click3Finalize"]
            self.assertEqual(finalize["action"]["param"], {"custom_action": "focus_guard_finalize", "custom_action_param": {"restore_delay_ms": 100}})
            self.assertEqual(finalize["next"][0], "CipherEndlessAgainDetected")

    def test_failed_selection_retries_without_confirm_or_progress_mutation(self):
        for _ in range(3):
            # The same unchanged frame still requires selection, never confirmation.
            self.assertIsNone(rewards.recognize_reward(self.original, "ready")[0])
            self.assertIsNotNone(rewards.recognize_reward(self.original, "select", 2)[0])
        for name, node in self.pipeline.items():
            if name.startswith("CipherEndlessReward"):
                self.assertNotIn("progress_event", json.dumps(node))
                self.assertNotIn("progress_total", json.dumps(node))
        self.assertEqual(self.pipeline["RewardConfirmThirdPageClick3Finalize"]["action"]["param"]["custom_action_param"]["progress_event"], "cipher_cycle_completed")

    def test_every_new_wait_keeps_natural_stop_and_original_page_recovery(self):
        for name in ("RewardConfirmEntry", "CipherEndlessRewardPage", "CipherEndlessRewardWait", "CipherEndlessRewardConfirmClick3Finalize", "RewardConfirmWaitContinue"):
            self.assertEqual(self.pipeline[name]["next"][0], "CipherEndlessAgainDetected")
        self.assertEqual(self.pipeline["CipherEndlessAgainDetected"]["action"], {"type": "StopTask"})
        self.assertIn("CipherEndlessRewardPage", self.pipeline["RewardConfirmWaitContinue"]["next"])
        self.assertIn("RewardConfirmContinueChallenge", self.pipeline["CipherEndlessRewardWait"]["next"])
        self.assertNotIn("RewardConfirmByClick", reachable(self.pipeline, "RewardConfirmEntry"))

    def test_expel_and_other_tasks_cannot_reach_reward_selection(self):
        expel_case = next(case for case in self.task["option"]["CipherMode"]["cases"] if case["name"] == "Expel")
        for skills in self.task["option"]["CipherEnableSkills"]["cases"]:
            graph = copy.deepcopy(self.pipeline)
            merge(graph, expel_case["pipeline_override"])
            merge(graph, skills.get("pipeline_override", {}))
            reached = reachable(graph, "RewardConfirmEntry")
            self.assertIn("RewardConfirmByClick", reached)
            self.assertFalse(any(name.startswith("CipherEndlessReward") for name in reached))
        for entry in ("NormalEndlessEntry", "CoinAFKEntry", "MediationAFKEntry", "MoonHunterAFKEntry", "FishingEntry", "TheatreAFKEntry"):
            reached = reachable(self.pipeline, entry)
            self.assertFalse(any(name.startswith("CipherEndlessReward") for name in reached), entry)

    def test_reward_switch_defaults_off_and_is_only_exposed_in_endless(self):
        option = self.task["option"]["CipherEndlessRedReward"]
        self.assertEqual(option["type"], "switch")
        self.assertEqual(option["label"], "优先选择红色方块奖励")
        self.assertEqual(option["default_case"], "No")
        mode = {case["name"]: case for case in self.task["option"]["CipherMode"]["cases"]}
        self.assertEqual(mode["Endless"]["option"], ["CipherEndlessRedReward"])
        self.assertNotIn("CipherEndlessRedReward", mode["Expel"]["option"])
        self.assertNotIn("CipherEndlessRedReward", self.task["task"][0]["option"])
        expected = copy.deepcopy(self.pipeline["RewardConfirmByClick"])
        direct = copy.deepcopy(self.pipeline["CipherEndlessRewardDefault"])
        self.assertTrue(direct.pop("enabled"))
        self.assertEqual(direct, expected)
        self.assertFalse(self.pipeline["CipherEndlessRewardPage"]["enabled"])

    def test_switching_both_directions_restores_exclusive_paths_without_changing_counts(self):
        cases = {case["name"]: case for case in self.task["option"]["CipherEndlessRedReward"]["cases"]}
        graph = copy.deepcopy(self.pipeline)
        for selection in ("No", "Yes", "No", "Yes"):
            with self.subTest(selection=selection):
                merge(graph, cases[selection]["pipeline_override"])
                reached = reachable(graph, "RewardConfirmEntry")
                enabled = selection == "Yes"
                self.assertEqual("CipherEndlessRewardPage" in reached, enabled)
                self.assertEqual("CipherEndlessRewardSelect2" in reached, enabled)
                self.assertEqual("CipherEndlessRewardDefault" in reached, not enabled)
                self.assertNotIn("RewardConfirmByClick", reached)
                self.assertIn("CipherEndlessAgainDetected", reached)
                self.assertIn("RewardConfirmThirdPageClick3Finalize", reached)
                for name in ("CipherEndlessAgainDetected", "RewardConfirmContinueChallenge",
                             "RewardConfirmThirdPageClick3Finalize"):
                    self.assertEqual(graph[name], self.pipeline[name])
                if not enabled:
                    # No title/icon/check recognition may gate the original confirmation.
                    self.assertFalse(any(
                        graph[name].get("recognition", {}).get("param", {}).get("custom_recognition") == "cipher_reward"
                        for name in reached
                    ))

    def test_saved_reward_selection_cannot_modify_expel_even_with_reversed_merge_order(self):
        expel = next(case for case in self.task["option"]["CipherMode"]["cases"] if case["name"] == "Expel")
        for skills in self.task["option"]["CipherEnableSkills"]["cases"]:
            baseline = copy.deepcopy(self.pipeline)
            merge(baseline, expel["pipeline_override"])
            merge(baseline, skills.get("pipeline_override", {}))
            baseline_nodes = reachable(baseline, "RewardConfirmEntry")
            for choice in self.task["option"]["CipherEndlessRedReward"]["cases"]:
                for reverse in (False, True):
                    graph = copy.deepcopy(self.pipeline)
                    overrides = [expel["pipeline_override"], skills.get("pipeline_override", {}),
                                 choice["pipeline_override"]]
                    # Keep skill override after mode, varying only the unrelated reward switch.
                    if reverse:
                        overrides = [overrides[2], overrides[0], overrides[1]]
                    for override in overrides:
                        merge(graph, override)
                    self.assertEqual(reachable(graph, "RewardConfirmEntry"), baseline_nodes)
                    self.assertTrue(all(graph[name] == baseline[name] for name in baseline_nodes))


if __name__ == "__main__":
    unittest.main()
