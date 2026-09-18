#!/usr/bin/env python
"""WeChat-Hook 探针：验证 hook HTTP API 与消息库结构。

前置：微信 4.1.10.27 已启动、version.dll 已加载（端口 30001）、小号已扫码登录。

用法：
  python scripts/wxhook_probe.py                # 全量体检
  python scripts/wxhook_probe.py --send-test 群ID "文本"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "http://127.0.0.1:30001"


def post(path: str, payload: dict | None = None):
    import requests

    resp = requests.post(f"{API}{path}", json=payload or {}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get(path: str):
    import requests

    resp = requests.get(f"{API}{path}", timeout=20)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send-test", nargs=2, metavar=("群ID", "文本"), default=None)
    args = parser.parse_args()

    print("== 1. 登录状态 ==")
    try:
        print(json.dumps(get("/QueryDB/status"), ensure_ascii=False))
    except Exception as exc:
        print(f"hook 不可达（{exc}）：确认微信已启动且 version.dll 已加载", file=sys.stderr)
        return 1

    print("\n== 2. 机器人账号 ==")
    try:
        print(json.dumps(post("/GetSelfProfile"), ensure_ascii=False)[:300])
    except Exception as exc:
        print("GetSelfProfile 失败:", exc)

    print("\n== 3. 数据库列表 ==")
    dbs = post("/QueryDB/GetAllDBName")
    print(json.dumps(dbs, ensure_ascii=False)[:500])

    db_names = [d.get("dbName") for d in dbs if isinstance(d, dict)] if isinstance(dbs, list) else []

    print("\n== 4. 各库表名 ==")
    for db in db_names:
        try:
            tables = post("/QueryDB/execute", {"optDbName": db,
                                               "SQL": "SELECT name FROM sqlite_master WHERE type='table'"})
            names = [t.get("name") for t in tables.get("data", []) if isinstance(t, dict)]
            print(f"  {db}: {names[:20]}")
        except Exception as exc:
            print(f"  {db}: 失败 {exc}")

    print("\n== 5. 消息表结构与样本 ==")
    for db in db_names:
        try:
            tables = post("/QueryDB/execute", {"optDbName": db,
                                               "SQL": "SELECT name FROM sqlite_master WHERE type='table'"})
            for t in tables.get("data", []):
                name = (t or {}).get("name", "")
                if not name.upper().startswith("MSG"):
                    continue
                rows = post("/QueryDB/execute",
                            {"optDbName": db, "SQL": f'SELECT * FROM "{name}" ORDER BY rowid DESC LIMIT 2'})
                data = rows.get("data", [])
                if not data:
                    continue
                cols = list(data[0].keys())
                print(f"  {db}.{name} 列: {cols}")
                for r in data[:1]:
                    print("    样本:", json.dumps({k: str(v)[:40] for k, v in r.items()},
                                                  ensure_ascii=False)[:400])
        except Exception as exc:
            print(f"  {db}: {exc}")

    print("\n== 6. 群列表（ChatRoom 表）==")
    for db in db_names:
        try:
            rows = post("/QueryDB/execute", {"optDbName": db,
                                             "SQL": "SELECT Name, NickName FROM ChatRoom LIMIT 30"})
            for r in rows.get("data", []):
                print(f"  {r.get('Name')}  {r.get('NickName')}")
            break
        except Exception:
            continue

    if args.send_test:
        room, text = args.send_test
        post("/SendTextMsg", {"wxidorgid": room, "msg": text})
        print(f"\n已发送测试消息到 {room}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
