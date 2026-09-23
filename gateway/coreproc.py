"""Core（main.py）子进程管理：env 注入、启停、stdout→日志流。

架构铁律：壳零直接文件访问；网关是唯一配置出口。Core 每次启动都拿到
config.db 的有效配置全量注入（显式覆盖所有键，.env 不再有机会漏进来）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from gateway import __version__
from gateway.characters import load_pack, persona_dir
from gateway.configdb import ConfigDB
from gateway.logs import LogHub
from gateway.paths import REPO_ROOT, is_frozen
from gateway.redact import register_secret

# Settings 字段名 → Core env 键（全部显式注入，空值也注入以屏蔽 .env）
_FLAG_ENV = {
    "douyin": "DOUYIN_ENABLED",
    "bilibili": "BILIBILI_ENABLED",
    "weekly_report": "WEEKLY_REPORT_ENABLED",
    "greeting": "GREETING_ENABLED",
}


def active_character(db: ConfigDB, data_dir: Path) -> dict:
    cid = db.get_setting("character.active", "pelica")
    d = persona_dir(data_dir)
    if not d.is_dir():
        return {}
    for toml_path in sorted(d.glob("*.toml")):
        if toml_path.stem == cid:
            return load_pack(toml_path)
    return {}


def build_core_env(db: ConfigDB, data_dir: Path) -> dict[str, str]:
    eff = db.effective_settings()
    key = db.provider_key()
    if key:
        register_secret(key)

    flags = {k: v for k, v in eff.items() if k.startswith("flag.")}
    character_id = eff.get("character.active", "pelica")
    pack = active_character(db, data_dir)
    char = pack.get("character") or {}
    aliases = char.get("at_aliases") or ["佩丽卡监督", "佩丽卡", "Pelica"]

    def _flag(name: str, default: bool = True) -> str:
        value = flags.get("flag." + name, default)
        return "true" if value else "false"

    env: dict[str, str] = {
        # LLM
        "DEEPSEEK_API_KEY": key,
        "DEEPSEEK_BASE_URL": eff.get("provider.base_url",
                                     "https://api.deepseek.com/v1"),
        "DEEPSEEK_MODEL": eff.get("provider.model", "deepseek-flash"),
        "DEEPSEEK_REASONING_EFFORT": str(eff.get("llm.reasoning_effort", "high")),
        "LLM_TEMPERATURE": str(eff.get("llm.temperature", 1.1)),
        "LLM_MAX_TOKENS": str(eff.get("llm.max_tokens", 600)),
        # 桥接
        "BRIDGE_MODE": str(eff.get("bridge.mode", "mock")),
        "WECHATY_TOKEN": "",
        "BOT_WXID": str(eff.get("bridge.bot_wxid", "")),
        "WXHOOK_API_URL": str(eff.get("bridge.wxhook_url",
                                      "http://127.0.0.1:30001")),
        # 白名单（群空 = 全放行；私聊空 = 私聊关闭——继承现有语义）
        "GROUP_WHITELIST": ",".join(db.group_whitelist()),
        "PRIVATE_WHITELIST": ",".join(db.private_whitelist()),
        "AT_ALIASES": ",".join(str(a) for a in aliases),
        # 路径（Core 只认数据目录，绝不写安装目录）
        "CORPUS_DIR": str(_corpus_dir(data_dir)),
        "DATA_DIR": str(data_dir),
        "LOG_DIR": str(data_dir / "logs"),
        "DOUYIN_DOWNLOAD_DIR": str(data_dir / "douyin"),
        # 功能开关
        "DOUYIN_ENABLED": _flag("douyin"),
        "BILIBILI_ENABLED": _flag("bilibili"),
        "WEEKLY_REPORT_ENABLED": _flag("weekly_report"),
        "GREETING_ENABLED": _flag("greeting"),
        # 调度
        "TIMEZONE": str(eff.get("schedule.timezone", "Asia/Shanghai")),
        "WEEKLY_REPORT_WEEKDAY": str(eff.get("schedule.weekly_weekday", "fri")),
        "WEEKLY_REPORT_TIME": str(eff.get("schedule.weekly_time", "18:00")),
        "GREETING_MORNING_TIME": str(eff.get("schedule.greeting_morning", "07:30")),
        "GREETING_NIGHT_TIME": str(eff.get("schedule.greeting_night", "23:00")),
        "GREETING_ACTIVE_DAYS": str(eff.get("schedule.greeting_days", 3)),
        "DOUYIN_KEEP_HOURS": str(eff.get("douyin.keep_hours", 48)),
        "DOUYIN_RESOLVER_API": str(eff.get("douyin.resolver_api", "")),
        # 告警 / 日志 / 角色
        "ALERT_KIND": str(eff.get("alert.kind", "none")),
        "ALERT_WEBHOOK_URL": str(eff.get("alert.webhook_url", "")),
        "ALERT_FAILURE_THRESHOLD": str(eff.get("alert.failure_threshold", 3)),
        "LOG_LEVEL": str(eff.get("log.level", "INFO")),
        "CHARACTER": character_id,
    }
    return env


def _corpus_dir(data_dir: Path) -> Path:
    if not is_frozen() and (REPO_ROOT / "corpus" / "releases").is_dir():
        return REPO_ROOT / "corpus" / "releases"
    return data_dir / "corpus" / "releases"


def _core_command() -> list[str]:
    if is_frozen():
        return [sys.executable, "--core"]
    return [sys.executable, "-m", "gateway.core_runner"]


class CoreProcess:
    """单实例 Core 子进程。所有方法线程安全（内部锁）。"""

    def __init__(self, db: ConfigDB, data_dir: Path, hub: LogHub):
        self._db = db
        self._data_dir = data_dir
        self._hub = hub
        self._lock = threading.RLock()  # status() 会在持锁路径内被调用
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._readers: list[threading.Thread] = []

    # -- 状态 -----------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            proc = self._proc
            running = proc is not None and proc.poll() is None
            return {
                "running": running,
                "pid": proc.pid if running else None,
                "started_at": (time.strftime("%Y-%m-%dT%H:%M:%S",
                                             time.localtime(self._started_at))
                               if running else None),
                "uptime_s": int(time.time() - self._started_at)
                            if running and self._started_at else 0,
            }

    # -- 生命周期 ------------------------------------------------------------

    def start(self, actor: str = "ui") -> dict:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self.status()
            env = build_core_env(self._db, self._data_dir)
            full_env = {k: v for k, v in os.environ.items()
                        if not k.startswith("PELICA_")}
            full_env.update(env)
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            self._proc = subprocess.Popen(
                _core_command(),
                cwd=str(REPO_ROOT) if not is_frozen() else None,
                env=full_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                text=True, encoding="utf-8", errors="replace",
            )
            self._started_at = time.time()
            pid = self._proc.pid
            stdout = self._proc.stdout
            self._readers = [
                threading.Thread(target=self._pump, args=(stdout,),
                                 daemon=True, name="core-stdout"),
            ]
            for t in self._readers:
                t.start()
        self._hub.emit("gateway", "INFO",
                       "Core 已启动 pid=%s bridge=%s character=%s"
                       % (pid, env["BRIDGE_MODE"], env["CHARACTER"]))
        return self.status()

    def stop(self, actor: str = "ui", timeout: float = 10.0) -> dict:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                return self.status()
            proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        with self._lock:
            self._proc = None
        self._hub.emit("gateway", "INFO", "Core 已停止")
        return self.status()

    def restart(self, actor: str = "ui") -> dict:
        self.stop(actor=actor)
        time.sleep(0.5)
        return self.start(actor=actor)

    def _pump(self, stream) -> None:
        try:
            for line in stream:
                line = line.rstrip("\r\n")
                if line:
                    self._hub.emit("core", "INFO", line)
        except (OSError, ValueError):
            pass
