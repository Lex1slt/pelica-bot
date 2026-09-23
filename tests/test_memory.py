"""多轮对话记忆测试：追问上下文、上下文续聊、记忆不落缓存。"""

from __future__ import annotations

import time

from pelica.bridge.mock_bridge import MockBridge
from pelica.db import Database
from pelica.llm import persona
from pelica.llm.answer import Answerer
from pelica.pipeline.router import GroupBot, REPLY_COOLDOWN_ROOM
from pelica.retrieval.cache import QACache
from pelica.retrieval.retriever import Evidence

from test_router import _ev, make_bot


class RecordingClient:
    def __init__(self):
        self.calls: list[list[dict]] = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return "好，我记得刚才说过。"


class SwitchRetriever:
    """covered 可切换的检索桩。"""

    def __init__(self):
        self.covered = True

    def retrieve(self, question: str) -> Evidence:
        return Evidence(question=question, covered=self.covered, snippets=[])


def test_answerer_passes_history_after_fixed_persona():
    client, retr = RecordingClient(), SwitchRetriever()
    ans = Answerer(client, retr)  # type: ignore[arg-type]
    ans.answer("阿米娅是谁", history=[("佩丽卡是谁", "我就是佩丽卡呀")])
    msgs = client.calls[-1]
    assert msgs[0]["role"] == "system", "人设固定前缀必须在最前"
    assert any(m["role"] == "user" and "佩丽卡是谁" in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" and "我就是佩丽卡呀" in m["content"] for m in msgs)
    # 当前问题在历史之后
    assert "阿米娅是谁" in msgs[-1]["content"]


def test_answerer_followup_uses_context_when_uncovered():
    """无实体追问走自由对话，历史轮次随消息带上，可顺着接话。"""
    client, retr = RecordingClient(), SwitchRetriever()
    retr.covered = False
    ans = Answerer(client, retr)  # type: ignore[arg-type]
    reply, ev = ans.answer("那她呢", history=[("阿米娅是谁", "她是罗德岛的领导人")])
    assert ev.covered is False
    assert len(client.calls) == 1
    msgs = client.calls[-1]
    assert any(m["role"] == "user" and "阿米娅是谁" in m["content"] for m in msgs[:-1])
    assert "不需要查任何记录" in msgs[-1]["content"]


def test_answerer_uncovered_no_entity_goes_freeform():
    """无证据且没碰到实体 -> 自由对话（社交直答），而不是「不知道」。"""
    client, retr = RecordingClient(), SwitchRetriever()
    retr.covered = False
    ans = Answerer(client, retr)  # type: ignore[arg-type]
    reply, ev = ans.answer("完全无关的问题")
    assert ev.covered is False
    assert len(client.calls) == 1, "应走自由对话路径"
    assert "不需要查任何记录" in client.calls[-1][-1]["content"]
    assert persona.find_forbidden(reply) == []


def test_answerer_history_cannot_inject_machine_speak():
    class BadClient:
        def chat(self, messages, **kw):
            return "作为AI，我无法回答"

    retr = SwitchRetriever()
    retr.covered = False
    ans = Answerer(BadClient(), retr)  # type: ignore[arg-type]
    reply, _ = ans.answer("那她呢", history=[("q", "a")])
    from pelica.llm import persona

    assert persona.find_forbidden(reply) == []


def test_router_keeps_room_history(db: Database):
    bridge, bot, answerer = make_bot(db)
    bridge.feed(text="@佩丽卡 阿米娅是谁", is_at=True)
    bot._queue.join()
    time.sleep(REPLY_COOLDOWN_ROOM + 0.1)
    bridge.feed(text="@佩丽卡 帝江号是什么", is_at=True, sender="同事甲",
                sender_id="sender-b")
    bot._queue.join()
    assert answerer.calls == 2
    first_h, second_h = answerer.histories
    assert first_h == []
    assert len(second_h) == 1 and second_h[0][0] == "阿米娅是谁", "第二轮应带上第一轮问答"
    bot.stop()


def test_router_history_survives_uncovered_followup(db: Database):
    """追问（无证据）也应走 LLM 续聊并进入记忆，而不是永远兜底。"""

    class PartialStub:
        """第一次 covered，第二次不 covered。"""

        def __init__(self):
            self.n = 0

        def answer(self, question, history=None, social=""):
            self.n += 1
            if self.n == 1:
                return "第一轮回答", _ev(True)
            return "顺着刚才的话接一句", _ev(False)

    bridge, bot, _orig = make_bot(db)
    bot._answerer = PartialStub()

    bridge.feed(text="@佩丽卡 阿米娅是谁", is_at=True)
    bot._queue.join()
    time.sleep(REPLY_COOLDOWN_ROOM + 0.1)
    bridge.feed(text="@佩丽卡 那她呢", is_at=True, sender="同事甲",
                sender_id="sender-b")
    bot._queue.join()

    assert any("顺着刚才" in o["text"] for o in bridge.outbox), "追问应得到续聊回复"
    assert len(bot._history["mockroom::测试群@chatroom"]) == 2, "追问回复也应进入群记忆"
    bot.stop()
