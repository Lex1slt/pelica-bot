#!/usr/bin/env python
"""构建发布包（在仓库根目录运行）：

  python scripts/package_release.py            # 全部：安装包 + 数据库资产
  python scripts/package_release.py --skip-db  # 只打安装包（快）

产物（dist/）：
  佩丽卡监督-<ver>-win64-setup.zip   代码 + 一键安装器 + version.dll（不含语料数据库）
  佩丽卡监督-<ver>-pelica.db.zip    预构建语料数据库（解压到 data\\pelica.db）
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
STAGE = DIST / "pkg"
VERSION = "1.0.0"
WECHAT_DIRS = [
    Path(r"D:\WeChat\Weixin"),
    Path(r"C:\Program Files\Tencent\Weixin"),
    Path(r"C:\Program Files (x86)\Tencent\Weixin"),
    Path(r"D:\WeChat\download\Weixin"),
]

CODE_ITEMS = [
    "pelica",
    "main.py",
    "scripts",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    "README.md",
    "LICENSE",
    ".gitignore",
    "deploy",
    "Dockerfile",
    "docker-compose.yml",
    "安装.bat",
    "启动机器人.bat",
    "mock体验.bat",
    "快速开始-Windows.txt",
]
SCRIPTS_KEEP = {"build_db.py", "healthcheck.py", "qa_regression.py",
                "router_scenario_test.py", "note_pipeline_test.py",
                "run_mock_chat.py", "wxhook_probe.py"}

HOOK_README = """version.dll 来自开源项目 WeChat-Hook（https://github.com/aixed/WeChat-Hook）。
把它复制到微信 4.1.10.27 的安装目录（与 Weixin.exe 同文件夹）即可启用本机
HTTP 桥接（127.0.0.1:30001）。微信自动升级到新版本会使 hook 失效。
"""


def _ignore(src: Path, names: list[str]) -> list[str]:
    drop = []
    for n in names:
        if n in {"__pycache__", ".venv", "node_modules", "dist", ".git"}:
            drop.append(n)
        elif n.endswith((".pyc", ".log", ".db", ".part")):
            drop.append(n)
    return drop


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for item in CODE_ITEMS:
        src = ROOT / item
        if not src.exists():
            print(f"[warn] 缺少 {item}，跳过")
            continue
        dst = STAGE / item
        if src.is_dir():
            shutil.copytree(src, dst, ignore=_ignore)
        else:
            shutil.copy2(src, dst)
    # scripts/ 只保留发布需要的脚本（探针/实验脚本不带）
    scripts_dst = STAGE / "scripts"
    if scripts_dst.exists():
        for f in scripts_dst.iterdir():
            if f.suffix == ".py" and f.name not in SCRIPTS_KEEP:
                f.unlink()
    # version.dll（开源 WeChat-Hook 编译产物）
    dll = next((d / "version.dll" for d in WECHAT_DIRS if (d / "version.dll").exists()), None)
    if dll:
        hook = STAGE / "hook"
        hook.mkdir()
        shutil.copy2(dll, hook / "version.dll")
        (hook / "来源说明.txt").write_text(HOOK_README, encoding="utf-8")
        print(f"version.dll <- {dll}")
    else:
        print("[warn] 未找到 version.dll，安装包不含 hook，请在 Release 页面说明")


def zip_dir(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, Path(src.name) / p.relative_to(src))
    print(f"{out.name}  {out.stat().st_size / 1024 / 1024:.1f} MB  "
          f"sha256={hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")


def zip_db(out: Path) -> None:
    db = ROOT / "data" / "pelica.db"
    if not db.exists():
        print("[warn] data/pelica.db 不存在，跳过数据库资产")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(db, "pelica.db")
    print(f"{out.name}  {out.stat().st_size / 1024 / 1024:.1f} MB  "
          f"sha256={hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-db", action="store_true", help="只打安装包")
    args = ap.parse_args()
    DIST.mkdir(exist_ok=True)
    stage()
    zip_dir(STAGE, DIST / f"佩丽卡监督-{VERSION}-win64-setup.zip")
    if not args.skip_db:
        zip_db(DIST / f"佩丽卡监督-{VERSION}-pelica.db.zip")
    print("完成。产物在 dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
