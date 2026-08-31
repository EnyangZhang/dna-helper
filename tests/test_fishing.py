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

    def test_pool_empty_text_matching_survives_brightness_change(self) -> None:
        rng = np.random.default_rng(45)
        screen = rng.integers(20, 100, size=(720, 1280, 3), dtype=np.uint8)
        x, y = 530, 230
        template = fishing._template_images["empty"].astype(np.int16)
        changed = np.clip(template - 20, 0, 255).astype(np.uint8)
        h, w = changed.shape[:2]
        screen[y : y + h, x : x + w] = changed

        score, location = fishing._match_prompt(screen, "empty")

        self.assertGreaterEqual(score, 0.80)
        self.assertEqual(location, (x, y))

    @staticmethod
    def _pool_empty_fixture() -> np.ndarray:
        path = Path(__file__).parent / "fixtures" / "fishing_pool_empty_ice.png"
        image = cv2.imread(str(path))
        if image is None:
            raise AssertionError(f"Missing real fishing regression screenshot: {path}")
        return image

    def test_pool_empty_real_ice_screenshot_reproduces_old_miss_and_now_matches(self) -> None:
        screen = self._pool_empty_fixture()
        old_result = cv2.matchTemplate(
            fishing._text_edge_mask(screen),
            fishing._text_edge_mask(fishing._template_images["empty"]),
            cv2.TM_CCOEFF_NORMED,
        )
        self.assertLess(cv2.minMaxLoc(old_result)[1], 0.72)

        for frame, expected in ((screen, (540, 253)), (screen[31:, 3:1283], (537, 222))):
            with self.subTest(expected=expected):
                score, box, segment_score = fishing._match_pool_empty(frame)
                self.assertGreaterEqual(score, 0.95)
                self.assertGreaterEqual(segment_score, 0.90)
                self.assertEqual(box, (*expected, 80, 20))

    def test_pool_empty_multiscale_text_survives_small_size_changes(self) -> None:
        template = fishing._template_images["empty"]
        for scale in (0.95, 0.96, 0.98, 1.0, 1.02, 1.04, 1.05):
            with self.subTest(scale=scale):
                screen = np.full((720, 1280, 3), 45, dtype=np.uint8)
                changed = cv2.resize(template, None, fx=scale, fy=scale)
                height, width = changed.shape[:2]
                screen[230 : 230 + height, 530 : 530 + width] = changed
                score, _, segment_score = fishing._match_pool_empty(screen)
                self.assertGreaterEqual(score, 0.85)
                self.assertGreaterEqual(segment_score, 0.80)

    def test_pool_empty_text_survives_colored_textured_background_and_fading(self) -> None:
        # Composite the same glyph strokes over generated scenery, not a pasted
        # rectangle of the old screenshot's background.
        glyphs = fishing._pool_empty_text_mask(fishing._template_images["empty"])
        alpha = glyphs.astype(np.float32)[..., None] / 255.0
        height, width = glyphs.shape
        yy, xx = np.indices((720, 1280))
        texture = (8 * np.sin(xx / 15.0) + 6 * np.cos(yy / 19.0))[..., None]
        for color in ((20, 20, 20), (100, 65, 20), (20, 90, 30), (160, 170, 180)):
            for opacity in (0.5, 0.75, 1.0):
                with self.subTest(color=color, opacity=opacity):
                    scene = np.clip(np.array(color) + texture, 0, 255).astype(np.float32)
                    roi = scene[230 : 230 + height, 530 : 530 + width]
                    roi[:] += (255.0 - roi) * alpha * opacity
                    score, _, segment_score = fishing._match_pool_empty(scene.astype(np.uint8))
                    self.assertGreaterEqual(score, 0.85)
                    self.assertGreaterEqual(segment_score, 0.80)

    def test_pool_empty_does_not_match_scenery_or_other_fishing_prompts(self) -> None:
        screen = self._pool_empty_fixture()
        # Replace only the notification strip with adjacent real ice/water pixels.
        screen[253:278, 350:930] = screen[280:305, 350:930]
        negatives = [screen, np.zeros((720, 1280, 3), dtype=np.uint8)]
        negatives.append(np.full((720, 1280, 3), 255, dtype=np.uint8))
        negatives.append(np.random.default_rng(85).integers(0, 256, (720, 1280, 3), dtype=np.uint8))
        for prompt in ("space", "e", "escape"):
            scene = np.full((720, 1280, 3), 45, dtype=np.uint8)
            template = fishing._template_images[prompt]
            height, width = template.shape[:2]
            scene[230 : 230 + height, 530 : 530 + width] = template
            negatives.append(scene)
        for index, frame in enumerate(negatives):
            with self.subTest(index=index):
                score, _ = fishing._match_prompt(frame, "empty")
                self.assertLess(score, 0.85)

    def test_pool_empty_requires_all_parts_of_phrase(self) -> None:
        template = fishing._template_images["empty"]
        height, width = template.shape[:2]
        for missing in range(6):
            with self.subTest(missing=missing):
                changed = template.copy()
                changed[:, missing * width // 6 : (missing + 1) * width // 6] = 45
                screen = np.full((720, 1280, 3), 45, dtype=np.uint8)
                screen[230 : 230 + height, 530 : 530 + width] = changed
                result = fishing.FishingPromptRecognition().analyze(
                    SimpleNamespace(),
                    SimpleNamespace(
                        custom_recognition_param={"prompt": "empty", "threshold": 0.85},
                        image=screen,
                        task_detail=SimpleNamespace(task_id=100 + missing),
                    ),
                )
                self.assertIsNone(result.box)
                self.assertFalse(result.detail["accepted"])

    def test_pool_empty_ignores_text_outside_notification_band(self) -> None:
        template = fishing._template_images["empty"]
        height, width = template.shape[:2]
        for x, y in ((1020, 40), (80, 580), (530, 500)):
            with self.subTest(x=x, y=y):
                screen = np.full((720, 1280, 3), 45, dtype=np.uint8)
                screen[y : y + height, x : x + width] = template
                self.assertLess(fishing._match_prompt(screen, "empty")[0], 0.85)

    def test_pool_empty_acceptance_keeps_correct_box_and_independent_lock(self) -> None:
        for prompt in ("space", "e", "escape"):
            self.assertTrue(fishing._accept_after_cooldown(90, True, 3000, prompt))
        argv = SimpleNamespace(
            custom_recognition_param={"prompt": "empty", "cooldown_ms": 60000},
            image=self._pool_empty_fixture(),
            task_detail=SimpleNamespace(task_id=90),
        )
        result = fishing.FishingPromptRecognition().analyze(SimpleNamespace(), argv)
        self.assertEqual(result.box, [540, 253, 80, 20])
        self.assertTrue(result.detail["accepted"])
        self.assertEqual(result.detail["roi"], [320, 180, 640, 140])
        repeated = fishing.FishingPromptRecognition().analyze(SimpleNamespace(), argv)
        self.assertIsNone(repeated.box)

    def test_pool_empty_rejects_invalid_or_too_small_frames(self) -> None:
        for shape in ((10, 10, 3), (195, 330, 3), (720, 1280), (720, 1280, 4)):
            with self.subTest(shape=shape):
                self.assertEqual(fishing._match_pool_empty(np.zeros(shape, np.uint8))[0], 0.0)

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
            return_value={"mode": "钓鱼挂机", "status": "running"},
        ):
            running = recognition.analyze(SimpleNamespace(), SimpleNamespace())
        with patch.object(
            fishing.progress_state,
            "snapshot",
            return_value={"mode": "钓鱼挂机", "status": "completed"},
        ):
            completed = recognition.analyze(SimpleNamespace(), SimpleNamespace())

        self.assertIsNone(running.box)
        self.assertEqual(completed.box, [0, 0, 1, 1])
