"""社交记忆：把 messages 流水变成佩丽卡「对群、对人的了解」。

三层：
1. 群近况  room_context()   —— 每次回复时注入：7 天活跃度、最活跃的人、
                               提问者本人画像（夜聊比例、@ 次数、最近在聊什么）、
                               长期印象、以及佩丽卡自己的「近期状态」；
2. 印象    refresh_impressions() —— 每周（或手动）让 LLM 以佩丽卡口吻给活跃
                               成员写一句话印象，存 social_notes 长期记忆；
3. 自身状态 self_state()    —— 由群活跃度与时刻推导的确定性状态描述，
                               让「今天心情怎么样」有真实依据可答。

全部本地 SQL，除了印象刷新（一次 LLM 调用 / 群 / 周）。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from pelica.db import Database
from pelica.llm.client import LLMError

log = logging.getLogger(__name__)

_WINDOW_DAYS = 7
_MAX_CONTEXT_CHARS = 600
_SAMPLE_MSG_CHARS = 60


def _ts(days_ago: int = 0) -> str:
    t = time.time() - days_ago * 86400
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


class SocialMemory:
    def __init__(self, db: Database, tz: str = "Asia/Shanghai"):
        self._db = db
        self._tz = tz

    # -- 群近况（每次回复注入） ----------------------------------------------

    def room_context(self, room_id: str, sender_id: str = "",
                     sender_name: str = "") -> str:
        """生成注入 LLM 的社交上下文短文（有限长度）。"""
        lines: list[str] = []

        top = self._top_members(room_id)
        if top:
            names = "、".join(f"{name}（{n} 句）" for name, n, _night in top[:3])
            lines.append(f"最近一周群里挺活跃的，最常说话的是 {names}。")
        else:
            lines.append("这个群最近不太活跃，没什么人说话。")

        state = self.self_state(room_id)
        if state:
            lines.append(state)

        if sender_id or sender_name:
            profile = self.member_profile(room_id, sender_id, sender_name)
            if profile:
                lines.append(profile)

        note = self.get_note(room_id, sender_id)
        if note:
            lines.append(f"你对他的印象：{note}")

        text = "\n".join(lines)
        return text[:_MAX_CONTEXT_CHARS]

    def _top_members(self, room_id: str) -> list[tuple[str, int, int]]:
        rows = self._db.query(
            """
            SELECT sender_name, COUNT(*) AS n,
                   SUM(CASE WHEN substr(ts,12,2) < '06' THEN 1 ELSE 0 END) AS night
            FROM messages
            WHERE room_id=? AND ts>=? AND sender_id != ''
            GROUP BY sender_id ORDER BY n DESC LIMIT 5
            """,
            (room_id, _ts(_WINDOW_DAYS)),
        )
        return [(r["sender_name"] or "匿名群友", r["n"], r["night"] or 0) for r in rows]

    # -- 成员画像 -------------------------------------------------------------

    def member_profile(self, room_id: str, sender_id: str, sender_name: str = "") -> str:
        where_id = "sender_id=?" if sender_id else "sender_name=?"
        param = sender_id or sender_name
        row = self._db.query_one(
            f"""
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN substr(ts,12,2) < '06' THEN 1 ELSE 0 END) AS night,
                   MAX(ts) AS last_ts
            FROM messages WHERE room_id=? AND {where_id} AND ts>=?
            """,
            (room_id, param, _ts(_WINDOW_DAYS)),
        )
        if row is None or not row["n"]:
            return ""
        name = sender_name or "这位管理员"
        parts = [f"说话的这位是「{name}」"]
        recent = self._db.query(
            f"""
            SELECT text FROM messages
            WHERE room_id=? AND {where_id} AND ts>=? ORDER BY ts DESC LIMIT 3
            """,
            (room_id, param, _ts(_WINDOW_DAYS)),
        )
        parts.append(f"最近 7 天说了 {row['n']} 句话")
        if row["night"] and row["night"] * 2 >= row["n"]:
            parts.append("常常深夜还在聊")
        at = self._db.query_one(
            f"""
            SELECT COUNT(*) AS n FROM messages
            WHERE room_id=? AND {where_id} AND is_at=1 AND ts>=?
            """,
            (room_id, param, _ts(_WINDOW_DAYS)),
        )
        if at and at["n"]:
            parts.append(f"这周找你问了 {at['n']} 次")
        if recent and recent[0]["text"]:
            sample = recent[0]["text"][:_SAMPLE_MSG_CHARS]
            parts.append(f"最近一句是「{sample}」")
        return "，".join(parts) + "。"

    def get_note(self, room_id: str, sender_id: str) -> str:
        if not sender_id:
            return ""
        row = self._db.query_one(
            "SELECT note FROM social_notes WHERE room_id=? AND sender_id=?",
            (room_id, sender_id),
        )
        return row["note"] if row else ""

    # -- 自身状态（确定性推导，让「今天心情怎么样」有依据） ---------------------

    def self_state(self, room_id: str, now: datetime | None = None) -> str:
        zone = ZoneInfo(self._tz)
        now = now or datetime.now(zone)
        hour = now.hour
        c24 = self._db.query_one(
            "SELECT COUNT(*) AS n FROM messages WHERE room_id=? AND ts>=?",
            (room_id, _ts(1)),
        )["n"]
        at7 = self._db.query_one(
            "SELECT COUNT(*) AS n FROM messages WHERE room_id=? AND is_at=1 AND ts>=?",
            (room_id, _ts(_WINDOW_DAYS)),
        )["n"]

        parts: list[str] = []
        if 0 <= hour < 6:
            parts.append("现在是深夜")
        elif hour >= 22:
            parts.append("夜已经深了")
        if c24 >= 50:
            parts.append("群里这两天特别热闹")
        elif c24 >= 10:
            parts.append("群里最近还挺热闹")
        elif c24 > 0:
            parts.append("群里最近安静了些")
        if at7:
            parts.append(f"这周管理员们找你问了 {at7} 次")
        return "你的近况：" + "，".join(parts) + "。" if parts else ""

    # -- 长期印象（LLM 生成，低频） --------------------------------------------

    def refresh_impressions(self, room_id: str, client, min_msgs: int = 8) -> int:
        """给最近一周最活跃的成员写/更新一句话印象。返回更新的人数。

        client 是 DeepSeekClient（签名一致的桩也可）。一次调用覆盖全成员。
        """
        top = [(name, n) for name, n, _ in self._top_members(room_id) if n >= min_msgs]
        if not top:
            return 0

        blocks = []
        id_by_name: dict[str, str] = {}
        for name, _n in top:
            rows = self._db.query(
                """
                SELECT sender_id, text FROM messages
                WHERE room_id=? AND sender_name=? AND ts>=?
                ORDER BY ts DESC LIMIT 20
                """,
                (room_id, name, _ts(_WINDOW_DAYS)),
            )
            if not rows:
                continue
            id_by_name[name] = rows[0]["sender_id"]
            samples = " / ".join(
                (r["text"] or "")[:30] for r in rows[:8] if r["text"]
            )
            blocks.append(f"【{name}】（{len(rows)} 句）{samples[:240]}")
        if not blocks:
            return 0

        prompt = (
            "你是佩丽卡。下面是群里几位管理员最近一周的发言摘录。"
            "请为每个人写一句你对他/她的印象，用你的口吻，一句话，不要客套，"
            "可以从说话内容和习惯里总结，但不要编造没出现的事。\n"
            "严格按行输出，每行格式：昵称|印象\n\n" + "\n".join(blocks)
        )
        try:
            reply = client.chat(
                [{"role": "system", "content": persona_core_for_notes()},
                 {"role": "user", "content": prompt}],
                max_tokens=300,
            )
        except LLMError as exc:
            log.warning("印象刷新失败：%s", exc)
            return 0

        updated = 0
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for line in reply.splitlines():
            line = line.strip().lstrip("-• ")
            if "|" not in line:
                continue
            name, _, note = line.partition("|")
            name = name.strip().strip("【】")
            note = note.strip()
            if not name or not note or name not in id_by_name:
                continue
            self._db.execute(
                "INSERT INTO social_notes(room_id,sender_id,sender_name,note,updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(room_id,sender_id) DO UPDATE SET"
                " note=excluded.note, updated_at=excluded.updated_at",
                (room_id, id_by_name[name], name, note[:120], now),
            )
            updated += 1
        log.info("印象刷新完成：%s 更新 %d 人", room_id, updated)
        return updated


def persona_core_for_notes() -> str:
    return (
        "你是佩丽卡，终末地的监督，说话沉稳温和。你在为群里的管理员写记忆便签，"
        "只输出指定格式的行，不要多余的话。"
    )
