"""回答编排：检索证据 -> 组装消息 -> DeepSeek 生成 -> 人设清洗。

消息结构说明（利用 DeepSeek Context Cache）：
  messages[0] 是固定不变的人设 system 提示词——所有请求共享同一前缀，
  服务端会缓存这部分 KV，长对话成本低、首字延迟也低。
  证据与问题放在后续 user 消息里，逐条变化。
"""

from __future__ import annotations

import logging

from pelica.llm.client import DeepSeekClient, LLMError
from pelica.llm import persona
from pelica.retrieval.retriever import Evidence, Retriever, Snippet

log = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 220


def _now_hint() -> str:
    """当前时段（本机时区）。告诉模型现在几点，免得它自己脑补「这么晚」。"""
    from datetime import datetime

    now = datetime.now().astimezone()
    h = now.hour
    if 5 <= h < 8:
        seg = "清晨"
    elif h < 11:
        seg = "上午"
    elif h < 13:
        seg = "中午"
    elif h < 18:
        seg = "下午"
    elif h < 23:
        seg = "晚上"
    else:
        seg = "深夜"
    return (f"【现在】{seg} {h} 点多。这只是帮你理解语境的背景信息："
            "对方不提时间、作息，你就绝不要主动提。")


def build_evidence_block(evidence: Evidence) -> str:
    lines = []
    for i, s in enumerate(evidence.snippets, 1):
        who = f"{s.speaker}：" if s.speaker else ""
        text = s.text if len(s.text) <= MAX_SNIPPET_CHARS else s.text[:MAX_SNIPPET_CHARS] + "……"
        lines.append(f"{i}. {s.citation}（{persona.source_phrase(s.title)}）")
        lines.append(f"   {who}{text}")
        if s.before and len(s.before) <= 80:
            lines.append(f"   （前一句：{s.before}）")
    block = "\n".join(lines)
    if evidence.graph_paths:
        block += "\n相关线索：这些篇章通过共同提到的角色互相关联：" + "；".join(
            evidence.graph_paths[:3]
        )
    return block


def _history_messages(history) -> list[dict]:
    """把 (question, answer) 轮次转成 messages。放在固定人设之后、当前问题之前。"""
    msgs: list[dict] = []
    for q, a in history or []:
        msgs.append({"role": "user", "content": f"【刚才管理员问】{q}"})
        msgs.append({"role": "assistant", "content": a})
    return msgs


class Answerer:
    def __init__(self, client: DeepSeekClient, retriever: Retriever):
        self._client = client
        self._retriever = retriever

    def retrieve(self, question: str) -> Evidence:
        return self._retriever.retrieve(question)

    def ask_llm(self, question: str, evidence: Evidence, history=None,
                social: str = "") -> str:
        evidence_block = build_evidence_block(evidence)
        user_content = (
            f"【群里的管理员问你】\n{question}\n\n"
            f"【可以参考的资料】\n{evidence_block}\n"
        )
        if social:
            user_content += f"\n【这个群和这位管理员的近况】\n{social}\n"
        user_content += (
            "\n用佩丽卡的口吻回答。资料往往来自不同篇章：回答尽量综合多个侧面"
            "（经历、关系、名场面、她自己的感受），不要只围着排最前的那一条打转；"
            "资料里没有的，就按人设说不清楚。"
            f"\n{_now_hint()}"
        )
        messages = (
            [{"role": "system", "content": persona.PERSONA_SYSTEM}]
            + _history_messages(history)
            + [{"role": "user", "content": user_content}]
        )
        return self._client.chat(messages)

    def ask_followup(self, question: str, history, social: str = "") -> str:
        """追问且本轮没查到资料：纯靠最近几轮上下文接话，接不住就说不知道。"""
        user_content = (
            f"【管理员接着刚才的话，说了一句】\n{question}\n\n"
            "这一句没有查到新资料。如果能顺着上面聊过的内容自然接话，就简短接一句；"
            "接不上就按你的规矩坦白说不清楚。"
        )
        if social:
            user_content += f"\n\n【这个群和这位管理员的近况】\n{social}"
        user_content += f"\n{_now_hint()}"
        messages = (
            [{"role": "system", "content": persona.PERSONA_SYSTEM}]
            + _history_messages(history)
            + [{"role": "user", "content": user_content}]
        )
        return self._client.chat(messages)

    def ask_freeform(self, question: str, history=None, social: str = "") -> str:
        """日常闲聊/情感/观点：不查语料，以佩丽卡身份直接回答。

        防编造约束仍在：如果对方实际问的是剧情设定，要说不知道而不是现编。
        """
        user_content = f"【群里的管理员对你说】\n{question}\n"
        if social:
            user_content += f"\n【这个群和这位管理员的近况】\n{social}\n"
        user_content += (
            "\n这句话不需要查任何记录。以佩丽卡的身份直接回应：说你的感受、"
            "态度或日常，可以自然用到上面的近况。但如果对方其实是在问剧情或"
            "设定的具体事实，那就坦白说你不清楚，绝不现编设定。"
            f"\n{_now_hint()}"
        )
        messages = (
            [{"role": "system", "content": persona.PERSONA_SYSTEM}]
            + _history_messages(history)
            + [{"role": "user", "content": user_content}]
        )
        return self._client.chat(messages)

    def answer(self, question: str, history=None, social: str = "") -> tuple[str, Evidence]:
        """返回 (回复文本, 证据)。

        - 有证据：历史 + 证据 + 群近况一起生成；
        - 没证据且是社交/日常话题：自由对话（人设直答，零语料引用）；
        - 没证据但有历史：追问模式，纯上下文续聊（不编造新事实）；
        - 剧情话题但没证据：人设兜底「不知道」，绝不现编。

        指代消解：短追问（那/它/她…）把上一条问题并入检索，让
        「那她的摩托车呢」能继承「佩丽卡为什么会骑摩托车」的上下文。
        """
        history = list(history or [])

        retrieval_query = question
        if history and len(question) <= 24:
            if any(p in question for p in ("那", "它", "她", "他", "呢")):
                retrieval_query = f"{question} {history[-1][0]}"

        evidence = self.retrieve(retrieval_query)

        # 对具体角色的看法/喜好（「你喜欢庄方宜吗」）：不算纯社交闲聊——
        # 有实体证据就放行走检索路径。否则会掉进自由对话只能复述历史，
        # 两次问同一个角色得到雷同回答。
        if (not evidence.covered and evidence.entity_names
                and evidence.snippets and persona.looks_like_social(question)):
            evidence.covered = True
            evidence.reason += "；观点类问题放宽守门"

        if not evidence.covered:
            # 社交/日常话题（没碰到语料实体，或明确带社交信号）-> 自由对话
            social_chat = (not evidence.entity_names) or persona.looks_like_social(question)
            if social_chat:
                try:
                    raw = self.ask_freeform(question, history, social)
                except LLMError as exc:
                    log.error("LLM 不可用：%s", exc)
                    return ("……抱歉管理员，我这会儿有点走神，等下再问你一次好不好？",
                            evidence)
                cleaned = persona.sanitize_reply(raw)
                if cleaned is not None:
                    return cleaned, evidence
                log.warning("自由对话回复含机器腔，改用兜底话术")
            elif history:
                try:
                    raw = self.ask_followup(question, history, social)
                except LLMError as exc:
                    log.error("LLM 不可用：%s", exc)
                    return ("……抱歉管理员，我这会儿有点走神，等下再问你一次好不好？",
                            evidence)
                cleaned = persona.sanitize_reply(raw)
                if cleaned is not None:
                    return cleaned, evidence
                log.warning("追问回复含机器腔，改用兜底话术")
            return persona.pick(persona.REPLY_NOT_SURE), evidence

        last_err: Exception | None = None
        for _ in range(2):  # 机器腔清洗失败时重试一次
            try:
                raw = self.ask_llm(question, evidence, history, social)
            except LLMError as exc:
                last_err = exc
                break
            cleaned = persona.sanitize_reply(raw)
            if cleaned is not None:
                return cleaned, evidence
            log.warning("回复含机器腔，重试：%s", raw[:80])
        if last_err is not None:
            log.error("LLM 不可用：%s", last_err)
            return "……抱歉管理员，我这会儿有点走神，等下再问你一次好不好？", evidence
        return persona.pick(persona.REPLY_NOT_SURE), evidence
