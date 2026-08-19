"""Stop the Python Agent when the MXU parent process exits."""

from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable
from ctypes import wintypes


_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:  # pragma: no cover - DNA Helper only runs on Windows.
    _kernel32 = None


def start_parent_watchdog(
    on_parent_exit: Callable[[], None],
    parent_pid: int | None = None,
) -> threading.Thread | None:
    """Watch the process that launched this Agent and stop when it disappears."""

    if _kernel32 is None:
        return None

    watched_pid = os.getppid() if parent_pid is None else parent_pid
    if watched_pid <= 0:
        print("[Agent] 无法确定父进程，父进程退出监控未启动", flush=True)
        return None

    parent_handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, watched_pid)
    if not parent_handle:
        error_code = ctypes.get_last_error()
        print(
            f"[Agent] 无法打开父进程 {watched_pid}（Win32 错误 {error_code}），"
            "父进程退出监控未启动",
            flush=True,
        )
        return None

    def wait_for_parent() -> None:
        try:
            result = _kernel32.WaitForSingleObject(parent_handle, _INFINITE)
            if result == _WAIT_OBJECT_0:
                print(
                    f"[Agent] 父进程 {watched_pid} 已退出，正在停止 Telegram 和 Agent",
                    flush=True,
                )
                on_parent_exit()
            elif result == _WAIT_FAILED:
                print(
                    f"[Agent] 等待父进程 {watched_pid} 失败"
                    f"（Win32 错误 {ctypes.get_last_error()}）",
                    flush=True,
                )
        finally:
            _kernel32.CloseHandle(parent_handle)

    thread = threading.Thread(
        target=wait_for_parent,
        name="dna-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread
