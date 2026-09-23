"""FastAPI 网关：全部 REST + WS 端点（仅 127.0.0.1 + Bearer token）。"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import requests as _requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gateway import __version__
from gateway import backup as backup_mod
from gateway import characters as chars
from gateway import diagnostics as diag_mod
from gateway.characters import persona_dir
from gateway.configdb import ConfigDB, now
from gateway.coreproc import CoreProcess, build_core_env
from gateway.logs import LogHub
from gateway.paths import (
    REPO_ROOT, corpus_release_dirs, discover_corpora,
    is_frozen, resolve_data_dir,
)
from gateway.redact import redact, register_secret, scan_plaintext_secrets
from gateway.sandbox import run_sandbox

ALLOWED_SETTING_KEYS = {
    "character.active", "bridge.mode", "bridge.wxhook_url", "bridge.bot_wxid",
    "llm.reasoning_effort", "llm.temperature", "llm.max_tokens",
    "schedule.timezone", "schedule.weekly_weekday", "schedule.weekly_time",
    "schedule.greeting_morning", "schedule.greeting_night", "schedule.greeting_days",
    "douyin.keep_hours", "douyin.resolver_api", "douyin.download_dir",
    "alert.kind", "alert.webhook_url", "alert.failure_threshold",
    "log.level", "ui.mode", "ui.theme", "provider.active_id",
    "wizard.current_step", "wizard.data", "wizard.done",
}

FLAG_PRESETS = {
    "minimal": {
        "label": "极简",
        "description": "仅 @ 触发，关闭链接解析与定时互动。",
        "flags": {"douyin": False, "bilibili": False,
                  "weekly_report": False, "greeting": False},
    },
    "standard": {
        "label": "标准",
        "description": "@ + 关键词触发，链接解析与周报问好开启（推荐）。",
        "flags": {"douyin": True, "bilibili": True,
                  "weekly_report": True, "greeting": True},
    },
    "full": {
        "label": "全能",
        "description": "全部功能开启；追问续聊与自发插话为内核常开能力。",
        "flags": {"douyin": True, "bilibili": True,
                  "weekly_report": True, "greeting": True},
    },
}

BUILTIN_PROFILES = [
    {
        "key": "pelica", "name": "佩丽卡 × PRTS × DeepSeek", "icon": "🦉",
        "manifest": {
            "persona": "pelica", "corpora": ["pelica.db"],
            "model": {"provider": "deepseek", "model": "deepseek-flash"},
            "flags_overlay": {}, "reply_policy": {},
        },
        "summary": "终末地监督，全剧情问答溯源（默认）。",
    },
    {
        "key": "kaltsit", "name": "凯尔希 × PRTS", "icon": "🩺",
        "manifest": {
            "persona": "kaltsit", "corpora": ["pelica.db"],
            "model": {"provider": "deepseek", "model": "deepseek-flash"},
            "flags_overlay": {}, "reply_policy": {},
        },
        "summary": "罗德岛医疗主管，复用同一套 PRTS 语料。",
    },
    {
        "key": "paimon", "name": "派蒙 × 原神语料", "icon": "✨",
        "manifest": {
            "persona": "paimon", "corpora": ["paimon.db"],
            "model": {"provider": "deepseek", "model": "deepseek-flash"},
            "flags_overlay": {}, "reply_policy": {},
        },
        "summary": "最好的伙伴（不是应急食品），需派蒙语料库。",
    },
]

PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "kimi": "https://api.moonshot.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

CORPUS_FLAG_KEYS = {"douyin", "bilibili", "weekly_report", "greeting"}


# ---------------------------------------------------------------------------
# 请求模型


class SettingsPut(BaseModel):
    values: dict


class GroupIn(BaseModel):
    name: str = ""
    wxid: str = ""
    remark: str = ""
    tags: str = ""
    trigger_mode: str = "at"
    member_policy: str = "all"
    status: str = "active"
    quiet_hours: str = ""
    expires_at: str | None = None
    overrides: dict | None = None


class PrivateIn(BaseModel):
    nickname: str = ""
    wxid: str = ""
    remark: str = ""
    role: str = "member"
    mode: str = "normal"
    blacklisted: bool = False
    expires_at: str | None = None


class ProviderIn(BaseModel):
    kind: str = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    api_key: str = ""


class FlagsPut(BaseModel):
    flags: dict


class SandboxIn(BaseModel):
    text: str
    room: str = "沙箱群"
    sender: str = "管理员"
    is_at: bool = True
    private: bool = False


class TestQueryIn(BaseModel):
    question: str
    corpus_id: str | None = None
    with_answer: bool = False


class WizardStep(BaseModel):
    step: int
    payload: dict = {}


class RestoreIn(BaseModel):
    path: str = ""


class ImportIn(BaseModel):
    content: str = ""       # JSON 文本或 base64（backup zip）
    path: str = ""          # 本地文件路径（导入语料等）


class PersonaIn(BaseModel):
    name: str = ""
    wechat_name: str = ""
    signature: str = ""
    at_aliases: list[str] = []
    persona_md: str = ""
    db: str = ""
    corpus_release: str = ""
    # 出处话术 [[关键词, 说法]]；None=未编辑（保留旧值），[]=用户清空
    source_phrases: list[list[str]] | None = None


def _toml_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# 应用工厂


class Tasks:
    """后台任务登记（索引重建等）：tid → 状态/日志。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def create(self, kind: str) -> str:
        tid = secrets.token_hex(6)
        with self._lock:
            self._tasks[tid] = {"id": tid, "kind": kind, "status": "running",
                                "started_at": now(), "log": []}
        return tid

    def log(self, tid: str, line: str) -> None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is not None:
                task["log"].append(redact(line))

    def finish(self, tid: str, ok: bool, error: str = "") -> None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is not None:
                task["status"] = "done" if ok else "failed"
                task["error"] = redact(error)
                task["finished_at"] = now()

    def get(self, tid: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(tid)
            return dict(task) if task else None


def create_app(data_dir: Path | None = None, token: str | None = None) -> FastAPI:
    data_dir = data_dir or resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)

    token = token or secrets.token_urlsafe(32)
    db = ConfigDB(data_dir / "config.db")
    hub = LogHub(data_dir / "logs")
    core = CoreProcess(db, data_dir, hub)
    tasks = Tasks()

    app = FastAPI(title="Pelica Console Gateway", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.db = db
    app.state.hub = hub
    app.state.core = core
    app.state.tasks = tasks
    app.state.token = token
    app.state.data_dir = data_dir

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5179", "http://127.0.0.1:5179",
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://tauri.localhost", "https://tauri.localhost",
        ],
        allow_methods=["*"], allow_headers=["*"],
    )

    # ---- 鉴权 ---------------------------------------------------------------

    def require_auth(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        supplied = auth.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="未授权：令牌无效")

    # ---- 启动种子 -----------------------------------------------------------

    def seed() -> None:
        staged = chars.stage_characters(data_dir)
        hub.emit("gateway", "INFO", "角色包已就绪：%s" % ",".join(staged))
        for p in chars.discover_personas(data_dir):
            db.upsert_persona(p["id"], p["name"], p["toml_path"],
                              p["persona_md_path"])
        existing = db.list_profiles()
        if not existing:
            for spec in BUILTIN_PROFILES:
                db.create_profile(spec["name"], spec["icon"], spec["manifest"],
                                  is_builtin=True, actor="seed")
        if db.get_setting("character.active") is None:
            db.set_setting("character.active", "pelica", actor="seed")
        if db.get_setting("wizard.current_step") is None:
            db.set_setting("wizard.current_step", 0, actor="seed")
            db.set_setting("wizard.data", {}, actor="seed")
        if not db.list_private_users():
            db.create_private_user(
                {"nickname": "管理员", "wxid": "", "role": "admin",
                 "mode": "normal"}, actor="seed")
        # 首启自动导入 .env（已导入过或 DB 已有 provider 则跳过）
        _auto_import_env()
        hub.emit("gateway", "INFO",
                 "网关就绪 v%s（数据目录 %s）" % (__version__, data_dir))

    def _auto_import_env() -> None:
        if db.get_setting("env.imported"):
            return
        if db.list_providers():
            db.set_setting("env.imported", True, actor="seed")
            return
        candidates: list[Path] = []
        explicit = os.environ.get("PELICA_ENV_IMPORT", "").strip()
        if explicit:
            # 显式指定（含指向不存在文件的哨兵值）：不再回落其他来源
            candidates.append(Path(explicit))
        elif not is_frozen():
            candidates.append(REPO_ROOT / ".env")
        for cand in candidates:
            if cand.exists():
                if _import_env_file(cand):
                    hub.emit("gateway", "INFO",
                             "已从 .env 导入配置（密钥已加密存放）")
                break
        db.set_setting("env.imported", True, actor="seed")

    def _import_env_file(path: Path) -> bool:
        from dotenv import dotenv_values

        values = dotenv_values(path)
        api_key = (values.get("DEEPSEEK_API_KEY") or "").strip()
        if not api_key or api_key.startswith("sk-xxx"):
            return False
        pid = db.create_provider(
            kind="deepseek",
            base_url=(values.get("DEEPSEEK_BASE_URL")
                      or "https://api.deepseek.com/v1").strip(),
            api_key=api_key,
            model=(values.get("DEEPSEEK_MODEL") or "deepseek-flash").strip(),
            actor="import",
        )
        db.set_setting("provider.active_id", pid, actor="import")
        register_secret(api_key)
        bridge = (values.get("BRIDGE_MODE") or "").strip()
        if bridge in ("mock", "wxhook", "pyweixin", "wechaty", "wcf"):
            db.set_setting("bridge.mode", bridge, actor="import")
        character = (values.get("CHARACTER") or "").strip()
        if character:
            db.set_setting("character.active", character, actor="import")
        groups = [g.strip() for g in
                  (values.get("GROUP_WHITELIST") or "").replace("，", ",").split(",")
                  if g.strip()]
        for g in groups:
            db.create_group({"name": g, "status": "active"}, actor="import")
        return True

    seed()

    # ---- 工具 ----------------------------------------------------------------

    def corpus_stats(path: Path) -> dict:
        try:
            conn = sqlite3.connect(path, timeout=5.0)
            try:
                doc = conn.execute("SELECT COUNT(*) FROM documents", ()).fetchone()[0]
                ent = conn.execute("SELECT COUNT(*) FROM entities", ()).fetchone()[0]
            finally:
                conn.close()
            return {"doc_count": doc, "entity_count": ent,
                    "size": path.stat().st_size,
                    "updated_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(path.stat().st_mtime))}
        except (sqlite3.Error, OSError):
            return {"doc_count": 0, "entity_count": 0,
                    "size": path.stat().st_size if path.exists() else 0,
                    "updated_at": ""}

    def list_corpora() -> list[dict]:
        out = []
        for path in discover_corpora(data_dir):
            stats = corpus_stats(path)
            out.append({
                "id": path.stem, "name": path.stem, "db_path": str(path),
                "release_dir": "", "index_status": "ready" if stats["doc_count"] else "empty",
                **stats,
            })
        for releases in corpus_release_dirs(data_dir):
            for d in sorted(releases.iterdir()):
                if d.is_dir():
                    out.append({
                        "id": "release:" + d.name, "name": d.name + "（未建库）",
                        "db_path": "", "release_dir": str(d),
                        "doc_count": 0, "entity_count": 0, "size": 0,
                        "updated_at": "", "index_status": "pending",
                    })
            break
        return out

    # ---- 基础 ----------------------------------------------------------------

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__,
                "mode": "packaged" if is_frozen() else "dev"}

    @app.get("/api/bootstrap")
    def bootstrap(request: Request, _=Depends(require_auth)):
        provider = db.active_provider()
        return {
            "version": __version__,
            "mode": "packaged" if is_frozen() else "dev",
            "data_dir": str(data_dir),
            "wizard": {
                "current_step": db.get_setting("wizard.current_step", 0),
                "data": db.get_setting("wizard.data", {}),
                "done": bool(db.get_setting("wizard.done", False)),
            },
            "character": db.get_setting("character.active", "pelica"),
            "core": core.status(),
            "provider": db.provider_row(provider) if provider else None,
            "has_corpus": bool(discover_corpora(data_dir)),
            "personas": [p["id"] for p in chars.discover_personas(data_dir)],
            "groups_count": len(db.group_whitelist()),
            "ui": {"mode": db.get_setting("ui.mode", "simple"),
                   "theme": db.get_setting("ui.theme", "dark")},
        }

    @app.get("/api/settings")
    def get_settings(_=Depends(require_auth)):
        eff = db.effective_settings()
        eff.pop("provider", None)
        return eff

    @app.put("/api/settings")
    def put_settings(body: SettingsPut, _=Depends(require_auth)):
        rejected = [k for k in body.values if k not in ALLOWED_SETTING_KEYS]
        accepted = {k: v for k, v in body.values.items()
                    if k in ALLOWED_SETTING_KEYS}
        for key, value in accepted.items():
            db.set_setting(key, value)
        hub.emit("gateway", "INFO", "设置已更新：%s" % ",".join(accepted))
        return {"updated": list(accepted), "rejected": rejected}

    # ---- 方案中心 --------------------------------------------------------------

    @app.get("/api/profiles")
    def get_profiles(_=Depends(require_auth)):
        active = db.get_setting("character.active", "pelica")
        out = []
        for row in db.list_profiles():
            manifest = db.profile_manifest(row["id"])
            summary = next((b["summary"] for b in BUILTIN_PROFILES
                            if b["key"] == manifest.get("persona")), "")
            out.append({**row, "manifest": manifest, "summary": summary,
                        "applied": manifest.get("persona") == active})
        return {"profiles": out, "active_character": active}

    @app.post("/api/profiles")
    def create_profile_endpoint(body: dict, _=Depends(require_auth)):
        name = str(body.get("name") or "新方案").strip()
        manifest = body.get("manifest") or {}
        pid = db.create_profile(name, body.get("icon", "⭐"), manifest)
        return {"id": pid}

    @app.post("/api/profiles/{pid}/apply")
    def apply_profile(pid: int, _=Depends(require_auth)):
        row = db.get_profile(pid)
        if row is None:
            raise HTTPException(404, "方案不存在")
        manifest = db.profile_manifest(pid) or {}
        before = {"character.active": db.get_setting("character.active")}
        persona = manifest.get("persona") or "pelica"
        # 切换前快照（审计行即回滚点）
        db.audit("ui", "profile.apply", "profile/%d" % pid,
                 before=before, after={"character.active": persona})
        db.set_setting("character.active", persona, actor="profile")
        overlay = manifest.get("flags_overlay") or {}
        if overlay:
            db.set_flags_bulk(overlay, actor="profile")
        # 方案模型 → 全局 Provider（保留密钥，只换 kind/base_url/model）
        model_cfg = manifest.get("model") or {}
        if model_cfg:
            provider = db.active_provider()
            if provider is not None:
                kind = str(model_cfg.get("provider") or provider["kind"])
                base_url = PROVIDER_BASE_URLS.get(kind, provider["base_url"])
                db.update_provider(int(provider["id"]), kind, base_url, None,
                                   str(model_cfg.get("model") or provider["model"]),
                                   actor="profile")
        if core.status()["running"]:
            core.restart(actor="profile")
        hub.emit("gateway", "INFO", "已应用方案：%s（角色 %s）" % (row["name"], persona))
        return {"applied": True, "character": persona}

    @app.put("/api/profiles/{pid}")
    def update_profile_ep(pid: int, body: dict, _=Depends(require_auth)):
        try:
            version = db.update_profile(
                pid,
                str(body.get("name") or "未命名方案"),
                str(body.get("icon") or "⭐"),
                body.get("manifest") or {},
                note=str(body.get("note") or ""),
            )
        except KeyError:
            raise HTTPException(404, "方案不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"id": pid, "version": version}

    @app.delete("/api/profiles/{pid}")
    def delete_profile_ep(pid: int, _=Depends(require_auth)):
        try:
            db.delete_profile(pid)
        except KeyError:
            raise HTTPException(404, "方案不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"deleted": pid}

    @app.post("/api/profiles/{pid}/duplicate")
    def duplicate_profile(pid: int, body: dict | None = None, _=Depends(require_auth)):
        row = db.get_profile(pid)
        if row is None:
            raise HTTPException(404, "方案不存在")
        manifest = db.profile_manifest(pid) or {}
        new_name = ((body or {}).get("name") or row["name"] + " 副本")
        new_id = db.create_profile(new_name, row["icon"], manifest,
                                   base_profile_id=row["id"])
        return {"id": new_id, "name": new_name}

    @app.post("/api/profiles/export")
    def export_profiles(body: dict | None = None, _=Depends(require_auth)):
        ids = (body or {}).get("ids")
        out = []
        for row in db.list_profiles():
            if ids and row["id"] not in ids:
                continue
            manifest = db.profile_manifest(row["id"]) or {}
            persona_id = manifest.get("persona", "")
            toml_text = md_text = ""
            pdir = persona_dir(data_dir)
            toml_path = pdir / (persona_id + ".toml")
            if toml_path.exists():
                toml_text = toml_path.read_text(encoding="utf-8")
                md_path = toml_path.with_suffix(".persona.md")
                md_text = (md_path.read_text(encoding="utf-8")
                           if md_path.exists() else "")
            out.append({"name": row["name"], "icon": row["icon"],
                        "manifest": manifest, "persona": {
                            "id": persona_id, "toml": toml_text,
                            "persona_md": md_text}})
        text = json.dumps({"version": __version__, "profiles": out},
                          ensure_ascii=False, indent=2)
        leaked = scan_plaintext_secrets(text)
        if leaked:
            text = redact(text)
        return {"content": text, "secrets_stripped": leaked,
                "note": "已自动去除 %d 个密钥" % leaked if leaked else ""}

    @app.post("/api/profiles/import")
    def import_profiles(body: ImportIn, _=Depends(require_auth)):
        try:
            data = json.loads(body.content)
        except ValueError:
            raise HTTPException(400, "导入内容不是合法 JSON")
        created, warnings = [], []
        for spec in data.get("profiles", []):
            manifest = spec.get("manifest") or {}
            persona = spec.get("persona") or {}
            pid = persona.get("id")
            if pid:
                pdir = persona_dir(data_dir)
                toml_text = persona.get("toml") or ""
                md_text = persona.get("persona_md") or ""
                if toml_text and md_text:
                    chars.write_pack(data_dir, pid, toml_text, md_text)
                    db.upsert_persona(pid, pid, str(pdir / (pid + ".toml")),
                                      str(pdir / (pid + ".persona.md")))
                else:
                    warnings.append("角色包 %s 文件不全，未导入人设" % pid)
            new_id = db.create_profile(spec.get("name", "导入方案"),
                                       spec.get("icon", "📦"), manifest)
            created.append(new_id)
        return {"created": created, "warnings": warnings}

    # ---- 人设 -----------------------------------------------------------------

    @app.get("/api/personas")
    def get_personas(_=Depends(require_auth)):
        rows = {p["id"]: p for p in db.list_personas()}
        out = []
        for p in chars.discover_personas(data_dir):
            row = rows.get(p["id"], {})
            versions = db.persona_versions(p["id"])
            out.append({**p, "enabled": row.get("enabled", 1),
                        "versions": len(versions),
                        "active": p["id"] == db.get_setting("character.active")})
        return {"personas": out}

    @app.get("/api/personas/{pid}")
    def get_persona(pid: str, _=Depends(require_auth)):
        import tomllib

        pdir = persona_dir(data_dir)
        toml_path = pdir / (pid + ".toml")
        if not toml_path.exists():
            raise HTTPException(404, "角色包不存在")
        md_path = toml_path.with_suffix(".persona.md")
        toml_text = toml_path.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(toml_text)
        except Exception:  # noqa: BLE001 手写 toml 语法错时仍返回原文
            parsed = {}
        char = parsed.get("character") or {}
        psec = parsed.get("persona") or {}
        return {
            "id": pid,
            "toml": toml_text,
            "persona_md": (md_path.read_text(encoding="utf-8")
                           if md_path.exists() else ""),
            "versions": db.persona_versions(pid),
            "fields": {
                "wechat_name": str(char.get("wechat_name") or pid),
                "signature": str(char.get("signature") or ""),
                "at_aliases": [str(a) for a in (char.get("at_aliases") or [])],
                "db": str(char.get("db") or ""),
                "corpus_release": str(char.get("corpus_release") or ""),
                "source_phrases": [[str(k), str(v)] for k, v in
                                   (psec.get("source_phrases") or [])],
            },
        }

    def _write_persona_files(pid: str, body: PersonaIn, actor: str) -> dict:
        toml_path = persona_dir(data_dir) / (pid + ".toml")
        before = {"toml": toml_path.read_text(encoding="utf-8")
                  if toml_path.exists() else "",
                  "persona_md": ""}
        md_path = toml_path.with_suffix(".persona.md")
        if md_path.exists():
            before["persona_md"] = md_path.read_text(encoding="utf-8")
        aliases = ", ".join(_toml_str(a) for a in body.at_aliases) or '"佩丽卡"'
        db_line = 'db = %s\n' % _toml_str(body.db) if body.db else ""
        release_line = ('corpus_release = %s\n' % _toml_str(body.corpus_release)
                        if body.corpus_release else "")
        # 出处话术：None=本次未编辑 → 从旧 toml 保留（防止控制台覆盖丢数据）
        source = body.source_phrases
        if source is None:
            try:
                import tomllib

                old = tomllib.loads(before["toml"]) if before["toml"] else {}
                source = old.get("persona", {}).get("source_phrases")
            except Exception:  # noqa: BLE001
                source = None
        source_line = ""
        if source:
            pairs = ", ".join("[%s, %s]" % (_toml_str(k), _toml_str(v))
                              for k, v in source if len(k) >= 1)
            if pairs:
                source_line = "source_phrases = [%s]\n" % pairs
        toml_text = (
            "# 由 Pelica Console 生成/维护的角色包。\n\n"
            "[character]\n"
            f"id = {_toml_str(pid)}\n"
            f"display_name = {_toml_str(body.name or pid)}\n"
            f"wechat_name = {_toml_str(body.wechat_name or pid)}\n"
            f"signature = {_toml_str(body.signature)}\n"
            f"at_aliases = [{aliases}]\n"
            f"{db_line}{release_line}\n"
            "[persona]\n"
            f"file = {_toml_str('characters/' + pid + '.persona.md')}\n"
            f"{source_line}"
        )
        chars.write_pack(data_dir, pid, toml_text, body.persona_md)
        version = db.save_persona_version(pid, body.persona_md)
        db.upsert_persona(pid, body.name or pid, str(toml_path), str(md_path))
        db.audit(actor, "persona.update", "persona/" + pid,
                 before=before, after={"toml": toml_text,
                                       "persona_md": body.persona_md})
        return {"id": pid, "version": version}

    @app.post("/api/personas")
    def create_persona(body: PersonaIn, _=Depends(require_auth)):
        pid = (body.name or "").strip()
        if not pid or not pid.replace("_", "").isascii() or \
                not pid.replace("_", "").isalnum():
            raise HTTPException(400, "角色 id 仅限英文字母/数字/下划线")
        if (persona_dir(data_dir) / (pid + ".toml")).exists():
            raise HTTPException(409, "角色包已存在")
        return _write_persona_files(pid, body, actor="ui")

    @app.put("/api/personas/{pid}")
    def update_persona(pid: str, body: PersonaIn, _=Depends(require_auth)):
        if not (persona_dir(data_dir) / (pid + ".toml")).exists():
            raise HTTPException(404, "角色包不存在")
        return _write_persona_files(pid, body, actor="ui")

    @app.delete("/api/personas/{pid}")
    def delete_persona(pid: str, _=Depends(require_auth)):
        if pid == db.get_setting("character.active"):
            raise HTTPException(400, "不能删除当前启用中的角色")
        pdir = persona_dir(data_dir)
        toml_path = pdir / (pid + ".toml")
        if not toml_path.exists():
            raise HTTPException(404, "角色包不存在")
        before = {"toml": toml_path.read_text(encoding="utf-8")}
        md_path = toml_path.with_suffix(".persona.md")
        if md_path.exists():
            before["persona_md"] = md_path.read_text(encoding="utf-8")
            md_path.unlink()
        toml_path.unlink()
        db.audit("ui", "persona.delete", "persona/" + pid,
                 before=before, after=None)
        return {"deleted": pid}

    @app.post("/api/personas/{pid}/rollback")
    def rollback_persona(pid: str, body: dict, _=Depends(require_auth)):
        version = int(body.get("version", 0))
        content = db.persona_version_content(pid, version)
        if content is None:
            raise HTTPException(404, "版本不存在")
        toml_path = persona_dir(data_dir) / (pid + ".toml")
        if not toml_path.exists():
            raise HTTPException(404, "角色包不存在")
        md_path = toml_path.with_suffix(".persona.md")
        before = {"persona_md": md_path.read_text(encoding="utf-8")
                  if md_path.exists() else ""}
        chars.write_pack(data_dir, pid, toml_path.read_text(encoding="utf-8"),
                         content)
        db.save_persona_version(pid, content)
        db.audit("ui", "persona.update", "persona/" + pid + "/rollback",
                 before=before, after={"persona_md": content})
        return {"restored_version": version}

    @app.put("/api/personas/{pid}/enable")
    def enable_persona(pid: str, body: dict, _=Depends(require_auth)):
        enabled = bool(body.get("enabled", True))
        db.set_persona_enabled(pid, enabled)
        return {"id": pid, "enabled": enabled}

    # ---- 语料库 ----------------------------------------------------------------

    @app.get("/api/corpora")
    def get_corpora(_=Depends(require_auth)):
        return {"corpora": list_corpora()}

    def _run_build_db(db_path: Path, release: str) -> None:
        """子进程重建索引（必须先停 Core，防 sqlite locked——由调用方保证）。"""
        env = build_core_env(db, data_dir)
        if is_frozen():
            cmd = [sys.executable, "--tool", "build-db",
                   "--db", str(db_path)]
        else:
            cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_db.py"),
                   "--db", str(db_path)]
        if release and not release.startswith("release:"):
            cmd += ["--release", release]
        full_env = {k: v for k, v in os.environ.items()
                    if not k.startswith("PELICA_")}
        full_env.update(env)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=full_env, timeout=3600,
                              creationflags=subprocess.CREATE_NO_WINDOW
                              if sys.platform == "win32" else 0)
        output = (proc.stdout or "") + (proc.stderr or "")
        tid = threading.current_thread().name
        for line in output.splitlines()[:200]:
            tasks.log(tid, line)
        if proc.returncode != 0:
            raise RuntimeError("build_db 退出码 %d" % proc.returncode)

    @app.post("/api/corpora/{cid}/reindex")
    def reindex_corpus(cid: str, _=Depends(require_auth)):
        db_path: Path | None = None
        release = ""
        if cid.startswith("release:"):
            release = cid.split(":", 1)[1]
            persona_db = data_dir / "pelica.db"
            db_path = persona_db
        else:
            db_path = data_dir / (cid + ".db")
        if db_path is None or (not db_path.exists() and not release):
            raise HTTPException(404, "语料库不存在")
        # 铁律 §7.7：重建索引前必须先停 Core
        was_running = core.status()["running"]
        if was_running:
            core.stop(actor="reindex")

        tid = tasks.create("reindex")

        def _job() -> None:
            threading.current_thread().name = tid
            try:
                tasks.log(tid, "开始重建索引：%s" % cid)
                _run_build_db(db_path, release)
                tasks.finish(tid, ok=True)
                hub.emit("gateway", "INFO", "索引重建完成：%s" % cid)
            except Exception as exc:  # noqa: BLE001
                tasks.finish(tid, ok=False, error=str(exc))
                hub.emit("gateway", "ERROR", "索引重建失败：%s" % exc)
            finally:
                if was_running:
                    core.start(actor="reindex")

        threading.Thread(target=_job, daemon=True).start()
        return {"task_id": tid}

    @app.get("/api/corpora/tasks/{tid}")
    def get_task(tid: str, _=Depends(require_auth)):
        task = tasks.get(tid)
        if task is None:
            raise HTTPException(404, "任务不存在")
        return task

    @app.post("/api/corpora/test-query")
    def test_query(body: TestQueryIn, _=Depends(require_auth)):
        from pelica.db import Database
        from pelica.graph.matcher import EntityMatcher
        from pelica.graph.walker import GraphWalker
        from pelica.llm import persona
        from pelica.retrieval.retriever import Retriever

        started = time.time()
        target = None
        if body.corpus_id and not body.corpus_id.startswith("release:"):
            target = data_dir / (body.corpus_id + ".db")
        if target is None or not target.exists():
            target = data_dir / (db.get_setting("character.active", "pelica")
                                 + ".db")
        if not target.exists():
            for p in discover_corpora(data_dir):
                target = p
                break
        if target is None or not target.exists():
            return {"evidence": [], "answer": "", "corpus": "",
                    "elapsed_ms": 0, "note": "无语料库：仅人设直答路径可用"}
        corpus = Database(target)
        try:
            retriever = Retriever(corpus, EntityMatcher(corpus),
                                  GraphWalker(corpus))
            evidence = retriever.retrieve(body.question)
            snippets = [{
                "title": s.title, "citation": s.citation, "speaker": s.speaker,
                "text": s.text[:300], "category": s.category,
            } for s in evidence.snippets[:5]]
        finally:
            corpus.close()
        answer = ""
        if body.with_answer and db.provider_key():
            result = run_sandbox(db, data_dir, hub, "@" + body.question)
            answer = "\n".join(result["replies"])
        elapsed = int((time.time() - started) * 1000)
        return {"evidence": snippets,
                "covered": bool(evidence.covered),
                "answer": answer, "corpus": str(target),
                "elapsed_ms": elapsed}

    def _safe_user_path(raw: str, base: Path | None = None,
                        suffixes: tuple = ()) -> Path:
        """校验用户提供的本地路径：拒绝 ..，可要求限定在 base 内与指定后缀。"""
        if not raw:
            raise HTTPException(400, "路径为空")
        candidate = Path(raw.strip().strip('"'))
        if ".." in candidate.parts:
            raise HTTPException(400, "路径不允许包含 ..")
        resolved = candidate.resolve()
        if base is not None and base.resolve() not in resolved.parents and \
                resolved != base.resolve():
            raise HTTPException(400, "路径超出允许范围：%s" % base)
        if suffixes and resolved.suffix.lower() not in suffixes:
            raise HTTPException(400, "仅支持 %s 文件" % "/".join(suffixes))
        if not resolved.exists():
            raise HTTPException(400, "文件不存在：%s" % raw)
        return resolved

    @app.post("/api/corpora/import")
    def import_corpus(body: ImportIn, _=Depends(require_auth)):
        import base64
        import shutil as _shutil
        import zipfile as _zipfile

        src = _safe_user_path(body.path, suffixes=(".db", ".zip")) \
            if body.path else None
        if src is not None and src.suffix == ".db":
            dst = data_dir / src.name
            _shutil.copy2(src, dst)
            return {"imported": dst.stem, "kind": "db"}
        if src is not None and src.suffix == ".zip":
            releases = data_dir / "corpus" / "releases"
            releases.mkdir(parents=True, exist_ok=True)
            with _zipfile.ZipFile(src) as zf:
                zf.extractall(releases)
            return {"imported": src.stem, "kind": "release-zip"}
        if body.content:
            raw = base64.b64decode(body.content)
            releases = data_dir / "corpus" / "releases"
            releases.mkdir(parents=True, exist_ok=True)
            import io

            with _zipfile.ZipFile(io.BytesIO(raw)) as zf:
                zf.extractall(releases)
            return {"imported": "upload", "kind": "release-zip"}
        raise HTTPException(400, "请提供 zip/db 文件路径或内容")

    # ---- 群白名单 ---------------------------------------------------------------

    @app.get("/api/groups")
    def get_groups(_=Depends(require_auth)):
        return {"groups": db.list_groups()}

    @app.post("/api/groups")
    def create_group_ep(body: GroupIn, _=Depends(require_auth)):
        if not body.name and not body.wxid:
            raise HTTPException(400, "群名或群 ID 至少填一个")
        gid = db.create_group(body.model_dump(exclude={"overrides"},
                                              exclude_none=True))
        return {"id": gid}

    @app.put("/api/groups/{gid}")
    def update_group_ep(gid: int, body: GroupIn, _=Depends(require_auth)):
        try:
            db.update_group(gid, body.model_dump(exclude={"overrides"},
                                                 exclude_none=True))
        except KeyError:
            raise HTTPException(404, "群不存在")
        return {"updated": gid}

    @app.delete("/api/groups/{gid}")
    def delete_group_ep(gid: int, _=Depends(require_auth)):
        try:
            db.delete_group(gid)
        except KeyError:
            raise HTTPException(404, "群不存在")
        return {"deleted": gid}

    @app.post("/api/groups/export")
    def export_groups(_=Depends(require_auth)):
        text = json.dumps({"groups": db.list_groups()}, ensure_ascii=False,
                          indent=2)
        leaked = scan_plaintext_secrets(text)
        if leaked:
            text = redact(text)
        return {"content": text, "secrets_stripped": leaked,
                "note": "已自动去除 %d 个密钥" % leaked if leaked else ""}

    @app.post("/api/groups/import")
    def import_groups(body: ImportIn, _=Depends(require_auth)):
        try:
            data = json.loads(body.content)
        except ValueError:
            raise HTTPException(400, "导入内容不是合法 JSON")
        ids = []
        for g in data.get("groups", []):
            if g.get("name") or g.get("wxid"):
                ids.append(db.create_group(g, actor="import"))
        return {"created": ids}

    # ---- 私聊白名单 ---------------------------------------------------------------

    @app.get("/api/private-users")
    def get_private_users(_=Depends(require_auth)):
        return {"users": db.list_private_users()}

    @app.post("/api/private-users")
    def create_private_ep(body: PrivateIn, _=Depends(require_auth)):
        if not body.nickname and not body.wxid:
            raise HTTPException(400, "昵称或 wxid 至少填一个")
        uid = db.create_private_user(body.model_dump(exclude_none=True))
        return {"id": uid}

    @app.put("/api/private-users/{uid}")
    def update_private_ep(uid: int, body: PrivateIn, _=Depends(require_auth)):
        data = body.model_dump(exclude_none=True)
        data["blacklisted"] = body.blacklisted
        try:
            db.update_private_user(uid, data)
        except KeyError:
            raise HTTPException(404, "用户不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"updated": uid}

    @app.delete("/api/private-users/{uid}")
    def delete_private_ep(uid: int, _=Depends(require_auth)):
        try:
            db.delete_private_user(uid)
        except KeyError:
            raise HTTPException(404, "用户不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"deleted": uid}

    # ---- 模型与 API --------------------------------------------------------------

    @app.get("/api/providers")
    def get_providers(_=Depends(require_auth)):
        return {"providers": db.list_providers(),
                "active_id": db.get_setting("provider.active_id")}

    @app.post("/api/providers")
    def create_provider_ep(body: ProviderIn, _=Depends(require_auth)):
        try:
            pid = db.create_provider(body.kind, body.base_url,
                                     body.api_key, body.model)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.set_setting("provider.active_id", pid)
        if body.api_key:
            register_secret(body.api_key)
        return {"id": pid}

    @app.put("/api/providers/{pid}")
    def update_provider_ep(pid: int, body: ProviderIn, _=Depends(require_auth)):
        try:
            db.update_provider(pid, body.kind, body.base_url,
                               body.api_key or None, body.model)
        except KeyError:
            raise HTTPException(404, "provider 不存在")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"updated": pid}

    @app.delete("/api/providers/{pid}")
    def delete_provider_ep(pid: int, _=Depends(require_auth)):
        try:
            db.delete_provider(pid)
        except KeyError:
            raise HTTPException(404, "provider 不存在")
        return {"deleted": pid}

    @app.post("/api/providers/{pid}/test")
    def test_provider(pid: int, _=Depends(require_auth)):
        row = db.get_provider(pid)
        if row is None:
            raise HTTPException(404, "provider 不存在")
        key = db.provider_key(pid)
        if not key:
            return {"ok": False, "error": "未配置密钥",
                    "translated": "尚未填写 API Key，请先保存。",
                    "code": "no_key"}
        payload = {
            "model": row["model"],
            "messages": [{"role": "user", "content": "回复：正常"}],
            "max_tokens": 16, "stream": False,
        }
        started = time.time()
        try:
            resp = _requests.post(
                row["base_url"].rstrip("/") + "/chat/completions",
                json=payload, timeout=30,
                headers={"Authorization": "Bearer " + key},
            )
        except _requests.RequestException as exc:
            return {"ok": False, "error": str(exc),
                    "translated": "网络错误：无法连接模型服务，请检查网络或地址。",
                    "code": "network"}
        latency = int((time.time() - started) * 1000)
        if resp.status_code == 401:
            return {"ok": False, "error": "HTTP 401",
                    "translated": "密钥无效或已过期。", "code": "401"}
        if resp.status_code == 429:
            return {"ok": False, "error": "HTTP 429",
                    "translated": "调用太频繁或额度受限。", "code": "429"}
        if resp.status_code >= 400:
            snippet = resp.text[:200]
            if "insufficient_balance" in snippet:
                return {"ok": False, "error": snippet,
                        "translated": "账户余额不足，请充值后重试。",
                        "code": "balance"}
            return {"ok": False, "error": redact(snippet),
                    "translated": "模型服务返回错误（HTTP %d）。" % resp.status_code,
                    "code": str(resp.status_code)}
        try:
            data = resp.json()
            model = data.get("model", row["model"])
            content = (data.get("choices") or [{}])[0].get("message", {}).get(
                "content", "")
        except ValueError:
            model, content = row["model"], ""
        hub.emit("gateway", "INFO",
                 "Provider 测试成功（%s，%dms）" % (row["kind"], latency))
        return {"ok": True, "latency_ms": latency, "model": model,
                "reply_preview": content[:40]}

    # ---- 功能开关 -------------------------------------------------------------

    @app.get("/api/flags")
    def get_flags(_=Depends(require_auth)):
        pairs = dict(db.global_flag_pairs())
        current = {}
        for flag_key, raw in pairs.items():
            current[flag_key] = None if raw == "inherit" else raw == "true"
        return {"current": current,
                "effective": {k: (v if v is not None else True)
                              for k, v in current.items()},
                "definitions": [
                    {"key": "douyin", "group": "内容解析", "name": "抖音链接解析",
                     "desc": "群里出现抖音链接时自动解析出片。"},
                    {"key": "bilibili", "group": "内容解析", "name": "B 站链接解析",
                     "desc": "B 站视频链接解析与补链。"},
                    {"key": "weekly_report", "group": "定时互动", "name": "每周播报",
                     "desc": "每周五 18:00 发群统计周报。"},
                    {"key": "greeting", "group": "定时互动", "name": "每日问好",
                     "desc": "每天早晚向活跃群发人设问候。"},
                ]}

    @app.put("/api/flags")
    def put_flags(body: FlagsPut, _=Depends(require_auth)):
        clean = {}
        for flag_key, value in body.flags.items():
            if flag_key in {d["key"] for d in get_flags()["definitions"]}:
                clean[flag_key] = bool(value)
        if not clean:
            raise HTTPException(400, "没有可识别的开关")
        db.set_flags_bulk(clean)
        return {"updated": clean}

    @app.get("/api/flags/presets")
    def get_presets(_=Depends(require_auth)):
        current = get_flags()["effective"]
        presets = []
        for name, spec in FLAG_PRESETS.items():
            diff = [k for k, v in spec["flags"].items()
                    if current.get(k) != v]
            presets.append({"name": name, "label": spec["label"],
                            "description": spec["description"],
                            "flags": spec["flags"], "diff": diff})
        return {"presets": presets}

    @app.post("/api/flags/presets/{name}/apply")
    def apply_preset(name: str, _=Depends(require_auth)):
        spec = FLAG_PRESETS.get(name)
        if spec is None:
            raise HTTPException(404, "套餐不存在")
        db.set_flags_bulk(spec["flags"], actor="preset")
        if core.status()["running"]:
            core.restart(actor="preset")
        return {"applied": name, "flags": spec["flags"]}

    # ---- 沙箱 / 日志 ------------------------------------------------------------

    @app.post("/api/sandbox/run")
    def sandbox_run(body: SandboxIn, _=Depends(require_auth)):
        if not body.text.strip():
            raise HTTPException(400, "消息不能为空")
        return run_sandbox(db, data_dir, hub, body.text, body.room,
                           body.sender, body.is_at, body.private)

    @app.get("/api/logs/recent")
    def logs_recent(limit: int = Query(200, ge=1, le=800),
                    _=Depends(require_auth)):
        return {"logs": hub.recent(limit)}

    @app.websocket("/api/logs/ws")
    async def logs_ws(ws: WebSocket):
        token_q = ws.query_params.get("token", "")
        if not secrets.compare_digest(token_q, token):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = hub.subscribe()
        try:
            await ws.send_text(json.dumps({"type": "backlog",
                                           "logs": hub.recent(100)},
                                          ensure_ascii=False))
            while True:
                entry = await q.get()
                await ws.send_text(json.dumps(
                    {"type": "log", "log": entry}, ensure_ascii=False))
        except Exception:  # noqa: BLE001 断开即退订
            pass
        finally:
            hub.unsubscribe(q)

    # ---- 审计 / 撤销 ---------------------------------------------------------------

    @app.get("/api/audit")
    def get_audit(limit: int = Query(100, ge=1, le=500),
                  _=Depends(require_auth)):
        rows = db.audit_list(limit)
        for row in rows:
            for field in ("before", "after"):
                try:
                    row[field] = json.loads(row[field])
                except (ValueError, TypeError):
                    row[field] = {}
            row["undoable"] = row["action"].split(".")[0] in (
                "settings", "flags", "group", "private", "persona",
                "provider", "profile")
        return {"audit": rows}

    @app.post("/api/audit/{audit_id}/undo")
    def undo_audit(audit_id: int, _=Depends(require_auth)):
        row = db.get_audit(audit_id)
        if row is None:
            raise HTTPException(404, "审计记录不存在")
        action = row["action"]
        before = json.loads(row["before"] or "{}")
        after = json.loads(row["after"] or "{}")
        undone = True

        if action == "settings.update":
            for key, value in before.items():
                db.set_setting(key, value, actor="undo")
        elif action == "flags.apply":
            mapping = before.get("flags") or {}
            restore = {}
            current = dict(db.global_flag_pairs())
            for flag_key, raw in mapping.items():
                restore[flag_key] = (raw == "true") if raw != "inherit" else (
                    current.get(flag_key) == "true")
            if restore:
                db.set_flags_bulk(restore, actor="undo")
        elif action.startswith("group."):
            gid = int(row["target"].split("/")[-1])
            if action == "group.create":
                db.delete_group(gid, actor="undo")
            elif action == "group.update":
                db.update_group(gid, {k: v for k, v in before.items()
                                      if k in db.GROUP_COLUMNS}, actor="undo")
            elif action == "group.delete":
                if before.get("id") is not None:
                    db.reinsert_group(before, actor="undo")
                else:
                    db.create_group({k: v for k, v in before.items()
                                     if k in db.GROUP_COLUMNS}, actor="undo")
        elif action.startswith("private."):
            uid = int(row["target"].split("/")[-1])
            if action == "private.create":
                db.delete_private_user(uid, actor="undo")
            elif action == "private.update":
                db.update_private_user(
                    uid, {k: v for k, v in before.items()
                          if k in db.PRIVATE_COLUMNS}, actor="undo")
            elif action == "private.delete":
                if before.get("id") is not None:
                    db.reinsert_private_user(before, actor="undo")
                else:
                    db.create_private_user(
                        {k: v for k, v in before.items()
                         if k in db.PRIVATE_COLUMNS}, actor="undo")
        elif action == "persona.update":
            pid = row["target"].split("/")[1]
            toml_text = before.get("toml") or ""
            md_text = before.get("persona_md") or ""
            if toml_text or md_text:
                # before 快照里两份文件俱全则原样回写；缺失的一份保持现状
                current_toml_path = persona_dir(data_dir) / (pid + ".toml")
                current_md_path = current_toml_path.with_suffix(".persona.md")
                restore_toml = toml_text or (
                    current_toml_path.read_text(encoding="utf-8")
                    if current_toml_path.exists() else "")
                restore_md = md_text or (
                    current_md_path.read_text(encoding="utf-8")
                    if current_md_path.exists() else "")
                chars.write_pack(data_dir, pid, restore_toml, restore_md)
                db.save_persona_version(pid, restore_md)
        elif action == "persona.enable":
            pid = row["target"].split("/")[1]
            db.set_persona_enabled(pid, bool(before.get("enabled")), actor="undo")
        elif action.startswith("provider."):
            pid = int(row["target"].split("/")[-1])
            if action == "provider.create":
                db.delete_provider(pid, actor="undo")
            elif action == "provider.update":
                db.update_provider(pid, before.get("kind"),
                                   before.get("base_url"), None,
                                   before.get("model"), actor="undo")
            elif action == "provider.delete":
                if before.get("kind"):
                    db.create_provider(before["kind"],
                                       before.get("base_url", ""),
                                       "", before.get("model", ""),
                                       actor="undo")
                    undone = "partial"  # 密钥不可恢复，需重新填写
        elif action == "profile.apply":
            for key, value in before.items():
                db.set_setting(key, value, actor="undo")
        else:
            raise HTTPException(400, "该操作不支持撤销：%s" % action)

        if core.status()["running"]:
            core.restart(actor="undo")
        hub.emit("gateway", "INFO", "已撤销操作 #%d（%s）" % (audit_id, action))
        return {"undone": undone, "action": action}

    # ---- 备份 / 诊断 / Core 控制 ---------------------------------------------------

    @app.post("/api/backup")
    def do_backup(body: dict | None = None, _=Depends(require_auth)):
        note = (body or {}).get("note", "")
        return create_backup_safe(note)

    def create_backup_safe(note: str) -> dict:
        try:
            return backup_mod.create_backup(db, data_dir, hub, note)
        except OSError as exc:
            raise HTTPException(500, "备份失败：%s" % exc)

    @app.get("/api/backup")
    def list_backups_ep(_=Depends(require_auth)):
        return {"backups": backup_mod.list_backups(data_dir)}

    @app.post("/api/restore")
    def do_restore(body: RestoreIn, _=Depends(require_auth)):
        path = _safe_user_path(body.path, base=data_dir / "backups",
                               suffixes=(".zip",))
        try:
            result = backup_mod.restore_backup(db, data_dir, hub, path, core)
        except (ValueError, zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(400, str(exc))
        return result

    @app.get("/api/core/status")
    def core_status(_=Depends(require_auth)):
        """仪表盘实时轮询：Core 进程 + 微信桥接连通性（轻量，无全套诊断）。"""
        st = core.status()
        bridge_mode = str(db.get_setting("bridge.mode", "mock"))
        connected = False
        detail = ""
        if not st["running"]:
            detail = "机器人未运行，微信未接入"
        elif bridge_mode == "mock":
            connected = True
            detail = "沙箱模式（mock，不发真实微信）"
        else:
            url = str(db.get_setting("bridge.wxhook_url",
                                     "http://127.0.0.1:30001"))
            host = url.split("//")[-1].split(":")[0] or "127.0.0.1"
            try:
                port = int(url.split(":")[-1].split("/")[0])
            except ValueError:
                port = 30001
            sock = socket.socket()
            sock.settimeout(1.2)
            try:
                sock.connect((host, port))
                connected = True
                detail = "微信桥接已连接（%s:%s）" % (host, port)
            except OSError:
                connected = False
                detail = "微信桥接不可达（%s:%s）——检查微信是否打开且已注入" % (
                    host, port)
            finally:
                sock.close()
        return {"core": st, "bridge": {"mode": bridge_mode,
                                       "connected": connected,
                                       "detail": detail}}

    @app.get("/api/diagnostics")
    def get_diagnostics(_=Depends(require_auth)):
        return diag_mod.run_diagnostics(db, core, data_dir)

    @app.post("/api/core/start")
    def core_start(_=Depends(require_auth)):
        return core.start()

    @app.post("/api/core/stop")
    def core_stop(_=Depends(require_auth)):
        return core.stop()

    @app.post("/api/core/restart")
    def core_restart(_=Depends(require_auth)):
        return core.restart()

    # ---- 向导 ---------------------------------------------------------------

    @app.post("/api/wizard/step")
    def wizard_step(body: WizardStep, _=Depends(require_auth)):
        step, payload = body.step, dict(body.payload)
        data = db.get_setting("wizard.data", {}) or {}

        if step == 2:
            if not payload.get("risk_accepted"):
                raise HTTPException(400, "必须勾选风险确认才能继续")
            data["risk_accepted"] = True
        elif step == 3:
            bridge = payload.get("bridge", "mock")
            if bridge in ("mock", "wxhook", "pyweixin"):
                db.set_setting("bridge.mode", bridge, actor="wizard")
            data["bridge"] = bridge
        elif step == 4:
            character = payload.get("character", "pelica")
            db.set_setting("character.active", character, actor="wizard")
            data["character"] = character
        elif step == 5:
            provider = payload.get("provider") or {}
            if provider.get("api_key"):
                try:
                    pid = db.create_provider(
                        provider.get("kind", "deepseek"),
                        provider.get("base_url",
                                     "https://api.deepseek.com/v1"),
                        provider["api_key"], provider.get("model",
                                                          "deepseek-flash"),
                        actor="wizard")
                    db.set_setting("provider.active_id", pid, actor="wizard")
                    register_secret(provider["api_key"])
                except ValueError as exc:
                    raise HTTPException(400, str(exc))
            elif provider.get("base_url") or provider.get("model"):
                existing = db.active_provider()
                if existing is not None:
                    db.update_provider(
                        existing["id"], provider.get("kind"),
                        provider.get("base_url"), None,
                        provider.get("model"), actor="wizard")
            data["provider_tested"] = bool(payload.get("tested"))
        elif step == 6:
            data["sandbox_tried"] = True
        elif step == 7:
            for group in payload.get("groups", []):
                if group.get("name") or group.get("wxid"):
                    db.create_group({
                        "name": group.get("name", ""),
                        "wxid": group.get("wxid", ""),
                        "status": "active",
                        "trigger_mode": "at",
                    }, actor="wizard")
            data["groups_enabled"] = len(payload.get("groups", []))
        elif step == 8:
            db.set_setting("wizard.done", True, actor="wizard")
            data["done"] = True
        else:
            data.update(payload)

        data["last_step"] = step
        db.set_setting("wizard.current_step", step, actor="wizard")
        db.set_setting("wizard.data", data, actor="wizard")
        return {"step": step, "data": data}

    return app
