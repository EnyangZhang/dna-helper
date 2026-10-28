from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from test_normal_acceleration import merge


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets/resource/base/image"
NODE = "NormalEndlessStartChallengeByClick"
LEGACY = "NormalEndlessBoost/start_challenge.png"


class NormalStartTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = cv2.imread(str(ROOT / "reference-screenshots/normal-start-challenge-template-original.png"))
        cls.template = cv2.imread(str(IMAGES / LEGACY))
        cls.sample = cv2.imread(str(ROOT / "tests/fixtures/normal_expel_start_countdown.png"))
        cls.pipeline = json.loads((ROOT / "assets/resource/base/pipeline/NormalEndlessBoost.json").read_text(encoding="utf-8"))
        task = json.loads((ROOT / "assets/resource/tasks/NormalEndlessBoost.json").read_text(encoding="utf-8"))
        cls.cases = {case["name"]: case for case in task["option"]["NormalMode"]["cases"]}

    def score(self, image):
        return cv2.minMaxLoc(cv2.matchTemplate(image, self.template, cv2.TM_CCOEFF_NORMED))[1]

    def test_exact_lossless_crop_of_existing_template_not_new_screenshot(self):
        self.assertEqual(self.old.shape, (33, 135, 3))
        self.assertEqual(self.template.shape, (19, 121, 3))
        np.testing.assert_array_equal(self.template, self.old[7:26, 4:125])
        spec = importlib.util.spec_from_file_location("extract_start", ROOT / "tools/extract_normal_start_template.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.TEXT_BOX, (4, 7, 125, 26))
        self.assertAlmostEqual(self.score(self.old), 1.0, places=6)

    def test_supplied_countdown_screenshot_matches_without_lowering_threshold(self):
        self.assertGreaterEqual(self.score(self.sample), 0.8)
        old_score = cv2.minMaxLoc(cv2.matchTemplate(self.sample, self.old, cv2.TM_CCOEFF_NORMED))[1]
        self.assertGreater(self.score(self.sample), old_score)

    def test_countdown_and_lower_bar_variation_do_not_change_text_match(self):
        expected = self.score(self.sample)
        for color in ((0, 0, 0), (255, 255, 255), (0, 0, 255)):
            with self.subTest(color=color):
                sample = self.sample.copy()
                # The recognized old text is x420:541/y289:308 in this cropped
                # sample; replace only the adjacent countdown and lower bar.
                cv2.rectangle(sample, (542, 285), (610, 309), color, -1)
                cv2.rectangle(sample, (376, 312), (613, 317), color, -1)
                self.assertGreaterEqual(self.score(sample), 0.8)
                self.assertAlmostEqual(self.score(sample), expected, places=5)

    def test_missing_start_text_does_not_match_cancel_or_countdown_alone(self):
        sample = self.sample.copy()
        sample[287:310, 418:542] = 0
        self.assertLess(self.score(sample), 0.8)
        blank = np.zeros_like(self.sample)
        cv2.putText(blank, '(2s)', (420, 302), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255))
        self.assertLess(self.score(blank), 0.8)

    def test_hold_and_expel_keep_shared_node_and_template_without_new_overrides(self):
        for mode in ("Endless", "Infinite", "Expel"):
            with self.subTest(mode=mode):
                current = copy.deepcopy(self.pipeline)
                merge(current, self.cases["Expel"]["pipeline_override"])
                merge(current, self.cases[mode]["pipeline_override"])
                node = current[NODE]
                self.assertEqual(node["recognition"], {
                    "type": "TemplateMatch",
                    "param": {"template": LEGACY, "roi": [650, 430, 350, 100], "threshold": 0.8},
                })
                self.assertNotIn(NODE, self.cases[mode]["pipeline_override"])
                self.assertEqual(node["action"], {"type": "Click", "param": {"target": [770, 490]}})
                self.assertEqual(node["post_delay"], 50)
        self.assertEqual(self.pipeline[NODE]["recognition"]["param"]["template"], LEGACY)

    def test_fast_click_tail_keeps_coords_timing_and_restore(self):
        for name, delay, next_name in (
            (NODE, 50, "NormalEndlessStartChallengeClick2"),
            ("NormalEndlessStartChallengeClick2", 50, "NormalEndlessStartChallengeClick3"),
            ("NormalEndlessStartChallengeClick3", 0, "NormalEndlessStartChallengeClick3Finalize"),
        ):
            node = self.pipeline[name]
            self.assertEqual(node["action"], {"type": "Click", "param": {"target": [770, 490]}})
            self.assertEqual((node["rate_limit"], node["pre_delay"], node["post_delay"]), (0, 0, delay))
            self.assertEqual(node["next"], [next_name])
        self.assertEqual(self.pipeline["NormalEndlessStartChallengeClick3Finalize"]["action"]["param"]["custom_action"], "focus_guard_finalize")

    def test_cipher_coin_and_mediation_use_their_existing_independent_templates(self):
        for path in (ROOT / "assets/resource").rglob("*.json"):
            if path.name != "NormalEndlessBoost.json":
                self.assertNotIn(LEGACY, path.read_text(encoding="utf-8"), str(path))


if __name__ == "__main__":
    unittest.main()
