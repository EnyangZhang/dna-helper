from __future__ import annotations

import json
import copy
import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import Mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import progress_monitor  # noqa: E402
import progress_state  # noqa: E402
import focus_restore  # noqa: E402
from maa.event_sink import NotificationType  # noqa: E402
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "assets/resource/base/pipeline/TheatreAFK.json"
TASK = ROOT / "assets/resource/tasks/TheatreAFK.json"
BACKGROUND_TRANSITION = focus_restore._send_background_key_transition


def apply_override(pipeline, override):
    """Pipeline options recursively merge objects and replace candidate lists."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(pipeline.get(key), dict):
            apply_override(pipeline[key], value)
        else:
            pipeline[key] = copy.deepcopy(value)
    return pipeline


def selected_pipeline(pipeline, task, profile, background="No", *, reverse=False):
    selections = (("TheatreAFKCharacterProfile", profile),
                  ("TheatreAFKBackgroundInput", background))
    result = copy.deepcopy(pipeline)
    for name, selected in reversed(selections) if reverse else selections:
        case = next(case for case in task["option"][name]["cases"] if case["name"] == selected)
        apply_override(result, case.get("pipeline_override", {}))
    return result


def reachable_nodes(pipeline):
    seen, pending = set(), ["TheatreAFKEntry"]
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            node = pipeline[name]
            pending.extend(node.get("next", []) + node.get("on_error", []))
    return seen


class TheatreGraphRunner:
    """Offline next/on_error routing model; never sends game input."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.current = "TheatreAFKEntry"
        self.actions = [self.current]

    def step(self, *, hud=False, go=False):
        current = self.pipeline[self.current]
        selected = None
        for name in current.get("next", []):
            recognition = self.pipeline[name]["recognition"]
            matched = recognition["type"] == "DirectHit"
            if recognition["type"] == "TemplateMatch":
                template = recognition["param"]["template"]
                matched = go if template == "TheatreAFK/go.png" else hud
            if matched:
                selected = name
                break
        if selected is None:
            selected = current["on_error"][0]
        self.current = selected
        self.actions.append(selected)

    @property
    def openings(self):
        return self.actions.count("TheatreAFKCombatSequence")

    def enter_first_dungeon(self):
        for _ in range(10):
            self.step(hud=True)
            if self.current == "TheatreAFKInsideMonitor":
                return
        raise AssertionError("Initial opening did not reach settlement wait")

    def click_go(self):
        for expected in (
            "TheatreAFKGo", "TheatreAFKGoClick2", "TheatreAFKGoClick3",
            "TheatreAFKGoClick3Finalize", "TheatreAFKRestartMonitor",
        ):
            self.step(hud=True, go=True)
            if self.current != expected:
                raise AssertionError((self.current, expected))


class TheatreAfkContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = json.loads(PIPELINE.read_text(encoding="utf-8"))
        cls.task = json.loads(TASK.read_text(encoding="utf-8"))

    def test_task_is_independent_daily_afk_and_disabled_by_default(self) -> None:
        task = self.task["task"][0]
        interface = json.loads((ROOT / "assets/interface.json").read_text(encoding="utf-8"))
        self.assertEqual(task["label"], "沉浸式戏剧挂机")
        self.assertEqual(task["entry"], "TheatreAFKEntry")
        self.assertIn("resource/tasks/TheatreAFK.json", interface["import"])
        preset = json.loads((ROOT / "assets/resource/tasks/preset/AFK.json").read_text(encoding="utf-8"))
        normal = next(x for x in preset["preset"] if x["name"] == "NormalAFK")
        theatre = next(x for x in normal["task"] if x["name"] == "TheatreAFK")
        self.assertFalse(theatre["enabled"])
        self.assertEqual(task["group"], ["DailyAFK"])
        self.assertEqual(task["controller"], ["Win32-Foreground"])
        option = self.task["option"]["TheatreAFKCharacterProfile"]
        self.assertEqual(option["default_case"], "CoinDefault")
        self.assertEqual(option["cases"][0]["name"], "CoinDefault")
        self.assertEqual(option["cases"][0]["label"], "伊薇")

    def test_profile_override_and_logs_are_explicit(self) -> None:
        case = self.task["option"]["TheatreAFKCharacterProfile"]["cases"][0]
        override = case["pipeline_override"]
        self.assertEqual(override["TheatreAFKProfileEntry"]["next"], ["TheatreAFKCombatSequence"])
        content = override["TheatreAFKEntry"]["focus"]["Node.Action.Succeeded"]["content"]
        self.assertIn("伊薇", content)
        self.assertIn("血条连续3帧", content)
        self.assertIn("动作链已完成", self.pipeline["TheatreAFKCombatSequence"]["focus"]["Node.Action.Succeeded"]["content"])

    def test_hud_chain_and_timings(self) -> None:
        names = ["TheatreAFKWaitCombatHud", "TheatreAFKCombatHudFrame1", "TheatreAFKCombatHudFrame2", "TheatreAFKCombatHudReady"]
        expected = {"template": "CharacterControl/combat_health_bar.png", "roi": [90, 675, 180, 40], "threshold": 0.85}
        for name in names[1:]:
            node = self.pipeline[name]
            self.assertEqual(node["recognition"]["param"], expected)
            self.assertEqual(node["timeout"], 120)
            self.assertEqual(node["on_error"], ["TheatreAFKWaitCombatHud"])
        self.assertEqual(self.pipeline[names[1]]["post_delay"], 50)
        self.assertEqual(self.pipeline[names[2]]["post_delay"], 50)
        self.assertEqual(self.pipeline[names[3]]["post_delay"], 0)

    def test_role_chain_and_e_loop_have_exact_timing(self) -> None:
        params = self.pipeline["TheatreAFKCombatSequence"]["action"]["param"]["custom_action_param"]
        self.assertEqual(params, {
            "kind": "input_sequence", "skill_input_group": True,
            "steps": [
                {"delay_ms": 3000},
                {"key_down": 87}, {"delay_ms": 1000}, {"key_up": 87},
                {"key_down": 68}, {"delay_ms": 1000}, {"key_up": 68},
                {"key_press": 70}, {"delay_ms": 200},
                {"key_press": 70}, {"delay_ms": 200},
                {"key_press": 70}, {"key_press": 81}, {"delay_ms": 1000},
            ],
        })
        e = self.pipeline["TheatreAFKPressE"]
        self.assertEqual(e["action"]["param"]["custom_action_param"], {
            "kind": "input_sequence", "steps": [{"key_press": 69}],
            "skill_input_group": True,
        })
        self.assertEqual((e["rate_limit"], e["pre_delay"], e["post_delay"]), (0, 0, 500))
        self.assertNotIn("focus", e)
        self.assertEqual(e["next"], ["TheatreAFKInsideMonitor"])
        terminal = self.pipeline["TheatreAFKInsideMonitor"]
        self.assertEqual(terminal["action"], {"type": "DoNothing"})
        self.assertEqual(terminal["next"], ["TheatreAFKGo", "TheatreAFKPressE"])
        self.assertNotIn("on_error", terminal)

    def test_reachable_graph_contains_only_theatre_nodes(self) -> None:
        seen = set()
        for profile, excluded in (("CoinDefault", "TheatreAFKWaitGo"), ("YiweiNoE", "TheatreAFKPressE")):
            current = reachable_nodes(selected_pipeline(self.pipeline, self.task, profile))
            self.assertEqual(current, set(self.pipeline) - {excluded})
            seen.update(current)
        self.assertEqual(seen, set(self.pipeline))
        forbidden = ("Map", "Lobby", "Continue", "Confirm", "StopTask", "Counter", "Again")
        self.assertFalse(any(any(word.lower() in name.lower() for word in forbidden) for name in seen))
        for node in self.pipeline.values():
            for field in ("rate_limit", "pre_delay", "post_delay"):
                self.assertIn(field, node)
            self.assertNotEqual(node["action"]["type"], "StopTask")
            if node["recognition"]["type"] == "TemplateMatch":
                self.assertIn(node["recognition"]["param"]["template"], {
                    "TheatreAFK/go.png", "CharacterControl/combat_health_bar.png",
                })
            if node["action"]["type"] == "Custom":
                params = node["action"]["param"]
                self.assertIn(params["custom_action"], {
                    "focus_guard_start", "focus_guard_action", "focus_guard_finalize",
                })
                self.assertNotIn("progress_event", params.get("custom_action_param", {}))

    def test_profiles_and_background_option_merge_in_either_order(self):
        cases = self.task["option"]["TheatreAFKCharacterProfile"]["cases"]
        self.assertEqual([(case["name"], case["label"]) for case in cases],
                         [("CoinDefault", "伊薇"), ("YiweiNoE", "伊薇（不持续 E）")])
        for profile, fallback in (("CoinDefault", "TheatreAFKPressE"), ("YiweiNoE", "TheatreAFKWaitGo")):
            for background in ("No", "Yes"):
                with self.subTest(profile=profile, background=background):
                    current = selected_pipeline(self.pipeline, self.task, profile, background)
                    self.assertEqual(current, selected_pipeline(self.pipeline, self.task, profile, background, reverse=True))
                    self.assertEqual(current["TheatreAFKInsideMonitor"]["next"], ["TheatreAFKGo", fallback])
                    for name in ("TheatreAFKCombatSequence", "TheatreAFKPressE"):
                        params = current[name]["action"]["param"]
                        self.assertEqual(params["custom_action_param"], self.pipeline[name]["action"]["param"]["custom_action_param"])
                        self.assertEqual(params["custom_action"], "theatre_background_keyboard_sequence" if background == "Yes" else "focus_guard_action")
                    for name in ("TheatreAFKGo", "TheatreAFKGoClick2", "TheatreAFKGoClick3"):
                        self.assertEqual(current[name], self.pipeline[name])
                    self.assertEqual(current["TheatreAFKGoClick3Finalize"]["action"], self.pipeline["TheatreAFKGoClick3Finalize"]["action"])

    def test_switching_back_restores_default_route_and_logs(self):
        current = selected_pipeline(self.pipeline, self.task, "YiweiNoE", "Yes")
        default = self.task["option"]["TheatreAFKCharacterProfile"]["cases"][0]
        apply_override(current, default["pipeline_override"])
        self.assertEqual(current, selected_pipeline(self.pipeline, self.task, "CoinDefault", "Yes"))
        for name in default["pipeline_override"]:
            self.assertEqual(selected_pipeline(self.pipeline, self.task, "CoinDefault")[name], self.pipeline[name])

    def test_no_e_wait_has_no_input_log_or_hud_unlock(self):
        for background in ("No", "Yes"):
            with self.subTest(background=background):
                current = selected_pipeline(self.pipeline, self.task, "YiweiNoE", background)
                wait = current["TheatreAFKWaitGo"]
                self.assertEqual(wait, {
                    "recognition": {"type": "DirectHit"}, "action": {"type": "DoNothing"},
                    "rate_limit": 0, "pre_delay": 0, "post_delay": 50,
                    "max_hit": 1000000000, "next": ["TheatreAFKInsideMonitor"],
                })
                runner = TheatreGraphRunner(current)
                runner.enter_first_dungeon()
                offset = len(runner.actions)
                for index in range(400):
                    runner.step(hud=index % 7 < 3)
                self.assertEqual(runner.openings, 1)
                self.assertEqual(set(runner.actions[offset:]), {"TheatreAFKInsideMonitor", "TheatreAFKWaitGo"})
                for name in ("TheatreAFKEntry", "TheatreAFKCombatSequence", "TheatreAFKGoClick3Finalize"):
                    log = current[name]["focus"]["Node.Action.Succeeded"]["content"]
                    self.assertIn("伊薇（不持续 E）", log)
                    self.assertNotIn("E 循环", log)

    def test_no_e_go_retries_and_later_dungeons_preserve_one_opening(self):
        for background in ("No", "Yes"):
            with self.subTest(background=background):
                current = selected_pipeline(self.pipeline, self.task, "YiweiNoE", background)
                runner = TheatreGraphRunner(current)
                runner.enter_first_dungeon()
                for dungeon in range(1, 4):
                    runner.step()  # Go may appear while the no-input wait is active.
                    self.assertEqual(runner.current, "TheatreAFKWaitGo")
                    runner.step(go=True)
                    for _ in range(4):
                        runner.click_go()
                        self.assertEqual(runner.openings, dungeon)
                    for _ in range(40):
                        runner.step()  # Unknown intermediate page stays safe.
                    self.assertEqual(runner.current, "TheatreAFKRestartMonitor")
                    runner.step(hud=True)
                    runner.step(hud=False)  # Broken HUD confirmation does not unlock.
                    self.assertEqual(runner.openings, dungeon)
                    self.assertEqual(runner.current, "TheatreAFKRestartMonitor")
                    for _ in range(6):
                        runner.step(hud=True)
                    self.assertEqual(runner.current, "TheatreAFKInsideMonitor")
                    self.assertEqual(runner.openings, dungeon + 1)
                self.assertNotIn("TheatreAFKPressE", runner.actions)
                self.assertEqual(runner.actions.count("TheatreAFKEntry"), 1)

    def test_go_is_native_three_clicks_with_one_input_free_log(self) -> None:
        names = ["TheatreAFKGo", "TheatreAFKGoClick2", "TheatreAFKGoClick3"]
        for index, name in enumerate(names):
            node = self.pipeline[name]
            self.assertEqual(node["action"], {
                "type": "Click", "param": {"target": [1172, 673]},
            })
            self.assertEqual(node["recognition"]["type"], "TemplateMatch" if index == 0 else "DirectHit")
            self.assertEqual((node["rate_limit"], node["pre_delay"], node["post_delay"]),
                             (0, 0, 50 if index < 2 else 0))
            self.assertNotIn("focus", node)
        self.assertEqual(self.pipeline[names[0]]["next"], [names[1]])
        self.assertEqual(self.pipeline[names[1]]["next"], [names[2]])
        self.assertEqual(self.pipeline[names[2]]["next"], [names[2] + "Finalize"])
        finalize = self.pipeline[names[2] + "Finalize"]
        self.assertEqual(finalize["action"], {
            "type": "Custom", "param": {
                "custom_action": "focus_guard_finalize",
                "custom_action_param": {"restore_delay_ms": 100, "finish_skill_input_group": True},
            },
        })
        self.assertEqual(list(finalize["focus"]), ["Node.Action.Succeeded"])
        self.assertEqual(finalize["next"], ["TheatreAFKRestartMonitor"])

    def test_hud_loss_or_return_never_unlocks_without_go(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        for hud in [False] * 100 + [True] * 100 + [False, True] * 20:
            runner.step(hud=hud)
            self.assertIn(runner.current, {"TheatreAFKInsideMonitor", "TheatreAFKPressE"})
        self.assertEqual(runner.openings, 1)
        self.assertGreater(runner.actions.count("TheatreAFKPressE"), 0)
        self.assertNotIn("TheatreAFKGo", runner.actions)

    def test_global_go_debug_is_reverted(self) -> None:
        initial = (
            "TheatreAFKEntry", "TheatreAFKWaitCombatHud",
            "TheatreAFKCombatHudFrame1", "TheatreAFKCombatHudFrame2",
            "TheatreAFKCombatHudReady",
        )
        for name in initial:
            self.assertNotIn("TheatreAFKGo", self.pipeline[name]["next"])
        runner = TheatreGraphRunner(self.pipeline)
        for _ in range(100):
            runner.step(go=True)
            self.assertEqual(runner.current, "TheatreAFKWaitCombatHud")
        self.assertEqual(runner.openings, 0)
        self.assertNotIn("TheatreAFKPressE", runner.actions)
        self.assertNotIn("TheatreAFKGo", runner.actions)

    def test_go_stops_e_before_clicking_and_has_priority_over_hud(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        for _ in range(12):
            runner.step(hud=False)
        sent_e = runner.actions.count("TheatreAFKPressE")
        runner.click_go()
        self.assertEqual(runner.actions.count("TheatreAFKPressE"), sent_e)
        for _ in range(5):
            runner.click_go()
        self.assertEqual(runner.actions.count("TheatreAFKPressE"), sent_e)
        for name in ("TheatreAFKRestartHudFrame1", "TheatreAFKRestartHudFrame2"):
            self.assertEqual(self.pipeline[name]["next"][0], "TheatreAFKGo")

    def test_go_residue_retries_without_opening_or_reinitializing(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        for _ in range(5):
            runner.click_go()
            self.assertEqual(runner.openings, 1)
        self.assertEqual(runner.actions.count("TheatreAFKEntry"), 1)
        for _ in range(3):
            runner.step(hud=True)
        self.assertEqual(runner.current, "TheatreAFKRestartHudReady")
        self.assertEqual(runner.openings, 1)
        runner.step(hud=True)
        runner.step(hud=True)
        self.assertEqual(runner.openings, 2)
        runner.step(hud=True)
        for _ in range(50):
            runner.step(hud=True)
        self.assertEqual(runner.openings, 2)

    def test_restart_hud_must_confirm_three_frames_without_go_residue(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        runner.click_go()
        runner.step(hud=True)
        runner.step(hud=False)
        self.assertEqual(runner.current, "TheatreAFKRestartMonitor")
        self.assertEqual(runner.openings, 1)
        runner.step(hud=True)
        runner.step(hud=True, go=True)
        self.assertEqual(runner.current, "TheatreAFKGo")
        self.assertEqual(runner.openings, 1)
        for name in ("TheatreAFKRestartHudFrame1", "TheatreAFKRestartHudFrame2", "TheatreAFKRestartHudReady"):
            node = self.pipeline[name]
            self.assertEqual(node["timeout"], 120)
            self.assertEqual(node["on_error"], ["TheatreAFKRestartMonitor"])
        self.assertEqual(self.pipeline["TheatreAFKRestartHudReady"]["next"], ["TheatreAFKProfileEntry"])

    def test_unknown_intermediate_page_waits_without_input_or_completion(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        runner.click_go()
        previous = len(runner.actions)
        for _ in range(200):
            runner.step()
        self.assertEqual(set(runner.actions[previous:]), {"TheatreAFKRestartMonitor"})
        self.assertEqual(runner.openings, 1)

    def test_multiple_dungeons_keep_one_opening_per_confirmed_go_boundary(self) -> None:
        runner = TheatreGraphRunner(self.pipeline)
        runner.enter_first_dungeon()
        for expected in range(2, 5):
            runner.click_go()
            for _ in range(6):
                runner.step(hud=True)
            self.assertEqual(runner.current, "TheatreAFKInsideMonitor")
            self.assertEqual(runner.openings, expected)

    def test_monitor_recognizes_theatre_entry(self) -> None:
        self.assertIn("TheatreAFKEntry", progress_monitor._GAME_TASK_ENTRIES)
        fake = {"status": "running", "mode": "沉浸式戏剧挂机", "completed_rounds": 0, "total_rounds": 0, "stage_count": 0, "stage_total": 0, "updated_at": 0.0}
        with mock.patch.object(progress_state, "_state", fake):
            self.assertNotIn("/", progress_state.format_status(now=0.0))

    def test_profile_and_repeated_e_share_one_focus_group_until_go_finalize(self) -> None:
        events = []
        job = SimpleNamespace(succeeded=True)
        job.wait = lambda: job
        controller = SimpleNamespace(
            info={"hwnd": 202},
            post_key_down=Mock(side_effect=lambda k: (events.append(("down", k)) or job)),
            post_key_up=Mock(side_effect=lambda k: (events.append(("up", k)) or job)),
            post_click_key=Mock(side_effect=lambda k: (events.append(("press", k)) or job)),
        )
        context = SimpleNamespace(tasker=SimpleNamespace(controller=controller), run_action=Mock())
        def argv(name):
            return SimpleNamespace(
                custom_action_param=self.pipeline[name]["action"]["param"]["custom_action_param"],
                task_detail=SimpleNamespace(task_id=991), node_name=name,
            )
        with (
            mock.patch.object(focus_restore, "_skill_input_groups", {}),
            mock.patch.object(focus_restore, "_remember_restore_target", return_value=(101, (300, 400))) as remember,
            mock.patch.object(focus_restore, "_activate_game_for_skill", return_value=True) as activate,
            mock.patch.object(focus_restore, "_foreground_window", return_value=202),
            mock.patch.object(focus_restore.time, "sleep", side_effect=lambda s: events.append(("sleep", s))),
            mock.patch.object(focus_restore, "_restore_window_and_cursor") as restore,
        ):
            self.assertTrue(focus_restore.FocusGuardAction().run(context, argv("TheatreAFKCombatSequence")).success)
            self.assertEqual(events, [
                ("sleep", 3.0), ("down", 87), ("sleep", 1.0), ("up", 87),
                ("down", 68), ("sleep", 1.0), ("up", 68),
                ("press", 70), ("sleep", 0.2), ("press", 70), ("sleep", 0.2),
                ("press", 70), ("press", 81), ("sleep", 1.0),
            ])
            for _ in range(3):
                self.assertTrue(focus_restore.FocusGuardAction().run(context, argv("TheatreAFKPressE")).success)
            self.assertEqual(events[-3:], [("press", 69)] * 3)
            activate.assert_called_once_with(202)
            remember.assert_called_once()
            restore.assert_not_called()
            self.assertTrue(focus_restore.FocusGuardFinalize().run(context, argv("TheatreAFKGoClick3Finalize")).success)
            restore.assert_called_once_with(101, (300, 400))
            self.assertFalse(focus_restore._skill_input_groups)
            # A residual Go click still restores through the normal native-click path.
            restore.reset_mock()
            self.assertTrue(focus_restore.FocusGuardFinalize().run(context, argv("TheatreAFKGoClick3Finalize")).success)
            restore.assert_called_once_with(101, (300, 400))
            self.assertEqual(remember.call_count, 2)
            context.run_action.assert_not_called()

    def test_role_input_failure_releases_key_and_closes_group(self) -> None:
        ok = SimpleNamespace(succeeded=True)
        ok.wait = lambda: ok
        failed = SimpleNamespace(succeeded=False)
        failed.wait = lambda: failed
        for key, up_results in ((87, [failed, ok]), (68, [ok, failed, ok])):
            with self.subTest(key=key):
                controller = SimpleNamespace(
                    info={"hwnd": 202}, post_key_down=Mock(return_value=ok),
                    post_key_up=Mock(side_effect=up_results), post_click_key=Mock(return_value=ok),
                )
                context = SimpleNamespace(tasker=SimpleNamespace(controller=controller))
                params = self.pipeline["TheatreAFKCombatSequence"]["action"]["param"]["custom_action_param"]
                argv = SimpleNamespace(custom_action_param=params, task_detail=SimpleNamespace(task_id=992), node_name="TheatreAFKCombatSequence")
                with (
                    mock.patch.object(focus_restore, "_skill_input_groups", {}),
                    mock.patch.object(focus_restore, "_remember_restore_target", return_value=(101, (300, 400))),
                    mock.patch.object(focus_restore, "_activate_game_for_skill", return_value=True),
                    mock.patch.object(focus_restore.time, "sleep"),
                    mock.patch.object(focus_restore, "_restore_window_and_cursor") as restore,
                ):
                    self.assertFalse(focus_restore.FocusGuardAction().run(context, argv).success)
                    self.assertEqual(controller.post_key_up.call_args_list[-2:], [mock.call(key)] * 2)
                    controller.post_click_key.assert_not_called()
                    self.assertFalse(focus_restore._skill_input_groups)
                    restore.assert_called_once_with(101, (300, 400))

    def test_theatre_manual_stop_cleans_input_group_only_for_this_task(self) -> None:
        with mock.patch.object(focus_restore, "_finish_skill_input_group") as finish:
            sink = focus_restore.TheatreInputLifecycle()
            sink.on_tasker_task(Mock(), NotificationType.Failed, SimpleNamespace(entry="TheatreAFKEntry", task_id=11))
            finish.assert_called_once_with(11, restore_delay_ms=0)
            sink.on_tasker_task(Mock(), NotificationType.Failed, SimpleNamespace(entry="MoonHunterAFKEntry", task_id=12))
            self.assertEqual(finish.call_count, 1)

    def test_manual_stop_stops_monitor_without_completion(self) -> None:
        lifecycle = progress_monitor.ProgressMonitorLifecycle()
        with mock.patch.object(progress_monitor.telegram_bot, "stop", return_value=True) as stop, mock.patch.object(progress_monitor.telegram_bot, "format_task_completed_message") as fmt:
            lifecycle.on_tasker_task(Mock(), NotificationType.Failed, SimpleNamespace(entry="TheatreAFKEntry"))
        stop.assert_called_once_with(final_message=None); fmt.assert_not_called()


class TheatreBackgroundInputTest(unittest.TestCase):
    def setUp(self):
        self.pipeline = json.loads(PIPELINE.read_text(encoding="utf-8"))
        self.task = json.loads(TASK.read_text(encoding="utf-8"))
        self.events = []
        job = SimpleNamespace(succeeded=True)
        job.wait = lambda: job
        self.controller = SimpleNamespace(
            info={"hwnd": 202},
            post_key_down=Mock(side_effect=lambda k: self.events.append(("down", k)) or job),
            post_key_up=Mock(side_effect=lambda k: self.events.append(("up", k)) or job),
            post_click_key=Mock(side_effect=lambda k: self.events.append(("press", k)) or job),
        )
        self.context = SimpleNamespace(tasker=SimpleNamespace(controller=self.controller))
        def patched(name, **kwargs):
            patcher = mock.patch.object(focus_restore, name, **kwargs)
            result = patcher.start()
            self.addCleanup(patcher.stop)
            return result
        patched("_skill_input_groups", new={})
        patched("_hybrid_skill_ready_hwnd", new=0)
        self.remember = patched("_remember_restore_target", return_value=(101, (300, 400)))
        self.activate = patched("_activate_game_for_skill", return_value=True)
        self.restore = patched("_restore_window_and_cursor")
        self.foreground = patched("_foreground_window", return_value=202)
        self.release_clip = patched("_release_cursor_clip")
        self.restore_cursor = patched("_restore_cursor")
        self.send = patched("_send_background_key_transition", side_effect=lambda h, k, p: self.events.append(("bg", k, p)) or True)
        patcher = mock.patch.object(focus_restore.time, "sleep", side_effect=lambda s: self.events.append(("sleep", s)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def argv(self, name):
        params = copy.deepcopy(self.pipeline[name]["action"]["param"]["custom_action_param"])
        return SimpleNamespace(custom_action_param=params, task_detail=SimpleNamespace(task_id=903), node_name=name)

    def execute(self, name):
        action = (focus_restore.FocusGuardFinalize() if name.endswith("Finalize")
                  else focus_restore.TheatreBackgroundKeyboardSequenceAction())
        result = action.run(self.context, self.argv(name))
        self.assertTrue(result.success)

    def test_option_only_switches_backend_without_replacing_profile_parameters(self):
        option = self.task["option"]["TheatreAFKBackgroundInput"]
        self.assertIn("TheatreAFKBackgroundInput", self.task["task"][0]["option"])
        self.assertEqual(option["default_case"], "No")
        cases = {case["name"]: case for case in option["cases"]}
        self.assertNotIn("pipeline_override", cases["No"])
        overrides = cases["Yes"]["pipeline_override"]
        self.assertEqual(set(overrides), {"TheatreAFKCombatSequence", "TheatreAFKPressE"})
        for name in ("TheatreAFKCombatSequence", "TheatreAFKPressE"):
            self.assertEqual(overrides[name], {"action": {"param": {"custom_action": "theatre_background_keyboard_sequence"}}})
        self.assertEqual(option["label"], "全程后台输入（实验）")
        self.assertIn("窗口由你手动调整", option["description"])
        self.assertNotIn("enable_background_next_dungeon", self.argv("TheatreAFKGoClick3Finalize").custom_action_param)
        case = self.task["option"]["TheatreAFKCharacterProfile"]["cases"][0]
        self.assertEqual(case["label"], "伊薇")
        for profile in self.task["option"]["TheatreAFKCharacterProfile"]["cases"]:
            for node in profile["pipeline_override"].values():
                self.assertNotIn("action", node)  # Profile routing/logs never replace the keyboard backend.

    def assert_no_foreground_input(self):
        self.activate.assert_not_called()
        self.remember.assert_not_called()
        self.restore.assert_not_called()
        self.foreground.assert_not_called()
        self.release_clip.assert_not_called()
        self.restore_cursor.assert_not_called()
        self.controller.post_key_down.assert_not_called()
        self.controller.post_key_up.assert_not_called()
        self.controller.post_click_key.assert_not_called()

    def test_first_and_later_dungeons_use_identical_background_chains(self):
        expected = [
            ("sleep", 3.0), ("bg", 87, True), ("sleep", 1.0), ("bg", 87, False),
            ("bg", 68, True), ("sleep", 1.0), ("bg", 68, False),
        ]
        for key, pause in ((70, 0.2), (70, 0.2), (70, 0), (81, 1.0)):
            expected += [("bg", key, True), ("sleep", 0.03), ("bg", key, False)]
            if pause:
                expected.append(("sleep", pause))
        for dungeon in range(3):
            with self.subTest(dungeon=dungeon), mock.patch.object(focus_restore, "_safe_user_log") as log:
                self.events.clear()
                self.execute("TheatreAFKCombatSequence")
                self.assertEqual(self.events, expected)
                group = focus_restore._skill_input_groups[903]
                self.assertTrue(group.background_key_input)
                self.assertEqual((group.restore_hwnd, group.restore_cursor_position), (0, None))
                for _ in range(25):  # Includes E #1, #2, #3 and all later presses.
                    self.events.clear()
                    self.execute("TheatreAFKPressE")
                    self.assertEqual(self.events, [("bg", 69, True), ("sleep", 0.03), ("bg", 69, False)])
                    self.assertIs(focus_restore._skill_input_groups[903], group)
                log.assert_not_called()  # No transition message or per-E spam.
                self.assert_no_foreground_input()
                self.assertFalse(focus_restore._is_hybrid_skill_ready(202))
                for _ in range(4):  # Native Go and residual retries still restore.
                    self.execute("TheatreAFKGoClick3Finalize")
                self.assertEqual(self.restore.call_count, 4)
                self.restore.assert_called_with(101, (300, 400))
                self.assertFalse(focus_restore._skill_input_groups)
                self.remember.reset_mock(); self.restore.reset_mock(); self.foreground.reset_mock()

    def test_background_does_not_depend_on_focus_or_other_modes_readiness(self):
        for ready in (0, 202):
            for foreground in (0, 101, 202):
                with self.subTest(ready=ready, foreground=foreground):
                    focus_restore._hybrid_skill_ready_hwnd = ready
                    self.foreground.return_value = foreground
                    self.execute("TheatreAFKPressE")
                    self.assertEqual(focus_restore._hybrid_skill_ready_hwnd, ready)
        self.assertEqual(self.send.call_count, 12)
        self.assert_no_foreground_input()

    def test_disabled_option_stays_foreground_even_if_other_mode_was_ready(self):
        focus_restore._mark_hybrid_skill_ready(202)
        action = focus_restore.FocusGuardAction()
        self.assertTrue(action.run(self.context, self.argv("TheatreAFKCombatSequence")).success)
        for _ in range(8):
            self.assertTrue(action.run(self.context, self.argv("TheatreAFKPressE")).success)
        self.send.assert_not_called()
        self.activate.assert_called_once()
        self.restore.assert_not_called()

    def test_failed_foreground_e_does_not_prime_or_replay_the_opening(self):
        action = focus_restore.FocusGuardAction()  # Disabled option remains unchanged.
        self.assertTrue(action.run(self.context, self.argv("TheatreAFKCombatSequence")).success)
        self.assertTrue(action.run(self.context, self.argv("TheatreAFKPressE")).success)
        job = SimpleNamespace(succeeded=False)
        job.wait = lambda: job
        self.controller.post_click_key.return_value = job
        self.controller.post_click_key.side_effect = None
        self.assertFalse(action.run(self.context, self.argv("TheatreAFKPressE")).success)
        self.assertFalse(focus_restore._is_hybrid_skill_ready(202))
        self.assertFalse(focus_restore._skill_input_groups)
        self.send.assert_not_called()
        self.restore.assert_called_once_with(101, (300, 400))

    def test_first_e_failure_releases_in_background_without_foreground_fallback(self):
        self.execute("TheatreAFKCombatSequence")
        self.send.reset_mock()
        self.send.side_effect = [True, False, True]
        with mock.patch.object(focus_restore, "_safe_user_log") as log:
            self.assertFalse(focus_restore.TheatreBackgroundKeyboardSequenceAction().run(self.context, self.argv("TheatreAFKPressE")).success)
        self.assertFalse(focus_restore._is_hybrid_skill_ready(202))
        self.assertFalse(focus_restore._skill_input_groups)
        self.assert_no_foreground_input()
        self.assertEqual(self.send.call_args_list, [mock.call(202, 69, True), mock.call(202, 69, False), mock.call(202, 69, False)])
        self.assertIn("失败", log.call_args.args[0])

    def test_manual_stop_and_new_task_still_start_in_background(self):
        self.execute("TheatreAFKCombatSequence")
        for _ in range(3):
            self.execute("TheatreAFKPressE")
        focus_restore.TheatreInputLifecycle().on_tasker_task(
            Mock(), NotificationType.Failed, SimpleNamespace(entry="TheatreAFKEntry", task_id=903)
        )
        self.assertFalse(focus_restore._skill_input_groups)
        self.assert_no_foreground_input()
        # Invoke the actual new-task initialization with all external effects mocked.
        argv = self.argv("TheatreAFKEntry")
        argv.task_detail.task_id = 904
        with (
            mock.patch.object(focus_restore, "_initialize_restore_target"),
            mock.patch.object(focus_restore, "_start_foreground_watcher"),
            mock.patch.object(focus_restore.progress_state, "start_task", return_value=True),
            mock.patch.object(focus_restore.telegram_bot, "notify_task_started"),
            mock.patch.object(focus_restore, "_reset_hybrid_fishing_ready"),
        ):
            self.assertTrue(focus_restore.FocusGuardStart().run(self.context, argv).success)
        self.assertFalse(focus_restore._is_hybrid_skill_ready(202))
        self.foreground.reset_mock()  # Start only reads focus for native page clicks.
        self.send.reset_mock()
        for name in ("TheatreAFKCombatSequence", "TheatreAFKPressE"):
            new_argv = self.argv(name)
            new_argv.task_detail.task_id = 904
            self.assertTrue(focus_restore.TheatreBackgroundKeyboardSequenceAction().run(self.context, new_argv).success)
        self.assertEqual(self.send.call_count, 14)
        self.assertTrue(focus_restore._skill_input_groups[904].background_key_input)
        self.assert_no_foreground_input()

    def test_early_go_cleans_group_without_changing_other_modes_readiness(self):
        self.execute("TheatreAFKCombatSequence")
        self.execute("TheatreAFKPressE")
        self.execute("TheatreAFKGoClick3Finalize")
        self.send.reset_mock()
        for _ in range(3):
            self.execute("TheatreAFKGoClick3Finalize")
        self.assertFalse(focus_restore._is_hybrid_skill_ready(202))
        self.send.assert_not_called()
        self.assertFalse(focus_restore._skill_input_groups)

    def test_background_up_failure_releases_key_without_replaying_or_focusing(self):
        for key, results in ((87, [True, False, True]),
                             (70, [True, True, True, True, True, False, True])):
            with self.subTest(key=key):
                self.send.reset_mock()
                self.send.side_effect = results
                with mock.patch("builtins.print"):
                    result = focus_restore.TheatreBackgroundKeyboardSequenceAction().run(self.context, self.argv("TheatreAFKCombatSequence"))
                self.assertFalse(result.success)
                self.assertEqual(self.send.call_args_list[-2:], [mock.call(202, key, False)] * 2)
                self.assertFalse(focus_restore._skill_input_groups)
                self.activate.assert_not_called(); self.remember.assert_not_called(); self.restore.assert_not_called()
                self.controller.post_key_down.assert_not_called(); self.controller.post_click_key.assert_not_called()

    def test_background_rejects_mouse_before_any_input_or_focus_change(self):
        argv = self.argv("TheatreAFKCombatSequence")
        argv.custom_action_param["steps"] = [{"mouse_down": "left"}, {"mouse_up": "left"}]
        for ready in (False, True):
            if ready:
                focus_restore._mark_hybrid_skill_ready(202)
            with self.subTest(ready=ready), mock.patch("builtins.print"):
                self.assertFalse(focus_restore.TheatreBackgroundKeyboardSequenceAction().run(self.context, argv).success)
        self.send.assert_not_called(); self.activate.assert_not_called(); self.remember.assert_not_called()

    def test_invalid_sequence_and_other_tasks_are_rejected_before_input(self):
        action = focus_restore.TheatreBackgroundKeyboardSequenceAction()
        for changes in (
            {"kind": "key"}, {"skill_input_group": False}, {"steps": None},
            {"steps": [{"key_down": 87}]}, {"steps": [{"key_up": 87}]},
        ):
            argv = self.argv("TheatreAFKCombatSequence")
            argv.custom_action_param.update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(action.run(self.context, argv).success)
        argv = self.argv("TheatreAFKPressE")
        argv.custom_action_param["steps"] = [{"key_press": 81}]
        self.assertFalse(action.run(self.context, argv).success)
        argv = self.argv("TheatreAFKCombatSequence")
        argv.node_name = "MediationAFKCombatSequence"
        self.assertFalse(action.run(self.context, argv).success)
        self.send.assert_not_called()
        self.assert_no_foreground_input()

    def test_transition_posts_matching_keyboard_messages_and_never_activates(self):
        user32 = Mock()
        user32.IsWindow.return_value = True
        user32.MapVirtualKeyW.return_value = 0x11
        user32.PostMessageW.return_value = True
        # Exercise the real helper beneath the patched action transport.
        with mock.patch.object(focus_restore, "_user32", user32):
            real_helper = BACKGROUND_TRANSITION
            self.assertTrue(real_helper(202, 87, True))
            self.assertTrue(real_helper(202, 87, False))
            self.assertEqual(user32.PostMessageW.call_args_list, [
                mock.call(202, focus_restore._WM_KEYDOWN, 87, 1 | (0x11 << 16)),
                mock.call(202, focus_restore._WM_KEYUP, 87, 1 | (0x11 << 16) | (1 << 30) | (1 << 31)),
            ])
            user32.IsWindow.return_value = False
            self.assertFalse(real_helper(202, 87, True))
            self.assertEqual(user32.PostMessageW.call_count, 2)
        self.activate.assert_not_called()


class TheatreGoImageTest(unittest.TestCase):
    def test_template_matches_supplied_button_not_return_or_changed_title(self):
        panel = cv2.imread(str(ROOT / "tests/fixtures/theatre_go_panel.png"))
        template = cv2.imread(str(ROOT / "assets/resource/base/image/TheatreAFK/go.png"))
        self.assertEqual(panel.shape[:2], (120, 480))
        self.assertEqual(template.shape[:2], (25, 46))
        roi = panel[40:105, 280:470]
        _, score, _, position = cv2.minMaxLoc(cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED))
        self.assertGreater(score, 0.99)
        self.assertEqual(position, (70, 22))  # Baseline window origin (1150, 662).
        negative = panel[40:105, 80:270]  # Adjacent 返回 button, not 前往.
        self.assertLess(cv2.matchTemplate(negative, template, cv2.TM_CCOEFF_NORMED).max(), 0.85)
        # Changing the next-stage title and scenery cannot enter the narrow ROI.
        changed = panel.copy()
        changed[:40] = np.random.default_rng(1).integers(0, 256, changed[:40].shape, dtype=np.uint8)
        dimmed = (changed[40:105, 280:470].astype(np.float32) * 0.7).astype(np.uint8)
        self.assertGreater(cv2.matchTemplate(dimmed, template, cv2.TM_CCOEFF_NORMED).max(), 0.95)


if __name__ == "__main__":
    unittest.main()
