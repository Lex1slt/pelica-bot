"""抖音解析测试：全程用桩 HTTP 会话，不访问真实抖音。"""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from pelica.douyin.parser import DouyinError, DouyinParser
from pelica.douyin.pipeline import DouyinPipeline
from pelica.llm import persona


class FakeResponse:
    def __init__(self, text="", url="", status_code=200, content=b"", json_data=None, headers=None):
        self.text = text
        self.url = url
        self.status_code = status_code
        self._content = content
        self._json = json_data
        self.headers = headers or {}

    @property
    def content(self):
        return self._content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size):
        yield self._content


class FakeSession:
    """脚本化的 requests.Session 替身。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, **kw):
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("没有更多预设响应")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


SHARE_HTML = """
<html><head><title>这是测试视频 | 抖音</title></head><body>
<script>window.__INIT__("https://www.douyin.com/video/7381000000000000001")</script>
<div id="RENDER_DATA">%7B%22video%22%3A%7B%22play_addr%22%3A%7B%22url_list%22%3A%5B%22https%3A%2F%2Fcdn.example.com%2Fvideo%2Fplaywm%2F7381%22%5D%7D%7D%7D</div>
</body></html>
"""


def test_detect_links():
    text = "看这个 https://v.douyin.com/iRNBho6/ 好笑，还有 https://www.douyin.com/video/7381000000000000001"
    urls = DouyinParser.detect(text)
    assert len(urls) == 2
    assert DouyinParser.detect("没有链接的消息") == []
    assert DouyinParser.detect("") == []


def test_resolve_full_pipeline(tmp_path: Path):
    session = FakeSession([
        FakeResponse(text=SHARE_HTML, url="https://www.douyin.com/video/7381000000000000001"),
        FakeResponse(content=b"\x00\x00\x00\x18ftypisom" + b"0" * 20000,
                     headers={"Content-Length": "20012"}),
    ])
    parser = DouyinParser(tmp_path / "dl", session=session)
    result = parser.resolve("https://v.douyin.com/iRNBho6/")

    assert result.item_id == "7381000000000000001"
    assert result.video_url == "https://cdn.example.com/video/play/7381"  # playwm->play
    assert "这是测试视频" in result.title
    assert result.local_path is not None and result.local_path.exists()
    assert result.local_path.stat().st_size > 10_000


def test_resolve_no_item_id(tmp_path: Path):
    session = FakeSession([FakeResponse(text="<html>没内容</html>", url="https://www.douyin.com/")])
    parser = DouyinParser(tmp_path / "dl", session=session)
    with pytest.raises(DouyinError):
        parser.resolve("https://www.douyin.com/user/x")


def test_resolve_network_error(tmp_path: Path):
    import requests

    session = FakeSession([requests.ConnectionError("timeout")])
    parser = DouyinParser(tmp_path / "dl", session=session)
    with pytest.raises(DouyinError):
        parser.resolve("https://v.douyin.com/xxx")


def test_resolver_api_success(tmp_path: Path):
    """配置第三方解析服务时优先使用，响应形态宽容。"""
    session = FakeSession([
        FakeResponse(json_data={"video_url": "https://cdn.example.com/p/playwm/1"}),
        FakeResponse(content=b"\x00\x00\x00\x18ftypisom" + b"2" * 20000,
                     headers={"Content-Length": "20008"}),
    ])
    parser = DouyinParser(tmp_path / "dl", session=session,
                          resolver_api="http://resolver.local/api")
    result = parser.resolve("https://v.douyin.com/xyz/")
    assert result.video_url == "https://cdn.example.com/p/play/1"  # playwm→play
    assert result.local_path is not None and result.local_path.exists()


def test_resolver_api_failure_falls_back(tmp_path: Path):
    import requests

    session = FakeSession([
        FakeResponse(json_data={"error": "rate limited"}),          # 第三方失败
        requests.ConnectionError("built-in fetch also fails"),      # 内置也失败
    ])
    parser = DouyinParser(tmp_path / "dl", session=session,
                          resolver_api="http://resolver.local/api")
    with pytest.raises(DouyinError):
        parser.resolve("https://v.douyin.com/broken/")


def test_router_data_parse(tmp_path: Path):
    """iesdouyin 移动分享页 _ROUTER_DATA.item_list 形态（2026-09 实测结构）。"""
    html = (
        "<html><script>window._ROUTER_DATA = "
        + json.dumps({
            "loaderData": {
                "video_(id)/page": {
                    "videoInfoRes": {"item_list": [{
                        "aweme_id": "7381000000000000001",
                        "desc": "测试视频标题",
                        "author": {"nickname": "神枪小子丶"},
                        "video": {"play_addr": {"uri": "v0d00abc",
                                                "url_list": [
                            "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0d00abc"]}},
                    }]},
                },
            },
        }, ensure_ascii=False)
        + "</script></html>"
    )
    parser = DouyinParser(tmp_path / "dl")
    item = parser._item_from_router_data(html)
    assert item and item["aweme_id"] == "7381000000000000001"
    url = parser._play_url_from_item(item)
    assert url == "https://aweme.snssdk.com/aweme/v1/play/?video_id=v0d00abc"


def test_pipeline_sends_video_on_success(tmp_path: Path):
    sent = []
    session = FakeSession([
        FakeResponse(text=SHARE_HTML, url="https://www.douyin.com/video/7381000000000000001"),
        FakeResponse(content=b"\x00\x00\x00\x18ftypisom" + b"1" * 20000,
                     headers={"Content-Length": "20008"}),
    ])
    parser = DouyinParser(tmp_path / "dl", session=session)
    pipe = DouyinPipeline(parser, send_video=lambda r, p, c: sent.append(("v", r, c)),
                          send_text=lambda r, t: sent.append(("t", r, t)))
    handled = pipe.handle("看这个 https://v.douyin.com/iRNBho6/", "room-1")
    assert handled is True
    assert sent and sent[0][0] == "v" and sent[0][1] == "room-1"


def test_pipeline_fallback_text_on_failure(tmp_path: Path):
    import requests

    sent = []
    session = FakeSession([requests.ConnectionError("timeout")])
    parser = DouyinParser(tmp_path / "dl", session=session)
    pipe = DouyinPipeline(parser, send_video=lambda r, p, c: sent.append("v"),
                          send_text=lambda r, t: sent.append(t))
    pipe.handle("https://v.douyin.com/broken/", "room-1")
    assert len(sent) == 1
    assert sent[0] in persona.REPLY_DOUYIN_FAIL
    # 兜底文案同样不许有机器腔
    assert persona.find_forbidden(sent[0]) == []
