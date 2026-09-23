"""新增端点：core/status 实时状态 / profiles PUT+DELETE / 应用方案同步模型。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.app import create_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "home"))
    app = create_app(tmp_path / "home")
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer " + app.state.token})
    return app, client


def test_core_status_shape(tmp_path, monkeypatch):
    app, client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/core/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"core", "bridge"}
    assert body["core"]["running"] is False
    assert body["bridge"]["mode"] == "mock"
    assert body["bridge"]["connected"] is False  # core 未跑 → 未接入
    # 启动后 mock 桥视为已连接（沙箱模式）
    client.post("/api/core/start")
    body = client.get("/api/core/status").json()
    assert body["core"]["running"] is True
    assert body["bridge"]["connected"] is True
    assert "沙箱" in body["bridge"]["detail"]
    client.post("/api/core/stop")
    app.state.db.close()


def test_profile_update_and_delete(tmp_path, monkeypatch):
    app, client = _client(tmp_path, monkeypatch)
    profiles = client.get("/api/profiles").json()["profiles"]
    builtin = next(p for p in profiles if p["is_builtin"])
    # 内置不可删
    assert client.delete(f"/api/profiles/{builtin['id']}").status_code == 400
    # 更新内置方案 manifest（模型换 kimi）
    resp = client.put(f"/api/profiles/{builtin['id']}", json={
        "name": builtin["name"], "icon": builtin["icon"],
        "manifest": {"persona": "pelica", "corpora": ["pelica.db"],
                     "model": {"provider": "kimi", "model": "moonshot-v1-8k"}}})
    assert resp.status_code == 200 and resp.json()["version"] >= 2
    updated = next(p for p in client.get("/api/profiles").json()["profiles"]
                   if p["id"] == builtin["id"])
    assert updated["manifest"]["model"]["model"] == "moonshot-v1-8k"
    # 审计有 profile.update → 可撤销
    audit = client.get("/api/audit?limit=10").json()["audit"]
    assert any(a["action"] == "profile.update" for a in audit)
    # 新建 + 删除自定义
    new_id = client.post("/api/profiles", json={
        "name": "临时", "icon": "🧪", "manifest": {"persona": "pelica"}}).json()["id"]
    assert client.delete(f"/api/profiles/{new_id}").status_code == 200
    app.state.db.close()


def test_apply_profile_syncs_model(tmp_path, monkeypatch):
    app, client = _client(tmp_path, monkeypatch)
    # 建一个 key 的 provider（先建 provider 才有 active_provider）
    client.post("/api/providers", json={
        "kind": "deepseek", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash", "api_key": "sk-" + "TEST" + "SYNC01"})
    profiles = client.get("/api/profiles").json()["profiles"]
    kaltsit = next(p for p in profiles if p["manifest"]["persona"] == "kaltsit")
    # 把方案 manifest 改为 kimi 模型，应用后全局 provider 应跟随
    client.put(f"/api/profiles/{kaltsit['id']}", json={
        "name": kaltsit["name"], "icon": kaltsit["icon"],
        "manifest": {"persona": "kaltsit", "corpora": ["pelica.db"],
                     "model": {"provider": "kimi", "model": "moonshot-v1-8k"}}})
    resp = client.post(f"/api/profiles/{kaltsit['id']}/apply")
    assert resp.status_code == 200
    provider = client.get("/api/providers").json()["providers"][-1]
    assert provider["kind"] == "kimi"
    assert provider["base_url"] == "https://api.moonshot.cn/v1"
    assert provider["model"] == "moonshot-v1-8k"
    # 撤销 apply → 角色回 pelica
    audit = client.get("/api/audit?limit=10").json()["audit"]
    row = next(a for a in audit if a["action"] == "profile.apply")
    client.post(f"/api/audit/{row['id']}/undo")
    assert client.get("/api/bootstrap").json()["character"] == "pelica"
    app.state.db.close()
