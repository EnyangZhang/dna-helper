"""Restore the user's foreground window after game input bursts."""

from __future__ import annotations

import ctypes
import json
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

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
_user32.mouse_event.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
_user32.mouse_event.restype = None
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
_MAX_KEY_HOLD_MS = 10000
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_FOREGROUND_MOUSE_MOVE_STEP_PX = 20
_FOREGROUND_MOUSE_MOVE_INTERVAL_SECONDS = 1.0 / 5
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
_hybrid_fishing_ready_hwnd = 0
_skill_input_group_lock = threading.RLock()


@dataclass(frozen=True)
class _SkillInputGroup:
    game_hwnd: int
    restore_hwnd: int
    restore_cursor_position: tuple[int, int] | None
    background_key_input: bool


_skill_input_groups: dict[int, _SkillInputGroup] = {}


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


def _send_foreground_mouse_move(dx: int, dy: int) -> bool:
    """Send visible, evenly paced relative gameplay-camera movement."""
    remaining_x, remaining_y = dx, dy
    while remaining_x or remaining_y:
        step_x = max(
            -_FOREGROUND_MOUSE_MOVE_STEP_PX,
            min(_FOREGROUND_MOUSE_MOVE_STEP_PX, remaining_x),
        )
        step_y = max(
            -_FOREGROUND_MOUSE_MOVE_STEP_PX,
            min(_FOREGROUND_MOUSE_MOVE_STEP_PX, remaining_y),
        )
        ctypes.set_last_error(0)
        _user32.mouse_event(
            _MOUSEEVENTF_MOVE,
            step_x & 0xFFFFFFFF,
            step_y & 0xFFFFFFFF,
            0,
            None,
        )
        if ctypes.get_last_error() != 0:
            return False
        remaining_x -= step_x
        remaining_y -= step_y
        if remaining_x or remaining_y:
            time.sleep(_FOREGROUND_MOUSE_MOVE_INTERVAL_SECONDS)
    return True


def _send_foreground_mouse_button(button: str, pressed: bool) -> bool:
    """Send a physical mouse button transition while the game owns focus."""
    flags = {
        ("left", True): _MOUSEEVENTF_LEFTDOWN,
        ("left", False): _MOUSEEVENTF_LEFTUP,
        ("right", True): _MOUSEEVENTF_RIGHTDOWN,
        ("right", False): _MOUSEEVENTF_RIGHTUP,
    }
    flag = flags.get((button, pressed))
    if flag is None:
        return False
    ctypes.set_last_error(0)
    _user32.mouse_event(flag, 0, 0, 0, None)
    return ctypes.get_last_error() == 0


def _remember_restore_target(
    hwnd: int, game_hwnd: int, *, keep_game_focused: bool = False
) -> tuple[int, tuple[int, int] | None]:
    global _fallback_cursor_position, _fallback_hwnd
    with _state_lock:
        if keep_game_focused and hwnd and hwnd == game_hwnd:
            return 0, None
        if not _restore_in_progress and _is_restore_target(hwnd, game_hwnd):
            position = _cursor_position()
            if hwnd != _fallback_hwnd or position is not None:
                _fallback_cursor_position = position
            _fallback_hwnd = hwnd
        if not _is_restore_target(_fallback_hwnd, game_hwnd):
            return 0, None
        return _fallback_hwnd, _fallback_cursor_position


def _initialize_restore_target(hwnd: int, game_hwnd: int) -> int:
    """Start a task without carrying a stale non-game target into a game-focused run."""
    global _fallback_cursor_position, _fallback_hwnd
    if hwnd and hwnd == game_hwnd:
        with _state_lock:
            _fallback_hwnd = 0
            _fallback_cursor_position = None
        return 0
    return _remember_window(hwnd, game_hwnd)


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


def _reset_hybrid_fishing_ready() -> None:
    global _hybrid_fishing_ready_hwnd
    with _hybrid_skill_lock:
        _hybrid_fishing_ready_hwnd = 0


def _mark_hybrid_fishing_ready(hwnd: int) -> None:
    global _hybrid_fishing_ready_hwnd
    with _hybrid_skill_lock:
        _hybrid_fishing_ready_hwnd = int(hwnd)


def _is_hybrid_fishing_ready(hwnd: int) -> bool:
    with _hybrid_skill_lock:
        return bool(hwnd and _hybrid_fishing_ready_hwnd == int(hwnd))


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


def _task_id(argv: CustomAction.RunArg) -> int:
    return int(getattr(argv.task_detail, "task_id", 0))


def _finish_skill_input_group(task_id: int, restore_delay_ms: int = 100) -> bool:
    """Close one E/Q group and restore the user only after the full group ends."""
    with _skill_input_group_lock:
        group = _skill_input_groups.pop(task_id, None)
    if group is None or group.background_key_input:
        return True
    if restore_delay_ms:
        time.sleep(max(0, restore_delay_ms) / 1000)
    _restore_window_and_cursor(group.restore_hwnd, group.restore_cursor_position)
    return True


def _finish_all_skill_input_groups() -> None:
    with _skill_input_group_lock:
        task_ids = list(_skill_input_groups)
    for task_id in task_ids:
        _finish_skill_input_group(task_id, restore_delay_ms=0)


def _begin_skill_input_group(
    context: Context,
    argv: CustomAction.RunArg,
    *,
    background_key_input: bool,
) -> _SkillInputGroup | None:
    """Start or reuse one foreground/background group for all E/Q inputs."""
    task_id = _task_id(argv)
    game_hwnd = _controller_hwnd(context)
    with _skill_input_group_lock:
        existing = _skill_input_groups.get(task_id)
    if existing is not None:
        if (
            existing.game_hwnd == game_hwnd
            and existing.background_key_input == background_key_input
        ):
            return existing
        _finish_skill_input_group(task_id, restore_delay_ms=0)

    if not game_hwnd:
        return None
    if background_key_input:
        group = _SkillInputGroup(game_hwnd, 0, None, True)
    else:
        restore_hwnd, restore_cursor_position = _remember_restore_target(
            _foreground_window(), game_hwnd, keep_game_focused=True
        )
        if not _activate_game_for_skill(game_hwnd):
            return None
        group = _SkillInputGroup(
            game_hwnd,
            restore_hwnd,
            restore_cursor_position,
            False,
        )
    with _skill_input_group_lock:
        _skill_input_groups[task_id] = group
    return group


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


def _apply_progress_event(params: dict) -> None:
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
    elif progress_event == "fishing_caught":
        progress_state.record_fishing_catch()
    if infinite_99_completed:
        telegram_bot.notify_infinite_99_completed()


def _safe_user_log(message: str) -> None:
    """Keep a broken log stream from changing an already-sent game action."""
    try:
        print(message, flush=True)
    except (OSError, UnicodeError):
        return


def _log_fishing_action(params: dict, background: bool) -> None:
    """Emit one user-facing summary after a successful fishing input."""
    key_label = str(params.get("fishing_log_key", ""))
    if key_label not in {"Space", "E", "Esc"}:
        return
    input_mode = "后台" if background else "前台"
    if params.get("progress_event") != "fishing_caught":
        _safe_user_log(f"[钓鱼挂机] {key_label} 已发送（{input_mode}）")
        return
    state = progress_state.snapshot()
    current = int(state.get("stage_count", 0))
    total = int(state.get("total_rounds", 0))
    _safe_user_log(
        f"[钓鱼挂机] {key_label} 已发送（{input_mode}），"
        f"钓鱼数量：{current} / {total}"
    )
    if state.get("status") == "completed":
        _safe_user_log(
            f"[钓鱼挂机] 已达到设定数量：{current} / {total}，任务完成"
        )


@AgentServer.custom_action("focus_guard_start")
class FocusGuardStart(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        game_hwnd = _controller_hwnd(context)
        _initialize_restore_target(_foreground_window(), game_hwnd)
        _start_foreground_watcher(game_hwnd)
        progress_mode = str(params.get("progress_mode", "普通扼守"))
        task_started = progress_state.start_task(
            progress_mode,
            int(params.get("progress_total", 1)),
            int(params.get("progress_stage_total", 99)),
            int(getattr(argv.task_detail, "task_id", 0)),
        )
        if task_started:
            _finish_all_skill_input_groups()
            _reset_hybrid_skill_ready()
            _reset_hybrid_fishing_ready()
            telegram_bot.notify_task_started(progress_mode)
            if progress_mode == "钓鱼挂机":
                state = progress_state.snapshot()
                _safe_user_log(
                    "[钓鱼挂机] 任务已启动，钓鱼数量："
                    f"{int(state.get('stage_count', 0))} / "
                    f"{int(state.get('total_rounds', 0))}"
                )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("progress_dungeon_entered")
class ProgressDungeonEntered(CustomAction):
    """Mark stage 1 only after the in-dungeon combat HUD is confirmed."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        return CustomAction.RunResult(success=progress_state.mark_dungeon_entered())


@AgentServer.custom_action("focus_guard_finalize")
class FocusGuardFinalize(CustomAction):
    """Restore focus and record progress after native mouse clicks."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        restore_delay_ms = min(
            1000, max(0, int(params.get("restore_delay_ms", 100)))
        )
        game_hwnd = _controller_hwnd(context)
        restore_hwnd, restore_cursor_position = _remember_restore_target(
            _foreground_window(), game_hwnd
        )
        if restore_delay_ms:
            time.sleep(restore_delay_ms / 1000)
        _restore_window_and_cursor(restore_hwnd, restore_cursor_position)
        _apply_progress_event(params)
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
        repeat = max(1, int(params.get("repeat", 3)))
        interval_ms = max(0, int(params.get("interval_ms", 50)))
        restore_delay_ms = min(
            1000, max(0, int(params.get("restore_delay_ms", 100)))
        )
        skill_input_group = bool(params.get("skill_input_group", False))
        background_key_input = bool(self.background_key_input and kind == "key")
        force_game_foreground = bool(
            (self.force_game_foreground and kind == "key")
            or kind == "input_sequence"
        )
        should_restore = (
            bool(params.get("restore", True))
            and not background_key_input
            and not skill_input_group
        )

        if kind == "key":
            key = params.get("key")
            if not isinstance(key, int):
                return CustomAction.RunResult(success=False)
            requested_proxy = params.get("proxy_node")
            allowed_proxy = {
                (32, "FishingSpaceKeyProxy"),
                (69, "FishingEKeyProxy"),
                (27, "FishingEscapeKeyProxy"),
            }
            if requested_proxy is not None and (key, requested_proxy) not in allowed_proxy:
                return CustomAction.RunResult(success=False)
            proxy_node = {
                32: "FishingSpaceKeyProxy",
                69: "FocusGuardEKeyProxy",
                81: "FocusGuardQKeyProxy",
                27: "CoinAFKEscapeProxy",
            }.get(key)
            if requested_proxy is not None:
                proxy_node = requested_proxy
            if not proxy_node:
                return CustomAction.RunResult(success=False)
        elif kind == "key_hold":
            key = params.get("key")
            hold_ms = min(_MAX_KEY_HOLD_MS, max(1, int(params.get("hold_ms", 1000))))
            if not isinstance(key, int):
                return CustomAction.RunResult(success=False)
            proxy_node = None
        elif kind == "key_sequence":
            raw_steps = params.get("steps")
            if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 20:
                return CustomAction.RunResult(success=False)
            key_sequence = []
            for step in raw_steps:
                if not isinstance(step, dict):
                    return CustomAction.RunResult(success=False)
                if "delay_ms" in step:
                    delay_ms = step.get("delay_ms")
                    if not isinstance(delay_ms, int) or not 0 <= delay_ms <= 5000:
                        return CustomAction.RunResult(success=False)
                    key_sequence.append(("delay", delay_ms, None))
                    continue
                step_key = step.get("key")
                if not isinstance(step_key, int):
                    return CustomAction.RunResult(success=False)
                if "hold_ms" in step:
                    step_hold_ms = step.get("hold_ms")
                    if (
                        not isinstance(step_hold_ms, int)
                        or not 1 <= step_hold_ms <= _MAX_KEY_HOLD_MS
                    ):
                        return CustomAction.RunResult(success=False)
                    key_sequence.append(("hold", step_key, step_hold_ms))
                    continue
                step_proxy = {
                    69: "FocusGuardEKeyProxy",
                    81: "FocusGuardQKeyProxy",
                    27: "CoinAFKEscapeProxy",
                }.get(step_key)
                if not step_proxy:
                    return CustomAction.RunResult(success=False)
                key_sequence.append(("key", step_key, step_proxy))
            proxy_node = None
        elif kind == "input_sequence":
            raw_steps = params.get("steps")
            if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 30:
                return CustomAction.RunResult(success=False)
            input_sequence = []
            parsed_keys_down: set[int] = set()
            parsed_mouse_down: set[str] = set()
            for step in raw_steps:
                if not isinstance(step, dict) or len(step) != 1:
                    return CustomAction.RunResult(success=False)
                if "delay_ms" in step:
                    delay_ms = step.get("delay_ms")
                    if not isinstance(delay_ms, int) or not 0 <= delay_ms <= 10000:
                        return CustomAction.RunResult(success=False)
                    input_sequence.append(("delay", delay_ms))
                    continue
                if "key_down" in step:
                    step_key = step.get("key_down")
                    if (
                        not isinstance(step_key, int)
                        or not 1 <= step_key <= 255
                        or step_key in parsed_keys_down
                    ):
                        return CustomAction.RunResult(success=False)
                    parsed_keys_down.add(step_key)
                    input_sequence.append(("key_down", step_key))
                    continue
                if "key_up" in step:
                    step_key = step.get("key_up")
                    if not isinstance(step_key, int) or step_key not in parsed_keys_down:
                        return CustomAction.RunResult(success=False)
                    parsed_keys_down.remove(step_key)
                    input_sequence.append(("key_up", step_key))
                    continue
                if "key_press" in step:
                    step_key = step.get("key_press")
                    if not isinstance(step_key, int) or not 1 <= step_key <= 255:
                        return CustomAction.RunResult(success=False)
                    input_sequence.append(("key_press", step_key))
                    continue
                if "mouse_move" in step:
                    movement = step.get("mouse_move")
                    if (
                        not isinstance(movement, list)
                        or len(movement) != 2
                        or not all(isinstance(value, int) for value in movement)
                        or not all(-20000 <= value <= 20000 for value in movement)
                    ):
                        return CustomAction.RunResult(success=False)
                    input_sequence.append(("mouse_move", tuple(movement)))
                    continue
                if "mouse_down" in step:
                    button = step.get("mouse_down")
                    if button not in {"left", "right"} or button in parsed_mouse_down:
                        return CustomAction.RunResult(success=False)
                    parsed_mouse_down.add(button)
                    input_sequence.append(("mouse_down", button))
                    continue
                if "mouse_up" in step:
                    button = step.get("mouse_up")
                    if button not in parsed_mouse_down:
                        return CustomAction.RunResult(success=False)
                    parsed_mouse_down.remove(button)
                    input_sequence.append(("mouse_up", button))
                    continue
                return CustomAction.RunResult(success=False)
            if parsed_keys_down or parsed_mouse_down:
                return CustomAction.RunResult(success=False)
            proxy_node = None
        else:
            return CustomAction.RunResult(success=False)

        track_e_sequence = bool(params.get("track_e_sequence", True))
        e_sequence_index = 0
        e_sequence_total = 0
        if kind == "key" and key == 69 and track_e_sequence:
            e_sequence_total = max(1, int(params.get("sequence_total", repeat)))
            e_sequence_index = _next_e_sequence_index(
                _task_id(argv), argv.node_name, e_sequence_total
            )

        game_hwnd = _controller_hwnd(context)
        if skill_input_group:
            group = _begin_skill_input_group(
                context,
                argv,
                background_key_input=background_key_input,
            )
            if group is None:
                return CustomAction.RunResult(success=False)
            background_key_input = group.background_key_input
            restore_hwnd, restore_cursor_position = 0, None
        else:
            restore_hwnd, restore_cursor_position = _remember_restore_target(
                _foreground_window(), game_hwnd, keep_game_focused=True
            )
            if force_game_foreground and not _activate_game_for_skill(game_hwnd):
                if should_restore:
                    _restore_window_and_cursor(restore_hwnd, restore_cursor_position)
                return CustomAction.RunResult(success=False)
        succeeded = True

        try:
            if kind == "key_hold":
                controller = context.tasker.controller
                key_down = controller.post_key_down(key).wait().succeeded
                succeeded = succeeded and key_down
                try:
                    if key_down:
                        time.sleep(hold_ms / 1000)
                finally:
                    key_up = controller.post_key_up(key).wait().succeeded
                    succeeded = succeeded and key_up
            elif kind == "key_sequence":
                controller = context.tasker.controller
                for operation, value, detail_value in key_sequence:
                    if operation == "delay":
                        if value:
                            time.sleep(value / 1000)
                        continue
                    if operation == "hold":
                        key_down = controller.post_key_down(value).wait().succeeded
                        succeeded = succeeded and key_down
                        try:
                            if key_down:
                                time.sleep(detail_value / 1000)
                        finally:
                            key_up = controller.post_key_up(value).wait().succeeded
                            succeeded = succeeded and key_up
                        continue
                    detail = context.run_action(detail_value)
                    succeeded = succeeded and detail is not None and detail.success
            elif kind == "input_sequence":
                controller = context.tasker.controller
                held_inputs: list[tuple[str, int | str]] = []
                try:
                    for operation, value in input_sequence:
                        if operation == "delay":
                            if value:
                                time.sleep(int(value) / 1000)
                            continue
                        if operation == "key_down":
                            key_down = controller.post_key_down(value).wait().succeeded
                            succeeded = succeeded and key_down
                            if key_down:
                                held_inputs.append(("key", value))
                        elif operation == "key_up":
                            key_up = controller.post_key_up(value).wait().succeeded
                            succeeded = succeeded and key_up
                            if key_up:
                                held_inputs.remove(("key", value))
                        elif operation == "key_press":
                            succeeded = (
                                succeeded
                                and controller.post_click_key(value).wait().succeeded
                            )
                        elif operation == "mouse_move":
                            mouse_move = _activate_game_for_skill(
                                game_hwnd
                            ) and _send_foreground_mouse_move(*value)
                            succeeded = succeeded and mouse_move
                        elif operation == "mouse_down":
                            mouse_down = _activate_game_for_skill(
                                game_hwnd
                            ) and _send_foreground_mouse_button(
                                value, True
                            )
                            succeeded = succeeded and mouse_down
                            if mouse_down:
                                held_inputs.append(("mouse", value))
                        else:
                            mouse_up = _send_foreground_mouse_button(value, False)
                            succeeded = succeeded and mouse_up
                            if mouse_up:
                                held_inputs.remove(("mouse", value))
                        if not succeeded:
                            break
                finally:
                    for held_kind, held_value in reversed(held_inputs):
                        if held_kind == "key":
                            released = (
                                controller.post_key_up(held_value).wait().succeeded
                            )
                        else:
                            released = _send_foreground_mouse_button(
                                str(held_value), False
                            )
                        succeeded = succeeded and released
            for index in range(
                repeat
                if kind not in {"key_hold", "key_sequence", "input_sequence"}
                else 0
            ):
                if kind == "key" and key == 69 and track_e_sequence:
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
                                            f"[角色] E 连续点击：第 {e_sequence_index + index} / "
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
                    if input_succeeded and key == 69 and track_e_sequence:
                        detail = context.run_action("FocusGuardEBackgroundLogProxy")
                        succeeded = succeeded and detail is not None and detail.success
                else:
                    detail = context.run_action(proxy_node)
                    succeeded = succeeded and detail is not None and detail.success
                if not succeeded:
                    break
                if index + 1 < repeat and interval_ms:
                    time.sleep(interval_ms / 1000)
            if should_restore and restore_delay_ms:
                time.sleep(restore_delay_ms / 1000)
        finally:
            if should_restore:
                _restore_window_and_cursor(restore_hwnd, restore_cursor_position)

        if succeeded:
            _apply_progress_event(params)
            _log_fishing_action(params, background_key_input)
        elif skill_input_group:
            _finish_skill_input_group(_task_id(argv), restore_delay_ms=0)

        return CustomAction.RunResult(success=succeeded)


class _ForegroundPrimingSkillAction(FocusGuardAction):
    """Force foreground input; grouped E/Q defers restoration to its boundary."""

    force_game_foreground = True


class _BackgroundSkillAction(FocusGuardAction):
    """Use background messages; grouped E/Q keeps that mode to its boundary."""

    background_key_input = True


@AgentServer.custom_action("hybrid_skill_action")
class HybridSkillAction(CustomAction):
    """Use foreground for the first dungeon and background for later dungeons."""

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
            return foreground_result

        return _ForegroundPrimingSkillAction().run(context, argv)


@AgentServer.custom_action("skill_input_group_complete")
class SkillInputGroupComplete(CustomAction):
    """Close the shared E/Q group after every configured skill input has run."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        params = _parse_params(argv.custom_action_param)
        restore_delay_ms = min(
            1000, max(0, int(params.get("restore_delay_ms", 100)))
        )
        return CustomAction.RunResult(
            success=_finish_skill_input_group(_task_id(argv), restore_delay_ms)
        )


@AgentServer.custom_action("hybrid_skill_dungeon_complete")
class HybridSkillDungeonComplete(CustomAction):
    """Enable background E/Q only after the first dungeon's full skill set ends."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        game_hwnd = _controller_hwnd(context)
        if not game_hwnd:
            return CustomAction.RunResult(success=False)
        if not _finish_skill_input_group(_task_id(argv), restore_delay_ms=100):
            return CustomAction.RunResult(success=False)
        _mark_hybrid_skill_ready(game_hwnd)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("hybrid_fishing_action")
class HybridFishingAction(CustomAction):
    """Send the first fishing Space in foreground, then use background messages."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        game_hwnd = _controller_hwnd(context)
        if _is_hybrid_fishing_ready(game_hwnd):
            background_result = _BackgroundSkillAction().run(context, argv)
            if background_result.success:
                return background_result
            _reset_hybrid_fishing_ready()

        foreground_result = _ForegroundPrimingSkillAction().run(context, argv)
        if foreground_result.success:
            _mark_hybrid_fishing_ready(game_hwnd)
        return foreground_result
