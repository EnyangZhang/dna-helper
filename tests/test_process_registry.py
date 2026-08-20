from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import main  # noqa: E402
import process_registry  # noqa: E402


class ProcessRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_root = tempfile.TemporaryDirectory()
        self._registry_dir = (
            Path(self._temp_root.name) / "config" / "agent-processes"
        )
        self._registry_patcher = patch.object(
            process_registry,
            "_REGISTRY_DIR",
            self._registry_dir,
        )
        self._registry_patcher.start()
        self.addCleanup(self._registry_patcher.stop)
        self.addCleanup(self._temp_root.cleanup)

    def _patch_identity(self) -> None:
        self._pid_patcher = patch.object(process_registry.os, "getpid", return_value=1234)
        self._time_patcher = patch.object(
            process_registry,
            "_get_process_creation_time_100ns",
            return_value=133700000000000000,
        )
        self._exe_patcher = patch.object(
            process_registry.sys,
            "executable",
            r"C:\\Python311\\python.exe",
        )
        self._pid_patcher.start()
        self._time_patcher.start()
        self._exe_patcher.start()
        self.addCleanup(self._pid_patcher.stop)
        self.addCleanup(self._time_patcher.stop)
        self.addCleanup(self._exe_patcher.stop)

    def test_schema_pid_and_creation_time_are_written(self) -> None:
        self._patch_identity()
        marker = process_registry.register_current_process()
        self.assertEqual(marker, self._registry_dir / "1234.json")

        with marker.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)

        self.assertEqual(loaded["schema_version"], 1)
        self.assertIsInstance(loaded["schema_version"], int)
        self.assertEqual(loaded["pid"], 1234)
        self.assertIsInstance(loaded["pid"], int)
        self.assertGreater(loaded["pid"], 0)
        self.assertLess(loaded["pid"], 2**32)
        self.assertEqual(loaded["creation_time_100ns"], 133700000000000000)
        self.assertEqual(loaded["executable_path"], r"C:\Python311\python.exe")
        self.assertLess(marker.stat().st_size, process_registry.MAX_MARKER_BYTES)

    def test_register_uses_atomic_replace(self) -> None:
        self._patch_identity()

        with patch.object(
            process_registry.os,
            "replace",
            wraps=process_registry.os.replace,
        ) as replace:
            marker = process_registry.register_current_process()

        self.assertTrue(self._registry_dir.exists())
        self.assertEqual(len(list(self._registry_dir.iterdir())), 1)
        self.assertEqual(marker, self._registry_dir / "1234.json")
        self.assertEqual(replace.call_count, 1)
        temp_path = Path(replace.call_args[0][0])
        target_path = Path(replace.call_args[0][1])
        self.assertNotEqual(temp_path.name, target_path.name)
        self.assertEqual(target_path, marker)
        self.assertFalse(temp_path.exists())
        self.assertLess(marker.stat().st_size, process_registry.MAX_MARKER_BYTES)

    def test_unregister_removes_marker(self) -> None:
        self._patch_identity()
        marker = process_registry.register_current_process()
        self.assertTrue(marker.exists())

        self.assertTrue(process_registry.unregister_current_process(1234))
        self.assertFalse(marker.exists())

    def test_unregister_is_idempotent(self) -> None:
        self._patch_identity()
        marker = process_registry.register_current_process()
        self.assertTrue(process_registry.unregister_current_process(1234))
        self.assertFalse(process_registry.unregister_current_process(1234))
        self.assertFalse(marker.exists())

    def test_unregister_rejects_reparse_registry_ancestor(self) -> None:
        self._patch_identity()
        marker = process_registry.register_current_process()

        with patch.object(
            process_registry,
            "_is_reparse_point",
            side_effect=lambda path: path == self._registry_dir.parent,
        ):
            with self.assertRaises(process_registry.ProcessRegistryError):
                process_registry.unregister_current_process(1234)

        self.assertTrue(marker.exists())

    def test_anomalous_registry_path_is_rejected(self) -> None:
        self._patch_identity()

        with patch.object(process_registry, "_is_reparse_point", return_value=True):
            with self.assertRaises(process_registry.ProcessRegistryError):
                process_registry.register_current_process()

    def test_broken_symlink_target_is_not_treated_as_missing(self) -> None:
        target = Mock()
        target.is_symlink.return_value = True
        target.exists.return_value = False

        with patch.object(process_registry, "_is_reparse_point", return_value=False):
            self.assertFalse(process_registry._is_normal_file_target(target))

        target.exists.assert_not_called()

    def test_ancestor_reparse_point_rejects_registration_without_creating_subdirs(self) -> None:
        self._patch_identity()
        self._registry_dir.parent.mkdir()

        with patch.object(
            process_registry,
            "_is_reparse_point",
            side_effect=lambda path: path == self._registry_dir.parent,
        ):
            with self.assertRaises(process_registry.ProcessRegistryError):
                process_registry.register_current_process()

        self.assertFalse(self._registry_dir.exists())
        self.assertEqual(len(list(self._registry_dir.parent.iterdir())), 0)

    def test_temporary_file_is_cleaned_up_on_write_failure(self) -> None:
        self._patch_identity()

        with patch.object(process_registry.os, "fsync", side_effect=OSError("write fail")):
            with self.assertRaises(OSError):
                process_registry.register_current_process()

        self.assertFalse(process_registry._marker_path(1234).exists())
        self.assertFalse(
            any(
                p.name.startswith(".tmp-agent-1234-")
                for p in self._registry_dir.iterdir()
                if p.is_file()
            )
        )


class MainLifecycleTest(unittest.TestCase):
    def test_main_unregisters_if_start_up_fails(self) -> None:
        events: list[str] = []

        with (
            patch.object(main.AgentServer, "start_up", side_effect=RuntimeError("start_up fail")),
            patch.object(main.AgentServer, "join"),
            patch.object(main.AgentServer, "shut_down", side_effect=lambda: events.append("shutdown")),
            patch.object(main.parent_watchdog, "start_parent_watchdog"),
            patch.object(main.telegram_bot, "stop", side_effect=lambda: events.append("bot-stop")),
            patch.object(main.process_registry, "register_current_process"),
            patch.object(
                main.process_registry,
                "unregister_current_process",
                side_effect=lambda: events.append("unregister"),
            ),
        ):
            original_argv = sys.argv
            sys.argv = ["agent/main.py", "socket"]
            try:
                with self.assertRaises(RuntimeError):
                    main.main()
            finally:
                sys.argv = original_argv

        self.assertIn("unregister", events)
        self.assertNotIn("shutdown", events)
        self.assertNotIn("bot-stop", events)

    def test_main_unregisters_after_stop_called(self) -> None:
        events: list[str] = []

        with (
            patch.object(main.AgentServer, "start_up"),
            patch.object(main.AgentServer, "join"),
            patch.object(main.AgentServer, "shut_down", side_effect=lambda: events.append("shutdown")),
            patch.object(main.parent_watchdog, "start_parent_watchdog"),
            patch.object(main.telegram_bot, "stop", side_effect=lambda: events.append("bot-stop")),
            patch.object(main.process_registry, "register_current_process"),
            patch.object(
                main.process_registry,
                "unregister_current_process",
                side_effect=lambda: events.append("unregister"),
            ),
        ):
            original_argv = sys.argv
            sys.argv = ["agent/main.py", "socket"]
            try:
                code = main.main()
            finally:
                sys.argv = original_argv

        self.assertEqual(code, 0)
        self.assertIn("bot-stop", events)
        self.assertIn("shutdown", events)
        self.assertIn("unregister", events)
        self.assertLess(events.index("shutdown"), events.index("unregister"))

    def test_main_unregisters_even_if_shutdown_fails(self) -> None:
        events: list[str] = []

        with (
            patch.object(main.AgentServer, "start_up"),
            patch.object(main.AgentServer, "join"),
            patch.object(
                main.AgentServer,
                "shut_down",
                side_effect=RuntimeError("shutdown fail"),
            ),
            patch.object(main.parent_watchdog, "start_parent_watchdog"),
            patch.object(main.telegram_bot, "stop"),
            patch.object(main.process_registry, "register_current_process"),
            patch.object(
                main.process_registry,
                "unregister_current_process",
                side_effect=lambda: events.append("unregister"),
            ),
        ):
            original_argv = sys.argv
            sys.argv = ["agent/main.py", "socket"]
            try:
                with self.assertRaises(RuntimeError):
                    main.main()
            finally:
                sys.argv = original_argv

        self.assertEqual(events, ["unregister"])


if __name__ == "__main__":
    unittest.main()
