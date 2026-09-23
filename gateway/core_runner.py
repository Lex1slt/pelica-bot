"""Core 子进程入口（被网关 spawn）：

- 把 pelica.character.ROOT 指到数据目录（读控制台维护的角色包，不改 pelica/ 源码）；
- 等价运行 main.py（env 已由网关注入为 config.db 有效配置）。
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from gateway.characters import apply_character_patch
from gateway.paths import bundled_root, is_frozen, resolve_data_dir


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR", "").strip()
    if env:
        return Path(env)
    return resolve_data_dir()


def run_core() -> int:
    data_dir = _data_dir()
    apply_character_patch(data_dir)
    sys.argv = ["main.py"]
    root = str(bundled_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    import main as main_module  # 打包版从 _MEIPASS，开发版从仓库根

    return main_module.main()


def run_tool_build_db(args: list[str]) -> int:
    """打包版重建索引：运行内置 scripts/build_db.py。"""
    data_dir = _data_dir()
    apply_character_patch(data_dir)
    script = bundled_root() / "scripts" / "build_db.py"
    if not script.exists():
        print("build_db.py missing", file=sys.stderr, flush=True)
        return 1
    sys.argv = ["build_db.py"] + args
    runpy.run_path(str(script), run_name="__main__")
    return 0
