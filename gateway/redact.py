"""日志/输出脱敏：任何落盘、推送、返回给前端的文本先过这里。"""

from __future__ import annotations

import re

# 常见 API Key 形态（OpenAI/DeepSeek/智谱等 sk- 前缀）
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")
# 环境变量形式 KEY=value
_ENV_KEY_RE = re.compile(
    r"((?:API_KEY|TOKEN|SECRET|WEBHOOK)[A-Z_]*\s*=\s*)([^\s,;\"']+)", re.IGNORECASE
)
# Bearer 头
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{6,}", re.IGNORECASE)

_EXTRA_SECRET_VALUES: set[str] = set()


def register_secret(value: str) -> None:
    """注册运行期敏感值（如当前生效 Key），脱敏时一并掩码。"""
    if value and len(value) >= 8:
        _EXTRA_SECRET_VALUES.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    out = _KEY_RE.sub("sk-****MASKED", text)
    out = _BEARER_RE.sub(r"\1****", out)
    out = _ENV_KEY_RE.sub(r"\1****MASKED", out)
    for secret in _EXTRA_SECRET_VALUES:
        if secret in out:
            out = out.replace(secret, "****MASKED")
    return out


def scan_plaintext_secrets(text: str) -> int:
    """导出前扫描：返回疑似密钥的个数（用于「已自动去除 N 个密钥」提示）。"""
    return len(_KEY_RE.findall(text or ""))
