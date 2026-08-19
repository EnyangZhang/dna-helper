"""Restore the user's foreground window after game input bursts."""

from __future__ import annotations

import ctypes
import json
import threading
import time
from ctypes import wintypes

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

import progress_state
import telegram_bot


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindowAsync.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.SetFocus.argtypes = [wintypes.HWND]
_user32.SetFocus.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.BOOL,
]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.ClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
_user32.ClipCursor.restype = wintypes.BOOL


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


_user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_user32.MapVirtualKeyW.restype = wintypes.UINT
_user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_SW_RESTORE = 9
_SKILL_FOREGROUND_SETTLE_SECONDS = 0.1
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_MAPVK_VK_TO_VSC = 0
_BACKGROUND_KEY_HOLD_SECONDS = 0.03
_state_lock = threading.Lock()
_fallback_hwnd = 0
_fallback_cursor_position: tuple[int, int] | None = None
_game_hwnd = 0
_watcher_started = False
_restore_in_progress = False
_e_sequence_lock = threading.Lock()
_e_sequence_progress: dict[tuple[int, str], int] = {}
_hybrid_skill_lock = threading.Lock()
_hybrid_skill_ready_hwnd = 0


def _next_e_sequence_index(task_id: int, node_name: str, total: int) -> int:
    """Track one pipeline-repeated E sequence and return its 1-based index."""
    key = (task_id, node_name)
    with _e_sequence_lock:
        current = _e_sequence_progress.get(key, 0) + 1
        if current >= total:
            _e_sequence_progress.pop(key, None)
        else:
            _e_sequence_progress[key] = current
    return current


def _foreground_window() -> int:
    return int(_user32.GetForegroundWindow() or 0)


def _controller_hwnd(context: Context) -> int:
    info = context.tasker.controller.info
    return int(info.get("hwnd", 0)) if isinstance(info, dict) else 0


def _is_restore_target(hwnd: int, game_hwnd: int) -> bool:
    return bool(
        hwnd
        and hwnd != game_hwnd
        and _user32.IsWindow(hwnd)
        and _user32.IsWindowVisible(hwnd)
    )


def _cursor_position() -> tuple[int, int] | None:
    point = _POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def _remember_restore_target(
    hwnd: int, game_hwnd: int
) -> tuple[int, tuple[int, int] | None]:
    global _fallback_cursor_position, _fallback_hwnd
    with _state_lock:
        if not _restore_in_progress and _is_restore_target(hwnd, game_hwnd):
            position = _cursor_position()
            if hwnd != _fallback_hwnd or position is not None:
                _fallback_cursor_position = position
            _fallback_hwnd = hwnd
        if not _is_restore_target(_fallback_hwnd, game_hwnd):
            return 0, None
        return _fallback_hwnd, _fallback_cursor_position


def _remember_window(hwnd: int, game_hwnd: int) -> int:
    restore_hwnd, _ = _remember_restore_target(hwnd, game_hwnd)
    return restore_hwnd


def _watch_foreground_window() -> None:
    while True:
        with _state_lock:
            game_hwnd = _game_hwnd
        _remember_window(_foreground_window(), game_hwnd)
        time.sleep(0.1)


def _start_foreground_watcher(game_hwnd: int) -> None:
    global _game_hwnd, _watcher_started
    with _state_lock:
        _game_hwnd = game_hwnd
        if _watcher_started:
            return
        _watcher_started = True
    threading.Thread(
        target=_watch_foreground_window,
        name="dna-focus-guard",
        daemon=True,
    ).start()


def _release_cursor_clip() -> None:
    _user32.ClipCursor(None)


def _restore_cursor(position: tuple[int, int]) -> bool:
    return bool(_user32.SetCursorPos(position[0], position[1]))


def _send_background_key(hwnd: int, key: int) -> bool:
    """Post one key press to the initialized game window without focusing it."""
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    scan_code = int(_user32.MapVirtualKeyW(key, _MAPVK_VK_TO_VSC))
    down_lparam = 1 | (scan_code << 16)
    up_lparam = down_lparam | (1 << 30) | (1 << 31)
    if not _user32.PostMessageW(hwnd, _WM_KEYDOWN, key, down_lparam):
        return False
    time.sleep(_BACKGROUND_KEY_HOLD_SECONDS)
    return bool(_user32.PostMessageW(hwnd, _WM_KEYUP, key, up_lparam))


def _reset_hybrid_skill_ready() -> None:
    global _hybrid_skill_ready_hwnd
    with _hybrid_skill_lock:
        _hybrid_skill_ready_hwnd = 0


def _mark_hybrid_skill_ready(hwnd: int) -> None:
    global _hybrid_skill_ready_hwnd
    with _hybrid_skill_lock:
        _hybrid_skill_ready_hwnd = int(hwnd)


def _is_hybrid_skill_ready(hwnd: int) -> bool:
    with _hybrid_skill_lock:
        return bool(hwnd and _hybrid_skill_ready_hwnd == int(hwnd))


def _set_restore_in_progress(value: bool) -> None:
    global _restore_in_progress
    with _state_lock:
        _restore_in_progress = value


def _restore_window(hwnd: int) -> bool:
    if not _is_restore_target(hwnd, 0):
        return False

    foreground = _foreground_window()
    current_thread = int(_kernel32.GetCurrentThreadId())
    thread_ids = []
    for window in (foreground, hwnd):
        if not window:
            continue
        thread_id = int(_user32.GetWindowThreadProcessId(window, None))
        if thread_id and thread_id != current_thread and thread_id not in thread_ids:
            if _user32.AttachThreadInput(current_thread, thread_id, True):
                thread_ids.append(thread_id)

    try:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindowAsync(hwnd, _SW_RESTORE)
        _user32.BringWindowToTop(hwnd)
        activated = bool(_user32.SetForegroundWindow(hwnd))
        if activated:
            _user32.SetFocus(hwnd)
        return activated or _foreground_window() == hwnd
    finally:
        for thread_id in reversed(thread_ids):
            _user32.AttachThreadInput(current_thread, thread_id, False)


def _restore_window_and_cursor(
    hwnd: int, cursor_position: tuple[int, int] | None
) -> bool:
    _set_restore_in_progress(True)
    try:
        _release_cursor_clip()
        if not hwnd or not _restore_window(hwnd):
            return False
        return cursor_position is None or _restore_cursor(cursor_position)
    finally:
        _set_restore_in_progress(False)


def _activate_game_for_skill(game_hwnd: int) -> bool:
    """Put the game in front before the first real E/Q input."""
    if not game_hwnd or not _user32.IsWindow(game_hwnd):
        return False
    if _foreground_window() != game_hwnd and not _restore_window(game_hwnd):
        return False
    time.sleep(_SKILL_FOREGROUND_SETTLE_SECONDS)
    return True


def _parse_params(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@AgentServer.custom_action("focus_guard_start")
class FocusGuardStart(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        game_hwnd = _controller_hwnd(context)
        _remember_window(_foreground_window(), game_hwnd)
        _start_foreground_watcher(game_hwnd)
        progress_mode = str(params.get("progress_mode", "普通扼守"))
        task_started = progress_state.start_task(
            progress_mode,
            int(params.get("progress_total", 1)),
            int(params.get("progress_stage_total", 99)),
            int(getattr(argv.task_detail, "task_id", 0)),
        )
        if task_started:
            _reset_hybrid_skill_ready()
            telegram_bot.notify_task_started(progress_mode)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("focus_guard_action")
class FocusGuardAction(CustomAction):
    background_key_input = False
    force_game_foreground = False

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        kind = params.get("kind")
        repeat = min(10, max(1, int(params.get("repeat", 3))))
        interval_ms = min(1000, max(0, int(params.get("interval_ms", 50))))
        restore_delay_ms = min(
            1000, max(0, int(params.get("restore_delay_ms", 100)))
        )
        background_key_input = bool(self.background_key_input and kind == "key")
        force_game_foreground = bool(self.force_game_foreground and kind == "key")
        should_restore = bool(params.get("restore", True)) and not background_key_input

        if kind == "click":
            target = params.get("target", [])
            if not (
                isinstance(target, list)
                and len(target) == 2
                and all(isinstance(value, int) for value in target)
            ):
                return CustomAction.RunResult(success=False)
            proxy_node = {
                (920, 480): "RewardConfirmThirdPageClick2",
                (620, 607): "RewardConfirmFirstPageClick2",
                (900, 500): "RewardConfirmContinueChallengeClick2",
                (920, 640): "CipherExpelAgainClick2",
                (770, 490): "NormalEndlessStartChallengeClick2",
                (640, 505): "NormalEndlessConfirmChoiceClick2",
            }.get(tuple(target))
            if not proxy_node:
                return CustomAction.RunResult(success=False)
        elif kind == "key":
            key = params.get("key")
            if not isinstance(key, int):
                return CustomAction.RunResult(success=False)
            proxy_node = {
                69: "FocusGuardEKeyProxy",
                81: "FocusGuardQKeyProxy",
            }.get(key)
            if not proxy_node:
                return CustomAction.RunResult(success=False)
        else:
            return CustomAction.RunResult(success=False)

        e_sequence_index = 0
        e_sequence_total = 0
        if kind == "key" and key == 69:
            e_sequence_total = max(1, int(params.get("sequence_total", 1)))
            task_id = int(getattr(argv.task_detail, "task_id", 0))
            e_sequence_index = _next_e_sequence_index(
                task_id, argv.node_name, e_sequence_total
            )

        game_hwnd = _controller_hwnd(context)
        restore_hwnd, restore_cursor_position = _remember_restore_target(
            _foreground_window(), game_hwnd
        )
        if force_game_foreground and not _activate_game_for_skill(game_hwnd):
            return CustomAction.RunResult(success=False)
        succeeded = True

        try:
            for index in range(repeat):
                if kind == "key" and key == 69:
                    log_proxy = (
                        "FocusGuardEBackgroundLogProxy"
                        if background_key_input
                        else "FocusGuardEKeyProxy"
                    )
                    log_ready = context.override_pipeline(
                        {
                            log_proxy: {
                                "focus": {
                                    "Node.Action.Succeeded": {
                                        "content": (
                                            f"[角色] E 连续点击：第 {e_sequence_index} / "
                                            f"{e_sequence_total} 次已发送"
                                        ),
                                        "display": ["log"],
                                    }
                                }
                            }
                        }
                    )
                    succeeded = succeeded and log_ready
                if background_key_input:
                    input_succeeded = _send_background_key(game_hwnd, key)
                    succeeded = succeeded and input_succeeded
                    if input_succeeded and key == 69:
                        detail = context.run_action("FocusGuardEBackgroundLogProxy")
                        succeeded = succeeded and detail is not None and detail.success
                else:
                    detail = context.run_action(proxy_node)
                    succeeded = succeeded and detail is not None and detail.success
                if index + 1 < repeat and interval_ms:
                    time.sleep(interval_ms / 1000)
            if should_restore and restore_delay_ms:
                time.sleep(restore_delay_ms / 1000)
        finally:
            if should_restore:
                _restore_window_and_cursor(restore_hwnd, restore_cursor_position)

        if succeeded:
            progress_event = params.get("progress_event")
            infinite_99_completed = False
            if progress_event == "continue_challenge":
                infinite_99_completed = progress_state.increment_stage(
                    dedupe_window_seconds=5.0
                )
            elif progress_event == "next_round_started":
                progress_state.start_next_round()
            elif progress_event == "cipher_cycle_completed":
                infinite_99_completed = progress_state.advance_cipher_cycle()
            if infinite_99_completed:
                telegram_bot.notify_infinite_99_completed()

        return CustomAction.RunResult(success=succeeded)


class _ForegroundPrimingSkillAction(FocusGuardAction):
    """Use one guaranteed foreground E/Q action and then restore focus."""

    force_game_foreground = True


class _BackgroundSkillAction(FocusGuardAction):
    """Use background messages only after foreground priming succeeded."""

    background_key_input = True


@AgentServer.custom_action("hybrid_skill_action")
class HybridSkillAction(CustomAction):
    """First E/Q is foreground with restore; later E/Q uses background input."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        game_hwnd = _controller_hwnd(context)
        if _is_hybrid_skill_ready(game_hwnd):
            background_result = _BackgroundSkillAction().run(context, argv)
            if background_result.success:
                return background_result
            _reset_hybrid_skill_ready()

        foreground_result = _ForegroundPrimingSkillAction().run(context, argv)
        if foreground_result.success:
            _mark_hybrid_skill_ready(game_hwnd)
        return foreground_result
