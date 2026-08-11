"""Interactively create the private Telegram status-bot configuration."""

from __future__ import annotations

import getpass
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILT_RUNTIME_ROOT = PROJECT_ROOT / "dist" / "DNAHelper"


def config_path() -> Path:
    runtime_root = (
        BUILT_RUNTIME_ROOT
        if (BUILT_RUNTIME_ROOT / "DNAHelper.exe").is_file()
        else PROJECT_ROOT
    )
    return runtime_root / "config" / "telegram.json"


def api_call(token: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urllib.parse.urlencode(params).encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("Telegram API 返回失败")
    return payload


def main() -> int:
    print("此脚本只把 Token 保存到本机 config/telegram.json，不会提交到 Git。")
    token = getpass.getpass("粘贴 BotFather 提供的 Bot Token（输入不会显示）：").strip()
    if not token:
        print("未输入 Token。", file=sys.stderr)
        return 1

    try:
        bot = api_call(token, "getMe", {})["result"]
    except Exception as error:
        print(f"无法连接 Telegram Bot：{error}", file=sys.stderr)
        return 1

    username = bot.get("username", "")
    print(f"已连接 @{username}。现在请在手机 Telegram 中打开它并发送 /start。")
    input("发送完成后按回车继续……")

    try:
        updates = api_call(
            token,
            "getUpdates",
            {"timeout": 25, "allowed_updates": json.dumps(["message"])},
        ).get("result", [])
    except Exception as error:
        print(f"读取消息失败：{error}", file=sys.stderr)
        return 1

    chats: dict[int, str] = {}
    for update in updates:
        message = update.get("message", {}) if isinstance(update, dict) else {}
        chat = message.get("chat", {}) if isinstance(message, dict) else {}
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if isinstance(chat_id, int):
            display = chat.get("username") or chat.get("first_name") or str(chat_id)
            chats[chat_id] = str(display)

    if not chats:
        print("没有读到消息。请确认已向新 Bot 发送 /start，然后重新运行脚本。", file=sys.stderr)
        return 1

    if len(chats) == 1:
        chat_id = next(iter(chats))
    else:
        print("检测到多个会话：")
        for candidate_id, display in chats.items():
            print(f"  {candidate_id}: {display}")
        try:
            chat_id = int(input("请输入你的 Chat ID：").strip())
        except ValueError:
            print("Chat ID 格式错误。", file=sys.stderr)
            return 1
        if chat_id not in chats:
            print("该 Chat ID 不在刚才收到的消息中。", file=sys.stderr)
            return 1

    config = {
        "enabled": True,
        "bot_token": token,
        "allowed_chat_id": chat_id,
        "poll_timeout_seconds": 25,
    }
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    print(f"配置完成：{destination}")
    print("重启 DNA Helper 后，在手机发送 /status 或“进度”即可查询。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
