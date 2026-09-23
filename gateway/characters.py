"""角色包装载与数据目录托管。

- 内置角色包在网关启动时复制进数据目录（缺失文件才复制），并规范化 db 路径
  （`data/xxx.db` → `xxx.db`，相对数据目录解析）。
- Core 子进程通过 patch `pelica.character.ROOT = <数据目录>` 读到同一份文件，
  不改 pelica/ 源码（红线：仅外部 monkeypatch）。
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

from gateway.paths import character_search_dirs

_DB_RE = re.compile(r'^(\s*db\s*=\s*")data/([^"/]+)(")', re.MULTILINE)


def normalize_toml(text: str) -> str:
    """把 db = "data/xxx.db" 规范化为 db = "xxx.db"（相对数据目录）。"""
    return _DB_RE.sub(r'\1\2\3', text)


def load_pack(toml_path: Path) -> dict:
    """解析角色包 toml（规范化后），失败返回空 dict。"""
    try:
        raw = toml_path.read_text(encoding="utf-8")
        return tomllib.loads(normalize_toml(raw))
    except (OSError, ValueError):
        return {}


def stage_characters(data_dir: Path) -> list[str]:
    """内置角色包 → 数据目录（只补缺失文件；已存在的不覆盖——保留用户编辑）。"""
    target = data_dir / "characters"
    search = character_search_dirs(data_dir)
    for src_dir in reversed(search):
        if src_dir == target:
            continue
        for toml_src in sorted(src_dir.glob("*.toml")):
            try:
                target.mkdir(parents=True, exist_ok=True)
                dst = target / toml_src.name
                if not dst.exists():
                    text = normalize_toml(toml_src.read_text(encoding="utf-8"))
                    dst.write_text(text, encoding="utf-8")
                md = toml_src.with_suffix(".persona.md")
                if md.exists():
                    md_dst = target / md.name
                    if not md_dst.exists():
                        shutil.copy2(md, md_dst)
            except OSError:
                continue
    if not target.is_dir():
        return []
    return sorted(p.stem for p in target.glob("*.toml"))


def discover_personas(data_dir: Path) -> list[dict]:
    """发现角色包（数据目录优先），返回 UI 需要的摘要。"""
    seen: dict[str, dict] = {}
    for d in character_search_dirs(data_dir):
        for toml_path in sorted(d.glob("*.toml")):
            pid = toml_path.stem
            if pid in seen:
                continue
            pack = load_pack(toml_path)
            char = pack.get("character") or {}
            seen[pid] = {
                "id": pid,
                "name": char.get("display_name") or char.get("wechat_name") or pid,
                "wechat_name": char.get("wechat_name") or pid,
                "signature": char.get("signature", ""),
                "at_aliases": char.get("at_aliases") or [],
                "db": char.get("db", ""),
                "corpus_release": char.get("corpus_release", ""),
                "toml_path": str(toml_path),
                "persona_md_path": str(toml_path.with_suffix(".persona.md")),
            }
    return [seen[k] for k in sorted(seen)]


def persona_dir(data_dir: Path) -> Path:
    return data_dir / "characters"


def write_pack(data_dir: Path, pid: str, toml_text: str, persona_md: str) -> None:
    """人设保存：双文件写入数据目录（唯一写入口）。"""
    d = persona_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / (pid + ".toml")).write_text(normalize_toml(toml_text), encoding="utf-8")
    (d / (pid + ".persona.md")).write_text(persona_md, encoding="utf-8")


def apply_character_patch(data_dir: Path) -> bool:
    """Core 子进程入口调用：把 pelica.character.ROOT 指到数据目录。"""
    import pelica.character as character

    if (data_dir / "characters").is_dir():
        character.ROOT = data_dir
        return True
    return False
