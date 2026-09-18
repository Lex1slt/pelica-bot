#!/usr/bin/env python
"""wcferry 探针：验证 PC 微信 Hook 环境，并列出群供白名单配置。

前置条件（Windows）：
  1. pip install -r requirements-windows.txt
  2. PC 微信已安装并登录（wcferry 39.x 要求微信 3.9.x，版本不符会报错，
     按报错/项目说明安装对应版本 WeChatSetup）

用法：
  python scripts/wcf_probe.py                      # 查看登录状态与群列表
  python scripts/wcf_probe.py --send-test 群ID "测试消息"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send-test", nargs=2, metavar=("群ID", "文本"), default=None,
                        help="向指定群发一条文本测试消息")
    args = parser.parse_args()

    try:
        from wcferry import Wcf
    except ImportError:
        print("wcferry 未安装：pip install -r requirements-windows.txt", file=sys.stderr)
        return 1

    print("连接 PC 微信（需要微信已登录）…")
    try:
        wcf = Wcf(debug=False)
    except Exception as exc:
        print(f"连接失败：{exc}\n"
              "常见原因：① 微信未启动/未登录；② 微信版本与 wcferry 不匹配"
              "（39.x 对应微信 3.9.x，需按项目说明安装指定版本）；"
              "③ 权限不足（用管理员试试）", file=sys.stderr)
        return 1

    print("登录状态:", wcf.is_login())
    print("机器人 wxid:", wcf.get_self_wxid())

    rooms = []
    for c in wcf.get_contacts():
        wxid = c.get("wxid", "")
        if wxid.endswith("@chatroom"):
            rooms.append((wxid, c.get("name", "") or wxid))
    print(f"\n群列表（{len(rooms)} 个）——把要启用的群名填进 .env 的 GROUP_WHITELIST：")
    for wxid, name in sorted(rooms, key=lambda x: x[1]):
        print(f"  {name}  ({wxid})")

    if args.send_test:
        room_id, text = args.send_test
        wcf.send_text(text, room_id)
        print(f"\n已向 {room_id} 发送测试消息：{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
