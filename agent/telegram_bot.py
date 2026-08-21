"""Background Telegram long-polling service for on-demand progress queries."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import progress_state
import process_registry


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "telegram.json"
_stop_event = threading.Event()
_lifecycle_lock = threading.Lock()
_thread: threading.Thread | None = None
_sender_thread: threading.Thread | None = None
_auto_status_thread: threading.Thread | None = None
_ownership_thread: threading.Thread | None = None
_config: dict[str, Any] | None = None
_outbound: queue.Queue[str] = queue.Queue()
_owner_id: str | None = None
_LOCK_PATH = _PROJECT_ROOT / "config" / "agent-processes" / ".telegram-owner.json"
_LOCK_TTL_SECONDS = 18
_OWNERSHIP_WATCHDOG_SECONDS = 2
_AUTO_STATUS_INTERVAL_SECONDS = 30 * 60
_TASK_LABELS = {
    "密函无尽": ("密函无尽加速", "无尽"),
    "密函驱离": ("密函无尽加速", "驱离"),
    "普通扼守": ("普通无尽加速", "扼守"),
    "普通无尽": ("普通无尽加速", "无尽"),
    "普通驱离": ("普通无尽加速", "驱离"),
    "皎皎币挂机": ("皎皎币挂机", "自动循环"),
}


def start() -> bool:
    """Start the bot if a valid local configuration is available."""
    global _auto_status_thread, _config, _sender_thread, _stop_event, _thread, _ownership_thread, _owner_id
    config = _load_config()
    if not config:
        return False
    with _lifecycle_lock:
        if _thread and _thread.is_alive() and not _stop_event.is_set():
            if _owner_id is not None and _is_owner(_owner_id):
                return True
            _stop_event.set()
        owner_id = f"{os.getpid()}-{uuid.uuid4()}"
        if not _acquire_ownership(owner_id):
            return False
        run_stop_event = threading.Event()
        _stop_event = run_stop_event
        _config = config
        _owner_id = owner_id
        _thread = threading.Thread(
            target=_poll_loop,
            args=(config, run_stop_event, owner_id),
            name="dna-telegram-status",
            daemon=True,
        )
        _sender_thread = threading.Thread(
            target=_send_loop,
            args=(config, run_stop_event, owner_id),
            name="dna-telegram-sender",
            daemon=True,
        )
        _auto_status_thread = threading.Thread(
            target=_auto_status_loop,
            args=(run_stop_event, owner_id),
            name="dna-telegram-auto-status",
            daemon=True,
        )
        _ownership_thread = threading.Thread(
            target=_ownership_watchdog,
            args=(run_stop_event, owner_id),
            name="dna-telegram-owner",
            daemon=True,
        )
        _thread.start()
        _sender_thread.start()
        _auto_status_thread.start()
        _ownership_thread.start()
    return True


def stop(final_message: str | None = None) -> bool:
    """Stop the active bot and optionally send one final lifecycle message."""

    global _config
    global _owner_id
    final_config: dict[str, Any] | None = None
    owned = False
    with _lifecycle_lock:
        was_running = _config is not None and not _stop_event.is_set()
        if _owner_id is not None and _is_owner(_owner_id):
            owned = True
        if was_running and final_message and _config is not None:
            final_config = dict(_config)
        _stop_event.set()
        _config = None
        if _owner_id is not None and owned:
            _release_ownership(_owner_id)
        _owner_id = None
        if was_running:
            progress_state.reset()
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
    except (KeyError, OSError, ValueError, urllib.error.URLError) as exc:
        print(
            f"[进度监控] 终止消息发送失败：{type(exc).__name__} {exc}",
            flush=True,
        )
        return


def _validate_owner_path() -> None:
    process_registry._validate_registry_directory(_LOCK_PATH.parent)
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    process_registry._validate_registry_directory(_LOCK_PATH.parent)
    if _LOCK_PATH.exists() and not process_registry._is_normal_file_target(_LOCK_PATH):
        raise ValueError("非法 owner 文件路径")


def _read_owner_record() -> dict[str, Any] | None:
    try:
        if _LOCK_PATH.exists():
            loaded = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return None


def _is_owner(owner_id: str | None, *, now: float | None = None) -> bool:
    if not owner_id:
        return False
    record = _read_owner_record()
    if not record:
        return False
    if record.get("owner_id") != owner_id:
        return False
    if int(record.get("pid", 0)) != os.getpid():
        return False
    expire_at = float(record.get("expires_at", 0))
    current = time.time() if now is None else now
    return current < expire_at


def _write_owner_record(owner_id: str, *, now: float | None = None) -> None:
    _validate_owner_path()
    current = time.time() if now is None else now
    payload = json.dumps(
        {
            "owner_id": owner_id,
            "pid": os.getpid(),
            "updated_at": current,
            "expires_at": current + _LOCK_TTL_SECONDS,
        },
        ensure_ascii=False,
    )
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_LOCK_PATH.parent,
            prefix=".tmp-telegram-owner-",
            suffix=".json",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, _LOCK_PATH)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _release_ownership(owner_id: str | None) -> None:
    if owner_id is None or not _is_owner(owner_id):
        return
    try:
        _LOCK_PATH.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"[进度监控] 释放监听权失败：{type(exc).__name__}", flush=True)


def _acquire_ownership(owner_id: str) -> bool:
    now = time.time()
    try:
        previous = _read_owner_record()
        _write_owner_record(owner_id, now=now)
    except OSError:
        return False
    if (
        previous is not None
        and previous.get("owner_id") != owner_id
        and int(previous.get("pid", 0)) != os.getpid()
        and float(previous.get("expires_at", 0)) > now
    ):
        print("[进度监控] 监听权被新实例接管", flush=True)
    return True


def _refresh_ownership(owner_id: str | None, *, now: float | None = None) -> bool:
    if not _is_owner(owner_id, now=now):
        return False
    try:
        _write_owner_record(owner_id, now=now)
        return True
    except OSError:
        return False


def _ownership_watchdog(stop_event: threading.Event, owner_id: str) -> None:
    while not stop_event.wait(_OWNERSHIP_WATCHDOG_SECONDS):
        if not _refresh_ownership(owner_id):
            stop_event.set()
            break


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


def _poll_loop(config: dict[str, Any], stop_event: threading.Event, owner_id: str) -> None:
    token = config["bot_token"]
    allowed_chat_id = config["allowed_chat_id"]
    poll_timeout = config["poll_timeout_seconds"]
    offset: int | None = None
    failure_delay = 1

    while not stop_event.is_set():
        if not _is_owner(owner_id):
            break
        if not _refresh_ownership(owner_id):
            break
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
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(
                f"[进度监控] 监听接口异常：{type(exc).__name__} {exc}",
                flush=True,
            )
            stop_event.wait(failure_delay)
            failure_delay = min(30, failure_delay * 2)


def _send_loop(
    config: dict[str, Any], stop_event: threading.Event, owner_id: str
) -> None:
    token = config["bot_token"]
    chat_id = config["allowed_chat_id"]
    while not stop_event.is_set():
        if not _is_owner(owner_id):
            break
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
                except (OSError, ValueError, urllib.error.URLError) as exc:
                    print(
                        f"[进度监控] 状态消息发送失败：{type(exc).__name__} {exc}",
                        flush=True,
                    )
                    if not _refresh_ownership(owner_id):
                        break
                    stop_event.wait(delay)
                    delay = min(30, delay * 2)
        finally:
            _outbound.task_done()


def _auto_status_loop(stop_event: threading.Event, owner_id: str) -> None:
    """Queue the current status every 30 minutes without blocking game work."""
    while not stop_event.wait(_AUTO_STATUS_INTERVAL_SECONDS):
        if not _is_owner(owner_id):
            break
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
