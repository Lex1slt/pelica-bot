"""生产桥接：pyweixin（微信 4.1+ PC 客户端 UI 自动化，免费）。

原理：不注入、不逆向，直接用 pywinauto/UIAutomation 驱动真实 PC 微信
（Weixin 4.1+）界面——监听群窗口新消息、代发文本和文件。因此：
- 不受「旧版本协议被服务端封禁」影响（用的就是官方最新客户端）；
- 新注册小号也可登录（正常扫码登录官方客户端）；
- 代价：UI 自动化需要微信窗口在桌面上；机器人巡检时会短暂占用鼠标键盘；
  消息捕获可靠性低于协议类方案。

来源：https://github.com/Hello-Mr-Crab/pywechat 的 pyweixin 模块（LGPL-2.1），
已内置在 vendor/pyweixin/。

双开配置（机器人用小号，你日常用大号）：
  - 用 bat 多开第二个微信 4.1 实例（start "" "Weixin.exe"），小号扫码登录；
  - 本桥接通过进程 PID 定位小号实例（见 scripts/pyweixin_probe.py 输出）。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from pelica.bridge.base import Bridge, Message, MessageHandler

log = logging.getLogger(__name__)

VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "vendor"
LISTEN_SLICE_SEC = 15  # 每轮监听时长


class PyweixinBridge(Bridge):
    mode = "pyweixin"

    def __init__(
        self,
        groups: list[str],
        at_aliases: list[str],
        bot_nickname: str = "佩丽卡监督",
        on_failure=None,
        max_failures: int = 3,
        duration_sec: int = LISTEN_SLICE_SEC,
    ):
        self._groups = [g.strip() for g in groups if g.strip()]
        self._at_aliases = at_aliases
        self._bot_nickname = bot_nickname
        self._on_failure = on_failure
        self._max_failures = max_failures
        self._duration = duration_sec

        self._handler: MessageHandler | None = None
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._healthy = False
        self._failures = 0

    # -- 内部工具 -----------------------------------------------------------

    @staticmethod
    def _import_pyweixin():
        """vendor 目录里的 pyweixin（优先于任何全局安装）。"""
        if str(VENDOR_DIR) not in sys.path:
            sys.path.insert(0, str(VENDOR_DIR))
        import pyweixin  # noqa: PLC0415

        return pyweixin

    def _parse_message(self, item, chat_name: str) -> Message | None:
        """监听返回的单条消息 -> 框架 Message。

        pyweixin 的消息条目可能是 dict（含 发送人/消息 字段）或纯文本，
        这里做防御性解析；解析不出的原文会进 DEBUG 日志便于迭代。
        """
        text = ""
        sender = ""
        if isinstance(item, dict):
            raw = dict(item)
            sender = (raw.get("sender") or raw.get("发送人")
                      or raw.get("sender_name") or raw.get("昵称") or "")
            text = (raw.get("content") or raw.get("消息") or raw.get("text") or "")
        else:
            text = str(item)
        text = text.strip()
        if not text:
            return None
        # 群消息文本常见「昵称：内容」前缀
        if not sender and ("：" in text or ":" in text):
            head, _, tail = text.partition("：")
            if not tail:
                head, _, tail = text.partition(":")
            if head and len(head) <= 30:
                sender, text = head, tail.strip()
        is_at = any(f"@{alias}" in text for alias in self._at_aliases)
        return Message(
            room_id=f"pyweixin::{chat_name}",
            room_name=chat_name,
            sender_id=sender,
            sender_name=sender,
            text=text,
            is_at=is_at,
            ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
            msg_id=f"pw-{time.time_ns()}",
        )

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pyweixin-bridge")
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    def is_healthy(self) -> bool:
        return self._healthy

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    # -- 主循环 ---------------------------------------------------------------

    def _loop(self) -> None:
        pw = self._import_pyweixin()
        from pyweixin.Config import GlobalConfig

        GlobalConfig.is_maximize = False
        GlobalConfig.close_weixin = False
        log.info("pyweixin 桥接启动，监听群：%s", self._groups or "未配置")
        while not self._stop_flag.is_set():
            try:
                new_msgs = pw.Monitor.listen_on_newMessages(
                    duration=f"{self._duration}s", maxPages=3
                )
                self._healthy = True
                self._failures = 0
                for chat_name, msgs in (new_msgs or {}).items():
                    if chat_name not in self._groups:
                        continue
                    for item in msgs or []:
                        message = self._parse_message(item, chat_name)
                        if message is None:
                            continue
                        if self._handler is not None:
                            self._handler(message)
            except Exception as exc:  # noqa: BLE001
                self._failures += 1
                log.error("pyweixin 监听失败（连续 %d 次）：%s",
                          self._failures, exc)
                self._healthy = False
                if self._on_failure is not None and self._failures >= self._max_failures:
                    try:
                        self._on_failure(f"pyweixin 桥接连续 {self._failures} 次监听失败")
                    except Exception:  # noqa: BLE001
                        log.exception("告警回调失败")
                time.sleep(min(15 * self._failures, 60))

    # -- 发送 -----------------------------------------------------------------

    @staticmethod
    def _group_name(room_id: str) -> str:
        return room_id.removeprefix("pyweixin::") if room_id.startswith("pyweixin::") else room_id

    def send_text(self, room_id: str, text: str) -> None:
        pw = self._import_pyweixin()
        pw.Messages.send_messages_to_friend(friend=self._group_name(room_id),
                                            messages=[text])

    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None:
        pw = self._import_pyweixin()
        group = self._group_name(room_id)
        pw.Files.send_files_to_friend(friend=group, files=[str(video_path)])
        if caption:
            pw.Messages.send_messages_to_friend(friend=group, messages=[caption])
