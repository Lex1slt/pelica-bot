"""B 站视频解析：b23.tv 短链 / BV·av 直链 → 直链 mp4 + 标题 + UP 主。

复用抖音管道的 DouyinResult 结构与发送流程（extras["quiet"]=True：
群里只发视频文件，不发文案和封面——分享卡片本身已带标题）。

画质策略：
  1) DASH（音视频分离，≤1080P 选最高档）下载后用 ffmpeg 流复制合并，
     超出大小预算自动降档；ffmpeg 缺失或 DASH 不可用时回退——
  2) html5 播放接口直链 mp4（720p，超限降 360p），无需拼接。

媒体 CDN 强制要求 Referer: bilibili.com，否则 403。
安全约束：落点文件名只能由严格正则校验的 BV 号经 _paths_for 工厂构造，
全部 resolve 并限定在 download_dir 内；子进程均为参数列表调用（shell=False）。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

from pelica.douyin.parser import DouyinError, DouyinResult

log = logging.getLogger(__name__)

BILI_URL_RE = re.compile(
    r"https?://(?:www\.bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)"
    r"|b23\.tv/[A-Za-z0-9]+)"
)
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"/av(\d+)")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_VIDEO_BYTES = 80 * 1024 * 1024
_QUALITY_FALLBACK = {64: 16}  # html5：720p 太大就降 360p


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

        # 高画质优先：DASH + ffmpeg 合并（≤1080P 选最高档）；失败回退 html5 直链
        local = self._resolve_dash(bvid, cid, float(view.get("duration") or 0))
        if local is None:
            video_url, _qn = self._pick_video_url(bvid, cid)
            result.video_url = video_url
            local = self._download(result)
        result.local_path = local
        result.extras["quiet"] = True  # 分享卡片自带标题，群里只发视频文件
        return result

    # -- 落点路径工厂：唯一合法的文件名构造方式 --------------------------------

    def _paths_for(self, bvid: str) -> tuple[Path, Path, Path, Path, Path]:
        """(mp4, 视频分片, 音频分片, 视频临时, 音频临时)——全部校验并限定在下载目录内。"""
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
            raise DouyinError(f"BV 号异常：{bvid!r}")
        base = self._download_dir.resolve()
        base.mkdir(parents=True, exist_ok=True)
        out = (base / ("bili_" + bvid + ".mp4")).resolve()
        v_path = (base / ("bili_" + bvid + "_v.m4s")).resolve()
        a_path = (base / ("bili_" + bvid + "_a.m4s")).resolve()
        v_tmp = v_path.with_name(v_path.name + ".part")
        a_tmp = a_path.with_name(a_path.name + ".part")
        for p in (out, v_path, a_path, v_tmp, a_tmp):
            if not str(p).startswith(str(base) + os.sep):
                raise DouyinError(f"路径越界：{p!r}")
        return out, v_path, a_path, v_tmp, a_tmp

    def _ffmpeg_path(self) -> str | None:
        found = shutil.which("ffmpeg")
        if found:
            return found
        # winget 安装的 ffmpeg 不在 PATH 时的常见位置
        for p in Path.home().glob(
            "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/ffmpeg.exe"
        ):
            return str(p)
        return None

    def _dl_stream(self, url: str, dest: Path, cap: int) -> None:
        """流式下载（限额，超限即抛错），落固定临时名后原子改名到 dest。"""
        payload = bytearray()
        with self._session.get(url, stream=True, timeout=(10, 120)) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(1 << 20):
                payload.extend(chunk)
                if len(payload) > cap:
                    raise DouyinError("分片超过大小预算")
        fixed = self._download_dir / "bili_download.part"
        fixed.write_bytes(bytes(payload))
        fixed.replace(dest)

    # -- 画质阶梯 -------------------------------------------------------------

    def _pick_dash(self, bvid: str, cid: int, duration: float):
        """选 DASH 视频轨（≤1080P 中最高）+ 最小音轨；预算不够就逐档降低。"""
        resp = self._session.get(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "fnval": 4048, "qn": 120},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = (resp.json().get("data") or {}).get("dash") or {}
        videos = [v for v in (data.get("video") or []) if v.get("id", 0) <= 80]
        audios = data.get("audio") or []
        if not videos or not audios:
            return None, None
        audio = min(audios, key=lambda a: a.get("size") or a.get("bandwidth") or 0)
        asize = audio.get("size") or (audio.get("bandwidth", 0) * duration / 8)
        for v in sorted(videos, key=lambda x: -x.get("id", 0)):
            vsize = v.get("size") or (v.get("bandwidth", 0) * duration / 8)
            if vsize + asize <= MAX_VIDEO_BYTES:
                return v, audio
        return None, None

    def _resolve_dash(self, bvid: str, cid: int, duration: float) -> Path | None:
        ffmpeg = self._ffmpeg_path()
        if not ffmpeg:
            log.info("未找到 ffmpeg，B 站回退 html5 直链（720p）")
            return None
        video, audio = self._pick_dash(bvid, cid, duration)
        if not video:
            return None
        out, v_path, a_path, _v_tmp, _a_tmp = self._paths_for(bvid)
        if out.exists() and out.stat().st_size > 10_000:
            return out
        try:
            self._dl_stream(video["baseUrl"] or video["base_url"], v_path,
                            MAX_VIDEO_BYTES)
            self._dl_stream(audio["baseUrl"] or audio["base_url"], a_path,
                            MAX_VIDEO_BYTES // 4)
            merged = subprocess.run(
                [ffmpeg, "-y", "-i", str(v_path), "-i", str(a_path),
                 "-c", "copy", "-movflags", "+faststart", str(out)],
                capture_output=True, shell=False, timeout=300,
            )
            if merged.returncode != 0 or not out.exists() or out.stat().st_size < 10_000:
                log.warning("ffmpeg 合并失败：%s", (merged.stderr or b"")[-200:])
                out.unlink(missing_ok=True)
                return None
            return out
        finally:
            v_path.unlink(missing_ok=True)
            a_path.unlink(missing_ok=True)

    # -- html5 直链回退 -------------------------------------------------------

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

    def _download(self, result: DouyinResult) -> Path:
        out, _v, _a, _vt, _at = self._paths_for(result.item_id)
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
