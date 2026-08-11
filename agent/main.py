"""Launch the DNA Helper MaaFramework custom-action agent."""

from __future__ import annotations

import sys

from maa.agent.agent_server import AgentServer

import focus_restore  # noqa: F401  Registers foreground-window restore actions.
import progress_monitor  # noqa: F401  Registers the monitor bootstrap action.
import round_logger  # noqa: F401  Registers the custom action.
import telegram_bot


def main() -> int:
    if len(sys.argv) < 2:
        raise RuntimeError("缺少 MaaFramework Agent socket_id")

    AgentServer.start_up(sys.argv[-1])
    try:
        AgentServer.join()
    finally:
        telegram_bot.stop()
        AgentServer.shut_down()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
