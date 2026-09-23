#!/usr/bin/env python
"""生成控制台图标：1024 主图标 + 三态托盘 PNG（32px）。

主 .ico 由 `npx tauri icon` 从 1024 PNG 生成。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "console" / "src-tauri" / "icons"

ORANGE = (26, 122, 255)   # BGR #FF7A1A
SURFACE = (19, 19, 20)    # BGR #131315
BASE = (10, 10, 11)       # BGR #0A0A0B


def main_icon() -> None:
    size = 1024
    img = np.full((size, size, 3), BASE, dtype=np.uint8)
    inset = size // 18
    # 深色卡片 + 橙描边
    cv2.rectangle(img, (inset, inset), (size - inset, size - inset), SURFACE, -1)
    cv2.rectangle(img, (inset, inset), (size - inset, size - inset), ORANGE,
                  size // 34)
    # 字母 P
    orange = ORANGE
    thickness = size // 15
    ox, oy = int(size * 0.32), int(size * 0.27)
    cv2.line(img, (ox, oy), (ox, int(size * 0.75)), orange, thickness)
    cv2.ellipse(img, (int(ox + size * 0.105), int(oy + size * 0.075)),
                (int(size * 0.12), int(size * 0.105)), 0, -75, 255, orange,
                thickness)
    cv2.imwrite(str(OUT / "icon.png"), img)


def tray(name: str, color_bgr: tuple[int, int, int]) -> None:
    size = 32
    img = np.full((size, size, 3), BASE, dtype=np.uint8)
    cv2.circle(img, (size // 2, size // 2), size // 3, color_bgr, -1,
               lineType=cv2.LINE_AA)
    cv2.circle(img, (size // 2, size // 2), size // 3,
               (244, 244, 245), 2, lineType=cv2.LINE_AA)
    cv2.imwrite(str(OUT / name), img)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    main_icon()
    tray("tray-running.png", ORANGE)
    tray("tray-silent.png", (161, 161, 170))
    tray("tray-offline.png", (74, 71, 240))
    print("icons ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
