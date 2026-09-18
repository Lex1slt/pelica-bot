#!/usr/bin/env python
"""交互式 mock 群聊：在本机跟佩丽卡对话，不发任何真实微信消息。

输入格式：群名|昵称|消息文本（文本以 @ 开头表示 @ 了机器人）
简化：直接输入文本 = 在「测试群」以 @ 方式发言。
退出：Ctrl+C 或输入 :quit
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.alerts import Alerter  # noqa: E402
from pelica.bridge.mock_bridge import MockBridge  # noqa: E402
from pelica.config import load_settings  # noqa: E402
from pelica.db import Database  # noqa: E402
from pelica.logging_setup import setup_logging  # noqa: E402
from pelica.pipeline.router import GroupBot  # noqa: E402
from pelica.retrieval.cache import QACache  # noqa: E402
from pelica.social import SocialMemory  # noqa: E402

from main import build_answerer, build_bridge  # noqa: E402


def main() -> int:
    settings = load_settings()
    setup_logging(settings.log_dir, settings.log_level)
    db = Database(settings.db_path)
    bridge = build_bridge(settings, Alerter())
    if not isinstance(bridge, MockBridge):
        print("交互式 mock 聊天需要 BRIDGE_MODE=mock", file=sys.stderr)
        return 1
    bot = GroupBot(
        bridge=bridge,
        db=db,
        answerer=build_answerer(settings, db),
        qa_cache=QACache(db),
        douyin=None,
        whitelist=settings.group_whitelist,
        at_aliases=settings.at_aliases,
        social=SocialMemory(db, tz=settings.timezone),
    )
    bot.start()
    bridge.start()

    print("== 佩丽卡 mock 群聊 ==")
    print("直接输入 = @佩丽卡 发言；前缀 群|昵称| 可自定义；:quit 退出")
    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line == ":quit":
            break
        parts = line.split("|", 2)
        if len(parts) == 3:
            room, sender, text = parts
        else:
            room, sender, text = "测试群", "管理员", line
        is_at = text.startswith("@")
        if is_at:
            text = text[1:]
        elif text.startswith(("佩丽卡", "佩丽卡监督")):
            is_at = True
        bridge.feed(text, room=room, sender=sender, is_at=is_at)
        # feed 是同步分发，回复已打印；稍等避免触发房间频控
        import time

        time.sleep(2.2)
    bot.stop()
    bridge.stop()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
