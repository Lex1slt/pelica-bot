#!/usr/bin/env python
"""容器健康检查：进程心跳 + 数据库可读即健康。"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

DATA_DIR = Path("/app/data")
HEARTBEAT_MAX_AGE = 180  # 秒


def main() -> int:
    heartbeat = DATA_DIR / "heartbeat"
    if not heartbeat.exists():
        print("no heartbeat file", file=sys.stderr)
        return 1
    age = time.time() - heartbeat.stat().st_mtime
    if age > HEARTBEAT_MAX_AGE:
        print(f"heartbeat stale: {age:.0f}s", file=sys.stderr)
        return 1
    db_path = DATA_DIR / "pelica.db"
    if not db_path.exists():
        print("no database", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
