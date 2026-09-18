"""抖音链接解析（无水印视频地址提取 + 下载）。

零成本自研方案（2026-09 实测可用），核心三件事：
1. **TLS 指纹**：用 curl_cffi 模拟 Chrome 握手，requests 的 Python TLS
   指纹会被 Argus 安全插件直接拦掉；
2. **ttwid**：向 ttwid.bytedance.com 注册一个 ttwid，并显式设置到
   .douyin.com / .iesdouyin.com 两个域上（requests 按 set-cookie 域存储，
   不显式设置就带不出去，这是最常见的踩坑点）；
3. **分享页 _ROUTER_DATA**：带 ttwid 请求 iesdouyin 分享页，HTML 里的
   window._ROUTER_DATA.loaderData.*.videoInfoRes.item_list[0] 包含
   desc / author / video.play_addr.url_list（playwm 地址，playwm→play 去水印）。

保留的兜底路径：RENDER_DATA（桌面 SSR）、旧 iteminfo 接口、以及可选的
第三方解析服务（DOUYIN_RESOLVER_API，优先级最高，为将来抖音再次变更留后门）。
abogus.py（a_bogus 签名）作为被签 API 的预留件保留在本目录，默认不用。

下载流式限 80MB；任何一步失败抛 DouyinError，由 pipeline 转人设兜底文案。
"""

from __future__ import annotations

import gzip  # noqa: F401  (保留：部分备用路径的页面可能 gzip)
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

try:  # TLS 指纹模拟，抖音解析的硬依赖
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover
    curl_requests = None

log = logging.getLogger(__name__)

DOUYIN_URL_RE = re.compile(
    r"https?://(?:www\.douyin\.com|v\.douyin\.com|www\.iesdouyin\.com|m\.douyin\.com)"
    r"/[A-Za-z0-9_\-./?=&%#:]+"
)
ITEM_ID_RE = re.compile(r"(?:/video/|/note/|modal_id=|aweme_id=|item_ids=)(\d+)")
RENDER_DATA_RE = re.compile(r'id="RENDER_DATA"[^>]*>([^<]+)<')
ROUTER_DATA_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", re.S)
PLAY_ADDR_RE = re.compile(
    r'"play_addr"\s*:\s*{[^}]*"url_list"\s*:\s*\[([^\]]+)\]', re.S
)
URL_IN_JSON_RE = re.compile(r'"(https?:\\?/\\?/[^"]+)"')

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)
MAX_VIDEO_BYTES = 80 * 1024 * 1024  # 80MB 上限，群传视频的合理边界

_TTWID_REGISTER = {
    "region": "cn",
    "aid": 1768,
    "needFid": False,
    "service": "www.ixigua.com",
    "migrate_info": {"ticket": "", "source": "node"},
    "cbUrlProtocol": "https",
    "union": True,
}


class DouyinError(RuntimeError):
    pass


@dataclass
class DouyinResult:
    share_url: str
    video_url: str = ""
    item_id: str = ""
    title: str = ""
    author: str = ""
    local_path: Path | None = None
    image_urls: list[str] = field(default_factory=list)   # 图文帖：原图地址（≤9 张）
    local_images: list[Path] = field(default_factory=list)  # 图文帖：已落盘的图片
    extras: dict = field(default_factory=dict)


class DouyinParser:
    def __init__(
        self,
        download_dir: Path,
        timeout: float = 20.0,
        session=None,
        resolver_api: str = "",
    ):
        self._download_dir = Path(download_dir)
        self._timeout = timeout
        self._resolver_api = resolver_api.strip()
        self._own_session = False
        self._ttwid_ok = False
        if session is not None:
            # 测试注入：跳过指纹/ttwid 引导
            self._session = session
            self._session.headers.update({"User-Agent": MOBILE_UA})
        elif curl_requests is not None:
            self._session = curl_requests.Session(impersonate="chrome124")
            self._own_session = True
            # 关键：TLS 用 Chrome 指纹，但 UA 必须是移动端——
            # 否则短链会跳到桌面版页面（无内嵌数据），分享页也不给 item_list
            self._session.headers.update({"User-Agent": MOBILE_UA})
        else:  # pragma: no cover - 未装 curl_cffi 时退化为 requests（大概率被拦）
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": MOBILE_UA})
        self._session.headers.update(
            {"Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://www.douyin.com/"}
        )

    # -- 对外 ---------------------------------------------------------------

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    @staticmethod
    def detect(text: str) -> list[str]:
        seen: set[str] = set()
        out = []
        for m in DOUYIN_URL_RE.finditer(text or ""):
            url = m.group(0).rstrip("。，,）)")
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out[:2]  # 一次最多处理两条，防刷屏

    def resolve(self, url: str) -> DouyinResult:
        result = DouyinResult(share_url=url)

        # 第一优先：第三方解析服务（如已配置）
        if self._resolver_api:
            result.video_url = self._video_url_from_resolver_api(url)

        # 自研主路径：分享页 _ROUTER_DATA -> item_list
        if not result.video_url:
            self._ensure_ttwid()
            html, final_url = self._fetch_share_page(url)
            result.item_id = self._extract_item_id(final_url, html)
            item = self._item_from_router_data(html)
            if item:
                result.title = (item.get("desc") or "")[:80]
                result.author = ((item.get("author") or {}).get("nickname")) or ""
                if not result.item_id:
                    result.item_id = item.get("aweme_id") or ""
                # 图文优先：图文帖也带 video 字段，但那是自动生成的幻灯片
                # （地址常是残废的），有 images 就按图文走，无视幻灯片
                result.image_urls = self._images_from_item(item)
                if not result.image_urls:
                    result.video_url = self._play_url_from_item(item)
            if not result.video_url and not result.image_urls:
                # 兜底链：RENDER_DATA -> 主动取分享页 -> 旧 iteminfo
                result.video_url = (
                    self._video_url_from_page(html)
                    or (self._video_url_from_share(result.item_id) if result.item_id else "")
                    or (self._video_url_from_api(result.item_id) if result.item_id else "")
                )
                if not result.title:
                    result.title = self._extract_title(html)
            if not result.item_id and not result.video_url and not result.image_urls:
                raise DouyinError("没有从链接里提取到内容 ID")
            if not result.video_url and not result.image_urls:
                self._refresh_ttwid()
                if self._video_url_from_share_retry(result, html, result.item_id):
                    pass  # video_url 已写回 result
            if not result.video_url and not result.image_urls:
                raise DouyinError("没能拿到可下载的内容地址（抖音反爬或服务不可用）")

        if result.image_urls and not result.video_url:
            result.local_images = self._download_images(result)
            return result
        if not result.local_path:
            result.local_path = self._download(result)
        return result

    # -- ttwid 引导 -----------------------------------------------------------

    def _ensure_ttwid(self) -> None:
        if self._ttwid_ok or not self._own_session:
            return
        try:
            self._session.post(
                "https://ttwid.bytedance.com/ttwid/union/register/",
                json=_TTWID_REGISTER, timeout=self._timeout,
            )
            ttwid = next(
                (c.value for c in getattr(self._session, "cookies", {}).jar
                 if c.name == "ttwid"),
                None,
            )
            if ttwid:
                for domain in (".douyin.com", ".iesdouyin.com"):
                    self._session.cookies.set("ttwid", ttwid, domain=domain)
                self._ttwid_ok = True
                log.debug("ttwid 引导完成")
        except Exception as exc:  # noqa: BLE001
            log.warning("ttwid 注册失败：%s", exc)

    def _refresh_ttwid(self) -> None:
        self._ttwid_ok = False
        self._ensure_ttwid()

    def _video_url_from_share_retry(self, result: DouyinResult, html: str,
                                    item_id: str) -> bool:
        """ttwid 刷新后再试一次主路径。"""
        if not item_id:
            return False
        try:
            fresh_html, _ = self._fetch_share_page(
                f"https://www.iesdouyin.com/share/video/{item_id}/"
            )
        except DouyinError:
            return False
        item = self._item_from_router_data(fresh_html)
        if not item:
            return False
        result.video_url = self._play_url_from_item(item)
        result.title = result.title or (item.get("desc") or "")[:80]
        result.author = result.author or ((item.get("author") or {}).get("nickname")) or ""
        return bool(result.video_url)

    # -- 数据提取 --------------------------------------------------------------

    def _item_from_router_data(self, html: str) -> dict | None:
        m = ROUTER_DATA_RE.search(html or "")
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except ValueError:
            return None
        for value in (data.get("loaderData") or {}).values():
            if not isinstance(value, dict):
                continue
            items = ((value.get("videoInfoRes") or {}).get("item_list")) or []
            if items:
                return items[0]
        return None

    def _play_url_from_item(self, item: dict) -> str:
        video = item.get("video") or {}
        for key in ("play_addr", "play_addr_lowbr", "download_addr"):
            urls = (video.get(key) or {}).get("url_list") or []
            if urls:
                return urls[0].replace("playwm", "play")  # 去水印
        return ""

    MAX_NOTE_IMAGES = 9
    MAX_IMAGE_BYTES = 20 * 1024 * 1024

    def _images_from_item(self, item: dict) -> list[str]:
        """图文帖：images[].url_list 取可用原图地址（每图至多 1 张，≤9 图）。"""
        out: list[str] = []
        for img in (item.get("images") or [])[: self.MAX_NOTE_IMAGES]:
            urls = (img.get("url_list") or []) if isinstance(img, dict) else []
            # url_list[0] 常带压缩后缀；挑一个 https 的即可
            for u in urls:
                if isinstance(u, str) and u.startswith("https://"):
                    out.append(u)
                    break
        return out

    def _download_images(self, result: DouyinResult) -> list[Path]:
        """下载图文帖的图片到 dy_<id>/01.jpg…；一张都拿不到才抛错。"""
        self._download_dir.mkdir(parents=True, exist_ok=True)
        name = result.item_id or hashlib.md5(
            result.share_url.encode("utf-8")
        ).hexdigest()[:12]
        out_dir = self._download_dir / f"dy_{name}"
        out_dir.mkdir(parents=True, exist_ok=True)
        got: list[Path] = []
        for i, url in enumerate(result.image_urls[: self.MAX_NOTE_IMAGES], 1):
            suffix = ".jpg"
            m = re.search(r"\.(jpe?g|png|webp)(?:[?#]|$)", url, re.I)
            if m:
                suffix = f".{m.group(1).lower().replace('jpeg', 'jpg')}"
            out = out_dir / f"{i:02d}{suffix}"
            if out.exists() and out.stat().st_size > 5_000:  # 已下载过
                got.append(self._to_jpg(out))
                continue
            try:
                resp = self._session.get(url, timeout=30)
                resp.raise_for_status()
                content = resp.content
                if len(content) > self.MAX_IMAGE_BYTES or len(content) < 3_000:
                    continue  # 单张失败不拖垮整套
                tmp = out.with_suffix(".part")
                tmp.write_bytes(content)
                tmp.replace(out)
                out = self._to_jpg(out)  # 微信对 webp 图片消息兼容性差
                got.append(out)
            except Exception as exc:  # noqa: BLE001
                log.warning("图文第 %d 张下载失败：%s", i, exc)
        if not got:
            raise DouyinError("图文一张都没能下载下来")
        return got

    @staticmethod
    def _to_jpg(path: Path) -> Path:
        """webp 尽力转 jpg；转不动就保留原格式。"""
        if path.suffix.lower() != ".webp":
            return path
        try:
            import cv2

            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                return path
            jpg = path.with_suffix(".jpg")
            if cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, 92]):
                path.unlink(missing_ok=True)
                return jpg
        except Exception:  # noqa: BLE001
            pass
        return path

    def _extract_item_id(self, final_url: str, html: str) -> str:
        m = ITEM_ID_RE.search(final_url or "") or ITEM_ID_RE.search(html or "")
        return m.group(1) if m else ""

    def _fetch_share_page(self, url: str) -> tuple[str, str]:
        try:
            resp = self._session.get(url, timeout=self._timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.text, resp.url
        except requests.RequestException as exc:
            raise DouyinError(f"链接打不开：{exc}") from exc
        except Exception as exc:  # curl_cffi 异常类型不同，统一转 DouyinError
            raise DouyinError(f"链接打不开：{exc}") from exc

    def _video_url_from_page(self, html: str) -> str:
        # RENDER_DATA 是 URL-encode 的 JSON；__pace_f 是桌面版路由数据
        m = RENDER_DATA_RE.search(html)
        candidates: list[str] = []
        if m:
            from urllib.parse import unquote

            candidates.append(unquote(m.group(1)))
        for chunk in re.findall(r"self\.__pace_f\.push\((.+?)\)</script>", html, re.S):
            candidates.append(chunk)
        for blob in candidates:
            for addr in PLAY_ADDR_RE.finditer(blob):
                for url_m in URL_IN_JSON_RE.finditer(addr.group(1)):
                    url = url_m.group(1).replace("\\/", "/")
                    return url.replace("playwm", "play")  # 去水印
        return ""

    def _video_url_from_share(self, item_id: str) -> str:
        """主动请求 iesdouyin 移动分享页（短链 landing 缺数据时的补一手）。"""
        for path in (f"/share/video/{item_id}/", f"/share/note/{item_id}/"):
            try:
                resp = self._session.get(
                    "https://www.iesdouyin.com" + path, timeout=self._timeout
                )
            except Exception:  # noqa: BLE001
                continue
            if resp.status_code != 200:
                continue
            item = self._item_from_router_data(resp.text)
            if item:
                url = self._play_url_from_item(item)
                if url:
                    return url
            url = self._video_url_from_page(resp.text)
            if url:
                return url
        return ""

    def _video_url_from_api(self, item_id: str) -> str:
        """旧版 iteminfo 接口（多数时候已死，留着当最后兜底）。"""
        try:
            resp = self._session.get(
                "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
                params={"item_ids": item_id},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            items = data.get("item_list") or []
            if not items:
                return ""
            urls = (items[0].get("video", {}).get("play_addr", {})).get("url_list") or []
            return urls[0].replace("playwm", "play") if urls else ""
        except Exception as exc:  # noqa: BLE001
            log.debug("iteminfo 接口失败：%s", exc)
            return ""

    def _video_url_from_resolver_api(self, url: str) -> str:
        """可选第三方解析服务：GET {api}?url=<分享链接>，宽容解析响应。"""
        try:
            resp = self._session.get(
                self._resolver_api, params={"url": url}, timeout=self._timeout
            )
            if resp.status_code != 200:
                log.warning("第三方解析服务返回 %d", resp.status_code)
                return ""
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("第三方解析服务调用失败：%s", exc)
            return ""
        for key in ("video_url", "url", "play_url", "play_addr"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value.startswith("http"):
                return value.replace("playwm", "play")
            if isinstance(value, list) and value and isinstance(value[0], str):
                return value[0].replace("playwm", "play")
        if isinstance(data, dict):
            nested = data.get("data") or data.get("item") or {}
            if isinstance(nested, dict):
                return self._video_url_from_resolver_payload(nested)
        return ""

    def _video_url_from_resolver_payload(self, payload: dict) -> str:
        video = payload.get("video") or payload
        play = video.get("play_addr") or {}
        urls = play.get("url_list") or []
        return urls[0].replace("playwm", "play") if urls else ""

    def _extract_title(self, html: str) -> str:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html)
        if m:
            title = m.group(1).strip()
            return re.sub(r"\s*\|\s*抖音.*$", "", title)[:80]
        return ""

    # -- 下载 ------------------------------------------------------------------

    def _download(self, result: DouyinResult) -> Path:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        name = result.item_id or hashlib.md5(
            result.share_url.encode("utf-8")
        ).hexdigest()[:12]
        out = self._download_dir / f"dy_{name}.mp4"
        if out.exists() and out.stat().st_size > 10_000:  # 已下载过
            return out
        try:
            resp = self._session.get(result.video_url, timeout=60)
            resp.raise_for_status()
            content = resp.content
            if len(content) > MAX_VIDEO_BYTES:
                raise DouyinError(
                    f"视频太大（{len(content) / 1024 / 1024:.0f} MB），不往群里发了"
                )
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
