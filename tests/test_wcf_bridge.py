"""WcfBridge 消息映射与发送测试（用桩，不碰真实微信）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pelica.bridge.wcf_bridge import WcfBridge


class FakeWxMsg:
    def __init__(self, roomid="", sender="", content="", at_bot=False,
                 group=True, self_msg=False, msg_id=1):
        self.roomid = roomid
        self.sender = sender
        self.content = content
        self.id = msg_id
        self._at_bot = at_bot
        self._group = group
        self._self = self_msg

    def from_group(self):
        return self._group

    def from_self(self):
        return self._self

    def is_at(self, wxid):
        return self._at_bot


class FakeWcf:
    def __init__(self):
        self.sent_text = []
        self.sent_files = []

    def send_text(self, msg, receiver, aters=""):
        self.sent_text.append((receiver, msg))

    def send_file(self, path, receiver):
        self.sent_files.append((receiver, path))


def make_bridge():
    bridge = WcfBridge()
    bridge._wcf = FakeWcf()
    bridge._self_wxid = "bot-wxid"
    bridge._room_names = {"123@chatroom": "测试群"}
    bridge._member_names = {"123@chatroom": {"user-a": "阿夜", "bot-wxid": "佩丽卡监督"}}
    bridge._member_at["123@chatroom"] = 9e9  # 冷却，避免触发 RPC
    return bridge


def test_to_message_maps_fields():
    bridge = make_bridge()
    msg = bridge._to_message(FakeWxMsg(
        roomid="123@chatroom", sender="user-a", content="@佩丽卡 你好",
        at_bot=True, msg_id=77))
    assert msg is not None
    assert msg.room_id == "123@chatroom"
    assert msg.room_name == "测试群"
    assert msg.sender_id == "user-a"
    assert msg.sender_name == "阿夜"
    assert msg.is_at is True
    assert msg.msg_id == "77"


def test_to_message_skips_self_and_non_group():
    bridge = make_bridge()
    assert bridge._to_message(FakeWxMsg(group=False, content="hi")) is None
    assert bridge._to_message(FakeWxMsg(group=True, self_msg=True)) is None
    assert bridge._to_message(FakeWxMsg(group=True, content="")) is None


def test_send_text_and_video_via_stub(tmp_path):
    bridge = make_bridge()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    bridge.send_text("123@chatroom", "你好")
    bridge.send_video("123@chatroom", video, caption="看这个")
    wcf = bridge._wcf
    assert wcf.sent_text[-1] == ("123@chatroom", "看这个")
    assert wcf.sent_files == [("123@chatroom", str(video))]


def test_health_gates():
    bridge = make_bridge()
    assert bridge.is_healthy() is False  # 未 start 前
    bridge._healthy = True
    assert bridge.is_healthy() is True
