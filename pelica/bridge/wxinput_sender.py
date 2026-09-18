"""微信 4.x 键盘编排文件发送器（免费路线的视频投递）。

原理：微信 4.1.10/4.1.13 的界面自绘、无 UIA 树、hook 又没有发文件接口，
但微信窗口对**真实键盘输入**永远正常。因此用 SendInput 模拟人工操作：
  剪贴板放文件(CF_HDROP) → 激活微信窗口 → Ctrl+F 搜群名 → 回车进群
  → Ctrl+V 粘贴文件 → 回车发送。

代价：发送瞬间微信窗口会到前台并占用键盘约 2-4 秒（用户正在打字会被
干扰）；因此只用于视频/文件这类低频大件，文本与图片仍走 hook HTTP API。

注意：
- 微信必须已登录且主窗口未关闭（可以最小化到任务栏，发送时会自动还原）；
- 多开场景下定位的是 FindWindow 找到的第一个「微信」窗口——机器人小号
  请保持单实例运行；
- 期间若用户抢焦点可能发送失败，失败会抛 WxInputError 由上层兜底。
"""

from __future__ import annotations

import ctypes
import struct
import time
from ctypes import wintypes

import win32clipboard
import win32con
import win32gui

log = __import__("logging").getLogger(__name__)


class WxInputError(RuntimeError):
    pass


# ---------- SendInput 基础 ----------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_F = 0x46
VK_V = 0x56
VK_DOWN = 0x28


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key_down(vk: int = 0, scan: int = 0, unicode_flag: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = KEYEVENTF_UNICODE if unicode_flag else 0
    if unicode_flag:
        inp.ki.wVk = 0
    return inp


def _key_up(vk: int = 0, scan: int = 0, unicode_flag: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    flags = KEYEVENTF_KEYUP
    if unicode_flag:
        flags |= KEYEVENTF_UNICODE
        inp.ki.wVk = 0
    inp.ki.dwFlags = flags
    return inp


def send_input(events: list[INPUT]) -> None:
    arr = (INPUT * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise WxInputError(f"SendInput 只发送了 {sent}/{len(events)} 个事件")


def tap_key(vk: int) -> None:
    send_input([_key_down(vk), _key_up(vk)])


def combo_key(modifier_vk: int, key_vk: int) -> None:
    send_input([_key_down(modifier_vk), _key_down(key_vk),
                _key_up(key_vk), _key_up(modifier_vk)])


def type_unicode(text: str, per_char_delay: float = 0.01) -> None:
    """逐字符 UNICODE 输入（支持中文群名）。"""
    for ch in text:
        code = ord(ch)
        send_input([_key_down(scan=code, unicode_flag=True),
                    _key_up(scan=code, unicode_flag=True)])
        time.sleep(per_char_delay)


# ---------- 剪贴板 CF_HDROP ----------

def clipboard_set_files(paths: list[str]) -> None:
    """把文件路径列表放进剪贴板（CF_HDROP），供 Ctrl+V 粘贴发送。"""
    import pythoncom
    import win32clipboard

    pythoncom.CoInitialize()
    try:
        # DROPFILES 头：pFiles=20, pt=(0,0), fNC=0, fWide=1（宽字符路径）
        payload = "\0".join(paths) + "\0"
        data = struct.pack("iiiI", 20, 0, 0, 1) + payload.encode("utf-16-le") + b"\x00\x00"
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, data)
        finally:
            win32clipboard.CloseClipboard()
    finally:
        pythoncom.CoUninitialize()


# ---------- 窗口定位与前置 ----------

def find_weixin_window() -> int:
    hwnd = win32gui.FindWindow("Qt51514QWindowIcon", "微信")
    if not hwnd:
        hwnd = win32gui.FindWindow("Qt51514QWindowIcon", "Weixin")
    if not hwnd:
        raise WxInputError("找不到微信主窗口（微信未启动？）")
    return hwnd


def focus_window(hwnd: int) -> None:
    """把微信窗口带到前台（含前台锁绕过：先按一下 Alt）。"""
    win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE（最小化时还原）
    try:
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)      # Alt down
        win32gui.SetForegroundWindow(hwnd)
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)      # Alt up
    except Exception:
        pass
    time.sleep(0.4)


# ---------- 对外主入口 ----------

def send_file_to_chat(group_name: str, file_path: str,
                      timeout: float = 15.0) -> None:
    """在 PC 微信里把本地文件发送到指定群（键盘编排）。

    流程：剪贴板放文件 → 前置微信窗口 → Ctrl+F 搜群名 → 回车打开会话
    → Ctrl+V 粘贴文件 → 回车发送。
    """
    import os

    if not os.path.isfile(file_path):
        raise WxInputError(f"文件不存在：{file_path}")

    clipboard_set_files([os.path.abspath(file_path)])
    hwnd = find_weixin_window()
    focus_window(hwnd)
    time.sleep(0.3)

    # Esc 复位（关闭可能残留的搜一搜/弹层）
    tap_key(VK_ESCAPE)
    time.sleep(0.4)

    # Ctrl+F 打开搜索
    combo_key(VK_CONTROL, VK_F)
    time.sleep(0.6)
    # 清空搜索框可能的残留
    combo_key(VK_CONTROL, 0x41)  # Ctrl+A
    tap_key(0x2E)                # Delete
    time.sleep(0.2)
    type_unicode(group_name)
    time.sleep(1.2)              # 等下拉结果
    # ↓ 先高亮下拉里的第一个联系人结果，再回车打开会话
    # （直接回车会跳到「搜一搜」全页搜索）
    tap_key(0x28)                # VK_DOWN
    time.sleep(0.3)
    tap_key(VK_RETURN)
    time.sleep(0.8)

    # 粘贴文件并发送
    combo_key(VK_CONTROL, VK_V)
    time.sleep(1.0)
    tap_key(VK_RETURN)
    time.sleep(0.5)

    log.info("文件已通过键盘编排发送到「%s」：%s", group_name, file_path)
