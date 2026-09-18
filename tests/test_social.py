"""社交记忆与自由对话测试。"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from pelica.db import Database
from pelica.llm import persona
from pelica.llm.answer import Answerer
from pelica.retrieval.retriever import Evidence
from pelica.social import SocialMemory


def _seed(db: Database, room_id="room-1"):
    """构造一周的群消息：阿测试（夜猫子、@多）、小李（白天）。"""
    zone = ZoneInfo("Asia/Shanghai")
    base = datetime(2026, 9, 17, 12, 0, tzinfo=zone)
    from pelica.social import _ts

    rows = []
    for i in range(6):  # 阿测试：白天 3 句 + 凌晨 3 句，@ 4 次
        day_offset = i % 2
        hour = 14 if i % 2 == 0 else 2
        ts = base.replace(day=base.day - day_offset, hour=hour).strftime("%Y-%m-%dT%H:%M:%S")
        rows.append(("阿测试", f"第{i}句话，聊聊源石技艺", 1 if i % 2 == 0 else 1, ts))
    for i in range(4):  # 小李：白天，不 @
        ts = base.replace(hour=15).strftime("%Y-%m-%dT%H:%M:%S")
        rows.append(("小李", f"白天的闲聊{i}", 0, ts))
    for sender, text, is_at, ts in rows:
        db.execute(
            "INSERT INTO messages(room_id,room_name,sender_id,sender_name,ts,is_at,kind,text)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (room_id, "测试群", f"sid-{sender}", sender, ts, is_at, "text", text),
        )


def test_room_context_contains_members(db: Database):
    _seed(db)
    sm = SocialMemory(db)
    ctx = sm.room_context("room-1", "sid-阿测试", "阿测试")
    assert "阿测试" in ctx
    assert "印象" not in ctx or "你对他的印象" in ctx


def test_member_profile_night_owl(db: Database):
    _seed(db)
    sm = SocialMemory(db)
    profile = sm.member_profile("room-1", "sid-阿测试", "阿测试")
    assert "阿测试" in profile
    assert "深夜" in profile, "半夜消息过半应识别为夜猫子"
    assert "找你问了" in profile


def test_self_state_by_hour_and_volume(db: Database):
    _seed(db)
    sm = SocialMemory(db)
    late = datetime(2026, 9, 18, 2, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    state = sm.self_state("room-1", now=late)
    assert "深夜" in state
    assert "近况" in state


def test_refresh_impressions_upserts(db: Database):
    _seed(db)

    class StubClient:
        def chat(self, messages, **kw):
            assert "佩丽卡" in messages[0]["content"]
            return "阿测试|夜里的常客，问题很认真\n小李|白天冒泡的闲聊担当"

    sm = SocialMemory(db)
    updated = sm.refresh_impressions("room-1", StubClient(), min_msgs=3)
    assert updated == 2
    note = sm.get_note("room-1", "sid-阿测试")
    assert "夜里的常客" in note
    # room_context 应带出长期印象
    ctx = sm.room_context("room-1", "sid-阿测试", "阿测试")
    assert "夜里的常客" in ctx


def test_refresh_impressions_no_active_members(db: Database):
    sm = SocialMemory(db)
    assert sm.refresh_impressions("empty-room", object()) == 0


# -- 自由对话路径 ---------------------------------------------------------------

class RecordingClient:
    def __init__(self, reply="嗯，我挺喜欢这个群的。"):
        self.calls: list[list[dict]] = []
        self.reply = reply

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return self.reply


class FixedEvidence:
    """可配置的检索桩。"""

    def __init__(self, covered=False, entity_names=None):
        self.covered = covered
        self.entity_names = entity_names or []

    def retrieve(self, question: str) -> Evidence:
        return Evidence(question=question, covered=self.covered,
                        entity_names=list(self.entity_names), snippets=[])


def _ans(client, retr):
    return Answerer(client, retr)  # type: ignore[arg-type]


def test_freeform_for_social_without_entities():
    client, retr = RecordingClient(), FixedEvidence(covered=False, entity_names=[])
    reply, ev = _ans(client, retr).answer("你喜欢我吗", social="近况：群里挺热闹")
    assert ev.covered is False
    assert len(client.calls) == 1, "社交话题应走自由对话"
    assert "不需要查任何记录" in client.calls[-1][-1]["content"]
    assert "群里挺热闹" in client.calls[-1][-1]["content"]
    assert persona.find_forbidden(reply) == []


def test_freeform_for_social_even_with_entity_match():
    """「你喜欢我吗」擦到实体也不该走剧情守门。"""
    client = RecordingClient(reply="……这种问题，真是拿你没办法。")
    retr = FixedEvidence(covered=False, entity_names=["矿石病"])
    reply, _ = _ans(client, retr).answer("你喜欢我吗")
    assert len(client.calls) == 1
    assert "拿你没办法" in reply


def test_lore_uncovered_without_social_signals_stays_guarded():
    client, retr = RecordingClient(), FixedEvidence(covered=False, entity_names=["阿米娅"])
    reply, ev = _ans(client, retr).answer("阿米娅的父亲是谁")
    assert ev.covered is False
    assert client.calls == [], "剧情问题无证据应守门兜底，不调模型"
    assert reply


def test_social_context_reaches_lore_answers():
    client = RecordingClient(reply="好的。")
    retr = FixedEvidence(covered=True, entity_names=[])
    _ans(client, retr).answer("帝江号是什么", social="近况：这周找你问了 13 次")
    content = client.calls[-1][-1]["content"]
    assert "这个群和这位管理员的近况" in content
    assert "13 次" in content
