"""桥接层测试：mock 桥接行为 + WechatyBridge 协议（用桩进程，不登录微信）。"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from pelica.bridge.base import Message
from pelica.bridge.mock_bridge import MockBridge


def test_mock_feed_dispatch_and_outbox(tmp_path: Path):
    received: list[Message] = []
    outbox_file = tmp_path / "outbox.jsonl"
    bridge = MockBridge(echo=False, outbox_file=outbox_file)
    bridge.on_message(received.append)
    bridge.start()
    bridge.feed("你好呀", room="群A", sender="小明")
    assert len(received) == 1
    assert received[0].room_name == "群A"
    assert received[0].sender_name == "小明"
    bridge.send_text("mockroom::群A", "收到")
    assert any(o["text"] == "收到" for o in bridge.outbox)
    assert outbox_file.exists() and "收到" in outbox_file.read_text(encoding="utf-8")
    bridge.stop()


def test_mock_video_records(tmp_path: Path):
    bridge = MockBridge(echo=False)
    bridge.start()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftyp")
    bridge.send_video("mockroom::群A", video, caption="看看")
    kinds = [o["kind"] for o in bridge.outbox]
    assert "video" in kinds


def test_wechaty_protocol_roundtrip(tmp_path: Path, monkeypatch):
    """用桩 Node 脚本验证 WechatyBridge 的 JSON 行协议与就绪/消息分发。"""
    bridge_dir = tmp_path / "wechaty"
    bridge_dir.mkdir()
    stub = r'''
import json, sys, time
for line in sys.stdin:
    cmd = json.loads(line)
    if cmd["type"] == "hello":
        print(json.dumps({"type": "ready", "user": "stub-bot"}), flush=True)
        print(json.dumps({"type": "message", "room_id": "r1", "room_name": "群",
                          "sender_id": "u1", "sender_name": "路人",
                          "text": "@佩丽卡 你好", "is_at": True, "is_self": False,
                          "ts": "2026-09-18T00:00:00", "msg_id": "m1"}), flush=True)
        print(json.dumps({"type": "send_ack", "echo": cmd}), flush=True)
'''
    (bridge_dir / "bridge.py").write_text(stub, encoding="utf-8")

    import pelica.bridge.wechaty_bridge as wb

    class _PyStubBridge(wb.WechatyBridge):
        """同协议，但用 python -u 跑桩脚本，避免依赖 node/wechaty。"""

        def _spawn(self):
            import os
            import subprocess

            env = dict(**os.environ)
            env.update(self._env_extra)
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "bridge.py"],
                cwd=str(self._dir), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8", bufsize=1,
            )
            self._last_heartbeat = time.time()
            threading.Thread(target=self._read_loop, daemon=True).start()

    received: list[Message] = []
    bridge = _PyStubBridge(bridge_dir)
    bridge.on_message(received.append)
    bridge.start()
    bridge._send_raw({"type": "hello"})  # 桩收到后回 ready + message + ack

    for _ in range(50):
        if received:
            break
        time.sleep(0.05)
    assert received, "应通过协议收到一条群消息"
    assert received[0].room_id == "r1" and received[0].is_at is True
    bridge.stop()


import time  # noqa: E402
