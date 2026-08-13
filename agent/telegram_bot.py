"""Background Telegram long-polling service for on-demand progress queries."""

from __future__ import annotations

import json
import os
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import progress_state


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "telegram.json"
_stop_event = threading.Event()
_lifecycle_lock = threading.Lock()
_thread: threading.Thread | None = None
_sender_thread: threading.Thread | None = None
_auto_status_thread: threading.Thread | None = None
_config: dict[str, Any] | None = None
_outbound: queue.Queue[str] = queue.Queue()
_AUTO_STATUS_INTERVAL_SECONDS = 30 * 60
_TASK_LABELS = {
    "密函无尽": ("密函无尽加速", "无尽"),
    "密函驱离": ("密函无尽加速", "驱离"),
    "普通扼守": ("普通无尽加速", "扼守"),
    "普通无尽": ("普通无尽加速", "无尽"),
    "普通驱离": ("普通无尽加速", "驱离"),
}


def start() -> bool:
    """Start the bot if a valid local configuration is available."""
    global _auto_status_thread, _config, _sender_thread, _stop_event, _thread
    config = _load_config()
    if not config:
        return False
    with _lifecycle_lock:
        if _thread and _thread.is_alive() and not _stop_event.is_set():
            return True
        run_stop_event = threading.Event()
        _stop_event = run_stop_event
        _config = config
        _thread = threading.Thread(
            target=_poll_loop,
            args=(config, run_stop_event),
            name="dna-telegram-status",
            daemon=True,
        )
        _sender_thread = threading.Thread(
            target=_send_loop,
            args=(config, run_stop_event),
            name="dna-telegram-sender",
            daemon=True,
        )
        _auto_status_thread = threading.Thread(
            target=_auto_status_loop,
            args=(run_stop_event,),
            name="dna-telegram-auto-status",
            daemon=True,
        )
        _thread.start()
        _sender_thread.start()
        _auto_status_thread.start()
    return True


def stop(final_message: str | None = None) -> bool:
    """Stop the active bot and optionally send one final lifecycle message."""

    global _config
    final_config: dict[str, Any] | None = None
    with _lifecycle_lock:
        was_running = _config is not None and not _stop_event.is_set()
        if was_running and final_message and _config is not None:
            final_config = dict(_config)
        _stop_event.set()
        _config = None
        while True:
            try:
                _outbound.get_nowait()
            except queue.Empty:
                break
            else:
                _outbound.task_done()
    if final_config is not None:
        _send_final_message_async(final_config, final_message)
    return was_running


def notify_monitor_started() -> bool:
    """Queue the standalone-monitor start notification."""

    if _config is None or _stop_event.is_set():
        return False
    _outbound.put("DNA Helper 监控已开启\n无任务")
    return True


def notify_task_started(mode: str) -> bool:
    """Queue one non-blocking notification when a new Maa task starts."""
    if _config is None or _stop_event.is_set():
        return False
    task_name, mode_name = _TASK_LABELS.get(mode, (mode, mode))
    _outbound.put(f"DNA Helper 任务已启动\n任务：{task_name}\n模式：{mode_name}")
    return True


def notify_infinite_99_completed() -> bool:
    """Queue the one-shot 99-cycle milestone for modes without an end node."""

    if _config is None or _stop_event.is_set():
        return False
    mode = str(progress_state.snapshot().get("mode", ""))
    if mode not in {"密函无尽", "普通无尽"}:
        return False
    task_name, mode_name = _TASK_LABELS[mode]
    _outbound.put(
        f"DNA Helper 局内 99 轮已完成\n任务：{task_name}\n模式：{mode_name}"
    )
    return True


def format_task_completed_message() -> str:
    """Build the natural-completion notification from the shared task state."""

    mode = str(progress_state.snapshot().get("mode", "任务"))
    task_name, mode_name = _TASK_LABELS.get(mode, (mode, mode))
    return f"DNA Helper 任务已完成\n任务：{task_name}\n模式：{mode_name}"


def _send_final_message_async(config: dict[str, Any], message: str) -> None:
    """Send the completion notice independently from the stopped main queue."""

    threading.Thread(
        target=_send_final_message,
        args=(config, message),
        name="dna-telegram-final-message",
        daemon=True,
    ).start()


def _send_final_message(config: dict[str, Any], message: str) -> None:
    try:
        _send_message(config["bot_token"], config["allowed_chat_id"], message)
    except (KeyError, OSError, ValueError, urllib.error.URLError):
        return


def _load_config() -> dict[str, Any] | None:
    raw: dict[str, Any] = {}
    try:
        if _CONFIG_PATH.is_file():
            parsed = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
    except (OSError, json.JSONDecodeError):
        return None

    token = os.getenv("DNA_TELEGRAM_BOT_TOKEN") or raw.get("bot_token")
    chat_id = os.getenv("DNA_TELEGRAM_CHAT_ID") or raw.get("allowed_chat_id")
    enabled = raw.get("enabled", True)
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return None
    if not enabled or not isinstance(token, str) or not token.strip():
        return None
    return {
        "bot_token": token.strip(),
        "allowed_chat_id": chat_id,
        "poll_timeout_seconds": min(
            50, max(5, int(raw.get("poll_timeout_seconds", 25)))
        ),
    }


def _poll_loop(config: dict[str, Any], stop_event: threading.Event) -> None:
    token = config["bot_token"]
    allowed_chat_id = config["allowed_chat_id"]
    poll_timeout = config["poll_timeout_seconds"]
    offset: int | None = None
    failure_delay = 1

    while not stop_event.is_set():
        params: dict[str, Any] = {
            "timeout": poll_timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        if offset is not None:
            params["offset"] = offset
        try:
            response = _api_call(token, "getUpdates", params, poll_timeout + 5)
            if stop_event.is_set():
                break
            failure_delay = 1
            for update in response.get("result", []):
                if stop_event.is_set():
                    break
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                _handle_update(token, allowed_chat_id, update)
                if isinstance(update_id, int):
                    offset = update_id + 1
        except (OSError, ValueError, urllib.error.URLError):
            stop_event.wait(failure_delay)
            failure_delay = min(30, failure_delay * 2)


def _send_loop(config: dict[str, Any], stop_event: threading.Event) -> None:
    token = config["bot_token"]
    chat_id = config["allowed_chat_id"]
    while not stop_event.is_set():
        try:
            message = _outbound.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            delay = 1
            while not stop_event.is_set():
                try:
                    _send_message(token, chat_id, message)
                    break
                except (OSError, ValueError, urllib.error.URLError):
                    stop_event.wait(delay)
                    delay = min(30, delay * 2)
        finally:
            _outbound.task_done()


def _auto_status_loop(stop_event: threading.Event) -> None:
    """Queue the current status every 30 minutes without blocking game work."""
    while not stop_event.wait(_AUTO_STATUS_INTERVAL_SECONDS):
        _outbound.put(progress_state.format_status())


def _handle_update(token: str, allowed_chat_id: int, update: dict[str, Any]) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") != allowed_chat_id:
        return
    text = message.get("text")
    if not isinstance(text, str):
        return
    command = text.strip().lower().split("@", 1)[0]
    if command in {"/status", "进度"}:
        _send_message(token, allowed_chat_id, progress_state.format_status())
    elif command in {"/start", "/help", "帮助"}:
        _send_message(
            token,
            allowed_chat_id,
            "DNA Helper 状态机器人已连接。\n发送 /status 或“进度”查询当前状态。",
        )


def _send_message(token: str, chat_id: int, text: str) -> None:
    _api_call(token, "sendMessage", {"chat_id": chat_id, "text": text}, timeout=5)


def _api_call(
    token: str, method: str, params: dict[str, Any], timeout: int
) -> dict[str, Any]:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise ValueError("Telegram API returned an unsuccessful response")
    return payload
