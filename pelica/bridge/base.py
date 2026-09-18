"""桥接抽象：所有实现（mock / wechaty）对外签名完全一致。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Message:
    """一条群消息的统一表示。"""

    room_id: str
    room_name: str
    sender_id: str
    sender_name: str
    text: str
    is_at: bool = False          # 是否 @ 了机器人（微信原生 @ 或文本触发词）
    is_self: bool = False        # 是否机器人自己发的
    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    msg_id: str = ""


MessageHandler = Callable[[Message], None]


class Bridge(ABC):
    """群消息的进出通道。start/stop 可安全重复调用。"""

    mode: str = "abstract"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def on_message(self, handler: MessageHandler) -> None:
        """注册消息回调（收到群消息时调用 handler(Message)）。"""

    @abstractmethod
    def send_text(self, room_id: str, text: str) -> None: ...

    @abstractmethod
    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None: ...

    @abstractmethod
    def is_healthy(self) -> bool: ...

    # -- 可选能力（统计播报用）；不支持实现的桥返回 None，调用方走本地库兜底 ----

    self_wxid: str = ""   # 机器人自己的 wxid（能拿到的话）

    def query_wechat_db(self, db_name: str, sql: str) -> list[dict] | None:
        """直查微信内部 SQLite；默认不支持，返回 None。"""
        return None
