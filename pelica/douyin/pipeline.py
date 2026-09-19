"""抖音管道：把解析器接到桥接上。成功发视频/图文，失败发人设化兜底文案。"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from pelica.douyin.parser import DouyinError, DouyinParser

log = logging.getLogger(__name__)


def sweep_old_cache(download_dir: Path, keep_hours: int = 48) -> int:
    """清理超过 keep_hours 的本地视频/缩略图缓存，返回删除数。"""
    cutoff = time.time() - keep_hours * 3600
    n = 0
    root = Path(download_dir)
    if not root.exists():
        return 0
    for f in root.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                n += 1
        except OSError:
            continue
    if n:
        log.info("清理过期抖音缓存 %d 个文件", n)
    return n


class DouyinPipeline:
    def __init__(
        self,
        parser: DouyinParser,
        send_video,          # Callable[[room_id, path, caption], None]
        send_text,           # Callable[[room_id, text], None]
        send_image=None,     # Callable[[room_id, image_path], None] 可选
        keep_hours: int = 48,
    ):
        self._parser = parser
        self._send_video = send_video
        self._send_text = send_text
        self._send_image = send_image
        self._keep_hours = max(keep_hours, 1)
        self._swept = False

    def handle(self, text: str, room_id: str) -> bool:
        """检测并处理文本里的抖音链接。返回是否处理了（调用方应停止后续分流）。"""
        if not self._swept:
            self._swept = True
            try:
                sweep_old_cache(self._parser.download_dir, self._keep_hours)
            except Exception:  # noqa: BLE001
                log.debug("缓存清理失败", exc_info=True)
        urls = DouyinParser.detect(text)
        if not urls:
            return False
        for url in urls:
            self._process_one(url, room_id)
        return True

    def _process_one(self, url: str, room_id: str) -> None:
        try:
            result = self._parser.resolve(url)
        except DouyinError as exc:
            log.warning("抖音解析失败 %s：%s", url, exc)
            from pelica.llm import persona

            self._send_text(room_id, persona.pick(persona.REPLY_DOUYIN_FAIL))
            return
        caption_parts = []
        if result.title:
            caption_parts.append(result.title)
        if result.author:
            caption_parts.append(f"@{result.author}")
        caption = " ｜ ".join(caption_parts) if caption_parts else ""
        quiet = bool(result.extras.get("quiet"))  # B 站：卡片自带标题，只发视频
        # 图文帖：先文案后逐张发图（像真人发九宫格）
        if result.local_images:
            try:
                if caption:
                    self._send_text(room_id, caption)
                for i, img in enumerate(result.local_images):
                    self._send_image(room_id, img)
                    if i < len(result.local_images) - 1:
                        time.sleep(random.uniform(0.8, 1.6))
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("图文发送失败：%s", exc)
                self._send_text(
                    room_id,
                    f"图我拿到了 {len(result.local_images)} 张，但往群里发的通道出了点问题……",
                )
            return
        try:
            if result.local_path is not None and Path(result.local_path).exists():
                if not quiet:
                    # 先发首帧缩略图（群里直接可见的视频预览）
                    thumb = self._extract_first_frame(Path(result.local_path))
                    if thumb:
                        self._send_image(room_id, thumb)
                self._send_video(room_id, Path(result.local_path),
                                 caption if not quiet else "")
            else:
                self._send_text(room_id, "视频取到了，但文件没落下来……我再试试别的办法。")
        except Exception as exc:  # noqa: BLE001 发送通道故障也不能沉默
            log.warning("视频发送失败（%s），发兜底文本", exc)
            from pelica.llm import persona

            size = ""
            if result.local_path is not None and Path(result.local_path).exists():
                size = f"（{Path(result.local_path).stat().st_size / 1024 / 1024:.0f}MB）"
            self._send_text(
                room_id,
                f"视频我拿到了{size}，但往群里转发的通道出了点问题……文件在我这边存着，管理员修好我就能发。",
            )

    @staticmethod
    def _extract_first_frame(video_path: Path):
        """抽取视频首帧存为 jpg（失败返回 None）。"""
        try:
            import cv2

            cap = cv2.VideoCapture(str(video_path))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return None
            thumb = video_path.with_suffix(".thumb.jpg")
            cv2.imwrite(str(thumb), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return thumb
        except Exception:  # noqa: BLE001
            return None
