"""每周群聊统计播报（参考统计机器人格式，Top5）。

数据源优先级：
1. 微信内部消息库（bridge.query_wechat_db）——完整，含图片/视频/表情包/
   拍了拍等媒体计数；表名 = Msg_ + md5(会话id)，发送人 = real_sender_id
   对应 Name2Id.rowid；
2. 本地 messages 表兜底（mock / 其他桥）——只有文本，媒体行省略。

输出格式：
    群名
    消息统计(近一周)
    ------------
    时间起: 2026-09-11 00:00:00
    时间止: 2026-09-18 19:41:15
    ------------
    文本消息: 4365
    ...
    ------------
    发言Top5
    1.名字【408】
"""

from __future__ import annotations

import hashlib

from pelica.db import Database

# WeChat local_type 低 32 位（高位是子分类标志，要掩掉）
_TYPE_TEXT = 1
_TYPE_IMAGE = 3
_TYPE_VOICE = 34
_TYPE_VIDEO = 43
_TYPE_STICKER = 47
_TYPE_APP = 49            # 文件/链接/小程序
_TYPE_SYSTEM = 10000      # 群改名/拍了拍等系统消息


def _lo(t) -> int:
    try:
        return int(t) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return -1


def _sender_names(db: Database) -> dict[str, str]:
    """wxid -> 最近一次出现的群昵称（来自我们自己的落库）。"""
    rows = db.query(
        "SELECT sender_id, sender_name, MAX(ts) AS last FROM messages"
        " GROUP BY sender_id"
    )
    return {r["sender_id"]: (r["sender_name"] or "") for r in rows if r["sender_id"]}


def _stats_via_bridge(bridge, room_id: str, since: int, until: int,
                      names: dict[str, str]) -> dict | None:
    """从微信消息库统计。桥不可用返回 None（调用方走本地兜底）；
    会话表不存在返回 {"total": 0}（该群压根没消息，跳过播报）。"""
    q = lambda sql: bridge.query_wechat_db("message_0.db", sql)  # noqa: E731
    table = "Msg_" + hashlib.md5(room_id.encode()).hexdigest()
    exists = q(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='" + table + "'"
    )
    if exists is None:
        return None  # 桥不可用 / 查询失败
    if not exists:
        return {"total": 0}

    win = f"WHERE create_time>={since} AND create_time<{until}"
    counts: dict[int, int] = {}
    for r in (q(f"SELECT local_type, COUNT(*) n FROM {table} {win} GROUP BY local_type") or []):
        counts[_lo(r.get("local_type"))] = int(r.get("n") or 0)

    pat = q(
        f"SELECT COUNT(*) n FROM {table} {win} "
        "AND message_content LIKE '%拍了拍%'"
    )
    paipai = int((pat or [{"n": 0}])[0].get("n") or 0)

    # 发送人：real_sender_id = Name2Id.rowid；排除系统与机器人自己
    id2wx = {
        int(r.get("rowid")): (r.get("user_name") or "")
        for r in (q("SELECT rowid, user_name FROM Name2Id") or [])
    }
    exclude = {"", "weixin", room_id}
    if getattr(bridge, "self_wxid", ""):
        exclude.add(bridge.self_wxid)
    by_sender: dict[str, int] = {}
    speakers = set()
    for r in (q(f"SELECT real_sender_id sid, COUNT(*) n FROM {table} {win} GROUP BY real_sender_id") or []):
        sid = int(r.get("sid") or 0)
        wx = id2wx.get(sid, "")
        if wx in exclude:
            continue
        by_sender[wx or f"id{sid}"] = int(r.get("n") or 0)
        speakers.add(wx or f"id{sid}")
    # 显示用群昵称（我们落库里积累的 wxid->昵称），查不到退回 wxid
    top = sorted(by_sender.items(), key=lambda kv: -kv[1])[:5]
    top = [(names.get(wx, "") or wx, n) for wx, n in top]

    return {
        "total": sum(counts.values()),
        "text": counts.get(_TYPE_TEXT, 0),
        "image": counts.get(_TYPE_IMAGE, 0),
        "voice": counts.get(_TYPE_VOICE, 0),
        "video": counts.get(_TYPE_VIDEO, 0),
        "sticker": counts.get(_TYPE_STICKER, 0),
        "app": counts.get(_TYPE_APP, 0),
        "paipai": paipai,
        "speakers": len(speakers),
        "top": top,
    }


def _stats_from_local(db: Database, room_id: str, since_ts: str,
                      until_ts: str) -> dict:
    """本地 messages 表兜底：只有文本消息。"""
    rows = db.query(
        "SELECT sender_id, sender_name, COUNT(*) n FROM messages"
        " WHERE room_id=? AND ts>=? AND ts<? GROUP BY sender_id, sender_name",
        (room_id, since_ts, until_ts),
    )
    by_sender: dict[str, int] = {}
    for r in rows:
        key = r["sender_name"] or r["sender_id"] or "匿名群友"
        by_sender[key] = by_sender.get(key, 0) + int(r["n"] or 0)
    return {
        "total": sum(by_sender.values()),
        "text": sum(by_sender.values()),
        "image": 0, "voice": 0, "video": 0, "sticker": 0, "app": 0, "paipai": 0,
        "speakers": len(rows),
        "top": sorted(by_sender.items(), key=lambda kv: -kv[1])[:5],
    }


def _fmt(room_name: str, since_disp: str, until_disp: str, s: dict) -> str:
    bar = "-" * 12
    lines = [
        room_name or "本群",
        "消息统计(近一周)",
        bar,
        f"时间起: {since_disp}",
        f"时间止: {until_disp}",
        bar,
        f"文本消息: {s['text']}",
        f"图片消息: {s['image']}",
        f"视频消息: {s['video']}",
        f"表情包: {s['sticker']}",
    ]
    if s.get("voice"):
        lines.append(f"语音消息: {s['voice']}")
    if s.get("app"):
        lines.append(f"文件/链接: {s['app']}")
    lines += [f"拍了拍: {s['paipai']}", f"发言人数: {s['speakers']}",
              f"总消息: {s['total']}", bar, "发言Top5"]
    lines += [f"{i}.{name}【{n}】" for i, (name, n) in enumerate(s["top"], 1)]
    return "\n".join(lines)


def build_weekly_report(
    db: Database,
    bridge,
    room_id: str,
    room_name: str,
    since_ts: str,
    until_ts: str,
) -> str | None:
    """返回播报文本；该群本周没有消息则返回 None。"""
    names = _sender_names(db)
    stats = None
    if bridge is not None:
        from datetime import datetime, timezone as _tz

        def _epoch(ts: str) -> int:
            return int(datetime.fromisoformat(ts).timestamp())

        try:
            stats = _stats_via_bridge(bridge, room_id, _epoch(since_ts), _epoch(until_ts), names)
        except Exception:  # noqa: BLE001 统计失败不炸播报，走兜底
            stats = None
    if stats is None:
        stats = _stats_from_local(db, room_id, since_ts, until_ts)
    if not stats or stats["total"] <= 0:
        return None
    return _fmt(room_name, since_ts.replace("T", " "), until_ts.replace("T", " "), stats)
