"""Launch the DNA Helper MaaFramework custom-action agent."""

from __future__ import annotations

import sys
import threading

from maa.agent.agent_server import AgentServer

import focus_restore  # noqa: F401  Registers foreground-window restore actions.
import parent_watchdog
import progress_monitor  # noqa: F401  Registers the monitor bootstrap action.
import round_logger  # noqa: F401  Registers the custom action.
import process_registry
import telegram_bot


def main() -> int:
    if len(sys.argv) < 2:
        raise RuntimeError("缺少 MaaFramework Agent socket_id")

    shutdown_lock = threading.Lock()
    shutdown_started = False

    def stop_agent_once() -> None:
        nonlocal shutdown_started
        with shutdown_lock:
            if shutdown_started:
                return
            shutdown_started = True
        try:
            telegram_bot.stop()
        finally:
            AgentServer.shut_down()

    server_started = False
    process_registry.register_current_process()
    try:
        AgentServer.start_up(sys.argv[-1])
        server_started = True
        parent_watchdog.start_parent_watchdog(stop_agent_once)
        AgentServer.join()
    finally:
        try:
            if server_started:
                stop_agent_once()
        finally:
            try:
                process_registry.unregister_current_process()
            except Exception as exc:
                print(f"[Agent] 清理 marker 失败：{exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
