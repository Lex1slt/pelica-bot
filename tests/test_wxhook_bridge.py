"""WeChat-Hook 桥接测试（桩 HTTP，不碰真实微信）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pelica.bridge.wxhook_bridge import WeChatHookBridge


class StubHook:
    def __init__(self):
        self.dbs = [{"dbName": "session.db"}, {"dbName": "contact.db"}]
        self.tables = {}
        self.sessions = []
        self.sent_text = []
        self.sent_files = []
        self.forwarded = []
        self.sent_img = []
        self.img_resp = {"ret": 0, "retmsg": "success"}

    def _post_json(self, path, payload=None, timeout=15.0):
        if path == "/QueryDB/status":
            return {"IsLogin": 1}
        if path == "/QueryDB/GetAllDBName":
            return self.dbs
        if path == "/QueryDB/execute":
            db = payload["optDbName"]
            sql = payload["SQL"]
            if "sqlite_master" in sql:
                return {"status": 0, "data": self.tables.get(db, [])}
            if "chat_room" in sql:
                return {"status": 0, "data": [{"Name": "123@chatroom", "NickName": "测试群"}]}
            if "SessionTable" in sql:
                return {"status": 0, "data": self.sessions}
            return {"status": 0, "data": []}
        if path == "/SendTextMsg":
            self.sent_text.append(payload)
            return {"ret": 0, "retmsg": "success"}
        if path == "/SendImgMsg":
            self.sent_img.append(payload)
            return self.img_resp
        if path == "/SendImgMsg":
            self.sent_files.append(payload)
            return {"ret": 0, "retmsg": "success"}
        if path == "/ForwardXMLMsg":
            self.forwarded.append(payload)
            return {"ret": 0, "retmsg": "success"}
        raise AssertionError(f"unexpected path {path}")


def make_bridge(sessions=None):
    bridge = WeChatHookBridge(groups=[], at_aliases=["佩丽卡监督"], video_xml_path=None)
    stub = StubHook()
    stub.sessions = sessions or []
    bridge._post_json = stub._post_json
    return bridge, stub


SESSION_ROW = {
    "username": "123@chatroom",
    "summary": "阿夜：@佩丽卡监督 醚质是什么",
    "last_timestamp": "1789709000",
    "last_msg_sender": "user-a",
    "last_sender_display_name": "阿夜",
}


def test_session_row_to_message():
    bridge, _ = make_bridge()
    msg = bridge._session_row_to_message(SESSION_ROW)
    assert msg is not None
    assert msg.room_id == "123@chatroom"
    assert msg.room_name == "测试群"
    assert msg.sender_id == "user-a"
    assert msg.sender_name == "阿夜"
    # 「阿夜：」前缀被剥掉
    assert msg.text == "@佩丽卡监督 醚质是什么"
    assert not msg.text.startswith("阿夜：")
    assert msg.is_at is True


def test_session_row_skips_non_group_and_empty():
    bridge, _ = make_bridge()
    row = dict(SESSION_ROW, username="wxid_friend")
    assert bridge._session_row_to_message(row) is None
    row2 = dict(SESSION_ROW, summary="")
    assert bridge._session_row_to_message(row2) is None


def test_send_video_via_hook_api(tmp_path):
    """视频投递：/SendImgMsg + filetype=43（真实客户端验证过的参数）。"""
    bridge, stub = make_bridge()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)

    bridge.send_video("123@chatroom", video, caption="看这个")
    assert stub.sent_img == [{"wxidorgid": "123@chatroom", "path": str(video), "filetype": 43}]
    assert stub.sent_text[-1] == {"wxidorgid": "123@chatroom", "msg": "看这个"}


def test_send_video_hook_failure_propagates(tmp_path):
    """hook 返回失败码时，send_video 应向上抛异常（pipeline 会发兜底文案）。"""
    bridge, stub = make_bridge()
    stub.img_resp = {"ret": 1, "retmsg": "fail"}
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    try:
        bridge.send_video("123@chatroom", video, caption="x")
        raised = False
    except Exception:
        raised = True
    assert raised, "hook 失败应向上抛出由 pipeline 兜底"
