"""B 站视频解析：b23.tv 短链 / BV·av 直链 → 直链 mp4 + 标题 + UP 主。

复用抖音管道的 DouyinResult 结构与发送流程（首帧封面 + 文件消息）。

主路径：api.bilibili.com 的 view（标题/UP/cid）+ html5 播放接口
（无需登录，720p 内直链 mp4，音视频已合并，无需 ffmpeg）。
媒体 CDN 强制要求 Referer: bilibili.com，否则 403。
清晰度阶梯：64（720p）→ 16（360p），超过大小上限自动降档。
DASH（音视频分离的高画质）需要 ffmpeg 拼接，留作后续增强。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import requests

from pelica.douyin.parser import DouyinError, DouyinResult

log = logging.getLogger(__name__)

BILI_URL_RE = re.compile(
    r"https?://(?:www\.bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)"
    r"|b23\.tv/[A-Za-z0-9]+)"
)
BV_RE = re.compile(r"(?:/video/)?(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"/av(\d+)")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_VIDEO_BYTES = 80 * 1024 * 1024
_QUALITY_FALLBACK = {64: 16}  # 720p 太大就降 360p


class BiliParser:
    def __init__(self, download_dir: Path, timeout: float = 20.0, session=None):
        self._download_dir = Path(download_dir)
        self._timeout = timeout
        self._own = False
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
            self._own = True
        self._session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://www.bilibili.com/",
        })

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    @staticmethod
    def detect(text: str) -> list[str]:
        seen: set[str] = set()
        out = []
        for m in BILI_URL_RE.finditer(text or ""):
            url = m.group(0).rstrip("。，,）)")
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out[:2]

    def _api(self, path: str) -> dict:
        resp = self._session.get("https://api.bilibili.com" + path,
                                 timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise DouyinError(f"B 站接口返回 {data.get('code')}：{data.get('message', '')[:60]}")
        return data["data"]

    def _pick_video_url(self, bvid: str, cid: int) -> tuple[str, int]:
        """html5 播放接口取直链 mp4；720p 超过上限自动降 360p。"""
        qn = 64
        while True:
            resp = self._session.get(
                "https://api.bilibili.com/x/player/playurl",
                params={"bvid": bvid, "cid": cid, "qn": qn,
                        "platform": "html5", "high_quality": 1 if qn >= 64 else 0},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise DouyinError(f"B 站播放接口返回 {data.get('code')}")
            durl = (data.get("data") or {}).get("durl") or []
            if not durl:
                raise DouyinError("该视频没有可下载的直链（可能仅限 APP 或充电专属）")
            if durl[0].get("size", 0) <= MAX_VIDEO_BYTES or qn not in _QUALITY_FALLBACK:
                return durl[0]["url"], qn
            qn = _QUALITY_FALLBACK[qn]

    def resolve(self, url: str) -> DouyinResult:
        result = DouyinResult(share_url=url)

        final_url = url
        if "b23.tv" in url:  # 短链 → 跳转拿真实 BV
            resp = self._session.get(url, timeout=self._timeout, allow_redirects=True)
            resp.raise_for_status()
            final_url = str(resp.url)
        bv = BV_RE.search(final_url)
        av = AV_RE.search(final_url)
        view_param = ({"bvid": bv.group(1)} if bv
                      else ({"aid": av.group(1)} if av else None))
        if not view_param:
            raise DouyinError("链接里没有 BV/av 号")

        view = self._api("/x/web-interface/view?" + "&".join(
            f"{k}={v}" for k, v in view_param.items()))
        bvid, cid = view["bvid"], view["cid"]
        result.item_id = bvid
        result.title = (view.get("title") or "")[:80]
        result.author = ((view.get("owner") or {}).get("name")) or ""

        video_url, _qn = self._pick_video_url(bvid, cid)
        result.video_url = video_url
        result.local_path = self._download(result)
        return result

    def _download(self, result: DouyinResult) -> Path:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        name = result.item_id or hashlib.md5(
            result.share_url.encode("utf-8")).hexdigest()[:12]
        out = self._download_dir / f"bili_{name}.mp4"
        if out.exists() and out.stat().st_size > 10_000:
            return out
        try:
            resp = self._session.get(result.video_url, timeout=180)
            resp.raise_for_status()
            content = resp.content
            if len(content) > MAX_VIDEO_BYTES:
                raise DouyinError(f"视频太大（{len(content) / 1048576:.0f} MB），不往群里发了")
            if len(content) < 10_000:
                raise DouyinError("取回的内容太小，不像视频")
            tmp = out.with_suffix(".part")
            tmp.write_bytes(content)
            tmp.replace(out)
            return out
        except DouyinError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DouyinError(f"视频下载失败：{exc}") from exc
