#!/usr/bin/env python
"""构建 Pelica Console v1.1.0 发布包（在仓库根目录运行）。

  python scripts/package_console.py              # 全流程：gateway-dist + Tauri 安装包
  python scripts/package_console.py --gateway    # 只打网关（调试打包问题）
  python scripts/package_console.py --skip-gateway  # 网关已就绪，只打壳

产物：
  dist/pelica-console-1.1.0-x64-setup.exe        NSIS 安装包（zh-CN）
  dist/pelica-console-1.1.0-x64-setup.exe.sha256
  gateway-dist/pelica-gateway/                   PyInstaller onedir 网关（spec 见 scripts/gateway.spec）
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.1.0"
DIST = ROOT / "dist"
GATEWAY_DIST = ROOT / "gateway-dist"
SETUP_NAME = f"pelica-console-{VERSION}-x64-setup.exe"

RELEASE_TEMPLATE = """# Pelica Console v{version} —— 带图形管理控制台的发布版

> 佩丽卡监督 v{version}：新增 **Pelica Console** 桌面控制台（Tauri 2 + FastAPI 网关，
> 零 Python 依赖、自包含安装包），非开发者双击即用。

## 新功能（相对 v1.0.0）

1. **图形控制台** —— 仪表盘/方案中心/人设/语料库/白名单/模型与 API/功能开关/测试沙箱/实时日志/备份诊断，全中文界面，暗色 + 亮色主题。
2. **首启向导 8 步** —— 约 8 分 30 秒完成首次配置（风险告知 → 选方案 → 填 Key → 沙箱试聊 → 启用群）。
3. **测试沙箱** —— 不碰微信的全链路试跑：回复 + 证据 + 完整提示词 + 耗时，改配置先沙箱验证再上真群。
4. **配置主存储迁移** —— `.env` 降级为导入/导出格式；主存储为本机加密的 config.db（密钥 DPAPI 加密，界面/日志/导出全程掩码）。
5. **审计与撤销** —— 所有写操作先落快照，控制台一键撤销；本地备份/恢复闭环。
6. **托盘常驻** —— 三态托盘（运行/静默/离线），关闭窗口即最小化到托盘，开机自启可选。
7. **命令面板** —— Ctrl+K 搜索一切；Ctrl+Shift+S 直达沙箱。

## 安装三步（Windows 10/11 x64）

```bat
1. 双击 pelica-console-{version}-x64-setup.exe     :: 安装「Pelica Console」（可自选目录）
2. 开始菜单/桌面启动 Pelica Console，按向导填 DeepSeek API Key
3. 沙箱发一句「@佩丽卡 你好」，收到角色化回复即配置成功
```

已有 v1.0.0 用户：启动控制台后会自动导入仓库 `.env`（密钥转密文），原 CLI 用法完全不受影响。

## 升级说明

- CLI 形态（`python main.py`）与 `.env` 继续可用；控制台与 CLI 不冲突（数据目录隔离：控制台默认 `%APPDATA%\\pelica-console`，可用 `PELICA_HOME` 覆盖）。
- 语料库不内嵌安装包：控制台「语料库」页可导入本地 zip 或指向已有 db；无语料时沙箱仍可人设直答。

## 已知限制

- 微信接入仍要求 **微信 4.1.10.27 + version.dll 注入**（与 v1.0.0 相同；存在账号风险，务必小号）。
- 群级人设/语料覆盖、任务路由、对话回放、WebDAV 备份为 P1，未包含在本版。
- 追问续聊与自发插话为内核常开能力（受冷却约束），暂无独立开关。
- 导出的任何文件都不含密钥明文（.env 导出同样以占位符代替，需手填）。
"""


def build_gateway() -> None:
    GATEWAY_DIST.mkdir(exist_ok=True)
    print("[run] PyInstaller gateway（spec: scripts/gateway.spec）", flush=True)
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    proc = subprocess.run(
        [
            str(venv_python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(GATEWAY_DIST),
            "--workpath",
            str(ROOT / "build" / "pyinstaller-gateway"),
            str(ROOT / "scripts" / "gateway.spec"),
        ],
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller 失败 rc={proc.returncode}")


def build_tauri() -> Path:
    console = ROOT / "console"
    tauri_bin = console / "node_modules" / "@tauri-apps" / "cli" / "tauri.js"
    if not tauri_bin.exists():
        raise SystemExit("缺少 @tauri-apps/cli，请先在 console/ 执行 npm install")
    print("[run] tauri build（node 直调 bin 入口）", flush=True)
    proc = subprocess.run(
        ["node", str(tauri_bin), "build"],
        cwd=str(console),
    )
    if proc.returncode != 0:
        raise SystemExit(f"tauri build 失败 rc={proc.returncode}")
    nsis_dir = console / "src-tauri" / "target" / "release" / "bundle" / "nsis"
    candidates = sorted(nsis_dir.glob("Pelica Console_*-setup.exe"))
    if not candidates:
        raise SystemExit(f"未找到 NSIS 安装包：{nsis_dir}")
    setup = DIST / SETUP_NAME
    DIST.mkdir(exist_ok=True)
    setup.write_bytes(candidates[-1].read_bytes())
    return setup


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", action="store_true", help="只打网关")
    ap.add_argument("--skip-gateway", action="store_true", help="网关已就绪，只打壳")
    args = ap.parse_args()

    if not args.skip_gateway:
        build_gateway()
        print("[ok] gateway-dist 完成")
    if args.gateway:
        return 0

    setup = build_tauri()
    digest = sha256_of(setup)
    (DIST / (SETUP_NAME + ".sha256")).write_text(
        f"{digest}  {SETUP_NAME}\n", encoding="utf-8")
    release = ROOT / "docs" / f"RELEASE_v{VERSION}.md"
    release.write_text(RELEASE_TEMPLATE.format(version=VERSION), encoding="utf-8")

    print(f"[ok] 安装包：{setup}")
    print(f"[ok] SHA256：{digest}")
    print(f"[ok] 发布说明草稿：{release}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
