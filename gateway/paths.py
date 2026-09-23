"""数据目录与资源目录解析。

数据目录优先级（任务书 §4.2）：
1. env PELICA_HOME（验收/自定义）
2. CWD 是本仓库 → <仓库>/data（开发模式，优先于 %APPDATA%）
3. %APPDATA%/pelica-console（发布版默认）

角色包/语料发现顺序：数据目录 → 安装包内置（exe 旁） → 仓库目录（仅开发）。
写入永远只进数据目录。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def exe_dir() -> Path:
    """网关可执行文件所在目录（打包后 = gateway-dist/）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return REPO_ROOT / "gateway"


def bundled_root() -> Path:
    """内置资源根：打包后为 _MEIPASS（= gateway-dist/），开发模式为仓库根。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return REPO_ROOT


def resolve_data_dir() -> Path:
    env = os.environ.get("PELICA_HOME", "").strip()
    if env:
        return Path(env)
    cwd = Path.cwd()
    if (cwd / "main.py").exists() and (cwd / "pelica").is_dir():
        return cwd / "data"
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "pelica-console"


def character_search_dirs(data_dir: Path) -> list[Path]:
    """角色包候选目录，按优先级：数据目录 → 内置（resources/gateway-dist 与 resources）→ 仓库。"""
    dirs = [data_dir / "characters", bundled_root() / "characters"]
    parent = exe_dir().parent / "characters"  # Tauri resources/characters
    if parent not in dirs:
        dirs.append(parent)
    if not is_frozen():
        dirs.append(REPO_ROOT / "characters")
    return [d for d in dirs if d.is_dir()]


def stage_bundled_characters(data_dir: Path) -> list[str]:
    """把内置角色包复制进数据目录（仅缺失的文件），使数据目录成为唯一写入口。

    返回已就位的角色 id 列表。失败（如只读）静默降级——读取仍可走内置目录。
    """
    staged: list[str] = []
    target = data_dir / "characters"
    for src_dir in reversed(character_search_dirs(data_dir)):
        # 反序复制：低优先级先铺，高优先级覆盖缺失文件
        if src_dir == target:
            continue
        for src in sorted(src_dir.glob("*.toml")):
            try:
                target.mkdir(parents=True, exist_ok=True)
                dst = target / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    md = src.with_suffix(".persona.md")
                    if md.exists() and not (target / md.name).exists():
                        shutil.copy2(md, target / md.name)
            except OSError:
                continue
    if target.is_dir():
        staged = sorted(p.stem for p in target.glob("*.toml"))
    return staged


def discover_corpora(data_dir: Path) -> list[Path]:
    """已构建语料库：数据目录下 *.db（排除 config.db / sandbox.db）。"""
    out: list[Path] = []
    if data_dir.is_dir():
        for p in sorted(data_dir.glob("*.db")):
            if p.name in ("config.db", "sandbox.db", "backup.db"):
                continue
            out.append(p)
    return out


def corpus_release_dirs(data_dir: Path) -> list[Path]:
    """语料 release 目录候选（数据目录优先，其次仓库/内置）。"""
    dirs = [data_dir / "corpus" / "releases", bundled_root() / "corpus" / "releases"]
    if not is_frozen():
        dirs.append(REPO_ROOT / "corpus" / "releases")
    return [d for d in dirs if d.is_dir()]
