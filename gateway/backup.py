"""本地备份/恢复：配置 DB + 角色包 + 白名单 打包 zip（不含语料索引）。"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from gateway import __version__
from gateway.characters import persona_dir
from gateway.configdb import ConfigDB
from gateway.coreproc import CoreProcess
from gateway.logs import LogHub
from gateway.redact import scan_plaintext_secrets


def create_backup(db: ConfigDB, data_dir: Path, hub: LogHub,
                  note: str = "") -> dict:
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    # 先落盘检查点，保证 zip 里 config.db 是完整的
    db.checkpoint()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = backups_dir / ("pelica-backup-%s.zip" % stamp)
    meta = {"version": __version__, "created_at": stamp, "note": note,
            "contents": ["config.db", "characters/"]}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("backup-manifest.json", json.dumps(meta, ensure_ascii=False))
        zf.write(db.path, "config.db")
        pdir = persona_dir(data_dir)
        if pdir.is_dir():
            for f in sorted(pdir.glob("*")):
                if f.is_file():
                    zf.write(f, "characters/" + f.name)
    hub.emit("gateway", "INFO", "已创建备份：%s（%.0f KB）"
             % (path.name, path.stat().st_size / 1024))
    return {"path": str(path), "size": path.stat().st_size,
            "name": path.name, "note": note}


def list_backups(data_dir: Path) -> list[dict]:
    backups_dir = data_dir / "backups"
    if not backups_dir.is_dir():
        return []
    out = []
    for p in sorted(backups_dir.glob("pelica-backup-*.zip"), reverse=True):
        out.append({"name": p.name, "path": str(p),
                    "size": p.stat().st_size,
                    "ts": p.stat().st_mtime})
    return out


def restore_backup(db: ConfigDB, data_dir: Path, hub: LogHub,
                   zip_path: Path, core: CoreProcess) -> dict:
    """恢复：停 Core → 校验 zip → 替换 config.db 与角色包 → 重载。"""
    core.stop(actor="restore")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "config.db" not in names:
            raise ValueError("备份包里没有 config.db")
        # 安全校验：恢复内容先脱敏扫描（备份本就不含密钥明文，双保险）
        leaked = 0
        for name in names:
            if name.endswith((".toml", ".md", ".json")):
                leaked += scan_plaintext_secrets(zf.read(name).decode("utf-8", "replace"))
        if leaked:
            raise ValueError("备份包含疑似明文密钥 %d 处，已拒绝恢复" % leaked)
        db.close()
        db.path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(db.path) + suffix).unlink(missing_ok=True)
        zf.extract("config.db", data_dir)
        target_chars = persona_dir(data_dir)
        target_chars.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name.startswith("characters/") and not name.endswith("/"):
                content = zf.read(name)
                (target_chars / Path(name).name).write_bytes(content)
    db.reopen()
    hub.emit("gateway", "INFO", "已恢复备份：%s" % zip_path.name)
    return {"restored": True, "name": zip_path.name}
