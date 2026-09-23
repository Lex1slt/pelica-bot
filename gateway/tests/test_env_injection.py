"""白名单 env 注入语义：群空 = 全放行、私聊空 = 私聊关闭（继承现有语义）。"""

from __future__ import annotations

from gateway.configdb import ConfigDB
from gateway.coreproc import build_core_env


def _db_with(data_dir, groups, private):
    db = ConfigDB(data_dir / "config.db")
    for g in groups:
        db.create_group(g)
    for u in private:
        db.create_private_user(u)
    return db


def test_group_empty_means_allow_all(data_dir):
    db = _db_with(data_dir, [], [])
    env = build_core_env(db, data_dir)
    assert env["GROUP_WHITELIST"] == ""  # load_settings 解析为 [] = 全放行
    from pelica.config import load_settings

    settings = load_settings(env_file=None, environ=env)
    assert settings.group_whitelist == []


def test_group_active_only(data_dir):
    db = _db_with(data_dir, [
        {"name": "启用群", "wxid": "wxid_on", "status": "active"},
        {"name": "停用群", "wxid": "wxid_off", "status": "paused"},
    ], [])
    env = build_core_env(db, data_dir)
    assert env["GROUP_WHITELIST"] == "wxid_on"
    from pelica.config import load_settings

    settings = load_settings(env_file=None, environ=env)
    assert settings.group_whitelist == ["wxid_on"]
    assert "停用群" not in settings.group_whitelist


def test_private_empty_means_disabled(data_dir):
    db = _db_with(data_dir, [], [])
    env = build_core_env(db, data_dir)
    assert env["PRIVATE_WHITELIST"] == ""
    from pelica.config import load_settings

    settings = load_settings(env_file=None, environ=env)
    assert settings.private_whitelist == []  # 私聊关闭


def test_private_blacklist_excluded(data_dir):
    db = _db_with(data_dir, [], [
        {"nickname": "正常用户", "wxid": "wxid_ok", "mode": "normal"},
        {"nickname": "拉黑用户", "wxid": "wxid_bad", "mode": "normal",
         "blacklisted": 1},
        {"nickname": "关闭用户", "wxid": "wxid_off", "mode": "disabled"},
    ])
    env = build_core_env(db, data_dir)
    assert env["PRIVATE_WHITELIST"] == "wxid_ok"


def test_env_full_coverage(data_dir):
    """所有 Settings 相关键都被显式注入（.env 无机会漏进来）。"""
    keys = {
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "DEEPSEEK_REASONING_EFFORT", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
        "BRIDGE_MODE", "WECHATY_TOKEN", "BOT_WXID", "WXHOOK_API_URL",
        "GROUP_WHITELIST", "PRIVATE_WHITELIST", "AT_ALIASES",
        "CORPUS_DIR", "DATA_DIR", "LOG_DIR", "DOUYIN_DOWNLOAD_DIR",
        "DOUYIN_ENABLED", "BILIBILI_ENABLED", "WEEKLY_REPORT_ENABLED",
        "GREETING_ENABLED", "TIMEZONE", "WEEKLY_REPORT_WEEKDAY",
        "WEEKLY_REPORT_TIME", "GREETING_MORNING_TIME", "GREETING_NIGHT_TIME",
        "GREETING_ACTIVE_DAYS", "DOUYIN_KEEP_HOURS", "DOUYIN_RESOLVER_API",
        "ALERT_KIND", "ALERT_WEBHOOK_URL", "ALERT_FAILURE_THRESHOLD",
        "LOG_LEVEL", "CHARACTER",
    }
    db = _db_with(data_dir, [], [])
    env = build_core_env(db, data_dir)
    missing = keys - set(env)
    assert not missing, f"缺注入: {missing}"
    from pelica.config import load_settings

    settings = load_settings(env_file=None, environ=env)
    assert settings.character == env["CHARACTER"]
    assert settings.bridge_mode == env["BRIDGE_MODE"]
