from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import progress_state  # noqa: E402


class ProgressStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_path = progress_state._STATUS_PATH
        self.original_state = progress_state.snapshot()
        progress_state._STATUS_PATH = Path(self.temporary.name) / "status.json"

    def tearDown(self) -> None:
        progress_state._STATUS_PATH = self.original_path
        with progress_state._lock:
            progress_state._state.clear()
            progress_state._state.update(self.original_state)
        self.temporary.cleanup()

    def test_tracks_logical_stage_and_completed_outer_rounds(self) -> None:
        progress_state.start_task("普通扼守", 3, 99)
        progress_state.increment_stage()
        progress_state.increment_stage()
        state = progress_state.snapshot()
        self.assertEqual((state["completed_rounds"], state["total_rounds"]), (0, 3))
        self.assertEqual(state["stage_count"], 2)

        progress_state.complete_round(1, 3, "普通扼守")
        self.assertEqual(progress_state.snapshot()["status"], "waiting_next_round")
        progress_state.start_next_round()
        state = progress_state.snapshot()
        self.assertEqual(state["completed_rounds"], 1)
        self.assertEqual(state["stage_count"], 0)

    def test_repeated_entry_does_not_reset_same_cipher_task(self) -> None:
        self.assertTrue(progress_state.start_task("密函无尽", 0, 0, task_id=88))
        progress_state.advance_cipher_cycle()
        self.assertFalse(progress_state.start_task("密函无尽", 0, 0, task_id=88))
        state = progress_state.snapshot()
        self.assertEqual(state["stage_count"], 1)

        message = progress_state.format_status()
        self.assertIn("局内轮次：1", message)

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
        started_at = progress_state.snapshot()["started_at"]
        message = progress_state.format_status(now=started_at + 3674)
        self.assertIn("局外副本轮次（已完成）：0 / 6", message)
        self.assertIn("局内轮次：0 / 99", message)
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


if __name__ == "__main__":
    unittest.main()
