from __future__ import annotations

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import focus_restore  # noqa: E402


class TheatreSceneMouseHoldActionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_groups = dict(focus_restore._skill_input_groups)
        focus_restore._skill_input_groups.clear()
        self.group_hwnd = 202
        self.task_id = 901
        self.context = SimpleNamespace(
            tasker=SimpleNamespace(controller=SimpleNamespace(info={"hwnd": self.group_hwnd}))
        )
        self.argv = SimpleNamespace(
            custom_action_param={"hold_ms": 300},
            task_detail=SimpleNamespace(task_id=self.task_id),
            node_name="TheatreAFKScene2MouseHold",
        )

    def tearDown(self) -> None:
        focus_restore._skill_input_groups.clear()
        focus_restore._skill_input_groups.update(self.original_groups)

    @staticmethod
    def _make_argv(node_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            custom_action_param={"hold_ms": 300},
            task_detail=SimpleNamespace(task_id=901),
            node_name=node_name,
        )

    def test_invalid_node_rejected(self) -> None:
        argv = self._make_argv("TheatreAFKScene1MouseHold")
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 10, (20, 30), False
        )

        result = focus_restore.TheatreSceneMouseHoldAction().run(self.context, argv)

        self.assertFalse(result.success)
        self.assertIn(self.task_id, focus_restore._skill_input_groups)

    def test_invalid_param_rejected(self) -> None:
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 10, (20, 30), False
        )
        for params in (
            {},
            {"hold_ms": 0},
            {"hold_ms": 301},
            {"hold_ms": 300, "scene": "Yiwei"},
            {"node": "TheatreAFKScene2MouseHold"},
        ):
            with self.subTest(params=params):
                argv = SimpleNamespace(
                    custom_action_param=params,
                    task_detail=SimpleNamespace(task_id=self.task_id),
                    node_name="TheatreAFKScene2MouseHold",
                )
                self.assertFalse(
                    focus_restore.TheatreSceneMouseHoldAction().run(
                        self.context, argv
                    ).success
                )

        self.assertIn(self.task_id, focus_restore._skill_input_groups)

    def test_requires_existing_scene_group_and_game_handle(self) -> None:
        with (
            patch.object(focus_restore, "_activate_game_for_skill") as activate,
            patch.object(focus_restore, "_send_foreground_mouse_button") as button,
        ):
            self.assertFalse(
                focus_restore.TheatreSceneMouseHoldAction().run(self.context, self.argv).success
            )
            activate.assert_not_called()
            button.assert_not_called()

    def test_foreground_scene_hold_uses_existing_group_and_preserves_snapshot(self) -> None:
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 101, (300, 400), False
        )
        events = []
        action = focus_restore.TheatreSceneMouseHoldAction()

        with (
            patch.object(focus_restore._user32, "IsWindow", return_value=True),
            patch.object(
                focus_restore,
                "_activate_game_for_skill",
                return_value=True,
            ) as activate,
            patch.object(
                focus_restore,
                "_send_foreground_mouse_button",
                side_effect=lambda button, pressed: events.append((button, pressed))
                or True,
            ),
            patch.object(focus_restore.time, "sleep") as sleep,
            patch.object(focus_restore, "_restore_window_and_cursor") as restore,
        ):
            result = action.run(self.context, self.argv)

        self.assertTrue(result.success)
        activate.assert_called_once_with(self.group_hwnd)
        self.assertEqual(events, [("left", True), ("left", False)])
        sleep.assert_called_once_with(0.3)
        restore.assert_not_called()
        self.assertEqual(
            focus_restore._skill_input_groups[self.task_id],
            focus_restore._SkillInputGroup(self.group_hwnd, 101, (300, 400), False),
        )

    def test_foreground_scene_hold_fails_and_cleans_up(self) -> None:
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 101, (300, 400), False
        )
        with (
            patch.object(focus_restore._user32, "IsWindow", return_value=True),
            patch.object(focus_restore, "_activate_game_for_skill", return_value=True),
            patch.object(
                focus_restore,
                "_send_foreground_mouse_button",
                side_effect=[True, RuntimeError("upstream"), True],
            ) as mouse_button,
            patch.object(focus_restore.time, "sleep"),
        ):
            result = focus_restore.TheatreSceneMouseHoldAction().run(
                self.context, self.argv
            )

        self.assertFalse(result.success)
        self.assertEqual(mouse_button.call_count, 3)


    def test_stale_background_group_is_rejected_without_input(self) -> None:
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 101, (300, 400), True
        )
        with (
            patch.object(focus_restore._user32, "IsWindow", return_value=True),
            patch.object(focus_restore, "_send_background_mouse_transition") as background,
            patch.object(focus_restore, "_activate_game_for_skill") as activate,
            patch.object(focus_restore, "_send_foreground_mouse_button") as foreground,
        ):
            result = focus_restore.TheatreSceneMouseHoldAction().run(self.context, self.argv)
        self.assertFalse(result.success)
        background.assert_not_called()
        activate.assert_not_called()
        foreground.assert_not_called()

    def test_down_failure_or_exception_still_releases_without_sleep_or_replay(self) -> None:
        for background in (False, True):
            with self.subTest(background=background):
                if background:
                    sender = "_send_background_mouse_transition"
                    helper = focus_restore._send_background_scene_hold
                    args = (202, 50, 50)
                else:
                    sender = "_send_foreground_mouse_button"
                    helper = focus_restore._send_foreground_scene_hold
                    args = ()
                for down_result in (False, RuntimeError("down")):
                    with self.subTest(down_result=type(down_result).__name__):
                        with patch.object(
                            focus_restore, sender, side_effect=[down_result, True]
                        ) as mocked, patch.object(focus_restore.time, "sleep") as sleep, patch.object(
                            focus_restore, "_client_center", return_value=(50, 50)
                        ):
                            result = helper(*(args[:1] + (0.3,) if background else (0.3,)))
                        self.assertFalse(result)
                        self.assertEqual(mocked.call_count, 2)
                        self.assertEqual(mocked.call_args_list[-1][0][-1], False)
                        sleep.assert_not_called()

    def test_up_failure_or_exception_retries_once_and_stays_failed(self) -> None:
        for background in (False, True):
            with self.subTest(background=background):
                sender = (
                    "_send_background_mouse_transition"
                    if background
                    else "_send_foreground_mouse_button"
                )
                helper = (
                    focus_restore._send_background_scene_hold
                    if background
                    else focus_restore._send_foreground_scene_hold
                )
                call_args = (202, 0.3) if background else (0.3,)
                for first_up in (False, RuntimeError("up")):
                    with self.subTest(first_up=type(first_up).__name__):
                        with patch.object(
                            focus_restore,
                            sender,
                            side_effect=[True, first_up, True],
                        ) as mocked, patch.object(
                            focus_restore, "_client_center", return_value=(50, 50)
                        ):
                            result = helper(*call_args)
                        self.assertFalse(result)
                        self.assertEqual(mocked.call_count, 3)
                        self.assertEqual(mocked.call_args_list[0][0][-1], True)
                        self.assertEqual(mocked.call_args_list[1][0][-1], False)
                        self.assertEqual(mocked.call_args_list[2][0][-1], False)

    def test_background_group_snapshot_and_no_group_recreate(self) -> None:
        focus_restore._skill_input_groups[self.task_id] = focus_restore._SkillInputGroup(
            self.group_hwnd, 111, (9, 10), True
        )
        snapshot = dict(focus_restore._skill_input_groups)
        with (
            patch.object(focus_restore._user32, "IsWindow", return_value=True),
            patch.object(
                focus_restore._user32,
                "GetClientRect",
                side_effect=lambda hwnd, rect: (
                    setattr(rect._obj, "right", 1280),
                    setattr(rect._obj, "bottom", 720),
                    True,
                )[-1],
            ),
            patch.object(focus_restore, "_send_background_mouse_transition", return_value=True),
            patch.object(focus_restore.time, "sleep"),
        ):
            focus_restore.TheatreSceneMouseHoldAction().run(self.context, self.argv)

        self.assertEqual(snapshot, dict(focus_restore._skill_input_groups))

    def test_background_mouse_group_still_rejects_mouse_steps_in_keyboard_wrapper(self) -> None:
        action = focus_restore.TheatreBackgroundKeyboardSequenceAction()
        argv = SimpleNamespace(
            custom_action_param={
                "kind": "input_sequence",
                "skill_input_group": True,
                "steps": [{"mouse_down": "left"}, {"mouse_up": "left"}],
            },
            task_detail=SimpleNamespace(task_id=self.task_id),
            node_name="TheatreAFKCombatSequence",
        )
        with patch.object(focus_restore, "_safe_user_log") as log:
            self.assertFalse(action.run(self.context, argv).success)
        log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
