"""沙箱端到端：无 Key 时管道不炸且仍有回复；提示词/证据结构齐备。"""

from __future__ import annotations

from pathlib import Path

from gateway.logs import LogHub
from gateway.sandbox import run_sandbox


def _db(data_dir: Path):
    from gateway.app import create_app

    app = create_app(data_dir)  # 种子（无 .env 导入：PELICA_ENV_IMPORT 由夹具隔离）
    return app.state.db, app


def test_sandbox_no_key_still_replies(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    data_dir = tmp_path / "home"
    db, app = _db(data_dir)
    try:
        result = run_sandbox(db, data_dir, LogHub(data_dir / "logs"),
                             "@佩丽卡 你好", sender="测试管理员")
        assert result["replies"], "无 Key 也必须有人设化回复（兜底路径）"
        assert result["llm_key_configured"] is False
        assert result["system_prompt"].startswith("你是佩丽卡")
        assert result["evidence"] == []  # 无语料 → 自由对话
        assert result["elapsed_s"] < 30
    finally:
        app.state.db.close()


def test_sandbox_identity_question_no_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    data_dir = tmp_path / "home2"
    db, app = _db(data_dir)
    try:
        result = run_sandbox(db, data_dir, LogHub(data_dir / "logs"),
                             "佩丽卡 你是真人吗", sender="测试管理员")
        assert result["replies"]
        assert result["llm_key_configured"] is False
    finally:
        app.state.db.close()


def test_sandbox_api_endpoint(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "home3"))
    from fastapi.testclient import TestClient

    from gateway.app import create_app

    app = create_app(tmp_path / "home3")
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer " + app.state.token})
    resp = client.post("/api/sandbox/run",
                       json={"text": "@佩丽卡 在吗", "sender": "验收员"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["replies"]
    assert body["system_prompt"]
    app.state.db.close()
