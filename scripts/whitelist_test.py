#!/usr/bin/env python
"""白名单回归：群聊白名单（空=全放行）+ 私聊白名单（空=关闭），纯路由层不联网。"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pelica.pipeline.router as R
from pelica.bridge.base import Message


class Clock:
    t = 1000.0

    def time(self):
        return Clock.t

    def sleep(self, s):
        Clock.t += s


R.time = Clock()  # type: ignore[assignment]


def make_bot(group_wl, private_wl):
    return R.GroupBot(
        bridge=SimpleNamespace(send_text=lambda *a, **k: None), db=None,
        answerer=SimpleNamespace(answer=lambda q, history=None, social="":
                                 ("好", SimpleNamespace(covered=True, snippets=[]))),
        qa_cache=None, douyin=None, whitelist=group_wl,
        at_aliases=["佩丽卡监督", "佩丽卡"], social=None, matcher=None,
        private_whitelist=private_wl,
    )


def m(room, sender="u1", name="阿夜", is_at=True, room_name=None):
    return Message(room_id=room, room_name=room_name or room, sender_id=sender,
                   sender_name=name, text="你好", is_at=is_at)


def main() -> int:
    # 群聊：未配置白名单=全放行
    bot = make_bot(None, None)
    assert bot._allowed(m("111@chatroom"))
    # 群聊：配置后按群名/群 ID 放行，其余拒绝
    bot = make_bot(["测试群"], [])
    assert bot._allowed(m("123@chatroom", room_name="测试群"))
    # 群聊消息绝不会被私聊规则误判（room_id 带 @chatroom 后缀）
    bot_g = make_bot(["999@chatroom"], [])
    assert bot_g._allowed(m("999@chatroom"))
    assert bot_g._allowed(m("888@chatroom", room_name="别的群")) is False

    # 私聊：未配置=关闭（默认，保持 v1 行为）
    bot = make_bot(None, None)
    assert bot._allowed(m("wxid_stranger")) is False
    # 私聊：配置后 wxid / 昵称 / 会话 ID 任一命中即放行
    bot = make_bot(None, ["wxid_boss", "玻璃盐词典"])
    assert bot._allowed(m("wxid_boss"))
    assert bot._allowed(m("wxid_other", sender="u9", name="玻璃盐词典"))  # 昵称命中
    assert bot._allowed(m("wxid_other", sender="u9", name="陌生人")) is False

    # 私聊消息走完整流程：不需要 @ 也应答（is_at 由桥接置 True）
    sent: list[str] = []

    class B:
        def send_text(self, rid, t):
            sent.append(t)

    bot2 = R.GroupBot(
        bridge=B(), db=None,
        answerer=SimpleNamespace(answer=lambda q, history=None, social="":
                                 ("答：" + q, SimpleNamespace(covered=True, snippets=[]))),
        qa_cache=None, douyin=None, whitelist=None, at_aliases=["佩丽卡监督"],
        social=None, matcher=None, private_whitelist=["wxid_boss"],
    )
    pm = Message(room_id="wxid_boss", room_name="老板", sender_id="wxid_boss",
                 sender_name="老板", text="最近在忙什么", is_at=True)
    assert bot2._allowed(pm)
    bot2._process(pm)
    assert sent and "答：" in sent[-1], sent
    # 私聊里的事实类问题不做「档案腔」（人设层负责），这里只验证通路

    print("WHITELIST-OK 8/8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
