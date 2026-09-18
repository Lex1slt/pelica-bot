"""本地开发用 mock 桥接：控制台收发，不发任何真实微信消息。

两种驱动方式：
- feed(Message)：编程注入（测试 / 脚本）；
- 交互模式：线程读 stdin，每行一条消息，格式：
    群名|发送者昵称|文本            （普通发言）
    群名|发送者昵称|@文本           （文本以 @ 开头即视为 @ 了机器人）
  发送方输出形如：[佩丽卡 -> 群名] 文本
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

from pelica.bridge.base import Bridge, Message, MessageHandler

log = logging.getLogger(__name__)


class MockBridge(Bridge):
    mode = "mock"

    def __init__(self, bot_name: str = "佩丽卡", echo: bool = True, outbox_file: Path | None = None):
        self._bot_name = bot_name
        self._echo = echo
        self._handler: MessageHandler | None = None
        self._outbox: list[dict] = []
        self._outbox_file = outbox_file
        self._started = False
        self._stdin_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        if outbox_file is not None:
            outbox_file.parent.mkdir(parents=True, exist_ok=True)

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_flag.clear()

    def start_interactive(self) -> None:
        self.start()
        self._stdin_thread = threading.Thread(target=self._stdin_loop, daemon=True)
        self._stdin_thread.start()

    def stop(self) -> None:
        self._started = False
        self._stop_flag.set()

    def is_healthy(self) -> bool:
        return self._started

    # -- 消息 ---------------------------------------------------------------

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def feed(
        self,
        text: str,
        room: str = "测试群",
        sender: str = "测试用户",
        is_at: bool = True,
        sender_id: str = "mock-sender",
    ) -> None:
        """注入一条消息并同步分发给 handler（测试友好：同步、无线程）。"""
        msg = Message(
            room_id=f"mockroom::{room}",
            room_name=room,
            sender_id=sender_id,
            sender_name=sender,
            text=text,
            is_at=is_at,
            ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
            msg_id=f"mock-{time.time_ns()}",
        )
        if self._handler is not None:
            self._handler(msg)

    def _stdin_loop(self) -> None:
        for line in sys.stdin:
            if self._stop_flag.is_set():
                break
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            try:
                if len(parts) == 3:
                    room, sender, text = parts
                else:
                    room, sender, text = "测试群", "群友", line
                is_at = text.startswith("@")
                if is_at:
                    text = text[1:]
                self.feed(text, room=room, sender=sender, is_at=is_at)
            except Exception as exc:  # noqa: BLE001
                log.error("mock 输入处理失败：%s (%s)", line, exc)

    # -- 发送 ---------------------------------------------------------------

    def send_text(self, room_id: str, text: str) -> None:
        room = room_id.removeprefix("mockroom::") if room_id.startswith("mockroom::") else room_id
        if self._echo:
            print(f"[{self._bot_name} -> {room}] {text}", flush=True)
        self._record(room_id, "text", text)

    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None:
        room = room_id.removeprefix("mockroom::") if room_id.startswith("mockroom::") else room_id
        size = ""
        if Path(video_path).exists():
            size = f"（{Path(video_path).stat().st_size / 1024 / 1024:.1f} MB）"
        if self._echo:
            print(f"[{self._bot_name} -> {room}] [视频] {video_path} {size}", flush=True)
            if caption:
                print(f"[{self._bot_name} -> {room}] {caption}", flush=True)
        self._record(room_id, "video", caption or str(video_path))

    # -- 内部 ---------------------------------------------------------------

    def _record(self, room_id: str, kind: str, text: str) -> None:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "room": room_id,
                 "kind": kind, "text": text}
        self._outbox.append(entry)
        if self._outbox_file is not None:
            with open(self._outbox_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def outbox(self) -> list[dict]:
        return list(self._outbox)
