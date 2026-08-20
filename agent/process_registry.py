"""Register and unregister this Agent process for safe orphan cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile


SCHEMA_VERSION = 1
MAX_MARKER_BYTES = 4096

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_WINAPI_ERROR_FILE_NOT_FOUND = 0xFFFFFFFF

_REGISTRY_DIR = (
    Path(__file__).resolve().parent.parent / "config" / "agent-processes"
)


if os.name == "nt":  # pragma: no cover - Windows runtime only.
    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetFileAttributesW.restype = wintypes.DWORD
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
else:  # pragma: no cover - non-Windows tests inject timestamps.
    _kernel32 = None


class ProcessRegistryError(RuntimeError):
    """Raised when an Agent marker cannot be safely written."""


def _is_reparse_point(path: Path) -> bool:
    """Return True when ``path`` is a filesystem reparse point."""

    if os.name != "nt" or _kernel32 is None:
        return False
    attributes = _kernel32.GetFileAttributesW(str(path))
    if attributes == _WINAPI_ERROR_FILE_NOT_FOUND:
        return False
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_normal_file_target(path: Path) -> bool:
    if path.is_symlink():
        return False
    if _is_reparse_point(path):
        return False
    if not path.exists():
        return True
    if not path.is_file():
        return False
    return True


def _validate_registry_directory(directory: Path) -> None:
    # Walk all existing ancestors and reject symlinks/reparse points first.
    current = directory
    while True:
        if current.exists():
            if current.is_symlink() or _is_reparse_point(current):
                raise ProcessRegistryError(
                    f"登记目录不允许为符号链接/重解析点：{current}"
                )
            if not current.is_dir():
                raise ProcessRegistryError(f"登记目录不是普通目录：{current}")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _validate_target_marker(path: Path) -> None:
    if not _is_normal_file_target(path):
        raise ProcessRegistryError(f"非法或异常 marker 文件路径：{path}")


def _get_pid() -> int:
    pid = os.getpid()
    if pid <= 0 or pid > 0xFFFFFFFF:
        raise ProcessRegistryError(f"非法 PID：{pid}")
    return pid


def _get_process_creation_time_100ns(pid: int) -> int:
    if os.name != "nt" or _kernel32 is None:
        # Non-Windows CI uses injection in tests; this is a safe fallback.
        # 当前实现仅 Windows 运行，Linux/CI 场景不依赖该值。
        return int.from_bytes(
            os.urandom(8), byteorder="little", signed=False
        )

    creation = _FileTime()
    exit_time = _FileTime()
    kernel_time = _FileTime()
    user_time = _FileTime()
    # GetCurrentProcess returns a pseudo-handle, which is safe on Windows.
    if not _kernel32.GetProcessTimes(
        _kernel32.GetCurrentProcess(),
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        raise ProcessRegistryError(
            f"无法读取进程创建时间（PID={pid}）"
        )
    return (int(creation.high) << 32) | int(creation.low)


def _marker_path(pid: int) -> Path:
    return _REGISTRY_DIR / f"{pid}.json"


def _record_payload(pid: int) -> dict[str, Any]:
    executable = Path(sys.executable).resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "pid": pid,
        "creation_time_100ns": _get_process_creation_time_100ns(pid),
        "executable_path": str(executable),
    }


def register_current_process() -> Path:
    """Create a marker for the current process and return its path."""

    pid = _get_pid()
    marker_path = _marker_path(pid)

    _validate_registry_directory(_REGISTRY_DIR)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_registry_directory(_REGISTRY_DIR)
    _validate_target_marker(marker_path)

    payload_text = json.dumps(
        _record_payload(pid), ensure_ascii=False, indent=2, sort_keys=True
    )
    payload_bytes = payload_text.encode()
    if len(payload_bytes) >= MAX_MARKER_BYTES:
        raise ProcessRegistryError("marker 内容超出 size 限制")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=marker_path.parent,
            prefix=f".tmp-agent-{pid}-",
            suffix=".json",
            delete=False,
        ) as tmp_file:
            temporary_path = Path(tmp_file.name)
            tmp_file.write(payload_text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(temporary_path, marker_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return marker_path


def unregister_current_process(pid: int | None = None) -> bool:
    """Delete the marker for ``pid`` if it exists.

    Returns True when a marker was removed, otherwise False.
    """

    target_pid = os.getpid() if pid is None else pid
    marker_path = _marker_path(target_pid)
    _validate_registry_directory(_REGISTRY_DIR)
    if not _is_normal_file_target(marker_path):
        raise ProcessRegistryError(f"非法 marker 文件：{marker_path}")
    if not marker_path.exists():
        return False
    _validate_registry_directory(_REGISTRY_DIR)
    marker_path.unlink()
    return True
