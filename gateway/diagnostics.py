"""诊断体检：环境清单逐项检查（状态 ok/warn/fail + 人话指引）。"""

from __future__ import annotations

import ctypes
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from gateway import __version__
from gateway.configdb import ConfigDB
from gateway.coreproc import CoreProcess
from gateway.paths import REPO_ROOT, discover_corpora, is_frozen

WECHAT_DIRS = [
    Path(r"D:\WeChat\Weixin"),
    Path(r"C:\Program Files\Tencent\Weixin"),
    Path(r"C:\Program Files (x86)\Tencent\Weixin"),
    Path(r"D:\WeChat\download\Weixin"),
]
EXPECTED_WECHAT = "4.1.10.27"


def _check(name: str, status: str, detail: str, hint: str = "") -> dict:
    return {"id": name, "status": status, "detail": detail, "hint": hint}


def _wechat_version() -> str:
    for d in WECHAT_DIRS:
        exe = d / "Weixin.exe"
        if not exe.exists():
            continue
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(str(exe), None)
            if not size:
                continue
            buf = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(str(exe), 0, size, buf)
            val = ctypes.c_void_p()
            length = ctypes.c_uint()
            if not ctypes.windll.version.VerQueryValueW(
                buf, "\\VarFileInfo\\Translation", ctypes.byref(val), ctypes.byref(length)
            ):
                continue
            codepage = ctypes.cast(val, ctypes.POINTER(ctypes.c_uint16))[
                0
            ].value << 16 | ctypes.cast(val, ctypes.POINTER(ctypes.c_uint16))[1].value
            key = f"\\StringFileInfo\\{codepage:08x}\\ProductVersion"
            if ctypes.windll.version.VerQueryValueW(
                buf, key, ctypes.byref(val), ctypes.byref(length)
            ):
                return ctypes.wstring_at(val.value, length.value - 1)
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_diagnostics(db: ConfigDB, core: CoreProcess, data_dir: Path) -> dict:
    checks: list[dict] = []

    # 1. 网关自身
    mode = "packaged" if is_frozen() else "dev"
    checks.append(_check("gateway", "ok",
                         "网关 v%s（%s 模式）运行中" % (__version__, mode)))

    # 2. 数据目录
    try:
        probe = data_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(_check("data_dir", "ok", str(data_dir)))
    except OSError:
        checks.append(_check("data_dir", "fail", str(data_dir),
                             "数据目录不可写，请检查权限"))

    # 3. Core 进程
    st = core.status()
    checks.append(_check(
        "core", "ok" if st["running"] else "warn",
        "运行中 pid=%s" % st["pid"] if st["running"] else "未运行",
        "" if st["running"] else "在仪表盘或托盘菜单启动机器人"))

    # 4. API Key（不回显任何明文）
    provider = db.active_provider()
    if provider is None:
        checks.append(_check("provider", "warn", "未配置模型服务",
                             "前往「模型与 API」填写 Key"))
    elif not provider["encrypted_key"]:
        checks.append(_check("provider", "warn",
                             "已配置 %s 但未填 Key" % provider["kind"],
                             "前往「模型与 API」填写 Key"))
    else:
        checks.append(_check("provider", "ok",
                             "密钥已加密存放（%s，%s）"
                             % (provider["kind"], provider["key_hint"] or "已掩码")))

    # 5. 桥接端口（wxhook 模式才检查）
    bridge_mode = db.get_setting("bridge.mode", "mock")
    if bridge_mode == "wxhook":
        url = db.get_setting("bridge.wxhook_url", "http://127.0.0.1:30001")
        host = url.split("//")[-1].split(":")[0] or "127.0.0.1"
        try:
            port = int(url.split(":")[-1].split("/")[0])
        except ValueError:
            port = 30001
        if _port_open(host, port):
            checks.append(_check("bridge_port", "ok", "%s:%s 可达" % (host, port)))
        else:
            checks.append(_check("bridge_port", "fail",
                                 "%s:%s 拒绝连接" % (host, port),
                                 "微信桥接未启动：确认微信 %s 已打开且 version.dll 已注入"
                                 % EXPECTED_WECHAT))
    else:
        checks.append(_check("bridge_port", "ok",
                             "桥接模式 %s（本机 mock，无需端口）" % bridge_mode))

    # 6. 微信版本
    ver = _wechat_version()
    if not ver:
        checks.append(_check("wechat_version", "warn", "未找到微信客户端",
                             "wxhook 模式需要微信 %s" % EXPECTED_WECHAT))
    elif ver.startswith(EXPECTED_WECHAT):
        checks.append(_check("wechat_version", "ok", "微信 %s" % ver))
    else:
        checks.append(_check("wechat_version", "warn", "微信 %s（预期 %s）" % (ver, EXPECTED_WECHAT),
                             "版本不符会使 hook 失效；开发机上此项橙警属预期"))

    # 7. 语料库
    corpora = discover_corpora(data_dir)
    if corpora:
        total = sum(p.stat().st_size for p in corpora)
        checks.append(_check("corpus", "ok",
                             "%d 个库，共 %.0f MB" % (len(corpora), total / 1048576)))
    else:
        checks.append(_check("corpus", "warn", "未发现语料库",
                             "沙箱仍可人设直答；完整剧情问答请到「语料库」导入"))

    # 8. 磁盘
    try:
        usage = shutil.disk_usage(data_dir if data_dir.exists() else Path.home())
        free_gb = usage.free / 1024 ** 3
        checks.append(_check("disk", "ok" if free_gb > 2 else "warn",
                             "剩余 %.1f GB" % free_gb))
    except OSError:
        checks.append(_check("disk", "warn", "无法读取磁盘空间"))

    # 9. Python（开发模式信息项）
    if not is_frozen():
        checks.append(_check("python", "ok", sys.version.split()[0]))

    passed = sum(1 for c in checks if c["status"] == "ok")
    failed = sum(1 for c in checks if c["status"] == "fail")
    return {
        "checks": checks,
        "summary": {"ok": passed, "warn": len(checks) - passed - failed,
                    "fail": failed},
    }
