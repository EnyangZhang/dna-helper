import unittest
from pathlib import Path
import cv2
import numpy as np
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "agent"))
import theatre_scenes

class TheatreSceneRecognitionTest(unittest.TestCase):
    def setUp(self):
        self.paths = [Path("tests/fixtures") / f"theatre_scene{i}.png" for i in (2,3,4,5)]
        self.images = [cv2.imread(str(p)) for p in self.paths]
    def test_stage_positives_and_cross_negative(self):
        for index, scene in enumerate((2,3,4)):
            full = np.zeros((720,1280,3), np.uint8)
            full[220:220+self.images[index].shape[0],500:500+self.images[index].shape[1]] = self.images[index]
            self.assertIsNotNone(theatre_scene_detection(full, scene))
            for other in (2,3,4):
                if other != scene:
                    self.assertIsNone(theatre_scenes.detect_scene(full, other))
    def test_boss_and_blank(self):
        full = np.zeros((720,1280,3), np.uint8)
        boss = self.images[3]
        full[35:35+boss.shape[0],300:300+boss.shape[1]] = boss
        self.assertIsNotNone(theatre_scenes.detect_scene(full, 5))
        plain = np.zeros_like(full); plain[72:88, 410:885] = (0, 0, 220)
        self.assertIsNone(theatre_scenes.detect_scene(plain, 5))
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((720,1280,3), np.uint8), 5))

    def assert_partial_boss_rejected(self, full, fraction):
        damaged = full.copy(); frame = damaged[72:88, 403:878]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 100, 90), (12, 255, 255)); ys, xs = np.where(red > 0)
        cutoff = int(xs.min() + (xs.max() - xs.min()) * fraction)
        frame[ys[xs >= cutoff], xs[xs >= cutoff]] = 0
        self.assertIsNone(theatre_scenes.detect_scene(damaged, 5))

    def test_boss_25_percent_is_not_a_full_health_match(self):
        full = np.zeros((720,1280,3), np.uint8); boss=self.images[3]; full[35:125,300:1000]=boss
        self.assert_partial_boss_rejected(full, 0.25)

    def test_boss_10_percent_is_not_a_full_health_match(self):
        full = np.zeros((720,1280,3), np.uint8); boss=self.images[3]; full[35:125,300:1000]=boss
        self.assert_partial_boss_rejected(full, 0.10)

    def test_similar_red_progress_strip_with_same_outer_frame_is_rejected(self):
        # Synthetic lookalike, not a capture of the user's reported progress bar.
        full = np.zeros((720,1280,3), np.uint8)
        full[35:125,300:1000] = self.images[3]
        frame = full[72:88,403:878]
        frame[3:11,20:-20] = (0,0,220)
        self.assertIsNone(theatre_scenes.detect_scene(full, 5))

    def test_boss_rectangle_rejected(self):
        plain=np.zeros((720,1280,3),np.uint8); plain[76:82,426:853]=(0,0,220)
        self.assertIsNone(theatre_scenes.detect_scene(plain,5))

    def test_small_boss_image_returns_none(self):
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((10,10,3),np.uint8),5))
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((100,500,3),np.uint8),5))
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((720,1280,3),np.float32),5))
    def test_invalid_inputs_fail_closed(self):
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((10,10,3), np.uint8), 2))
        self.assertIsNone(theatre_scenes.detect_scene(np.zeros((10,10), np.uint8), 2))

def theatre_scene_detection(full, scene):
    return theatre_scenes.detect_scene(full, scene)

if __name__ == '__main__': unittest.main()
