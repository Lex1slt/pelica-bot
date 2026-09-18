"""Pelica Agent —— 让 LLM 带着工具自主检索语料、理解剧情后作答。

架构（现代 agentic RAG）：
- 系统提示词 = 佩丽卡人格文档（内化的角色知识，非规则堆砌）
- 工具：search_lore（语料混合检索）/ read_document（读文档片段）/
  get_group_brief（群近况）
- 循环：LLM 自主决定查什么、读什么，直到给出最终回答
- 预算：最多 max_rounds 轮工具调用；超时交给兜底

与其他模块的关系：
- Retriever 保留，作为 search_lore 工具的后端（第一轮候选召回）
- SessionTable 轮询（wxhook_bridge）不变
- 旧的 Answerer/QACache 停用（对话不再缓存，回复即席生成）
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    max_rounds: int = 8
    search_top_k: int = 6
    passage_context_lines: int = 2
    tool_timeout: float = 20.0


TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "search_lore",
            "description": (
                "在明日方舟/终末地语料库中检索。返回最相关的剧情段落（含出处"
                "《篇章》第 N 行）。适用于：查剧情、角色、组织、地名、事件、"
                "设定、因果。query 用具体的关键词组合。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，例如「帝江号 来源」或「佩丽卡 摩托」"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entity",
            "description": (
                "按实体名精确检索语料中提到该实体的段落。适合按角色名/组织名"
                "查所有相关剧情。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "实体名，如「陈千语」"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_brief",
            "description": "获取本微信群的近况：活跃成员、近期话题、群友印象。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SYSTEM_TMPL = """{persona}

# 你此刻的工作方式

你在一个微信群聊里。有人对说话，你需要给出符合佩丽卡身份的回应。

你可以使用工具：
- search_lore(query)：在语料库中检索剧情段落。涉及剧情/设定/角色/地点/事件的问题，先检索再回答。
- search_entity(name)：按实体名检索相关段落。
- get_group_brief()：获取本群近况概览（谁在群里、最近聊了什么）。

工作规则：
1. 闲聊、问候、情绪交流：不需要检索，直接以佩丽卡身份回应。
2. 剧情/设定问题：先 search_lore 或 search_entity 检索，读到相关段落再回答。
   引用出处口语化：「密录里写过」「档案里有」——不要报行号，不要说「根据检索」。
3. 检索不到可靠依据：坦白说你不清楚，每次措辞可以不同。
4. 回答用佩丽卡的口吻：短句、克制、温柔。多数回复一两句话；内容确实多时用
   换行分段（系统会拆成多条消息连发）。
5. 群友可以称作「管理员」——但记住每个人是独立的个体，别张冠李戴。
6. 绝不：说自己是 AI/模型/检索系统；编造语料中不存在的剧情；输出 markdown。
"""


@dataclass
class ToolResult:
    name: str
    payload: Any


class PelicaAgent:
    """把 DeepSeek 变成带着语料检索工具的佩丽卡。"""

    def __init__(
        self,
        client,                     # DeepSeekClient（需支持 chat_with_tools）
        retriever,                  # Retriever
        social,                     # SocialMemory（可为 None）
        db,                         # Database（群消息查询）
        persona_doc: str,
        config: AgentConfig | None = None,
    ):
        self._client = client
        self._retriever = retriever
        self._social = social
        self._db = db
        self._persona_doc = persona_doc
        self._config = config or AgentConfig()

    # ---- 工具实现 ---------------------------------------------------------

    def _tool_search_lore(self, query: str) -> str:
        ev = self._retriever.retrieve(query)
        if not ev.snippets:
            return "（语料库中没有找到相关段落）"
        lines = []
        for s in ev.snippets[: self._config.search_top_k]:
            who = f"（{s.speaker}）" if s.speaker else ""
            ctx = f"\n   上文：{s.before[:60]}" if s.before else ""
            lines.append(f"《{s.title}》第 {s.line_number} 行{who}：{s.text[:200]}{ctx}")
        return "\n".join(lines)

    def _tool_search_entity(self, name: str) -> str:
        ev = self._retriever.retrieve(name)
        if not ev.snippets:
            return f"（语料库中没有找到关于「{name}」的段落）"
        lines = []
        for s in ev.snippets[: self._config.search_top_k]:
            who = f"（{s.speaker}）" if s.speaker else ""
            lines.append(f"《{s.title}》第 {s.line_number} 行{who}：{s.text[:200]}")
        return "\n".join(lines)

    def _tool_group_brief(self, room_id: str, sender_name: str) -> str:
        if not self._social:
            return "（暂无群近况数据）"
        try:
            return self._social.room_context(room_id, sender_name or "", sender_name)
        except Exception:  # noqa: BLE001
            return "（群近况暂不可用）"

    # ---- 工具分发 ---------------------------------------------------------

    def _dispatch(self, name: str, args: dict, room_id: str, sender_name: str) -> str:
        if name == "search_lore":
            return self._tool_search_lore(args.get("query", ""))
        if name == "search_entity":
            return self._tool_search_entity(args.get("name", ""))
        if name == "get_group_brief":
            return self._tool_group_brief(room_id, sender_name)
        return f"（未知工具 {name}）"

    # ---- 主循环 -----------------------------------------------------------

    def run(
        self,
        question: str,
        history: list[tuple[str, str]] | None = None,
        room_id: str = "",
        sender_name: str = "",
    ) -> tuple[list[str], dict]:
        """运行 agent，返回 (气泡消息列表, 调试信息)。"""
        system = SYSTEM_TMPL.format(persona=self._persona_doc)
        messages: list[dict] = [{"role": "system", "content": system}]
        for q, a in (history or [])[-4:]:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})
        messages.append({"role": "user", "content": question})

        tools = list(TOOLS_SPEC)
        debug: dict = {"rounds": 0, "tool_calls": []}

        for _ in range(self._config.max_rounds):
            debug["rounds"] += 1
            resp = self._client.chat_with_tools(messages, tools, room_id=room_id)
            msg = resp.get("choices", [{}])[0].get("message", {})

            calls = msg.get("tool_calls") or []
            if not calls:
                content = (msg.get("content") or "").strip()
                debug["final_content"] = content
                return [content] if content else [], debug

            # 执行工具调用并回填结果
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch(name, args, room_id, sender_name)
                debug.setdefault("tool_log", []).append({"name": name, "args": args})
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""),
                     "content": result}
                )

        return [], debug

    # 兼容旧 Answerer 接口的便捷入口
    def answer_bubbles(
        self,
        question: str,
        history: list[tuple[str, str]] | None = None,
        room_id: str = "",
        sender_name: str = "",
    ) -> list[str]:
        bubbles, _debug = self.run(question, history, room_id, sender_name)
        return bubbles
