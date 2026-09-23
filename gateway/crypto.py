"""Windows DPAPI 密钥加密（CryptProtectData / CryptUnprotectData）。

密文只绑定当前 Windows 用户。加密失败时拒绝落库（返回 None 由调用方报错）。
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _unblob(blob: _DATA_BLOB) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def dpapi_protect(plain: str) -> str | None:
    """加密为 base64 密文；失败返回 None（调用方必须拒绝落库）。"""
    if not plain:
        return None
    raw = plain.encode("utf-8")
    in_blob, out_blob = _blob(raw), _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        return None
    return base64.b64encode(_unblob(out_blob)).decode("ascii")


def dpapi_unprotect(cipher_b64: str) -> str | None:
    """解密 base64 密文；失败（换机器/换用户/损坏）返回 None。"""
    try:
        raw = base64.b64decode(cipher_b64)
    except (ValueError, TypeError):
        return None
    in_blob, out_blob = _blob(raw), _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        return None
    return _unblob(out_blob).decode("utf-8")


def key_hint(key: str) -> str:
    """界面掩码：sk-****f3a2 形式。"""
    if len(key) <= 6:
        return "****"
    return f"{key[:3]}****{key[-4:]}"
