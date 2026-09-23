"""日志脱敏：假 sk- 注入后必须已掩码（D3）。"""

from __future__ import annotations

from gateway.logs import LogHub
from gateway.redact import redact, register_secret, scan_plaintext_secrets


def test_sk_pattern_masked():
    text = "provider 调用失败 key=sk-TESTFAKE123456789 done"
    out = redact(text)
    assert "sk-TESTFAKE123456789" not in out
    assert "sk-****MASKED" in out


def test_bearer_masked():
    out = redact("Authorization: Bearer abcdefghijklmn")
    assert "abcdefghijklmn" not in out


def test_registered_secret_masked():
    register_secret("Zy9SECRETVALUE99x")
    out = redact("token=Zy9SECRETVALUE99x;")
    assert "Zy9SECRETVALUE99x" not in out


def test_hub_emit_redacts(tmp_path):
    hub = LogHub(tmp_path / "logs")
    entry = hub.emit("core", "INFO", "加载 Key sk-TESTFAKE987654321 完成")
    assert "sk-TESTFAKE987654321" not in entry["message"]
    assert "sk-****MASKED" in entry["message"]
    # 落盘文件同样不得出现明文
    content = (tmp_path / "logs" / "gateway.log").read_text(encoding="utf-8")
    assert "sk-TESTFAKE987654321" not in content


def test_scan_counts():
    assert scan_plaintext_secrets("a sk-AAAA1111BBBB b sk-CCCC2222") == 2
    assert scan_plaintext_secrets("nothing here") == 0
