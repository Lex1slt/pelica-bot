"""Pelica Console 网关入口。

用法：
  python -m gateway                # 网关模式：随机端口 + token，握手行打到 stdout
  python -m gateway --core         # Core 模式（被网关 spawn，等价 main.py，env 注入）
  python -m gateway --tool build-db --db <path> [--release <name>]
                                   # 工具模式：重建语料索引（打包版用）

握手行格式：PELICA_GATEWAY_READY {"port":..,"token":".."}
环境变量：PELICA_GATEWAY_PORT / PELICA_GATEWAY_TOKEN（开发模式固定端口用）。
"""

from __future__ import annotations

import os
import re
import sys


def _gateway() -> int:
    import json as _json
    import threading
    import time as _time

    import uvicorn

    from gateway.app import create_app
    from gateway.paths import resolve_data_dir

    data_dir = resolve_data_dir()
    fixed_token = os.environ.get("PELICA_GATEWAY_TOKEN", "").strip()
    # 显式校验外部注入的 token：只接受足够长的 URL 安全字符，杜绝畸形值透传
    if fixed_token and not re.fullmatch(r"[A-Za-z0-9_-]{16,}", fixed_token):
        raise SystemExit("PELICA_GATEWAY_TOKEN 非法：需 16 位以上字母/数字/下划线/连字符")
    app = create_app(data_dir, token=fixed_token or None)
    token = app.state.token
    port = int(os.environ.get("PELICA_GATEWAY_PORT", "0") or 0)

    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    deadline = _time.time() + 15
    bound_port = 0
    while _time.time() < deadline:
        for srv in getattr(server, "servers", None) or []:
            sockets = getattr(srv, "sockets", None) or []
            if sockets:
                bound_port = sockets[0].getsockname()[1]
                break
        if bound_port:
            break
        _time.sleep(0.1)
    if not bound_port:
        print("PELICA_GATEWAY_FAILED uvicorn 未在 15s 内就绪", flush=True)
        return 1
    print("PELICA_GATEWAY_READY " + _json.dumps(
        {"port": bound_port, "token": token}), flush=True)
    # token 同时落盘一份（数据目录在 %APPDATA% 下，仅本用户可读）
    try:
        (data_dir / "gateway.token").write_text(token, encoding="utf-8")
    except OSError:
        pass
    try:
        t.join()
    except KeyboardInterrupt:
        pass
    return 0


def _core() -> int:
    from gateway.core_runner import run_core

    return run_core()


def _tool(args: list[str]) -> int:
    tool = args[0] if args else ""
    if tool == "build-db":
        from gateway.core_runner import run_tool_build_db

        return run_tool_build_db(args[1:])
    if tool == "selftest":
        return _selftest()
    print("未知工具：%s" % tool, file=sys.stderr)
    return 2


def _selftest() -> int:
    """纯净环境验证：导入全部重依赖并检查关键数据文件就位。"""
    import importlib

    from gateway.paths import bundled_root

    modules = [
        "fastapi", "uvicorn", "pydantic", "requests", "dotenv", "jieba",
        "cv2", "curl_cffi", "zoneinfo", "anyio",
        "pelica.config", "pelica.character", "pelica.db", "pelica.pipeline.router",
        "pelica.llm.client", "pelica.llm.answer", "pelica.llm.persona",
        "pelica.retrieval.retriever", "pelica.graph.matcher",
        "pelica.graph.walker", "pelica.douyin.parser", "pelica.douyin.pipeline",
        "pelica.bilibili.parser", "pelica.bridge.mock_bridge",
        "pelica.stats.weekly", "pelica.social", "gateway.app", "gateway.sandbox",
    ]
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {exc}")
    root = bundled_root()
    for asset in ("main.py", "characters/pelica.toml", "characters/pelica.persona.md"):
        if not (root / asset).exists():
            failed.append(f"missing asset: {asset}")
    if failed:
        print("SELFTEST_FAILED")
        for line in failed:
            print("  " + line)
        return 1
    print("SELFTEST_OK %d modules + assets" % len(modules))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--core":
        return _core()
    if argv and argv[0] == "--tool":
        return _tool(argv[1:])
    return _gateway()


if __name__ == "__main__":
    raise SystemExit(main())
