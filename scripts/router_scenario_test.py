#!/usr/bin/env python
"""路由剧本回归：连续对话/喊名/缓存拾取/自发插话，全程 mock 不调 LLM、不发真实消息。

覆盖 GroupBot._process 的分流规则：
  @ 问答开窗 → 窗口内无 @ 追问直答 → 非追问缓存 → 光喊名字拾取
  → 窗外语料话题概率插话 → 插话冷却 → 光杆 @ 空拾取 → 句中喊名 → @ 别人不掺和
"""
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


R.time = Clock()  # type: ignore[assignment] 可控时钟
random.seed(7)

sent: list[tuple[str, str]] = []


class FakeBridge:
    def send_text(self, room_id, text):
        sent.append((room_id, text))


class FakeAnswerer:
    def __init__(self):
        self.calls = []

    def answer(self, q, history=None, social=""):
        self.calls.append(q)
        return f"答：{q}", SimpleNamespace(covered=True, snippets=[])


class FakeMatcher:
    def __init__(self, hits):
        self.hits = hits

    def match(self, text, limit=8):
        return [SimpleNamespace(alias=text)] if any(h in text for h in self.hits) else []


bot = R.GroupBot(
    bridge=FakeBridge(), db=None, answerer=FakeAnswerer(), qa_cache=None,
    douyin=None, whitelist=None, at_aliases=["佩丽卡监督", "佩丽卡"],
    social=None, matcher=FakeMatcher(["提丰", "罗德岛"]),
)
ans = bot._answerer


def m(text, sender="u1", name="阿夜", is_at=False, room="r1"):
    return Message(room_id=room, room_name="测试", sender_id=sender,
                   sender_name=name, text=text, is_at=is_at)


# 1) @ 问答，开窗（注意 _extract_question 会剥句尾问号）
bot._process(m("@佩丽卡监督 提丰和提弗洛斯你知道吗？", is_at=True))
assert ans.calls == ["提丰和提弗洛斯你知道吗"], ans.calls
assert sent[-1][1] == "答：提丰和提弗洛斯你知道吗", sent[-1]

# 2) 窗口内不带 @ 的追问 → 直接接
Clock.t += 5
bot._process(m("她们有什么关系"))
assert ans.calls[-1] == "她们有什么关系", ans.calls

# 3) 窗口内非追问 → 缓存不应答
Clock.t += 10
n = len(sent)
bot._process(m("哈哈这个视频好搞笑"))
assert len(sent) == n, sent
assert "r1" in bot._pending, bot._pending

# 4) 只喊一声名字 → 拾取缓存那句当问题
Clock.t += 3
bot._process(m("佩丽卡"))
assert ans.calls[-1] == "哈哈这个视频好搞笑", ans.calls

# 5) 窗口外的语料话题 → 通路验证（概率临时设 1）
Clock.t += 999
R.AUTO_JOIN_CHANCE = 1.0
bot._process(m("罗德岛是不是搬空了", sender="u2"))
assert ans.calls[-1] == "罗德岛是不是搬空了", ans.calls

# 6) 插话群冷却 300s 内 → 不再插话
Clock.t += 1
n = len(ans.calls)
bot._process(m("提丰好强啊", sender="u3"))
assert len(ans.calls) == n, ans.calls

# 7) 光杆 @ 且无缓存 → 「有什么事」
Clock.t += 999
bot._pending.clear()
bot._process(m("@佩丽卡监督", is_at=True))
assert "有什么事" in sent[-1][1], sent[-1]

# 8) 句中提到别名 → 触发
Clock.t += 5
bot._process(m("让佩丽卡说说提丰", sender="u4"))
assert ans.calls[-1] == "让佩丽卡说说提丰", ans.calls

# 9) 在 @ 别人的消息 → 不掺和
Clock.t += 5
n = len(ans.calls)
bot._process(m("@张三 罗德岛搬空了吗", sender="u5"))
assert len(ans.calls) == n, ans.calls

# 10) 辱骂（点名）：第一次人设化回应一次，不调 LLM
Clock.t += 5
n = len(ans.calls)
bot._process(m("@佩丽卡监督 操你妈", sender="u9"))
assert len(ans.calls) == n, ans.calls          # 不走 LLM
assert len(sent) > 0 and sent[-1][0] == "r1"   # 但回了一句
assert "r1" not in bot._pending                # 不进待拾取
h_before = len(bot._history.get("r1", ()))

# 11) 24h 内再犯 → 完全沉默
Clock.t += 30
n_sent = len(sent)
bot._process(m("@佩丽卡监督 操你妈", sender="u9"))
bot._process(m("@佩丽卡监督 操你妈", sender="u9"))
assert len(sent) == n_sent, sent
assert len(bot._history.get("r1", ())) == h_before  # 不进历史

# 12) 群友互相骂（没点名）→ 不掺和
Clock.t += 30
n_sent = len(sent)
bot._process(m("你就是个傻逼", sender="u10"))
assert len(sent) == n_sent, sent

# 13) 单人 LLM 限流：连续 8 问后沉默（走 _answer 需要每次被点名）
bot2 = R.GroupBot(
    bridge=FakeBridge(), db=None, answerer=FakeAnswerer(), qa_cache=None,
    douyin=None, whitelist=None, at_aliases=["佩丽卡监督", "佩丽卡"],
    social=None, matcher=FakeMatcher([]),
)
ans2 = bot2._answerer
Clock.t += 99999
for i in range(R.MAX_LLM_PER_SENDER):
    bot2._process(m(f"@佩丽卡监督 问题{i}", sender="u20", is_at=True))
    Clock.t += 3  # 推过 2 秒群冷却，确保每一问都真到达 LLM
assert len(ans2.calls) == R.MAX_LLM_PER_SENDER, len(ans2.calls)
Clock.t += 3
bot2._process(m("@佩丽卡监督 再问一个", sender="u20", is_at=True))
assert len(ans2.calls) == R.MAX_LLM_PER_SENDER, len(ans2.calls)  # 第 9 问沉默

print("ROUTER-SCENARIO-OK 13/13")
