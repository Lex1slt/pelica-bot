"""DeepSeek 客户端（OpenAI 兼容接口，requests 直连，带重试）。

支持两种调用：
- chat(messages) -> str            普通对话
- chat_with_tools(messages, tools) -> dict   带工具调用的对话（agent 用），
  返回完整的 assistant message 字典
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-flash",
        temperature: float = 1.1,
        max_tokens: int = 600,
        reasoning_effort: str = "high",
        timeout: float = 60.0,
        retries: int = 3,
    ):
        if not api_key:
            raise LLMError("DEEPSEEK_API_KEY 未配置")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._retries = retries
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )

    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        message = self._chat_raw(payload)
        content = message.get("content") or ""
        if not content:
            raise LLMError("空回复")
        return content

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """带工具调用的对话，返回完整的 assistant message 字典
        （含 content 或 tool_calls，供 agent 循环使用）。"""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
            "reasoning_effort": self._reasoning_effort,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return self._chat_raw(payload)

    def _chat_raw(self, payload: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._session.post(
                    f"{self._base_url}/chat/completions", json=payload,
                    timeout=self._timeout,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = 1.5 ** (attempt - 1)
                log.warning("LLM 第 %d 次调用失败: %s，%.1fs 后重试",
                            attempt, exc, wait)
                time.sleep(wait)
        raise LLMError(f"LLM 调用失败（已重试 {self._retries} 次）: {last_exc}")
