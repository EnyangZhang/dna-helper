from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "RewardConfirm/space_confirm_choice.png"
NODE = "RewardConfirmThirdPageByClick"


class CipherSpaceTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = cv2.imread(str(ROOT / "reference-screenshots/cipher-space-confirm-template-original.png"))
        cls.template = cv2.imread(str(ROOT / "assets/resource/base/image" / TEMPLATE))
        cls.pipeline = json.loads((ROOT / "assets/resource/base/pipeline/RewardConfirm.json").read_text(encoding="utf-8"))

    def score(self, image):
        return cv2.minMaxLoc(cv2.matchTemplate(image, self.template, cv2.TM_CCOEFF_NORMED))[1]

    def test_exact_lossless_crop_and_reproducible_coordinates(self):
        self.assertEqual(self.original.shape, (33, 134, 3))
        self.assertEqual(self.template.shape, (19, 122, 3))
        np.testing.assert_array_equal(self.template, self.original[6:25, 5:127])
        spec = importlib.util.spec_from_file_location("extract_cipher_space", ROOT / "tools/extract_cipher_space_template.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.TEXT_BOX, (5, 6, 127, 25))

    def test_original_page_without_countdown_still_matches(self):
        self.assertAlmostEqual(self.score(self.original), 1.0, places=6)

    def test_synthetic_countdown_and_bottom_bar_do_not_affect_match(self):
        # Synthetic regression only: no Cipher countdown screenshot was supplied.
        for color in ((255, 255, 255), (0, 0, 255), (0, 0, 0)):
            with self.subTest(color=color):
                image = np.full((100, 260, 3), 25, dtype=np.uint8)
                image[30:63, 40:174] = self.original
                cv2.rectangle(image, (167, 30), (245, 54), color, -1)
                cv2.rectangle(image, (20, 55), (245, 62), color, -1)
                self.assertGreaterEqual(self.score(image), 0.8)
                self.assertAlmostEqual(self.score(image), 1.0, places=6)

    def test_keycap_alone_or_different_text_is_not_confirmation(self):
        keycap = self.original.copy()
        keycap[:, 50:] = 0
        self.assertLess(self.score(keycap), 0.8)
        ordinary = cv2.imread(str(ROOT / "reference-screenshots/normal-start-challenge-template-original.png"))
        self.assertLess(self.score(ordinary), 0.8)
        self.assertLess(self.score(np.zeros((80, 200, 3), dtype=np.uint8)), 0.8)

    def test_shared_recognition_geometry_and_mode_references_unchanged(self):
        self.assertEqual(self.pipeline[NODE]["recognition"], {
            "type": "TemplateMatch",
            "param": {"template": TEMPLATE, "roi": [760, 380, 360, 150], "threshold": 0.8},
        })
        references = [name for name, node in self.pipeline.items()
                      if node.get("recognition", {}).get("param", {}).get("template") == TEMPLATE]
        self.assertEqual(references, [NODE])
        self.assertIn(NODE, self.pipeline["RewardConfirmWaitThird"]["next"])
        self.assertIn(NODE, self.pipeline["CipherExpelRestartMonitor"]["next"])

    def test_native_click_chain_timing_and_no_input_finalizer_unchanged(self):
        for name, delay, next_name in (
            (NODE, 50, "RewardConfirmThirdPageClick2"),
            ("RewardConfirmThirdPageClick2", 50, "RewardConfirmThirdPageClick3"),
            ("RewardConfirmThirdPageClick3", 0, "RewardConfirmThirdPageClick3Finalize"),
        ):
            node = self.pipeline[name]
            self.assertEqual(node["action"], {"type": "Click", "param": {"target": [920, 480]}})
            self.assertEqual((node["rate_limit"], node["pre_delay"], node["post_delay"]), (0, 0, delay))
            self.assertEqual(node["next"], [next_name])
            if name != NODE:
                self.assertEqual(node["recognition"], {"type": "DirectHit"})
        finalizer = self.pipeline["RewardConfirmThirdPageClick3Finalize"]["action"]
        self.assertEqual(finalizer["type"], "Custom")
        self.assertEqual(finalizer["param"]["custom_action"], "focus_guard_finalize")
        self.assertEqual(finalizer["param"]["custom_action_param"]["progress_event"], "cipher_cycle_completed")


if __name__ == "__main__":
    unittest.main()
