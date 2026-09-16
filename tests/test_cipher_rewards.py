from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.assertNotIn("selected_slots", page)
        self.assertIsNone(rewards.recognize_reward(self.original, "ready")[0])
        box, _ = rewards.recognize_reward(self.original, "select", 2)
        self.assertEqual(box, (635, 514, 10, 10))

    def test_target_can_occupy_any_slot_and_selection_marks_are_ignored(self):
        for slot in (1, 2, 3):
            with self.subTest(slot=slot):
                image = self.choose(self.red_at(slot), 1 if slot != 1 else 3)
                self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [slot])
                self.assertEqual(rewards.recognize_reward(image, "ready")[0] is not None, slot == 1)
                for candidate in (1, 2, 3):
                    box, _ = rewards.recognize_reward(image, "select", candidate)
                    self.assertEqual(box is not None, candidate == slot and slot != 1)
                selected = self.choose(image, slot)
                self.assertEqual(rewards.recognize_reward(selected, "ready")[0] is not None, slot == 1)
                self.assertEqual(rewards.recognize_reward(selected, "select", slot)[0] is not None, slot != 1)

    def test_no_red_preserves_any_currently_selected_default(self):
        for slot in (1, 2, 3):
            image = self.choose(self.without_red(), slot)
            self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [])
            self.assertIsNotNone(rewards.recognize_reward(image, "ready")[0])
            self.assertTrue(all(rewards.recognize_reward(image, "select", i)[0] is None for i in (1, 2, 3)))

    def test_no_red_fallback_does_not_require_card_headers_title_or_check(self):
        image = self.choose(self.without_red(), None)
        for cx in rewards.SLOT_CENTERS:
            image[270:312, cx - 22:cx + 22] = 0
        image[155:190, 590:695] = 0
        box, detail = rewards.recognize_reward(image, "page")
        self.assertIsNotNone(box)
        self.assertEqual(detail["red_slots"], [])
        self.assertNotIn("card_layout", detail)
        self.assertEqual(rewards.recognize_reward(image, "ready")[0], (610, 602, 20, 10))
        for slot in (1, 2, 3):
            self.assertIsNone(rewards.recognize_reward(image, "select", slot)[0])

    def test_red_target_ignores_all_titles_headers_and_selection_marks(self):
        for slot, cx in enumerate(rewards.SLOT_CENTERS, 1):
            image = self.original.copy()
            image[270:312, cx - 22:cx + 22] = 0
            with self.subTest(missing_header=slot):
                self.assertIsNone(rewards.recognize_reward(image, "ready")[0])
                self.assertIsNotNone(rewards.recognize_reward(image, "select", 2)[0])
                self.assertIsNotNone(rewards.recognize_reward(self.choose(image, 2), "select", 2)[0])
        for roi in ((590, 155, 105, 35),):
            image = self.original.copy()
            x, y, w, h = roi
            image[y:y + h, x:x + w] = 0
            self.assertIsNone(rewards.recognize_reward(image, "ready")[0])
            self.assertIsNotNone(rewards.recognize_reward(image, "select", 2)[0])
            self.assertIsNotNone(rewards.recognize_reward(self.choose(image, 2), "select", 2)[0])
        self.assertIsNone(rewards.recognize_reward(self.choose(self.original, None), "ready")[0])

    def test_all_red_combinations_choose_leftmost_and_only_select_slots_two_or_three(self):
        for mask in range(8):
            image = self.without_red()
            red_slots = [slot for slot in (1, 2, 3) if mask & (1 << (slot - 1))]
            for slot in red_slots:
                cx = rewards.SLOT_CENTERS[slot - 1]
                image[352:430, cx - 38:cx + 38] = self.original[352:430, 602:678]
            target = red_slots[0] if red_slots else None
            # Gold/rarity styling must never be used as selection evidence.
            image[155:190, 590:695] = 0
            for cx in rewards.SLOT_CENTERS:
                image[270:312, cx - 22:cx + 22] = 0
            for selected in (None, 1, 2, 3):
                with self.subTest(red=red_slots, selected=selected):
                    frame = self.choose(image, selected)
                    box, detail = rewards.recognize_reward(frame, "ready")
                    self.assertEqual(detail["red_slots"], red_slots)
                    self.assertEqual(detail["target_slot"], target)
                    ready = target in (None, 1)
                    self.assertEqual(box is not None, ready)
                    for slot in (1, 2, 3):
                        self.assertEqual(rewards.recognize_reward(frame, "select", slot)[0] is not None,
                                         not ready and slot == target)
                    expected = "CipherEndlessRewardConfirm" if ready else f"CipherEndlessRewardSelect{target}"
                    self.assertEqual(self.reward_decision_after_loading(lambda ms: frame), (1000, expected))

    def test_runtime_no_longer_requires_rarity_sensitive_templates(self):
        self.assertEqual(set(rewards.TEMPLATE_NAMES),
                         {"confirm_choice.png", "reward_red_cube.png"})
        self.assertNotIn("CipherEndlessRewardSelect1", self.pipeline)

    def test_missing_confirm_button_never_falls_back_even_without_red(self):
        for frame in (self.original, self.without_red()):
            image = frame.copy()
            image[520:650, 500:800] = 0
            self.assertIsNone(rewards.inspect_reward_page(image))
            for mode in ("page", "ready", "select"):
                self.assertIsNone(rewards.recognize_reward(image, mode, 2)[0])

    def test_no_red_and_missing_check_progresses_through_enabled_pipeline(self):
        graph = copy.deepcopy(self.pipeline)
        enabled = next(case for case in self.task["option"]["CipherEndlessRedReward"]["cases"] if case["name"] == "Yes")
        merge(graph, enabled["pipeline_override"])
        image = self.choose(self.without_red(), None)
        for name in ("CipherEndlessRewardPage", "CipherEndlessRewardConfirm"):
            self.assertTrue(graph[name].get("enabled", True))
            params = graph[name]["recognition"]["param"]["custom_recognition_param"]
            self.assertIsNotNone(rewards.recognize_reward(image, **params)[0])
        self.assertIn("CipherEndlessRewardConfirm", graph["CipherEndlessRewardPage"]["next"])
        self.assertEqual(graph["CipherEndlessRewardConfirm"]["next"], ["CipherEndlessRewardConfirmClick2"])

    def reward_decision_after_loading(self, frame_at):
        """Model Pipeline post_delay then fresh-frame candidate recognition (no input)."""
        gate = self.pipeline["CipherEndlessRewardPage"]
        self.assertEqual(gate["action"], {"type": "DoNothing"})
        self.assertEqual(gate["pre_delay"], 0)
        self.assertIsNotNone(rewards.recognize_reward(frame_at(0), "page")[0])
        elapsed = gate["post_delay"]
        self.assertEqual(gate["next"][0], "CipherEndlessAgainDetected")
        for name in gate["next"][1:]:
            node = self.pipeline[name]
            recognition = node["recognition"]
            if recognition["type"] == "DirectHit":
                return elapsed, name
            params = recognition["param"]["custom_recognition_param"]
            if rewards.recognize_reward(frame_at(elapsed), **params)[0] is not None:
                return elapsed, name
        self.fail("Missing safe wait candidate")

    def test_late_red_reward_is_selected_instead_of_confirming_early_frame(self):
        early = self.without_red()
        for appears_at in (100, 500, 900):
            elapsed, decision = self.reward_decision_after_loading(
                lambda ms: early if ms < appears_at else self.original
            )
            self.assertEqual(decision, "CipherEndlessRewardSelect2")
            self.assertEqual(elapsed, 1000)

    def test_no_red_still_confirms_default_after_loading_grace(self):
        image = self.choose(self.without_red(), None)
        elapsed, decision = self.reward_decision_after_loading(lambda ms: image)
        self.assertEqual(elapsed, 1000)
        self.assertEqual(decision, "CipherEndlessRewardConfirm")
        # The disabled-option legacy route has no loading delay added.
        self.assertEqual(self.pipeline["CipherEndlessRewardDefault"]["pre_delay"], 0)
        self.assertEqual(self.pipeline["CipherEndlessRewardDefault"]["post_delay"], 50)

    def test_page_disappears_during_loading_without_clicking_stale_result(self):
        elapsed, decision = self.reward_decision_after_loading(
            lambda ms: self.without_red() if ms == 0 else np.zeros_like(self.original)
        )
        self.assertEqual(elapsed, 1000)
        self.assertEqual(decision, "CipherEndlessRewardWait")

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

    def test_diagnostics_explain_leftmost_selection_without_title_or_header_gates(self):
        missing_header = self.original.copy()
        missing_header[270:312, 618:662] = 0
        ambiguous = self.original.copy()
        ambiguous[352:430, 418:494] = self.original[352:430, 602:678]
        for image, expected in (
            (self.original, "点击第 2 张后直接确认，不检查勾选"),
            (self.choose(self.original, 2), "点击第 2 张后直接确认，不检查勾选"),
            (self.without_red(), "未发现红色目标，允许确认默认奖励"),
            (ambiguous, "最左红色在第 1 张，直接确认"),
            (missing_header, "点击第 2 张后直接确认，不检查勾选"),
        ):
            with self.subTest(expected=expected), patch("builtins.print") as output:
                box, detail = rewards.recognize_reward(image, "ready")
                rewards.RewardRecognitionLog().emit(1, "ready", box, detail)
                line = output.call_args.args[0]
                for text in (expected, "红色=", "确认按钮=", "阈值0.85"):
                    self.assertIn(text, line)
                self.assertNotIn("标题", line)
                self.assertNotIn("编号", line)
                self.assertNotIn("勾选=", line)
                self.assertNotIn("已点击", line)

    def test_diagnostics_suppress_score_jitter_but_refresh_stuck_page_every_ten_seconds(self):
        logger = rewards.RewardRecognitionLog()
        box, detail = rewards.recognize_reward(self.original, "ready")
        with patch.object(rewards.time, "monotonic", return_value=100.0) as clock, patch("builtins.print") as output:
            logger.emit(1, "ready", box, detail)
            jitter = copy.deepcopy(detail)
            jitter["red_scores"][0] += 0.001
            clock.return_value = 109.9
            logger.emit(1, "ready", box, jitter)
            self.assertEqual(output.call_count, 1)
            clock.return_value = 110.0
            logger.emit(1, "ready", box, jitter)
            self.assertEqual(output.call_count, 2)
            changed_box, changed = rewards.recognize_reward(self.red_at(3), "ready")
            logger.emit(1, "ready", changed_box, changed)
            self.assertEqual(output.call_count, 3)
            logger.emit(2, "ready", changed_box, changed)
            self.assertEqual(output.call_count, 4)

    def test_diagnostics_skip_pre_wait_page_result_and_duplicate_select_candidates(self):
        logger = rewards.RewardRecognitionLog()
        with patch("builtins.print") as output:
            box, detail = rewards.recognize_reward(self.without_red(), "page")
            logger.emit(1, "page", box, detail)
            for slot in (1, 2, 3):
                box, detail = rewards.recognize_reward(self.original, "select", slot)
                logger.emit(1, "select", box, detail)
            output.assert_not_called()
            box, detail = rewards.recognize_reward(self.original, "ready")
            logger.emit(1, "ready", box, detail)
            self.assertIn("点击第 2 张后直接确认", output.call_args.args[0])

    def test_diagnostics_report_missing_page_only_once_until_decision_changes(self):
        logger = rewards.RewardRecognitionLog()
        box, detail = rewards.recognize_reward(np.zeros_like(self.original), "page")
        self.assertIsNone(box)
        self.assertEqual(detail["reason"], "confirm_not_matched")
        with patch.object(rewards.time, "monotonic", return_value=0.0) as clock, patch("builtins.print") as output:
            logger.emit(1, "page", box, detail)
            self.assertIn("确认按钮未命中", output.call_args.args[0])
            clock.return_value = 10000.0
            logger.emit(1, "page", box, detail)
            logger.emit(1, "ready", box, detail)
            self.assertEqual(output.call_count, 1)

    def test_diagnostics_report_bad_frames_and_missing_templates(self):
        with patch("builtins.print") as output:
            box, detail = rewards.recognize_reward(None, "page")
            rewards.RewardRecognitionLog().emit(1, "page", box, detail)
            self.assertIn("画面尺寸/类型无效", output.call_args.args[0])
            with patch.object(rewards, "_templates", return_value={}):
                box, detail = rewards.recognize_reward(self.original, "page")
            rewards.RewardRecognitionLog().emit(1, "page", box, detail)
            self.assertIn("模板缺失", output.call_args.args[0])
            self.assertIn("reward_red_cube.png", output.call_args.args[0])

    def test_callback_logging_preserves_recognition_even_if_ui_pipe_is_closed(self):
        for image in (self.original, self.choose(self.original, 2), self.without_red()):
            box, detail = rewards.recognize_reward(image, "ready")
            argv = SimpleNamespace(image=image, custom_recognition_param='{"mode":"ready"}',
                                   task_detail=SimpleNamespace(task_id=123))
            with patch.object(rewards, "_recognition_log", rewards.RewardRecognitionLog()), patch("builtins.print", side_effect=OSError):
                result = rewards.CipherRewardRecognition().analyze(None, argv)
            self.assertEqual(result.box, list(box) if box else None)
            self.assertEqual(result.detail, detail)

    def test_red_outside_cards_is_ignored_and_first_red_confirms_directly(self):
        image = self.without_red()
        image[100:178, 100:176] = self.original[352:430, 602:678]
        self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [])
        image = self.original.copy()
        image[352:430, 418:494] = self.original[352:430, 602:678]
        self.assertEqual(rewards.inspect_reward_page(image)["red_slots"], [1, 2])
        self.assertEqual(rewards.recognize_reward(image, "ready")[0], (610, 602, 20, 10))
        for slot in (1, 2, 3):
            self.assertIsNone(rewards.recognize_reward(image, "select", slot)[0])
        elapsed, decision = self.reward_decision_after_loading(lambda ms: image)
        self.assertEqual((elapsed, decision), (1000, "CipherEndlessRewardConfirm"))

    def test_all_three_triples_are_native_50ms_with_input_free_finalize(self):
        for prefix, target in [(f"CipherEndlessRewardSelect{i}", [rewards.SLOT_CENTERS[i - 1], 519]) for i in (2, 3)] + [("CipherEndlessRewardConfirm", [620, 607])]:
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

    def test_page_retry_can_reselect_without_progress_mutation(self):
        for _ in range(3):
            # The same unchanged frame still requires selection, never confirmation.
            self.assertIsNone(rewards.recognize_reward(self.original, "ready")[0])
            self.assertIsNotNone(rewards.recognize_reward(self.original, "select", 2)[0])
        for name, node in self.pipeline.items():
            if name.startswith("CipherEndlessReward"):
                self.assertNotIn("progress_event", json.dumps(node))
                self.assertNotIn("progress_total", json.dumps(node))
        self.assertEqual(self.pipeline["RewardConfirmThirdPageClick3Finalize"]["action"]["param"]["custom_action_param"]["progress_event"], "cipher_cycle_completed")

    def test_after_selection_uses_button_only_and_shared_native_confirmation_chain(self):
        name = "CipherEndlessRewardConfirmAfterSelect"
        node = self.pipeline[name]
        self.assertEqual(node["recognition"], self.pipeline["CipherEndlessRewardDefault"]["recognition"])
        self.assertEqual(node["action"], {"type": "Click", "param": {"target": [620, 607]}})
        self.assertEqual([node[k] for k in ("rate_limit", "pre_delay", "post_delay")], [0, 0, 50])
        self.assertEqual(node["next"], ["CipherEndlessRewardConfirmClick2"])
        self.assertNotIn(name, self.pipeline["CipherEndlessRewardPage"]["next"])
        for slot in (2, 3):
            finalize = self.pipeline[f"CipherEndlessRewardSelect{slot}Click3Finalize"]
            self.assertEqual(finalize["next"], ["CipherEndlessAgainDetected", name, "CipherEndlessRewardWait"])
            # A cursor hiding the check and even the reward icon cannot block confirmation.
            frame = self.red_at(slot)
            frame[260:545, 375:905] = 0
            params = node["recognition"]["param"]
            template = rewards._templates()["confirm_choice.png"]
            self.assertGreaterEqual(rewards._score(frame, template, params["roi"]), params["threshold"])
            frame[590:650, 500:800] = 0
            self.assertLess(rewards._score(frame, template, params["roi"]), params["threshold"])

    def test_check_occlusion_never_affects_red_recognition_or_target_decision(self):
        for slot in (2, 3):
            original = self.red_at(slot)
            hidden = original.copy()
            for cx in rewards.SLOT_CENTERS:
                hidden[498:540, cx - 22:cx + 22] = 0
            with patch.object(rewards, "_score", wraps=rewards._score) as score:
                result = rewards.recognize_reward(hidden, "select", slot)
                self.assertEqual(score.call_count, 4)  # Confirm plus three icons, no check ROIs.
            self.assertEqual(result, rewards.recognize_reward(original, "select", slot))

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
