#!/usr/bin/env python
"""佩丽卡监督 入口。

用法：
  python main.py                       # 按 .env 的 BRIDGE_MODE 启动（默认 mock）
  python main.py --bridge mock --interactive
                                       # mock 桥接 + 控制台交互群聊
  python main.py --smoke               # 注入几条预置消息做端到端冒烟后退出
  python main.py --bridge wechaty      # 生产：Wechaty + PadLocal
  python main.py --no-weekly --no-douyin
                                       # 生产模式下独立关闭某个管道
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("pelica.main")

from pelica.alerts import Alerter
from pelica.bridge.base import Bridge, Message
from pelica.bridge.mock_bridge import MockBridge
from pelica.bridge.wechaty_bridge import WechatyBridge
from pelica.config import Settings, load_settings
from pelica.db import Database
from pelica.douyin.parser import DouyinParser
from pelica.douyin.pipeline import DouyinPipeline
from pelica.graph.matcher import EntityMatcher
from pelica.graph.walker import GraphWalker
from pelica.llm.answer import Answerer
from pelica.llm.client import DeepSeekClient
from pelica.llm import persona
from pelica.logging_setup import setup_logging
from pelica.pipeline.router import GroupBot
from pelica.retrieval.cache import QACache
from pelica.retrieval.retriever import Retriever
from pelica.social import SocialMemory
from pelica.stats.scheduler import DailyScheduler, WeeklyScheduler
from pelica.stats.weekly import build_weekly_report


def build_client(settings: Settings) -> DeepSeekClient:
    return DeepSeekClient(
        settings.deepseek_api_key,
        settings.deepseek_base_url,
        settings.deepseek_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        reasoning_effort=settings.deepseek_reasoning_effort,
    )


def build_answerer(settings: Settings, db: Database, client: DeepSeekClient | None = None) -> Answerer:
    retriever = Retriever(db, EntityMatcher(db), GraphWalker(db))
    return Answerer(client or build_client(settings), retriever)


def build_bridge(settings: Settings, alerter: Alerter) -> Bridge:
    if settings.bridge_mode == "wechaty":
        if not settings.wechaty_token:
            raise SystemExit("BRIDGE_MODE=wechaty 需要在 .env 配置 WECHATY_TOKEN")
        return WechatyBridge(
            bridge_dir=settings.wechaty_dir,
            env_extra={"WECHATY_TOKEN": settings.wechaty_token},
            on_failure=alerter.notify,
            max_failures=settings.alert_failure_threshold,
        )
    if settings.bridge_mode == "wcf":
        from pelica.bridge.wcf_bridge import WcfBridge  # Windows 专用，延迟导入

        return WcfBridge(on_failure=alerter.notify,
                         max_failures=settings.alert_failure_threshold)
    if settings.bridge_mode == "pyweixin":
        from pelica.bridge.pyweixin_bridge import PyweixinBridge  # Windows + 微信4.1+

        return PyweixinBridge(groups=settings.group_whitelist,
                              at_aliases=settings.at_aliases,
                              on_failure=alerter.notify,
                              max_failures=settings.alert_failure_threshold)
    if settings.bridge_mode == "wxhook":
        from pelica.bridge.wxhook_bridge import WeChatHookBridge  # Windows + 微信4.1.10.27 + WeChat-Hook

        return WeChatHookBridge(
            api_url=settings.wxhook_api_url,
            groups=settings.group_whitelist,
            at_aliases=settings.at_aliases,
            on_failure=alerter.notify,
            max_failures=settings.alert_failure_threshold,
            video_xml_path=settings.data_dir / "cached_video_xml.txt",
        )
    return MockBridge(bot_name="佩丽卡")


def weekly_job(settings: Settings, db: Database, bridge: Bridge,
               social=None, client: DeepSeekClient | None = None):
    zone = ZoneInfo(settings.timezone)
    now = datetime.now(zone)
    until = now.strftime("%Y-%m-%dT%H:%M:%S")
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    rooms = db.query(
        "SELECT DISTINCT room_id, room_name FROM messages"
        " WHERE ts >= ? AND room_id LIKE '%@chatroom'", (since,)
    )
    for row in rooms:
        report = build_weekly_report(db, bridge, row["room_id"], row["room_name"], since, until)
        if report:
            bridge.send_text(row["room_id"], report)
        # 播报顺带刷新对本群活跃成员的长期印象（每群一次 LLM 调用）
        if social is not None and client is not None:
            try:
                social.refresh_impressions(row["room_id"], client)
            except Exception:  # noqa: BLE001
                log.exception("印象刷新失败：%s", row["room_id"])


class _LinkParsers:
    """按链接类型分发到对应平台解析器（抖音 / B 站），对管道透明。"""

    def __init__(self, parsers):
        self._parsers = parsers

    @property
    def download_dir(self):
        return self._parsers[0].download_dir

    def detect(self, text: str) -> list[str]:
        out, seen = [], set()
        for p in self._parsers:
            for u in p.detect(text):
                if u not in seen:
                    seen.add(u)
                    out.append(u)
        return out[:2]

    def resolve(self, url: str):
        for p in self._parsers:
            if p.detect(url):
                return p.resolve(url)
        from pelica.douyin.parser import DouyinError

        raise DouyinError(f"不支持的链接：{url[:60]}")


def greeting_job(kind: str, settings: Settings, db: Database, bridge: Bridge):
    """定时问好：向最近有动静的白名单群发一句人设问候（kind: morning/night）。"""
    zone = ZoneInfo(settings.timezone)
    since = (datetime.now(zone) - timedelta(days=settings.greeting_active_days)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    rooms = db.query(
        "SELECT DISTINCT room_id, room_name FROM messages"
        " WHERE ts >= ? AND room_id LIKE '%@chatroom'", (since,)
    )
    text = persona.pick(persona.GREETING_MORNING if kind == "morning" else persona.GREETING_NIGHT)
    for row in rooms:
        name, rid = row["room_name"], row["room_id"]
        if settings.group_whitelist and name not in settings.group_whitelist and rid not in settings.group_whitelist:
            continue
        try:
            bridge.send_text(rid, text)
            log.info("已发送%s问好 -> %s", "早上" if kind == "morning" else "晚间", name or rid)
        except Exception:  # noqa: BLE001 单群失败不影响其他群
            log.exception("问好发送失败：%s", rid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", choices=["mock", "wechaty", "wcf", "pyweixin", "wxhook"], help="覆盖 .env 的 BRIDGE_MODE")
    parser.add_argument("--interactive", action="store_true", help="mock 模式下从控制台读消息")
    parser.add_argument("--smoke", action="store_true", help="端到端冒烟：注入预置消息后退出")
    parser.add_argument("--no-weekly", action="store_true", help="关闭每周播报")
    parser.add_argument("--no-greeting", action="store_true", help="关闭每日早晚问好")
    parser.add_argument("--no-douyin", action="store_true", help="关闭抖音管道")
    args = parser.parse_args()

    settings = load_settings()
    from pelica.character import apply_character
    apply_character(settings)
    setup_logging(settings.log_dir, settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)

    alerter = Alerter(settings.alert_kind, settings.alert_webhook_url)
    bridge = build_bridge(settings, alerter)
    if args.bridge and args.bridge != settings.bridge_mode:
        settings.bridge_mode = args.bridge
        bridge = build_bridge(settings, alerter)

    douyin = None
    video_parsers = []
    if settings.douyin_enabled and not args.no_douyin:
        video_parsers.append(
            DouyinParser(
                settings.douyin_download_dir,
                resolver_api=settings.douyin_resolver_api,
            )
        )
    if settings.bilibili_enabled:
        from pelica.bilibili.parser import BiliParser

        video_parsers.append(BiliParser(settings.douyin_download_dir))

    douyin = None
    if video_parsers:
        send_image = getattr(bridge, "send_image", None)
        if len(video_parsers) == 1:
            link_parser = video_parsers[0]
        else:
            link_parser = _LinkParsers(video_parsers)
        douyin = DouyinPipeline(
            parser=link_parser,
            send_video=bridge.send_video,
            send_text=bridge.send_text,
            send_image=send_image,
            keep_hours=settings.douyin_keep_hours,
        )

    social_memory = SocialMemory(db, tz=settings.timezone)
    llm_client = build_client(settings)
    answerer = build_answerer(settings, db, llm_client)

    bot = GroupBot(
        bridge=bridge,
        db=db,
        answerer=answerer,
        qa_cache=QACache(db),
        douyin=douyin,
        whitelist=settings.group_whitelist,
        private_whitelist=settings.private_whitelist,
        at_aliases=settings.at_aliases,
        social=social_memory,
        matcher=EntityMatcher(db),
    )

    scheduler = None
    if settings.weekly_report_enabled and not args.no_weekly:
        scheduler = WeeklyScheduler(
            job=lambda: weekly_job(settings, db, bridge, social_memory, llm_client),
            weekday=settings.weekly_report_weekday,
            time_str=settings.weekly_report_time,
            tz=settings.timezone,
        )

    daily_schedulers: list[DailyScheduler] = []
    if settings.greeting_enabled and not args.no_greeting:
        daily_schedulers.append(DailyScheduler(
            job=lambda: greeting_job("morning", settings, db, bridge),
            time_str=settings.greeting_morning_time,
            tz=settings.timezone, name="morning-greeting",
        ))
        daily_schedulers.append(DailyScheduler(
            job=lambda: greeting_job("night", settings, db, bridge),
            time_str=settings.greeting_night_time,
            tz=settings.timezone, name="night-greeting",
        ))

    bot.start()
    bridge.start()
    if scheduler:
        scheduler.start()
    for ds in daily_schedulers:
        ds.start()
    log.info("佩丽卡监督已上线（bridge=%s, whitelist=%s）",
             bridge.mode, settings.group_whitelist or "未配置(全部放行)")

    if args.smoke:
        return run_smoke(bridge)

    if args.interactive and isinstance(bridge, MockBridge):
        bridge.start_interactive()
        print("== mock 群聊已启动。输入格式：群名|昵称|消息（消息以 @ 开头表示 @ 了佩丽卡），Ctrl+C 退出 ==")

    stop_signal = {"flag": False}

    def _shutdown(signum, _frame):
        if stop_signal["flag"]:
            return
        stop_signal["flag"] = True
        log.info("收到信号 %s，正在下线…", signum)
        for ds in daily_schedulers:
            ds.stop()
        if scheduler:
            scheduler.stop()
        bot.stop()
        bridge.stop()
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 心跳文件：容器健康检查据此判断进程活性
    heartbeat_file = settings.data_dir / "heartbeat"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    last_beat = 0.0
    while True:
        now_ts = time.time()
        if now_ts - last_beat > 30:
            heartbeat_file.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
            last_beat = now_ts
        time.sleep(1)


def run_smoke(bridge: Bridge) -> int:
    """端到端冒烟：模拟一个群里的几条消息，观察回复（mock 桥接，不碰真实微信）。"""
    assert isinstance(bridge, MockBridge)
    time.sleep(0.5)
    bridge.feed("今天天气不错啊", room="冒烟群", sender="阿测试", is_at=False)      # 不应回复
    bridge.feed("@佩丽卡 你是真人吗", room="冒烟群", sender="阿测试")               # 身份问题
    bridge.feed("@佩丽卡 帝江号是什么？", room="冒烟群", sender="阿测试")           # 语料问题（走 LLM）
    time.sleep(8)  # 等 worker 处理完（LLM 调用可能要几秒）
    print(f"== 冒烟完成，机器人共发出 {len(bridge.outbox)} 条消息 ==")
    bridge.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
