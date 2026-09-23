"""DPAPI 加解密往返与掩码。"""

from __future__ import annotations

import pytest

from gateway import crypto

pytestmark = pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="DPAPI 仅 Windows"
)


def test_roundtrip():
    cipher = crypto.dpapi_protect("sk-TEST-FAKE-ROUNDTRIP")
    assert cipher and cipher != "sk-TEST-FAKE-ROUNDTRIP"
    assert "sk-TEST-FAKE-ROUNDTRIP" not in cipher
    assert crypto.dpapi_unprotect(cipher) == "sk-TEST-FAKE-ROUNDTRIP"


def test_unicode_roundtrip():
    value = "密钥-тест-🔑-value"
    assert crypto.dpapi_unprotect(crypto.dpapi_protect(value)) == value


def test_corrupt_cipher_returns_none():
    assert crypto.dpapi_unprotect("not-base64!!") is None


def test_empty_returns_none():
    assert crypto.dpapi_protect("") is None


def test_key_hint():
    assert crypto.key_hint("sk-abcdef123456") == "sk-****3456"
    assert crypto.key_hint("short") == "****"
