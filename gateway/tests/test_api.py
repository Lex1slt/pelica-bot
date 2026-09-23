"""API 鉴权 / 备份恢复闭环 / Core 控制（不起真 Core）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.app import create_app


def test_auth_401_without_token(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "home"))
    app = create_app(tmp_path / "home")
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200  # 仅健康检查公开
    for path in ("/api/bootstrap", "/api/settings", "/api/groups",
                 "/api/personas", "/api/corpora", "/api/flags",
                 "/api/audit", "/api/logs/recent", "/api/diagnostics"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/sandbox/run",
                       json={"text": "hi"}).status_code == 401
    app.state.db.close()


def test_wrong_token_401(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "home"))
    app = create_app(tmp_path / "home")
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer wrong-token-xyz"})
    assert client.get("/api/bootstrap").status_code == 401
    app.state.db.close()


def test_backup_restore_roundtrip(client):
    client.post("/api/groups", json={"name": "备份群", "wxid": "wxid_bk"})
    client.put("/api/settings", json={"values": {"log.level": "INFO"}})
    # 建份备份
    resp = client.post("/api/backup", json={"note": "验收备份"})
    assert resp.status_code == 200
    path = resp.json()["path"]
    # 破坏现场：删掉群、改设置
    groups = client.get("/api/groups").json()["groups"]
    gid = next(g["id"] for g in groups if g["name"] == "备份群")
    client.delete(f"/api/groups/{gid}")
    assert not any(g["name"] == "备份群"
                   for g in client.get("/api/groups").json()["groups"])
    # 恢复
    resp = client.post("/api/restore", json={"path": path})
    assert resp.status_code == 200, resp.text
    # 恢复后同一 app 立即可用，群回来了
    groups = client.get("/api/groups").json()["groups"]
    assert any(g["name"] == "备份群" for g in groups)


def test_backup_restore_rejects_outside_dir(client, tmp_path):
    evil = tmp_path / "evil.zip"
    evil.write_bytes(b"PK\x03\x04 not a real zip")
    resp = client.post("/api/restore", json={"path": str(evil)})
    assert resp.status_code == 400  # 路径超出备份目录被拒


def test_diagnostics_shape(client):
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    body = resp.json()
    ids = {c["id"] for c in body["checks"]}
    assert {"gateway", "data_dir", "core", "provider", "corpus"} <= ids
    for check in body["checks"]:
        assert check["status"] in ("ok", "warn", "fail")
        assert check["detail"]


def test_core_status_endpoint(client):
    resp = client.post("/api/core/start")
    assert resp.status_code == 200
    assert resp.json()["running"] is True
    resp = client.post("/api/core/stop")
    assert resp.json()["running"] is False
