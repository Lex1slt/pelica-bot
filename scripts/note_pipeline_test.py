#!/usr/bin/env python
"""图文帖解析/管道回归：合成 _ROUTER_DATA 样例，注入假 session，全程不联网。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from types import SimpleNamespace

from pelica.douyin.parser import ROUTER_DATA_RE, DouyinParser
from pelica.douyin.pipeline import DouyinPipeline

IMG1 = "https://p3-sign.douyinpic.com/img/tos-cn-i-0000/a.jpeg?x-expires=1"
IMG2 = "https://p9-sign.douyinpic.com/img/tos-cn-i-0000/b.jpeg?x-expires=1"
IMG3 = "https://p26-sign.douyinpic.com/img/tos-cn-i-0000/c.webp?x-expires=1"

ITEM = {
    "aweme_id": "7412345678901234567",
    "desc": "随拍三张：晚霞、猫、咖啡",
    "author": {"nickname": "管理员小张"},
    "images": [
        {"url_list": [IMG1, "https://p3.douyinpic.com/img/a.thumb.jpg"]},
        {"url_list": [IMG2]},
        {"url_list": [IMG3]},
    ],
}
ROUTER = {"loaderData": {"note_(id=7412345678901234567)": {"videoInfoRes": {"item_list": [ITEM]}}}}


class FakeResp:
    def __init__(self, content=b""):
        self._content = content
        self.url = "https://www.iesdouyin.com/share/note/7412345678901234567/"

    def raise_for_status(self):
        pass

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        return self._content.decode("utf-8", "replace")

    @property
    def status_code(self):
        return 200


class FakeSession:
    """分享页返回合成 HTML；图片 URL 返回假 JPEG 字节。"""

    def __init__(self):
        self.headers = {}
        self.cookies = SimpleNamespace(jar=())

    def get(self, url, timeout=0, **kw):
        if "douyinpic.com" in url:
            return FakeResp(b"\xff\xd8\xff" + b"x" * 6000)
        html = (
            '<html><script>window._ROUTER_DATA = ' + json.dumps(ROUTER, ensure_ascii=False)
            + "</script></html>"
        )
        return FakeResp(html.encode("utf-8"))

    def post(self, *a, **kw):  # ttwid 注册不会被触发（测试注入跳过）
        raise AssertionError("不应发起 ttwid 注册")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dy_note_"))
    parser = DouyinParser(download_dir=tmp, session=FakeSession())
    result = parser.resolve("https://v.douyin.com/testnote1/")
    assert not result.video_url, result.video_url
    assert len(result.image_urls) == 3, result.image_urls
    assert len(result.local_images) == 3, result.local_images
    assert all(p.exists() and p.stat().st_size > 5000 for p in result.local_images)
    assert result.local_images[0].suffix in (".jpg", ".webp")  # webp 会被尽力转 jpg
    assert result.local_images[2].suffix in (".webp", ".jpg")
    assert result.title.startswith("随拍三张"), result.title
    assert result.author == "管理员小张"

    # 管道：图文走 send_text(文案) + send_image x3
    sent: list[tuple[str, str]] = []

    class FakeBridge:
        def send_text(self, room_id, text):
            sent.append(("text", text))

        def send_image(self, room_id, path):
            sent.append(("image", str(path)))

    pipe = DouyinPipeline(parser=parser, send_video=lambda *a, **k: sent.append(("video", "")),
                          send_text=FakeBridge().send_text, send_image=FakeBridge().send_image)
    pipe._process_one("https://v.douyin.com/testnote1/", "room1")
    kinds = [k for k, _ in sent]
    assert kinds == ["text", "image", "image", "image"], kinds
    assert "随拍三张" in sent[0][1] and "管理员小张" in sent[0][1]
    print("NOTE-PIPELINE-OK：解析 3 图 + 文案 + 逐张发送全通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
