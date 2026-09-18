"""周期调度：每周固定时刻（默认周五 18:00，Asia/Shanghai）向活跃群发播报。

设计成可注入时钟的独立线程循环，便于测试：
  WeeklyScheduler(build_and_send, weekday="fri", time_str="18:00",
                  tz="Asia/Shanghai").start()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

WEEKDAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


def next_run(weekday: str | None, time_str: str, tz: str,
             now: datetime | None = None) -> datetime:
    """下次触发时刻（tz 本地时间）。weekday=None 表示每天；否则按周几。

    若本周（今天）时刻已过则为下周（明天）同一时刻。
    """
    zone = ZoneInfo(tz)
    now_local = now.astimezone(zone) if now else datetime.now(zone)
    hour, minute = (int(x) for x in time_str.split(":")[:2])
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        wd = WEEKDAY_MAP[weekday.lower()[:3]]
        candidate += timedelta(days=(wd - candidate.weekday()) % 7)
    if candidate <= now_local:
        candidate += timedelta(days=7 if weekday is not None else 1)
    return candidate


class WeeklyScheduler:
    def __init__(
        self,
        job,  # Callable[[], None]：触发时执行的播报动作
        weekday: str = "fri",
        time_str: str = "18:00",
        tz: str = "Asia/Shanghai",
        check_interval: float = 20.0,
    ):
        self._job = job
        self._weekday = weekday
        self._time_str = time_str
        self._tz = tz
        self._check_interval = check_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next: datetime | None = None

    @property
    def next_run_time(self) -> datetime:
        if self._next is None:
            self._next = next_run(self._weekday, self._time_str, self._tz)
        return self._next

    def start(self) -> None:
        if self._next is None:
            self._next = next_run(self._weekday, self._time_str, self._tz)
        log.info("每周播报已排程：%s %s %s（下一次 %s）",
                 self._weekday, self._time_str, self._tz, self._next)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="weekly-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            zone = ZoneInfo(self._tz)
            now_local = datetime.now(zone)
            if self._next is None:
                self._next = next_run(self._weekday, self._time_str, self._tz)
            if now_local >= self._next:
                try:
                    self._job()
                except Exception:  # noqa: BLE001
                    log.exception("每周播报执行失败")
                # 滚到下一周，防止同一分钟重复触发
                self._next = next_run(self._weekday, self._time_str, self._tz,
                                      now=self._next + timedelta(seconds=1))
                log.info("播报完成，下一次 %s", self._next)
            time.sleep(self._check_interval)


class DailyScheduler(WeeklyScheduler):
    """每天固定时刻触发（早上问好 / 晚上晚安）。"""

    def __init__(self, job, time_str: str = "07:30", tz: str = "Asia/Shanghai",
                 check_interval: float = 20.0, name: str = "daily-job"):
        super().__init__(job=job, weekday=None, time_str=time_str, tz=tz,
                         check_interval=check_interval)
        self._name = name

    def start(self) -> None:
        if self._next is None:
            self._next = next_run(None, self._time_str, self._tz)
        log.info("每日任务[%s]已排程：%s %s（下一次 %s）",
                 self._name, self._time_str, self._tz, self._next)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"daily-{self._name}")
        self._thread.start()
