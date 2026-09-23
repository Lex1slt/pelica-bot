"""网关日志：环形缓冲 + WS 广播 + 文件落盘（全部先脱敏）。

直接管理文件句柄（不经 logging 单例），多实例（测试）互不串目录。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path

from gateway.redact import redact

MAX_BUFFER = 800
MAX_FILE_BYTES = 4 * 1024 * 1024


class LogHub:
    def __init__(self, log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / "gateway.log"
        self._buffer: deque[dict] = deque(maxlen=MAX_BUFFER)
        self._subscribers: set[asyncio.Queue] = set()
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115 测试多实例场景

    def emit(self, source: str, level: str, message: str) -> dict:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": source,       # gateway | core | sandbox
            "level": level.lower(),
            "message": redact(str(message)),
        }
        self._buffer.append(entry)
        try:
            self._file.write(f"{entry['ts']} {level.upper()} [{source}] "
                             f"{entry['message']}\n")
            self._file.flush()
            if self._file.tell() > MAX_FILE_BYTES:
                self._rotate()
        except (OSError, ValueError):
            pass
        for q in list(self._subscribers):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass
        return entry

    def _rotate(self) -> None:
        try:
            self._file.close()
            rotated = self._path.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            self._path.replace(rotated)
            self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
        except OSError:
            pass

    @property
    def file_path(self) -> Path:
        return self._path

    def recent(self, limit: int = 200) -> list[dict]:
        items = list(self._buffer)
        return items[-int(limit):]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)
