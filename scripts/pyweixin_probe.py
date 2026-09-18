#!/usr/bin/env python
"""pyweixin 探针：验证微信 4.1+ UI 自动化环境。

前置条件：
  1. PC 微信 4.1.6+ 已安装并登录（机器人小号）
  2. 依赖已安装：pip install -r requirements-windows.txt

用法：
  python scripts/pyweixin_probe.py                 # 环境检查 + 群列表 + 监听 30 秒
  python scripts/pyweixin_probe.py --send-test 群名 "测试消息"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send-test", nargs=2, metavar=("群名", "文本"), default=None)
    parser.add_argument("--listen", default="30", help="监听秒数，默认 30")
    args = parser.parse_args()

    try:
        from pyweixin import Contacts, Files, Messages, Monitor
        from pyweixin.Config import GlobalConfig
    except Exception as exc:
        print(f"pyweixin 导入失败：{exc}", file=sys.stderr)
        return 1

    GlobalConfig.is_maximize = False
    GlobalConfig.close_weixin = False

    print("== 环境检查 ==")
    print("微信版本:", GlobalConfig.Version)

    print("\n== 群列表 ==")
    groups = Contacts.get_groups_info()
    for g in groups:
        print(" ", g)

    if args.send_test:
        room, text = args.send_test
        Messages.send_messages_to_friend(friend=room, messages=[text])
        print(f"\n已向「{room}」发送：{text}")

    seconds = int(args.listen)
    print(f"\n== 监听 {seconds} 秒内的群消息（在群里说句话试试）==")
    result = Monitor.listen_on_newMessages(duration=f"{seconds}s", maxPages=3)
    for chat, msgs in (result or {}).items():
        print(f"[{chat}]")
        for m in msgs or []:
            print("   ", m)
    if not result:
        print("（没有新消息）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
