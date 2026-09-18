#!/usr/bin/env python
"""手动刷新群成员长期印象（也可等每周五播报时自动刷新）。

用法：
  python scripts/update_impressions.py            # 全部最近 7 天活跃的群
  python scripts/update_impressions.py --room 群ID或群名
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.config import load_settings  # noqa: E402
from pelica.db import Database  # noqa: E402
from pelica.logging_setup import setup_logging  # noqa: E402
from pelica.social import SocialMemory  # noqa: E402
from main import build_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", default="", help="只刷新指定群（ID 或名称）")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_dir, settings.log_level)
    db = Database(settings.db_path)
    social = SocialMemory(db, tz=settings.timezone)
    client = build_client(settings)

    rooms = db.query(
        "SELECT DISTINCT room_id, room_name FROM messages WHERE ts >= ?",
        (__import__("time").strftime("%Y-%m-%dT%H:%M:%S",
                                     __import__("time").localtime(
                                         __import__("time").time() - 7 * 86400)),),
    )
    done = 0
    for row in rooms:
        if args.room and args.room not in (row["room_id"], row["room_name"]):
            continue
        n = social.refresh_impressions(row["room_id"], client)
        print(f"{row['room_name'] or row['room_id']}: 更新 {n} 人印象")
        done += 1
    if not done:
        print("没有匹配的活跃群")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
