from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import fishing  # noqa: E402


class FishingRecognitionTest(unittest.TestCase):
    def setUp(self) -> None:
        fishing._prompt_states.clear()

    def test_white_icon_matching_ignores_changed_scenery_background(self) -> None:
        rng = np.random.default_rng(42)
        screen = rng.integers(0, 120, size=(720, 1280, 3), dtype=np.uint8)
        x, y = 735, 410
        h, w = fishing._template_image.shape[:2]
        target = screen[y : y + h, x : x + w]
        white_pixels = fishing._template_mask > 0
        target[white_pixels] = fishing._template_image[white_pixels]

        score, location = fishing._match_prompt(screen)

        self.assertGreaterEqual(score, 0.90)
        self.assertEqual(location, (x, y))

    def test_e_icon_matching_ignores_changed_scenery_background(self) -> None:
        rng = np.random.default_rng(43)
        screen = rng.integers(0, 120, size=(720, 1280, 3), dtype=np.uint8)
        x, y = 610, 330
        template = fishing._template_images["e"]
        mask = fishing._template_masks["e"] > 0
        h, w = template.shape[:2]
        target = screen[y : y + h, x : x + w]
        target[mask] = template[mask]

        score, location = fishing._match_prompt(screen, "e")

        self.assertGreaterEqual(score, 0.90)
        self.assertEqual(location, (x, y))

    def test_close_text_matching_survives_brightness_change(self) -> None:
        rng = np.random.default_rng(44)
        screen = rng.integers(20, 100, size=(720, 1280, 3), dtype=np.uint8)
        x, y = 480, 210
        template = fishing._template_images["escape"].astype(np.int16)
        changed = np.clip(template - 30, 0, 255).astype(np.uint8)
        h, w = changed.shape[:2]
        screen[y : y + h, x : x + w] = changed

        score, location = fishing._match_prompt(screen, "escape")

        self.assertGreaterEqual(score, 0.80)
        self.assertEqual(location, (x, y))

    def test_changed_scenery_without_icon_does_not_match(self) -> None:
        rng = np.random.default_rng(84)
        screen = rng.integers(0, 150, size=(720, 1280, 3), dtype=np.uint8)
        score, _ = fishing._match_prompt(screen)
        self.assertLess(score, 0.72)

    def test_prompt_retriggers_after_three_seconds_even_if_still_visible(self) -> None:
        self.assertTrue(fishing._accept_after_cooldown(7, True, 3000, now=10.0))
        self.assertFalse(fishing._accept_after_cooldown(7, True, 3000, now=12.999))
        self.assertTrue(fishing._accept_after_cooldown(7, True, 3000, now=13.0))

    def test_prompt_disappearance_does_not_end_cooldown_early(self) -> None:
        self.assertTrue(fishing._accept_after_cooldown(7, True, 3000, now=20.0))
        self.assertFalse(fishing._accept_after_cooldown(7, False, 3000, now=21.5))
        self.assertFalse(fishing._accept_after_cooldown(7, True, 3000, now=22.9))
        self.assertTrue(fishing._accept_after_cooldown(7, True, 3000, now=23.0))

    def test_three_prompt_types_have_independent_cooldowns(self) -> None:
        self.assertTrue(
            fishing._accept_after_cooldown(8, True, 3000, "space", now=30.0)
        )
        self.assertTrue(
            fishing._accept_after_cooldown(8, True, 3000, "e", now=30.0)
        )
        self.assertTrue(
            fishing._accept_after_cooldown(8, True, 3000, "escape", now=30.0)
        )
        self.assertFalse(
            fishing._accept_after_cooldown(8, True, 3000, "space", now=32.9)
        )
        self.assertTrue(
            fishing._accept_after_cooldown(8, True, 3000, "e", now=33.0)
        )

    def test_custom_recognition_returns_icon_box_on_first_appearance(self) -> None:
        x, y = 20, 30
        screen = np.zeros((180, 220, 3), dtype=np.uint8)
        h, w = fishing._template_image.shape[:2]
        target = screen[y : y + h, x : x + w]
        white_pixels = fishing._template_mask > 0
        target[white_pixels] = fishing._template_image[white_pixels]
        argv = SimpleNamespace(
            custom_recognition_param={"threshold": 0.72, "cooldown_ms": 3000},
            image=screen,
            task_detail=SimpleNamespace(task_id=9),
        )

        result = fishing.FishingPromptRecognition().analyze(SimpleNamespace(), argv)

        self.assertEqual(result.box, [x, y, w, h])
        self.assertTrue(result.detail["accepted"])

    def test_target_recognition_only_succeeds_after_fishing_completion(self) -> None:
        recognition = fishing.FishingTargetReachedRecognition()
        with patch.object(
            fishing.progress_state,
            "snapshot",
            return_value={"mode": "挂机钓鱼", "status": "running"},
        ):
            running = recognition.analyze(SimpleNamespace(), SimpleNamespace())
        with patch.object(
            fishing.progress_state,
            "snapshot",
            return_value={"mode": "挂机钓鱼", "status": "completed"},
        ):
            completed = recognition.analyze(SimpleNamespace(), SimpleNamespace())

        self.assertIsNone(running.box)
        self.assertEqual(completed.box, [0, 0, 1, 1])
