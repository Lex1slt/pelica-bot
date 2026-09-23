"""config.db：控制台配置主存储（SQLite WAL，schema 照设计文档 §4）。

SQL 全部参数绑定：每条语句都是方法内字面量 + 参数元组，不存在动态拼 SQL 的入口。
所有写操作先落 audit_log（before/after 快照），撤销/版本回滚由这一张表驱动。
`.env` 仅作为导入源/导出物。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from gateway import crypto

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    base_profile_id INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_versions (
    profile_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    manifest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (profile_id, version)
);
CREATE TABLE IF NOT EXISTS personas (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    toml_source TEXT NOT NULL DEFAULT '',
    persona_md TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    scope_default TEXT NOT NULL DEFAULT 'global'
);
CREATE TABLE IF NOT EXISTS persona_versions (
    persona_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (persona_id, version)
);
CREATE TABLE IF NOT EXISTS corpora (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    release_dir TEXT NOT NULL DEFAULT '',
    db_path TEXT NOT NULL,
    doc_count INTEGER NOT NULL DEFAULT 0,
    entity_count INTEGER NOT NULL DEFAULT 0,
    index_status TEXT NOT NULL DEFAULT 'ready',
    size INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS corpus_bindings (
    owner TEXT NOT NULL,
    corpus_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    priority INTEGER NOT NULL DEFAULT 5,
    PRIMARY KEY (owner, corpus_id)
);
CREATE TABLE IF NOT EXISTS sessions_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wxid TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    remark TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    trigger_mode TEXT NOT NULL DEFAULT 'at',
    member_policy TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'active',
    quiet_hours TEXT NOT NULL DEFAULT '',
    overrides TEXT NOT NULL DEFAULT '{}',
    last_active_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions_private (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wxid TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL,
    remark TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'member',
    mode TEXT NOT NULL DEFAULT 'normal',
    blacklisted INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    last_active_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'deepseek',
    base_url TEXT NOT NULL DEFAULT 'https://api.deepseek.com/v1',
    encrypted_key TEXT NOT NULL DEFAULT '',
    key_hint TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT 'deepseek-flash',
    params TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS model_routes (
    scope TEXT NOT NULL,
    task TEXT NOT NULL,
    provider_id INTEGER,
    model TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (scope, task)
);
CREATE TABLE IF NOT EXISTS flags (
    scope TEXT NOT NULL,
    flag_key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT 'inherit',
    PRIMARY KEY (scope, flag_key)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'ui',
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    before TEXT NOT NULL DEFAULT '{}',
    after TEXT NOT NULL DEFAULT '{}',
    undo_token TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'manual',
    payload_path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _dump(obj) -> str:
    return json.dumps(obj or {}, ensure_ascii=False, default=str)


class ConfigDB:
    """线程安全 config.db 封装。每条 SQL 都是方法内字面量 + 参数绑定。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()

    def reopen(self) -> None:
        """恢复备份替换文件后重连（close 的逆操作）。"""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = sqlite3.connect(
                self.path, check_same_thread=False, timeout=30.0
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def checkpoint(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # -- 审计（所有写操作的账本）----------------------------------------------

    def audit(self, actor: str, action: str, target: str,
              before: dict | None = None, after: dict | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit_log(ts,actor,action,target,before,after) "
                "VALUES (?,?,?,?,?,?)",
                (now(), actor, action, target, _dump(before), _dump(after)),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def audit_list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_audit(self, audit_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM audit_log WHERE id=?", (int(audit_id),)
            ).fetchone()
        return dict(row) if row else None

    # -- settings ---------------------------------------------------------------

    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return row["value"]

    def set_setting(self, key: str, value, actor: str = "ui") -> None:
        old = self.get_setting(key)
        if old == value:
            return
        self.audit(actor, "settings.update", "settings/" + key,
                   before={key: old}, after={key: value})
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    def settings_items(self) -> list[tuple]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM settings", ()
            ).fetchall()
        items: list[tuple] = []
        for row in rows:
            try:
                parsed = json.loads(row["value"])
            except (ValueError, TypeError):
                parsed = row["value"]
            items.append((row["key"], parsed))
        return items

    # -- flags ------------------------------------------------------------------

    def global_flag_pairs(self) -> list[tuple]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT flag_key, value FROM flags WHERE scope=?", ("global",)
            ).fetchall()
        return [(row["flag_key"], row["value"]) for row in rows]

    def set_flag(self, flag_key: str, value: bool, actor: str = "ui") -> None:
        old_pairs = dict(self.global_flag_pairs())
        old_raw = old_pairs.get(flag_key, "inherit")
        new_raw = "true" if value else "false"
        if old_raw == new_raw:
            return
        self.audit(actor, "flags.apply", "flags/" + flag_key,
                   before={"value": old_raw}, after={"value": new_raw})
        with self._lock:
            self._conn.execute(
                "INSERT INTO flags(scope,flag_key,value) VALUES ('global',?,?) "
                "ON CONFLICT(scope,flag_key) DO UPDATE SET value=excluded.value",
                (flag_key, new_raw),
            )
            self._conn.commit()

    def set_flags_bulk(self, mapping: dict, actor: str = "ui") -> None:
        old_pairs = dict(self.global_flag_pairs())
        self.audit(actor, "flags.apply", "flags/bulk",
                   before={"flags": old_pairs},
                   after={"flags": {k: ("true" if v else "false")
                                    for k, v in mapping.items()}})
        with self._lock:
            for flag_key, value in mapping.items():
                self._conn.execute(
                    "INSERT INTO flags(scope,flag_key,value) VALUES ('global',?,?) "
                    "ON CONFLICT(scope,flag_key) DO UPDATE SET value=excluded.value",
                    (flag_key, "true" if value else "false"),
                )
            self._conn.commit()

    # -- providers ----------------------------------------------------------------

    def list_providers(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM providers ORDER BY id", ()
            ).fetchall()
        return [self.provider_row(r) for r in rows]

    def provider_row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d.pop("encrypted_key", None)
        d["has_key"] = bool(row["encrypted_key"])
        return d

    def get_provider(self, pid: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM providers WHERE id=?", (int(pid),)
            ).fetchone()

    def active_provider(self) -> sqlite3.Row | None:
        pid = self.get_setting("provider.active_id")
        row = self.get_provider(int(pid)) if pid else None
        if row is None:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM providers WHERE enabled=1 ORDER BY id LIMIT 1", ()
                ).fetchone()
        return row

    def create_provider(self, kind: str, base_url: str, api_key: str,
                        model: str, actor: str = "ui") -> int:
        cipher = crypto.dpapi_protect(api_key)
        if api_key and not cipher:
            raise ValueError("密钥加密失败（DPAPI），拒绝落库")
        hint = crypto.key_hint(api_key) if api_key else ""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO providers(kind,base_url,encrypted_key,key_hint,model,"
                "params,enabled,created_at) VALUES (?,?,?,?,?,'{}',1,?)",
                (kind, base_url, cipher or "", hint, model, now()),
            )
            self._conn.commit()
            pid = int(cur.lastrowid or 0)
        self.audit(actor, "provider.create", "provider/" + str(pid),
                   before=None,
                   after={"kind": kind, "base_url": base_url,
                          "model": model, "key_hint": hint})
        return pid

    def update_provider(self, pid: int, kind: str | None, base_url: str | None,
                        api_key: str | None, model: str | None,
                        actor: str = "ui") -> None:
        row = self.get_provider(pid)
        if row is None:
            raise KeyError("provider 不存在")
        updates: dict = {}
        if kind is not None:
            updates["kind"] = kind
        if base_url is not None:
            updates["base_url"] = base_url
        if model is not None:
            updates["model"] = model
        if api_key is not None:
            cipher = crypto.dpapi_protect(api_key)
            if api_key and not cipher:
                raise ValueError("密钥加密失败（DPAPI），拒绝落库")
            updates["encrypted_key"] = cipher or ""
            updates["key_hint"] = crypto.key_hint(api_key) if api_key else ""
        before = {"kind": row["kind"], "base_url": row["base_url"],
                  "model": row["model"], "key_hint": row["key_hint"]}
        after = dict(before)
        after.update({k: v for k, v in updates.items() if k != "encrypted_key"})
        self.audit(actor, "provider.update", "provider/" + str(pid),
                   before=before, after=after)
        with self._lock:
            for column, value in updates.items():
                self._conn.execute(
                    "UPDATE providers SET " + column + "=? WHERE id=?",
                    (value, int(pid)),
                )
            self._conn.commit()

    def delete_provider(self, pid: int, actor: str = "ui") -> None:
        row = self.get_provider(pid)
        if row is None:
            raise KeyError("provider 不存在")
        self.audit(actor, "provider.delete", "provider/" + str(pid),
                   before={"kind": row["kind"], "base_url": row["base_url"],
                           "model": row["model"]},
                   after=None)
        with self._lock:
            self._conn.execute("DELETE FROM providers WHERE id=?", (int(pid),))
            self._conn.commit()

    def provider_key(self, pid: int | None = None) -> str:
        row = self.get_provider(int(pid)) if pid else self.active_provider()
        if row is None or not row["encrypted_key"]:
            return ""
        return crypto.dpapi_unprotect(row["encrypted_key"]) or ""

    # -- personas -------------------------------------------------------------

    def upsert_persona(self, pid: str, name: str, toml_source: str,
                       persona_md: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO personas(id,name,toml_source,persona_md,enabled,"
                "scope_default) VALUES (?,?,?,?,1,'global') "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
                "toml_source=excluded.toml_source, persona_md=excluded.persona_md",
                (pid, name, toml_source, persona_md),
            )
            self._conn.commit()

    def list_personas(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, enabled, scope_default FROM personas "
                "ORDER BY id", ()
            ).fetchall()
        return [dict(r) for r in rows]

    def set_persona_enabled(self, pid: str, enabled: bool, actor: str = "ui") -> None:
        old = 1 if enabled else 0
        self.audit(actor, "persona.enable", "persona/" + pid,
                   before={"enabled": 0 if enabled else 1}, after={"enabled": old})
        with self._lock:
            self._conn.execute(
                "UPDATE personas SET enabled=? WHERE id=?", (old, pid)
            )
            self._conn.commit()

    def save_persona_version(self, pid: str, content: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(version) AS v FROM persona_versions WHERE persona_id=?",
                (pid,),
            ).fetchone()
            version = (row["v"] or 0) + 1
            self._conn.execute(
                "INSERT INTO persona_versions(persona_id,version,content,created_at) "
                "VALUES (?,?,?,?)",
                (pid, version, content, now()),
            )
            self._conn.commit()
        return version

    def persona_versions(self, pid: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT version, created_at, length(content) AS size "
                "FROM persona_versions WHERE persona_id=? ORDER BY version DESC",
                (pid,),
            ).fetchall()
        return [dict(r) for r in rows]

    def persona_version_content(self, pid: str, version: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT content FROM persona_versions "
                "WHERE persona_id=? AND version=?",
                (pid, int(version)),
            ).fetchone()
        return row["content"] if row else None

    # -- 群白名单 ----------------------------------------------------------------

    def list_groups(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions_groups ORDER BY id", ()
            ).fetchall()
        return [dict(r) for r in rows]

    def get_group(self, gid: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions_groups WHERE id=?", (int(gid),)
            ).fetchone()
        return dict(row) if row else None

    GROUP_COLUMNS = ("wxid", "name", "remark", "tags", "trigger_mode",
                     "member_policy", "status", "quiet_hours")

    def create_group(self, data: dict, actor: str = "ui") -> int:
        cols = [c for c in self.GROUP_COLUMNS if c in data]
        placeholders = ",".join("?" for _ in cols)
        col_names = ",".join(cols)
        values = [data[c] for c in cols]
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions_groups(" + col_names + ") "
                "VALUES (" + placeholders + ")",
                tuple(values),
            )
            self._conn.commit()
            gid = int(cur.lastrowid or 0)
        self.audit(actor, "group.create", "group/" + str(gid),
                   before=None, after=self.get_group(gid))
        return gid

    def update_group(self, gid: int, data: dict, actor: str = "ui") -> None:
        before = self.get_group(gid)
        if before is None:
            raise KeyError("群不存在")
        cols = [c for c in self.GROUP_COLUMNS if c in data]
        if not cols:
            return
        assignments = ",".join(c + "=?" for c in cols)
        values = [data[c] for c in cols] + [int(gid)]
        with self._lock:
            self._conn.execute(
                "UPDATE sessions_groups SET " + assignments + " WHERE id=?",
                tuple(values),
            )
            self._conn.commit()
        self.audit(actor, "group.update", "group/" + str(gid),
                   before=before, after=self.get_group(gid))

    def delete_group(self, gid: int, actor: str = "ui") -> None:
        before = self.get_group(gid)
        if before is None:
            raise KeyError("群不存在")
        self.audit(actor, "group.delete", "group/" + str(gid),
                   before=before, after=None)
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions_groups WHERE id=?", (int(gid),)
            )
            self._conn.commit()

    def reinsert_group(self, row: dict, actor: str = "ui") -> int:
        """撤销删除：按原 id 原样复活该行。"""
        cols = ["id"] + [c for c in self.GROUP_COLUMNS if c in row]
        placeholders = ",".join("?" for _ in cols)
        col_names = ",".join(cols)
        values = [row.get(c) for c in cols]
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions_groups(" + col_names + ") "
                "VALUES (" + placeholders + ")",
                tuple(values),
            )
            self._conn.commit()
        gid = int(row["id"])
        self.audit(actor, "group.create", "group/" + str(gid),
                   before=None, after=self.get_group(gid))
        return gid

    # -- 私聊白名单 ----------------------------------------------------------------

    def list_private_users(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions_private ORDER BY "
                "CASE role WHEN 'admin' THEN 0 ELSE 1 END, id", ()
            ).fetchall()
        return [dict(r) for r in rows]

    def get_private_user(self, uid: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions_private WHERE id=?", (int(uid),)
            ).fetchone()
        return dict(row) if row else None

    PRIVATE_COLUMNS = ("wxid", "nickname", "remark", "role", "mode", "blacklisted")

    def create_private_user(self, data: dict, actor: str = "ui") -> int:
        cols = [c for c in self.PRIVATE_COLUMNS if c in data]
        placeholders = ",".join("?" for _ in cols)
        col_names = ",".join(cols)
        values = [data[c] for c in cols]
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions_private(" + col_names + ") "
                "VALUES (" + placeholders + ")",
                tuple(values),
            )
            self._conn.commit()
            uid = int(cur.lastrowid or 0)
        self.audit(actor, "private.create", "private/" + str(uid),
                   before=None, after=self.get_private_user(uid))
        return uid

    def update_private_user(self, uid: int, data: dict, actor: str = "ui") -> None:
        before = self.get_private_user(uid)
        if before is None:
            raise KeyError("用户不存在")
        if before["role"] == "admin" and data.get("role") not in (None, "admin"):
            raise ValueError("管理员角色不可修改")
        cols = [c for c in self.PRIVATE_COLUMNS if c in data]
        if not cols:
            return
        assignments = ",".join(c + "=?" for c in cols)
        values = [data[c] for c in cols] + [int(uid)]
        with self._lock:
            self._conn.execute(
                "UPDATE sessions_private SET " + assignments + " WHERE id=?",
                tuple(values),
            )
            self._conn.commit()
        self.audit(actor, "private.update", "private/" + str(uid),
                   before=before, after=self.get_private_user(uid))

    def delete_private_user(self, uid: int, actor: str = "ui") -> None:
        before = self.get_private_user(uid)
        if before is None:
            raise KeyError("用户不存在")
        if before["role"] == "admin":
            raise ValueError("管理员行不可删除")
        self.audit(actor, "private.delete", "private/" + str(uid),
                   before=before, after=None)
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions_private WHERE id=?", (int(uid),)
            )
            self._conn.commit()

    def reinsert_private_user(self, row: dict, actor: str = "ui") -> int:
        """撤销删除：按原 id 原样复活该行（管理员保护仍由 delete 侧把守）。"""
        cols = ["id"] + [c for c in self.PRIVATE_COLUMNS if c in row]
        placeholders = ",".join("?" for _ in cols)
        col_names = ",".join(cols)
        values = [row.get(c) for c in cols]
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions_private(" + col_names + ") "
                "VALUES (" + placeholders + ")",
                tuple(values),
            )
            self._conn.commit()
        uid = int(row["id"])
        self.audit(actor, "private.create", "private/" + str(uid),
                   before=None, after=self.get_private_user(uid))
        return uid

    # -- 方案（profiles）----------------------------------------------------------

    def list_profiles(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM profiles ORDER BY is_builtin DESC, id", ()
            ).fetchall()
        return [dict(r) for r in rows]

    def get_profile(self, pid: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM profiles WHERE id=?", (int(pid),)
            ).fetchone()
        return dict(row) if row else None

    def create_profile(self, name: str, icon: str, manifest: dict,
                       is_builtin: bool = False, base_profile_id: int | None = None,
                       actor: str = "ui") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO profiles(name,icon,is_builtin,base_profile_id,version,"
                "created_at) VALUES (?,?,?,?,1,?)",
                (name, icon, 1 if is_builtin else 0, base_profile_id, now()),
            )
            pid = int(cur.lastrowid or 0)
            self._conn.execute(
                "INSERT INTO profile_versions(profile_id,version,manifest,"
                "created_at,note) VALUES (?,1,?,?,?)",
                (pid, _dump(manifest), now(), "初始版本"),
            )
            self._conn.commit()
        self.audit(actor, "profile.create", "profile/" + str(pid),
                   before=None, after={"name": name})
        return pid

    def profile_manifest(self, pid: int) -> dict | None:
        row = self.get_profile(pid)
        if row is None:
            return None
        with self._lock:
            vrow = self._conn.execute(
                "SELECT manifest FROM profile_versions "
                "WHERE profile_id=? ORDER BY version DESC LIMIT 1",
                (int(pid),),
            ).fetchone()
        if vrow is None:
            return {}
        try:
            return json.loads(vrow["manifest"])
        except (ValueError, TypeError):
            return {}

    def update_profile(self, pid: int, name: str, icon: str,
                       manifest: dict, note: str = "",
                       actor: str = "ui") -> int:
        """更新方案（name/icon/manifest），manifest 落一份新版本快照。返回新版本号。"""
        row = self.get_profile(pid)
        if row is None:
            raise KeyError("方案不存在")
        before = {"name": row["name"], "icon": row["icon"],
                  "manifest": self.profile_manifest(pid)}
        with self._lock:
            vrow = self._conn.execute(
                "SELECT MAX(version) AS v FROM profile_versions WHERE profile_id=?",
                (int(pid),),
            ).fetchone()
            version = (vrow["v"] or 0) + 1
            self._conn.execute(
                "UPDATE profiles SET name=?, icon=?, version=? WHERE id=?",
                (name, icon, version, int(pid)),
            )
            self._conn.execute(
                "INSERT INTO profile_versions(profile_id,version,manifest,"
                "created_at,note) VALUES (?,?,?,?,?)",
                (int(pid), version, _dump(manifest), now(), note),
            )
            self._conn.commit()
        self.audit(actor, "profile.update", "profile/" + str(pid),
                   before=before,
                   after={"name": name, "icon": icon, "manifest": manifest})
        return version

    def delete_profile(self, pid: int, actor: str = "ui") -> None:
        row = self.get_profile(pid)
        if row is None:
            raise KeyError("方案不存在")
        if row["is_builtin"]:
            raise ValueError("内置方案不可删除（可复制为自定义方案后使用）")
        self.audit(actor, "profile.delete", "profile/" + str(pid),
                   before={"name": row["name"]}, after=None)
        with self._lock:
            self._conn.execute(
                "DELETE FROM profile_versions WHERE profile_id=?", (int(pid),)
            )
            self._conn.execute("DELETE FROM profiles WHERE id=?", (int(pid),))
            self._conn.commit()

    # -- Core env 注入 ---------------------------------------------------------

    def effective_settings(self) -> dict:
        """DB 有效配置（不含密钥明文；密钥单独经 provider_key 取）。"""
        out: dict = {}
        for key, value in self.settings_items():
            out[key] = value
        for flag_key, flag_value in self.global_flag_pairs():
            if flag_value in ("true", "false"):
                out["flag." + flag_key] = (flag_value == "true")
        provider = self.active_provider()
        if provider is not None:
            out["provider.base_url"] = provider["base_url"]
            out["provider.model"] = provider["model"]
        return out

    def group_whitelist(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT wxid, name FROM sessions_groups WHERE status='active'", ()
            ).fetchall()
        return [r["wxid"] or r["name"] for r in rows if (r["wxid"] or r["name"])]

    def private_whitelist(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT wxid, nickname FROM sessions_private "
                "WHERE blacklisted=0 AND mode!='disabled'", ()
            ).fetchall()
        return [r["wxid"] or r["nickname"]
                for r in rows if (r["wxid"] or r["nickname"])]
