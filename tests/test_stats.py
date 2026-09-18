"""统计播报与调度测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pelica.db import Database
from pelica.stats.scheduler import WeeklyScheduler, next_run
from pelica.stats.weekly import build_weekly_report


def _seed_week(db: Database, room_id="room-1", room_name="测试群"):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    rows = []
    for i in range(6):
        rows.append(("阿测试", f"今天源石技艺的讨论很热烈{i}", 1))
    for i in range(4):
        rows.append(("小李", f"哈哈，帝江号食堂今天吃什么{i}", 0))
    for i in range(2):
        rows.append(("老王", f"同意楼上{i}", 0))
    for i, (sender, text, is_at) in enumerate(rows):
        ts = (now - timedelta(days=2, hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
        db.execute(
            "INSERT INTO messages(room_id,room_name,sender_id,sender_name,ts,is_at,kind,text)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (room_id, room_name, f"sid-{sender}", sender, ts, is_at, "text", text),
        )


def test_weekly_report_top3(db: Database):
    _seed_week(db)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    until = now.strftime("%Y-%m-%dT%H:%M:%S")
    report = build_weekly_report(db, "room-1", "测试群", since, until)
    assert report is not None
    assert "阿测试" in report and "小李" in report and "老王" in report
    # 佩丽卡口吻：有结尾礼貌语；不出现机器腔
    assert "第" not in report or "前三名" in report
    assert "AI" not in report and "语料" not in report


def test_weekly_report_empty_room(db: Database):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    until = now.strftime("%Y-%m-%dT%H:%M:%S")
    assert build_weekly_report(db, "no-such-room", "空群", since, until) is None


def test_next_run_friday():
    zone = ZoneInfo("Asia/Shanghai")
    # 2026-09-18 是周五；15:00 时下次播报 = 当天 18:00
    now = datetime(2026, 9, 18, 15, 0, tzinfo=zone)
    nxt = next_run("fri", "18:00", "Asia/Shanghai", now=now)
    assert nxt.weekday() == 4 and nxt.hour == 18
    assert (nxt - now).total_seconds() == 3 * 3600
    # 20:00（已过 18:00）-> 下周五 18:00，即 6 天 22 小时后
    now2 = datetime(2026, 9, 18, 20, 0, tzinfo=zone)
    nxt2 = next_run("fri", "18:00", "Asia/Shanghai", now=now2)
    assert nxt2 - now2 == timedelta(days=6, hours=22)
    # 周三 10:00 -> 本周五 18:00
    now3 = datetime(2026, 9, 16, 10, 0, tzinfo=zone)
    nxt3 = next_run("fri", "18:00", "Asia/Shanghai", now=now3)
    assert (nxt3 - now3) == timedelta(days=2, hours=8)


def test_scheduler_fires_job(monkeypatch):
    fired = []

    def job():
        fired.append(datetime.now(ZoneInfo("Asia/Shanghai")))

    s = WeeklyScheduler(job, weekday="fri", time_str="18:00", tz="Asia/Shanghai",
                        check_interval=0.05)
    # 把下一次触发时间改到马上
    s._next = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(seconds=1)
    s.start()
    import time

    time.sleep(0.5)
    s.stop()
    assert len(fired) == 1, "应恰好触发一次并滚动到下周"
    # 触发后下一次应在未来（今天 18:00 或下周，取决于当前时刻）
    assert s.next_run_time > datetime.now(ZoneInfo("Asia/Shanghai"))
