"""消息路由测试：白名单、@检测、非@沉默、身份追问、频控、缓存。"""

from __future__ import annotations

import time

from pelica.bridge.mock_bridge import MockBridge
from pelica.db import Database
from pelica.douyin.pipeline import DouyinPipeline
from pelica.llm import persona
from pelica.pipeline.router import GroupBot, REPLY_COOLDOWN_ROOM, REPLY_COOLDOWN_SENDER
from pelica.retrieval.cache import QACache


class StubAnswerer:
    """不发真实 LLM 请求的桩：签名与 Answerer 一致。"""

    def __init__(self):
        self.calls = 0
        self.histories = []

    def answer(self, question: str, history=None, social=""):
        self.calls += 1
        self.histories.append(list(history or []))
        return f"测试回答：{question}", _ev(True)


def _ev(covered: bool):
    from pelica.retrieval.retriever import Evidence

    return Evidence(question="q", covered=covered)


class StubDouyin(DouyinPipeline):
    """签名一致的抖音桩：文本含 'douyin' 即视为处理。"""

    def __init__(self):
        self.handled = []

    def handle(self, text, room_id):
        if "douyin.com" in text:
            self.handled.append((text, room_id))
            return True
        return False


def make_bot(db: Database, whitelist=None, answerer=None, douyin=None):
    bridge = MockBridge(echo=False)
    answerer = answerer or StubAnswerer()
    bot = GroupBot(
        bridge=bridge, db=db, answerer=answerer, qa_cache=QACache(db),
        douyin=douyin, whitelist=whitelist, at_aliases=["佩丽卡"],
    )
    bot.start()
    return bridge, bot, answerer


def feed_and_drain(bot: GroupBot, bridge: MockBridge, **kw):
    bridge.feed(**kw)
    bot._queue.join()
    time.sleep(0.05)


def test_silent_without_at(db: Database):
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="随便聊聊天气", is_at=False)
    assert bridge.outbox == []
    assert answerer.calls == 0
    bot.stop()


def test_self_message_ignored(db: Database):
    bridge, bot, answerer = make_bot(db)
    from pelica.bridge.base import Message

    bot._on_message(Message(room_id="r", room_name="g", sender_id="bot",
                            sender_name="佩丽卡", text="@佩丽卡 你在吗", is_self=True))
    bot._queue.join()
    time.sleep(0.05)
    assert bridge.outbox == []
    bot.stop()


def test_whitelist_blocks_nonlisted_room(db: Database):
    bridge, bot, answerer = make_bot(db, whitelist=["允许的群"])
    bridge.feed(text="大家好", room="陌生群", sender="路人", is_at=False)
    # 白名单外连记录都不该有
    assert db.query_one("SELECT COUNT(*) n FROM messages")["n"] == 0
    feed_and_drain(bot, bridge, text="@佩丽卡 你好", room="允许的群", is_at=True)
    assert answerer.calls == 1
    bot.stop()


def test_at_question_answered(db: Database):
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="@佩丽卡 阿米娅是谁", is_at=True)
    assert answerer.calls == 1
    assert any("测试回答" in o["text"] for o in bridge.outbox)
    bot.stop()


def test_text_alias_triggers(db: Database):
    bridge, bot, answerer = make_bot(db)
    bridge.feed(text="佩丽卡，阿米娅是谁", is_at=False)  # 文本称呼也算 @
    bot._queue.join()
    assert answerer.calls == 1
    bot.stop()


def test_identity_question_no_llm(db: Database):
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="@佩丽卡 你是真人吗", is_at=True)
    assert answerer.calls == 0
    assert any("佩丽卡" in o["text"] and "我就是" in o["text"] for o in bridge.outbox)
    bot.stop()


def test_identity_chase(db: Database):
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="@佩丽卡 你是不是机器人", is_at=True)
    feed_and_drain(bot, bridge, text="@佩丽卡 别装了，承认吧", is_at=True)
    texts = [o["text"] for o in bridge.outbox]
    from pelica.llm import persona
    assert any(x in persona.REPLY_CHASED for x in texts), f"应回复追问变体，实际: {texts}"
    assert answerer.calls == 0
    bot.stop()


def test_douyin_intercepts(db: Database):
    bridge, bot, answerer = make_bot(db)
    douyin = StubDouyin()
    bot._douyin = douyin
    feed_and_drain(bot, bridge, text="看看这个 https://v.douyin.com/abc123/", is_at=False)
    assert douyin.handled
    assert answerer.calls == 0  # 抖音路径不走问答
    bot.stop()


def test_same_question_gets_fresh_reply(db: Database):
    """2026-09-19 用户反馈：不同人问同一句不应得到一字不差的回复。
    QA 缓存已整体停用（因人而异、因时而异），每次都实时生成。"""
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="@佩丽卡 阿米娅是谁", is_at=True)
    first_calls = answerer.calls
    # 换个人、等过房间冷却，再问同一个问题 -> 每次都实时生成
    time.sleep(REPLY_COOLDOWN_ROOM + 0.1)
    bridge.feed(text="@佩丽卡 阿米娅是谁", is_at=True, sender="同事甲",
                sender_id="sender-b")
    bot._queue.join()
    assert answerer.calls == first_calls + 1, "第二次应实时生成（不再缓存）"
    texts = [o["text"] for o in bridge.outbox]
    assert len(texts) >= 2
    bot.stop()


def test_message_recorded_for_stats(db: Database):
    bridge, bot, answerer = make_bot(db)
    feed_and_drain(bot, bridge, text="普通发言", is_at=False)
    assert db.query_one("SELECT COUNT(*) n FROM messages")["n"] == 1
    bot.stop()
