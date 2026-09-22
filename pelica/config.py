"""集中配置：全部来自 .env / 环境变量，代码不写死密钥、路径、群 ID。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]


@dataclass
class Settings:
    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-flash"
    deepseek_reasoning_effort: str = "high"
    llm_temperature: float = 1.1
    llm_max_tokens: int = 600

    # 桥接
    bridge_mode: str = "mock"  # mock | wechaty
    wechaty_token: str = ""
    bot_wxid: str = ""
    group_whitelist: list[str] = field(default_factory=list)
    private_whitelist: list[str] = field(default_factory=list)  # 空=私聊关闭
    at_aliases: list[str] = field(default_factory=lambda: ["佩丽卡监督", "佩丽卡", "Pelica"])

    # 路径
    corpus_dir: Path = PROJECT_ROOT / "corpus" / "releases"
    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"

    # 抖音
    douyin_enabled: bool = True
    douyin_download_dir: Path = PROJECT_ROOT / "data" / "douyin"
    douyin_resolver_api: str = ""  # 可选：第三方解析服务 {api}?url=<分享链接>
    douyin_keep_hours: int = 48            # 本地视频缓存保留时长（定时清理）

    # B 站
    bilibili_enabled: bool = True

    # 调度
    timezone: str = "Asia/Shanghai"
    weekly_report_enabled: bool = True
    weekly_report_weekday: str = "fri"
    weekly_report_time: str = "18:00"
    greeting_enabled: bool = True
    greeting_morning_time: str = "07:30"
    greeting_night_time: str = "23:00"
    greeting_active_days: int = 3   # 问好目标=最近 N 天有动静的群

    # WeChat-Hook 桥接（wxhook 模式）
    wxhook_api_url: str = "http://127.0.0.1:30001"

    # 告警
    alert_kind: str = "none"  # wecom | generic | none
    alert_webhook_url: str = ""
    alert_failure_threshold: int = 3

    # 日志
    log_level: str = "INFO"

    # 角色包（characters/<id>.toml + .persona.md），由 pelica.character.apply_character 应用
    character: str = "pelica"
    character_pack: dict = None  # type: ignore[assignment]
    _db_override: Path | None = None

    @property
    def db_path(self) -> Path:
        return self._db_override or (self.data_dir / "pelica.db")

    @property
    def wechaty_dir(self) -> Path:
        return PROJECT_ROOT / "bridges" / "wechaty"


def load_settings(env_file: Path | None = ..., environ: dict | None = None) -> Settings:
    """从 .env + 环境变量装配 Settings。environ 参数便于测试注入。

    env_file 用 ...（省略）表示默认项目根 .env；显式传 None 可跳过文件。
    """
    if env_file is ...:
        env_file = PROJECT_ROOT / ".env"
    env = dict(os.environ)
    if env_file is not None and env_file.exists():
        load_dotenv(env_file, override=False)
        env.update(os.environ)
    if environ:
        env.update(environ)

    def get(key: str, default: str = "") -> str:
        value = env.get(key, default).strip()
        return value if value else default

    corpus_dir = Path(get("CORPUS_DIR", "corpus/releases"))
    data_dir = Path(get("DATA_DIR", "data"))
    log_dir = Path(get("LOG_DIR", "logs"))
    if not corpus_dir.is_absolute():
        corpus_dir = PROJECT_ROOT / corpus_dir
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    douyin_dir = Path(get("DOUYIN_DOWNLOAD_DIR", str(data_dir / "douyin")))
    if not douyin_dir.is_absolute():
        douyin_dir = PROJECT_ROOT / douyin_dir

    return Settings(
        deepseek_api_key=get("DEEPSEEK_API_KEY"),
        deepseek_base_url=get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
        deepseek_model=get("DEEPSEEK_MODEL", "deepseek-flash"),
        deepseek_reasoning_effort=get("DEEPSEEK_REASONING_EFFORT", "high"),
        llm_temperature=float(get("LLM_TEMPERATURE", "1.1")),
        llm_max_tokens=int(get("LLM_MAX_TOKENS", "600")),
        bridge_mode=get("BRIDGE_MODE", "mock").lower(),
        wechaty_token=get("WECHATY_TOKEN"),
        bot_wxid=get("BOT_WXID"),
        group_whitelist=_split_csv(get("GROUP_WHITELIST")),
        private_whitelist=_split_csv(get("PRIVATE_WHITELIST")),
        at_aliases=_split_csv(get("AT_ALIASES", "佩丽卡监督,佩丽卡,Pelica")) or ["佩丽卡"],
        corpus_dir=corpus_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        douyin_enabled=get("DOUYIN_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
        douyin_download_dir=douyin_dir,
        douyin_resolver_api=get("DOUYIN_RESOLVER_API"),
        douyin_keep_hours=int(get("DOUYIN_KEEP_HOURS", "48")),
        bilibili_enabled=get("BILIBILI_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
        timezone=get("TIMEZONE", "Asia/Shanghai"),
        weekly_report_enabled=get("WEEKLY_REPORT_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
        weekly_report_weekday=get("WEEKLY_REPORT_WEEKDAY", "fri").lower(),
        weekly_report_time=get("WEEKLY_REPORT_TIME", "18:00"),
        greeting_enabled=get("GREETING_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
        greeting_morning_time=get("GREETING_MORNING_TIME", "07:30"),
        greeting_night_time=get("GREETING_NIGHT_TIME", "23:00"),
        greeting_active_days=int(get("GREETING_ACTIVE_DAYS", "3")),
        wxhook_api_url=get("WXHOOK_API_URL", "http://127.0.0.1:30001"),
        alert_kind=get("ALERT_KIND", "none").lower(),
        alert_webhook_url=get("ALERT_WEBHOOK_URL"),
        alert_failure_threshold=int(get("ALERT_FAILURE_THRESHOLD", "3")),
        log_level=get("LOG_LEVEL", "INFO").upper(),
        character=get("CHARACTER", "pelica").strip() or "pelica",
    )
