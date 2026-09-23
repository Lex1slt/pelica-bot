"""config.db CRUD / 审计 / 撤销闭环。"""

from __future__ import annotations


def fake_key(tag: str) -> str:
    """测试专用假密钥占位（拼接构造，非任何真实凭据）。"""
    return "sk-" + "TESTFAKE" + tag


def test_group_crud_and_audit(client):
    # create
    resp = client.post("/api/groups", json={"name": "测试群A", "wxid": "wxid_a"})
    assert resp.status_code == 200
    gid = resp.json()["id"]
    # read
    groups = client.get("/api/groups").json()["groups"]
    assert any(g["id"] == gid and g["name"] == "测试群A" for g in groups)
    # update
    assert client.put(f"/api/groups/{gid}", json={"remark": "备注X"}).status_code == 200
    groups = client.get("/api/groups").json()["groups"]
    assert next(g for g in groups if g["id"] == gid)["remark"] == "备注X"
    # audit 记录了 create/update
    audit = client.get("/api/audit").json()["audit"]
    assert any(a["action"] == "group.create" for a in audit)
    assert any(a["action"] == "group.update" for a in audit)
    # delete + audit
    assert client.delete(f"/api/groups/{gid}").status_code == 200
    audit = client.get("/api/audit").json()["audit"]
    assert any(a["action"] == "group.delete" for a in audit)


def test_undo_group_create_and_update(client):
    gid = client.post("/api/groups", json={"name": "撤销群"}).json()["id"]
    client.put(f"/api/groups/{gid}", json={"remark": "改过"})
    audit = client.get("/api/audit").json()["audit"]
    update_row = next(a for a in audit if a["action"] == "group.update")
    # 撤销 update → remark 复原
    assert client.post(f"/api/audit/{update_row['id']}/undo").status_code == 200
    groups = client.get("/api/groups").json()["groups"]
    assert next(g for g in groups if g["id"] == gid)["remark"] == ""
    # 撤销 create → 行删除
    audit = client.get("/api/audit").json()["audit"]
    create_row = next(a for a in audit if a["action"] == "group.create")
    client.post(f"/api/audit/{create_row['id']}/undo")
    groups = client.get("/api/groups").json()["groups"]
    assert not any(g["id"] == gid for g in groups)
    # 撤销 delete → 行复活
    audit = client.get("/api/audit").json()["audit"]
    delete_row = next(a for a in audit if a["action"] == "group.delete")
    client.post(f"/api/audit/{delete_row['id']}/undo")
    groups = client.get("/api/groups").json()["groups"]
    assert any(g["id"] == gid and g["name"] == "撤销群" for g in groups)


def test_undo_group_delete_restores_fields(client):
    gid = client.post("/api/groups", json={
        "name": "字段群", "wxid": "wxid_f", "remark": "保留我",
        "trigger_mode": "keyword", "status": "paused"}).json()["id"]
    client.delete(f"/api/groups/{gid}")
    audit = client.get("/api/audit").json()["audit"]
    delete_row = next(a for a in audit if a["action"] == "group.delete"
                      and a["target"] == f"group/{gid}")
    client.post(f"/api/audit/{delete_row['id']}/undo")
    row = next(g for g in client.get("/api/groups").json()["groups"]
               if g["id"] == gid)
    assert row["remark"] == "保留我" and row["wxid"] == "wxid_f"
    assert row["trigger_mode"] == "keyword" and row["status"] == "paused"


def test_settings_update_and_undo(client):
    client.put("/api/settings", json={"values": {"log.level": "DEBUG"}})
    assert client.get("/api/settings").json()["log.level"] == "DEBUG"
    audit = client.get("/api/audit").json()["audit"]
    row = next(a for a in audit if a["action"] == "settings.update"
               and "log.level" in a["after"])
    client.post(f"/api/audit/{row['id']}/undo")
    assert client.get("/api/settings").json()["log.level"] != "DEBUG"


def test_settings_key_whitelist(client):
    resp = client.put("/api/settings", json={"values": {"evil.key": "x"}})
    assert resp.json()["rejected"] == ["evil.key"]


def test_private_admin_row_protected(client):
    users = client.get("/api/private-users").json()["users"]
    admin = next(u for u in users if u["role"] == "admin")
    assert client.delete(f"/api/private-users/{admin['id']}").status_code == 400


def test_provider_crud_no_plaintext_leak(client):
    key = fake_key("000111")
    resp = client.post("/api/providers", json={
        "kind": "deepseek", "api_key": key,
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash"})
    pid = resp.json()["id"]
    providers = client.get("/api/providers").json()["providers"]
    row = next(p for p in providers if p["id"] == pid)
    assert "encrypted_key" not in row
    assert row["has_key"] is True
    # config.db 落盘无明文
    import sqlite3

    conn = sqlite3.connect(client.app.state.data_dir / "config.db")
    raw = conn.execute("SELECT encrypted_key FROM providers WHERE id=?",
                       (pid,)).fetchone()[0]
    conn.close()
    assert key not in raw
    assert raw  # 密文存在


def test_profiles_apply_and_rollback(client):
    profiles = client.get("/api/profiles").json()["profiles"]
    assert len(profiles) >= 3
    kaltsit = next(p for p in profiles if p["manifest"]["persona"] == "kaltsit")
    resp = client.post(f"/api/profiles/{kaltsit['id']}/apply")
    assert resp.status_code == 200
    assert client.get("/api/bootstrap").json()["character"] == "kaltsit"
    # 审计含 profile.apply → undo 回到 pelica
    audit = client.get("/api/audit").json()["audit"]
    row = next(a for a in audit if a["action"] == "profile.apply")
    client.post(f"/api/audit/{row['id']}/undo")
    assert client.get("/api/bootstrap").json()["character"] == "pelica"


def test_groups_export_strips_fake_key(client):
    leaked_name = "sk-" + "TESTFAKE" + "EXPORT99 群"
    client.post("/api/groups", json={"name": leaked_name, "wxid": "wxid_x"})
    resp = client.post("/api/groups/export").json()
    assert resp["secrets_stripped"] >= 1
    assert leaked_name not in resp["content"]


def test_flags_presets(client):
    presets = client.get("/api/flags/presets").json()["presets"]
    names = {p["name"] for p in presets}
    assert {"minimal", "standard", "full"} <= names
    resp = client.post("/api/flags/presets/minimal/apply")
    assert resp.status_code == 200
    flags = client.get("/api/flags").json()["effective"]
    assert flags["douyin"] is False and flags["weekly_report"] is False
    client.post("/api/flags/presets/standard/apply")
    flags = client.get("/api/flags").json()["effective"]
    assert flags["douyin"] is True
    # undo bulk flags
    audit = client.get("/api/audit").json()["audit"]
    bulk = [a for a in audit if a["action"] == "flags.apply"]
    assert bulk
    assert client.post(f"/api/audit/{bulk[0]['id']}/undo").status_code == 200


def test_wizard_risk_gate(client):
    resp = client.post("/api/wizard/step",
                       json={"step": 2, "payload": {"risk_accepted": False}})
    assert resp.status_code == 400
    resp = client.post("/api/wizard/step",
                       json={"step": 2, "payload": {"risk_accepted": True}})
    assert resp.status_code == 200
    boot = client.get("/api/bootstrap").json()["wizard"]
    assert boot["current_step"] == 2
    # 第 8 步完成
    client.post("/api/wizard/step", json={"step": 8, "payload": {}})
    assert client.get("/api/bootstrap").json()["wizard"]["done"] is True


def test_wizard_groups_and_key(client):
    key = fake_key("WIZARD01")
    client.post("/api/wizard/step", json={"step": 5, "payload": {
        "provider": {"kind": "deepseek",
                     "base_url": "https://api.deepseek.com/v1",
                     "model": "deepseek-flash",
                     "api_key": key}}})
    client.post("/api/wizard/step", json={"step": 7, "payload": {
        "groups": [{"name": "向导群", "wxid": "wxid_w"}]}})
    groups = client.get("/api/groups").json()["groups"]
    assert any(g["name"] == "向导群" for g in groups)
    providers = client.get("/api/providers").json()["providers"]
    assert any(p["has_key"] for p in providers)


def test_persona_update_undo_restores_toml(client):
    """B7：改昵称保存→版本+1→undo 恢复（toml 与 md 双文件回滚）。"""
    detail = client.get("/api/personas/pelica").json()
    v0 = len(detail["versions"])
    new_toml = detail["toml"].replace(
        'wechat_name = "佩丽卡"', 'wechat_name = "小佩丽卡"')
    import tomllib

    def _fields(toml_text):
        pack = tomllib.loads(toml_text)
        return pack["character"]["wechat_name"]

    assert _fields(detail["toml"]) == "佩丽卡"
    # PUT 需要拆字段——用 toml 解析结果构造请求体
    pack = tomllib.loads(detail["toml"])
    char = pack["character"]
    client.put("/api/personas/pelica", json={
        "name": char.get("display_name", "佩丽卡监督"),
        "wechat_name": "小佩丽卡",
        "signature": char.get("signature", ""),
        "at_aliases": char.get("at_aliases", []),
        "persona_md": detail["persona_md"],
    })
    after = client.get("/api/personas/pelica").json()
    assert len(after["versions"]) == v0 + 1
    assert "小佩丽卡" in after["toml"]

    audit = client.get("/api/audit?limit=10").json()["audit"]
    row = next(a for a in audit if a["action"] == "persona.update")
    resp = client.post(f"/api/audit/{row['id']}/undo")
    assert resp.status_code == 200
    restored = client.get("/api/personas/pelica").json()
    assert _fields(restored["toml"]) == "佩丽卡", "undo 应恢复原昵称"
    assert restored["persona_md"] == detail["persona_md"]
