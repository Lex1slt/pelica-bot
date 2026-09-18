"""异常告警：桥接连续失败、LLM 长期不可用时通知管理员。

支持两种 webhook：
- wecom：企业微信群机器人 {"msgtype":"text","text":{"content":"..."}}
- generic：任意接收 {"text": "..."} 的端点
kind=none 时只记 ERROR 日志（默认）。
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, kind: str = "none", webhook_url: str = ""):
        self._kind = kind
        self._url = webhook_url
        self._session = requests.Session()

    def notify(self, title: str, detail: str = "") -> None:
        log.error("[告警] %s %s", title, detail)
        if self._kind == "none" or not self._url:
            return
        content = f"{title}\n{detail}".strip()
        try:
            if self._kind == "wecom":
                payload = {"msgtype": "text", "text": {"content": content}}
            else:
                payload = {"text": content}
            resp = self._session.post(self._url, json=payload, timeout=10)
            if resp.status_code >= 300:
                log.error("告警 webhook 返回 %d", resp.status_code)
        except Exception as exc:  # noqa: BLE001
            log.error("告警发送失败：%s", exc)
