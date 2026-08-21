"""Thread-safe runtime progress shared by Maa actions and the Telegram bot."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATUS_PATH = _PROJECT_ROOT / "config" / "progress_status.json"
_INFINITE_COMPLETION_STAGE = 99
_lock = threading.RLock()
_last_stage_increment_monotonic = 0.0
_state: dict[str, Any] = {
    "task_id": 0,
    "status": "idle",
    "mode": "普通副本",
    "completed_rounds": 0,
    "total_rounds": 0,
    "stage_count": 0,
    "stage_total": 99,
    "started_at": None,
    "updated_at": time.time(),
}


def start_task(
    mode: str, total_rounds: int, stage_total: int = 99, task_id: int = 0
) -> bool:
    """Reset progress when a new Maa task first enters its pipeline."""
    global _last_stage_increment_monotonic
    now = time.time()
    with _lock:
        if task_id and int(_state.get("task_id", 0)) == task_id:
            return False
        _state.update(
            {
                "task_id": task_id,
                "status": "running",
                "mode": mode or "普通副本",
                "completed_rounds": 0,
                "total_rounds": max(0, int(total_rounds)),
                "stage_count": 0,
                "stage_total": max(0, int(stage_total)),
                "started_at": now,
                "updated_at": now,
            }
        )
        _last_stage_increment_monotonic = 0.0
        _persist_locked()
        return True


def reset() -> None:
    """Clear progress state for monitor-only or manual reset scenarios."""
    global _last_stage_increment_monotonic
    now = time.time()
    with _lock:
        _state.update(
            {
                "task_id": 0,
                "status": "idle",
                "mode": "普通副本",
                "completed_rounds": 0,
                "total_rounds": 0,
                "stage_count": 0,
                "stage_total": 99,
                "started_at": None,
                "updated_at": now,
            }
        )
        _last_stage_increment_monotonic = 0.0
        _persist_locked()


def increment_stage(dedupe_window_seconds: float = 0.0) -> bool:
    """Record one logical cycle and report the infinite-mode 99 milestone."""
    global _last_stage_increment_monotonic
    monotonic_now = time.monotonic()
    with _lock:
        if _state["status"] not in {"running", "waiting_next_round"}:
            return False
        dedupe_window_seconds = max(0.0, float(dedupe_window_seconds))
        if (
            dedupe_window_seconds
            and _last_stage_increment_monotonic
            and monotonic_now - _last_stage_increment_monotonic
            < dedupe_window_seconds
        ):
            return False
        _last_stage_increment_monotonic = monotonic_now
        stage_total = int(_state["stage_total"])
        next_count = int(_state["stage_count"]) + 1
        _state["stage_count"] = min(next_count, stage_total) if stage_total else next_count
        _state["updated_at"] = time.time()
        _persist_locked()
        return (
            _state["mode"] == "普通无尽"
            and int(_state["stage_count"]) == _INFINITE_COMPLETION_STAGE
        )


def complete_round(current: int, total: int, mode: str | None = None) -> None:
    """Record one completed out-of-dungeon round after Again is detected."""
    current = max(1, int(current))
    total = max(1, int(total))
    with _lock:
        if mode:
            _state["mode"] = mode
        if not _state.get("started_at"):
            _state["started_at"] = time.time()
        _state["completed_rounds"] = current
        _state["total_rounds"] = total
        if _state["stage_total"]:
            _state["stage_count"] = int(_state["stage_total"])
        _state["status"] = "completed" if current >= total else "waiting_next_round"
        _state["updated_at"] = time.time()
        _persist_locked()


def advance_cipher_cycle() -> bool:
    """Advance cipher progress and report its infinite-mode 99 milestone."""
    with _lock:
        if _state["mode"] == "密函无尽" and _state["status"] == "running":
            _state["stage_count"] = int(_state["stage_count"]) + 1
            milestone_reached = (
                int(_state["stage_count"]) == _INFINITE_COMPLETION_STAGE
            )
        elif _state["mode"] == "密函驱离" and _state["status"] == "waiting_next_round":
            _state["status"] = "running"
            _state["stage_count"] = 0
            milestone_reached = False
        else:
            return False
        _state["updated_at"] = time.time()
        _persist_locked()
        return milestone_reached


def start_next_round() -> None:
    """Reset intra-dungeon progress after Start Challenge succeeds."""
    global _last_stage_increment_monotonic
    with _lock:
        _state["stage_count"] = 0
        _state["status"] = "running"
        _state["updated_at"] = time.time()
        _last_stage_increment_monotonic = 0.0
        _persist_locked()


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def format_status(now: float | None = None) -> str:
    state = snapshot()
    now = time.time() if now is None else now
    status = state["status"]
    labels = {
        "idle": "未运行",
        "running": "进行中",
        "waiting_next_round": "等待下一轮",
        "completed": "已完成",
    }
    updated_at = float(state["updated_at"])
    if status == "idle":
        return (
            "DNA Helper：未运行\n"
            "尚无本次任务进度\n"
            f"更新时间：{datetime.fromtimestamp(updated_at).strftime('%H:%M:%S')}"
        )

    mode = str(state["mode"])
    total = int(state["total_rounds"])
    completed = int(state["completed_rounds"])
    stage_total = int(state["stage_total"])
    stage_count = int(state["stage_count"])
    lines = [f"{mode}：{labels.get(status, status)}"]
    if mode in {"普通无尽", "密函无尽"}:
        lines.append(f"局内轮次：{stage_count}")
    else:
        lines.append(f"局外副本轮次（已完成）：{completed} / {total}")
        if stage_total:
            lines.append(f"局内轮次：{stage_count} / {stage_total}")

    started_at = state.get("started_at")
    if started_at:
        end_time = updated_at if status == "completed" else now
        lines.append(f"已运行：{_format_duration(max(0, int(end_time - started_at)))}")
    lines.append(f"更新时间：{datetime.fromtimestamp(updated_at).strftime('%H:%M:%S')}")
    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def _persist_locked() -> None:
    try:
        _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _STATUS_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, _STATUS_PATH)
    except OSError:
        # Progress reporting must never interrupt game automation.
        return
