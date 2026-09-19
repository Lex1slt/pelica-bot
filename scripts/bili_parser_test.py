#!/usr/bin/env python
"""B 站解析回归：链接识别 / 复合分发 / 合成数据解析，全程不联网。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.bilibili.parser import BiliParser
from pelica.douyin.parser import DouyinParser

TEXT = ("看看这个 https://b23.tv/JzU0abcG 十分推荐\n"
        "还有 https://www.bilibili.com/video/BV1GJ411x7h7/?p=1\n"
        "抖音的 https://v.douyin.com/oIvX-jyu7Ag/ 也在")


class FakeResp:
    def __init__(self, payload=None, content=b"", url=""):
        self._payload = payload
        self.content = content
        self.url = url

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """b23.tv 跳转 / view API / playurl / 媒体下载 全部合成。"""

    def __init__(self):
        self.headers = {}
        self.download_calls = 0

    def get(self, url, timeout=0, **kw):
        if "b23.tv" in url:
            return FakeResp(url="https://www.bilibili.com/video/BV1GJ411x7h7/?p=1")
        if "/web-interface/view" in url:
            return FakeResp({"code": 0, "data": {
                "bvid": "BV1GJ411x7h7", "cid": 137649199,
                "title": "【官方 MV】Never Gonna Give You Up",
                "owner": {"name": "索尼音乐中国"}}})
        if "/player/playurl" in url:
            return FakeResp({"code": 0, "data": {"durl": [{
                "url": "https://upos.bilivideo.com/fake.m4s",
                "size": 6 * 1024 * 1024}]}})
        if "bilivideo.com" in url:
            self.download_calls += 1
            return FakeResp(content=b"\x00\x01mp4" + b"x" * 20000)
        raise AssertionError("意外 URL：" + url)


def main() -> int:
    import tempfile
    from types import SimpleNamespace

    tmp = Path(tempfile.mkdtemp(prefix="bili_"))

    # 1) detect：只认 B 站链接；抖音解析器不认 B 站链接
    bili = BiliParser(download_dir=tmp, session=FakeSession())
    douyin = DouyinParser(download_dir=tmp, session=SimpleNamespace(headers={}))
    assert len(bili.detect(TEXT)) == 2, bili.detect(TEXT)
    assert all("bilibili" in u or "b23.tv" in u for u in bili.detect(TEXT))
    assert douyin.detect(TEXT) == ["https://v.douyin.com/oIvX-jyu7Ag/"]

    # 2) 复合分发：两个解析器各自认领自己的链接，互不越界
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from types import SimpleNamespace

    class P:
        def __init__(self, marker, parser):
            self.marker, self._p = marker, parser

        download_dir = property(lambda self: self._p.download_dir)
        detect = lambda self, text: self._p.detect(text)  # noqa: E731
        resolve = lambda self, url: self._p.resolve(url)  # noqa: E731

    from main import _LinkParsers
    comp = _LinkParsers([P("douyin", douyin), P("bili", bili)])
    assert len(comp.detect(TEXT)) == 2  # 跨平台去重后仍保留单条消息 ≤2 链接的防刷屏上限
    assert any("b23.tv" in u for u in comp.detect(TEXT))
    assert any("douyin" in u for u in comp.detect(TEXT))
    r = comp.resolve("https://b23.tv/JzU0abcG")
    assert r.item_id == "BV1GJ411x7h7" and r.video_url, r
    assert "索尼音乐中国" == r.author
    assert r.local_path.exists() and r.local_path.stat().st_size > 10000
    assert r.local_path.name == "bili_BV1GJ411x7h7.mp4"
    assert r.extras.get("quiet") is True  # B 站只发视频文件，不带文案/封面

    print("BILI-PARSER-OK：识别/分发/解析/下载 全通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
