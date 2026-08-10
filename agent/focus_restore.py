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
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_SW_RESTORE = 9
_state_lock = threading.Lock()
_fallback_hwnd = 0
_game_hwnd = 0
_watcher_started = False


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


def _remember_window(hwnd: int, game_hwnd: int) -> int:
    global _fallback_hwnd
    with _state_lock:
        if _is_restore_target(hwnd, game_hwnd):
            _fallback_hwnd = hwnd
        return _fallback_hwnd if _is_restore_target(_fallback_hwnd, game_hwnd) else 0


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
        game_hwnd = _controller_hwnd(context)
        _remember_window(_foreground_window(), game_hwnd)
        _start_foreground_watcher(game_hwnd)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("focus_guard_action")
class FocusGuardAction(CustomAction):
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
        should_restore = bool(params.get("restore", True))

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

        game_hwnd = _controller_hwnd(context)
        restore_hwnd = _remember_window(_foreground_window(), game_hwnd)
        succeeded = True

        try:
            for index in range(repeat):
                detail = context.run_action(proxy_node)
                succeeded = succeeded and detail is not None and detail.success
                if index + 1 < repeat and interval_ms:
                    time.sleep(interval_ms / 1000)
            if should_restore and restore_delay_ms:
                time.sleep(restore_delay_ms / 1000)
        finally:
            if should_restore:
                _release_cursor_clip()
                if restore_hwnd:
                    _restore_window(restore_hwnd)

        return CustomAction.RunResult(success=succeeded)
