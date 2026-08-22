from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import progress_state  # noqa: E402


class ProgressStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_path = progress_state._STATUS_PATH
        self.original_state = progress_state.snapshot()
        self.original_last_stage_increment = (
            progress_state._last_stage_increment_monotonic
        )
        progress_state._STATUS_PATH = Path(self.temporary.name) / "status.json"

    def tearDown(self) -> None:
        progress_state._STATUS_PATH = self.original_path
        with progress_state._lock:
            progress_state._state.clear()
            progress_state._state.update(self.original_state)
            progress_state._last_stage_increment_monotonic = (
                self.original_last_stage_increment
            )
        self.temporary.cleanup()

    def test_tracks_logical_stage_and_completed_outer_rounds(self) -> None:
        progress_state.start_task("普通扼守", 3, 99)
        self.assertTrue(progress_state.mark_dungeon_entered())
        progress_state.increment_stage()
        progress_state.increment_stage()
        state = progress_state.snapshot()
        self.assertEqual((state["completed_rounds"], state["total_rounds"]), (0, 3))
        self.assertEqual(state["stage_count"], 3)

        completion = progress_state.complete_round(1, 3, "普通扼守")
        self.assertTrue(completion.early)
        self.assertTrue(completion.should_notify_early)
        self.assertEqual(completion.stage_count, 3)
        self.assertEqual(progress_state.snapshot()["status"], "waiting_next_round")
        progress_state.start_next_round()
        state = progress_state.snapshot()
        self.assertEqual(state["completed_rounds"], 1)
        self.assertEqual(state["stage_count"], 0)
        self.assertFalse(state["stage_tracking_active"])

        self.assertTrue(progress_state.mark_dungeon_entered())
        self.assertEqual(progress_state.snapshot()["stage_count"], 1)

    def test_repeated_entry_does_not_reset_same_cipher_task(self) -> None:
        self.assertTrue(progress_state.start_task("密函无尽", 0, 0, task_id=88))
        progress_state.advance_cipher_cycle()
        self.assertFalse(progress_state.start_task("密函无尽", 0, 0, task_id=88))
        state = progress_state.snapshot()
        self.assertEqual(state["stage_count"], 1)

        message = progress_state.format_status()
        self.assertIn("局内轮次：1", message)

    def test_normal_infinite_reports_99_only_once(self) -> None:
        progress_state.start_task("普通无尽", 0, 0, task_id=101)
        milestones = [progress_state.increment_stage() for _ in range(100)]

        self.assertEqual([index + 1 for index, hit in enumerate(milestones) if hit], [98])
        self.assertEqual(progress_state.snapshot()["stage_count"], 101)

    def test_continue_stage_debounce_ignores_button_afterimage(self) -> None:
        progress_state.start_task("普通无尽", 0, 0, task_id=104)
        with patch.object(
            progress_state.time, "monotonic", side_effect=[100.0, 100.854, 106.0]
        ):
            self.assertFalse(progress_state.increment_stage(5.0))
            self.assertFalse(progress_state.increment_stage(5.0))
            self.assertFalse(progress_state.increment_stage(5.0))

        self.assertEqual(progress_state.snapshot()["stage_count"], 3)

    def test_cipher_infinite_reports_99_only_once(self) -> None:
        progress_state.start_task("密函无尽", 0, 0, task_id=102)
        milestones = [progress_state.advance_cipher_cycle() for _ in range(100)]

        self.assertEqual([index + 1 for index, hit in enumerate(milestones) if hit], [99])
        self.assertEqual(progress_state.snapshot()["stage_count"], 100)

    def test_finite_modes_do_not_report_infinite_99_milestone(self) -> None:
        progress_state.start_task("普通扼守", 1, 99, task_id=103)
        progress_state.mark_dungeon_entered()
        self.assertFalse(any(progress_state.increment_stage() for _ in range(100)))

    def test_complete_round_preserves_real_progress_and_deduplicates_alert(self) -> None:
        progress_state.start_task("皎皎币挂机", 3, 99, task_id=105)
        progress_state.mark_dungeon_entered()
        for _ in range(14):
            progress_state.increment_stage()

        first = progress_state.complete_round(1, 3, "皎皎币挂机")
        repeated = progress_state.complete_round(1, 3, "皎皎币挂机")

        self.assertEqual(first.stage_count, 15)
        self.assertTrue(first.early)
        self.assertTrue(first.should_notify_early)
        self.assertTrue(repeated.early)
        self.assertFalse(repeated.should_notify_early)
        self.assertEqual(progress_state.snapshot()["stage_count"], 15)

    def test_starting_on_again_page_does_not_create_false_early_alert(self) -> None:
        progress_state.start_task("普通扼守", 2, 99, task_id=106)

        completion = progress_state.complete_round(1, 2, "普通扼守")

        self.assertFalse(completion.stage_tracking_active)
        self.assertFalse(completion.early)
        self.assertFalse(completion.should_notify_early)

    def test_cipher_expel_uses_finite_completed_round_count(self) -> None:
        progress_state.start_task("密函驱离", 4, 0, task_id=99)
        progress_state.complete_round(1, 4, "密函驱离")
        state = progress_state.snapshot()
        self.assertEqual(state["completed_rounds"], 1)
        self.assertEqual(state["total_rounds"], 4)
        self.assertEqual(state["status"], "waiting_next_round")

        progress_state.advance_cipher_cycle()
        self.assertEqual(progress_state.snapshot()["status"], "running")
        message = progress_state.format_status()
        self.assertIn("局外副本轮次（已完成）：1 / 4", message)
        self.assertNotIn("无上限", message)

    def test_formats_status_message(self) -> None:
        progress_state.start_task("普通扼守", 6, 99)
        progress_state.mark_dungeon_entered()
        started_at = progress_state.snapshot()["started_at"]
        message = progress_state.format_status(now=started_at + 3674)
        self.assertIn("局外副本轮次（已完成）：0 / 6", message)
        self.assertIn("局内轮次：1 / 99", message)
        self.assertIn("已运行：1小时1分14秒", message)

    def test_completed_duration_does_not_keep_growing(self) -> None:
        progress_state.start_task("普通驱离", 1, 0)
        started_at = progress_state.snapshot()["started_at"]
        progress_state.complete_round(1, 1, "普通驱离")
        completed_at = progress_state.snapshot()["updated_at"]
        message = progress_state.format_status(now=completed_at + 3600)
        expected = progress_state._format_duration(int(completed_at - started_at))
        self.assertIn(f"已运行：{expected}", message)
        self.assertIn("局外副本轮次（已完成）：1 / 1", message)

    def test_reset_returns_to_idle_without_task_context(self) -> None:
        progress_state.start_task("普通扼守", 4, 99)
        progress_state.increment_stage()
        progress_state.complete_round(1, 4)
        progress_state.reset()
        state = progress_state.snapshot()
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["mode"], "普通副本")
        self.assertEqual(state["completed_rounds"], 0)
        self.assertEqual(state["total_rounds"], 0)
        self.assertEqual(state["stage_count"], 0)
        self.assertFalse(state["stage_tracking_active"])
        self.assertIsNone(state["started_at"])


if __name__ == "__main__":
    unittest.main()
