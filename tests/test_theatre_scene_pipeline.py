from __future__ import annotations

import unittest
import json

from tests.test_theatre_afk import TheatreGraphRunner, reachable_nodes, selected_pipeline


class TheatreScenePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        import tests.test_theatre_afk as base
        self.pipeline = json.loads(base.PIPELINE.read_text(encoding="utf-8"))
        self.task = json.loads(base.TASK.read_text(encoding="utf-8"))

    def runner(self, background: str = "No") -> TheatreGraphRunner:
        return TheatreGraphRunner(selected_pipeline(self.pipeline, self.task, "YiweiNoE", background))

    def enter_scene_monitor(self, runner: TheatreGraphRunner) -> None:
        runner.enter_first_dungeon()
        self.assertEqual(runner.current, "TheatreAFKSceneMonitor2")

    def detect(self, runner: TheatreGraphRunner, scene: int) -> None:
        for _ in range(8):
            runner.step(scene=scene)
            if runner.current == f"TheatreAFKScene{scene}Detected":
                return
        self.fail(f"scene {scene} was not detected")

    def test_each_scene_is_consumed_once_and_stale_candidates_do_not_repeat(self) -> None:
        for background in ("No", "Yes"):
            runner = self.runner(background)
            self.enter_scene_monitor(runner)
            for scene in (2, 3, 4, 5):
                self.detect(runner, scene)
                runner.step(scene=scene)
                self.assertEqual(runner.current, f"TheatreAFKScene{scene}MouseHold")
                runner.step()
                self.assertEqual(runner.current, f"TheatreAFKSceneMonitor{scene + 1}" if scene < 5 else "TheatreAFKInsideMonitor")
                before = runner.actions.count(f"TheatreAFKScene{scene}MouseHold")
                for index in range(10):
                    runner.step(scene=scene, hud=bool(index % 2))
                self.assertEqual(runner.actions.count(f"TheatreAFKScene{scene}MouseHold"), before)
            for scene in (2, 3, 4, 5):
                self.assertEqual(runner.actions.count(f"TheatreAFKScene{scene}MouseHold"), 1)

    def test_missed_scene_two_can_advance_to_scene_three(self) -> None:
        runner = self.runner()
        self.enter_scene_monitor(runner)
        self.detect(runner, 3)
        runner.step(scene=3)
        self.assertEqual(runner.current, "TheatreAFKScene3MouseHold")
        runner.step()
        self.assertEqual(runner.current, "TheatreAFKSceneMonitor4")

    def test_go_during_scene_delay_has_priority_over_mouse_hold(self) -> None:
        runner = self.runner()
        self.enter_scene_monitor(runner)
        self.detect(runner, 2)
        runner.step(go=True, scene=2)
        self.assertEqual(runner.current, "TheatreAFKGo")
        self.assertEqual(runner.actions.count("TheatreAFKScene2MouseHold"), 0)

    def test_hud_blinks_do_not_reopen_the_scene_sequence(self) -> None:
        runner = self.runner()
        self.enter_scene_monitor(runner)
        for _ in range(4):
            runner.step(scene=2)
            runner.step(hud=True)
        self.assertEqual(runner.openings, 1)
        self.assertLessEqual(runner.actions.count("TheatreAFKScene2MouseHold"), 1)

    def test_go_residue_and_three_hud_frames_allow_new_dungeon_scene_two(self) -> None:
        runner = self.runner()
        self.enter_scene_monitor(runner)
        self.detect(runner, 2)
        runner.step()
        runner.step(scene=2)
        self.assertIn(runner.current, {"TheatreAFKScene2MouseHold", "TheatreAFKSceneMonitor3"})
        runner.step()
        runner.step(go=True)
        runner.click_go()
        self.assertEqual(runner.openings, 1)
        runner.step(hud=True); runner.step(hud=True); runner.step(hud=True)
        runner.step(); runner.step(); runner.step()
        self.assertEqual(runner.current, "TheatreAFKSceneMonitor2")
        self.assertEqual(runner.openings, 2)
        self.detect(runner, 2); runner.step()
        self.assertEqual(runner.actions.count("TheatreAFKScene2MouseHold"), 2)

    def test_default_profile_never_reaches_scene_nodes(self) -> None:
        scene_nodes = {name for name in self.pipeline if "Scene" in name}
        for background in ("No", "Yes"):
            current = reachable_nodes(selected_pipeline(self.pipeline, self.task, "CoinDefault", background))
            self.assertTrue(scene_nodes.isdisjoint(current))


if __name__ == "__main__":
    unittest.main()
