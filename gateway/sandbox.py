"""测试沙箱：mock 桥 UI 化（进程内构造 MockBridge + GroupBot，参考 run_mock_chat）。

- 注入当前有效配置（角色包/白名单/LLM），跑真实管道，不碰微信。
- GroupBot 的中间态不外露——按任务书 §10 双轨：GroupBot 取回复，
  Retriever 单独跑一次取证据，提示词按 Answerer 组装规则重建展示。
- 无语料时走自由对话路径，照样有角色化回复（§4.4）。
"""

from __future__ import annotations

import time
from pathlib import Path

from gateway import __version__
from gateway.characters import apply_character_patch, load_pack, persona_dir
from gateway.configdb import ConfigDB
from gateway.coreproc import build_core_env
from gateway.logs import LogHub


def _persona_settings(db: ConfigDB, data_dir: Path, env: dict):
    """按当前有效配置装配 pelica 设置（进程内，不真正起 Core）。"""
    from pelica.config import Settings

    settings = Settings()
    settings.deepseek_api_key = env["DEEPSEEK_API_KEY"]
    settings.deepseek_base_url = env["DEEPSEEK_BASE_URL"]
    settings.deepseek_model = env["DEEPSEEK_MODEL"]
    settings.deepseek_reasoning_effort = env["DEEPSEEK_REASONING_EFFORT"]
    settings.llm_temperature = float(env["LLM_TEMPERATURE"])
    settings.llm_max_tokens = int(env["LLM_MAX_TOKENS"])
    settings.bridge_mode = "mock"
    settings.at_aliases = [a for a in env["AT_ALIASES"].split(",") if a]
    settings.data_dir = data_dir
    settings.log_dir = data_dir / "logs"
    settings.character = env["CHARACTER"]
    return settings


def _resolve_character_db(data_dir: Path, character_id: str) -> Path | None:
    d = persona_dir(data_dir)
    toml_path = d / (character_id + ".toml")
    if toml_path.exists():
        pack = load_pack(toml_path)
        db_rel = (pack.get("character") or {}).get("db", "")
        if db_rel:
            p = Path(db_rel)
            candidate = p if p.is_absolute() else (data_dir / p)
            if candidate.exists():
                return candidate
    default = data_dir / "pelica.db"
    return default if default.exists() else None


def run_sandbox(db: ConfigDB, data_dir: Path, hub: LogHub,
                text: str, room: str = "沙箱群", sender: str = "管理员",
                is_at: bool = True, private: bool = False,
                timeout_s: float = 60.0) -> dict:
    """跑一条消息过完整管道，返回回复/证据/提示词/耗时。"""
    started = time.time()
    from pelica.bridge.mock_bridge import MockBridge
    from pelica.db import Database
    from pelica.llm.answer import Answerer, build_evidence_block
    from pelica.llm.client import DeepSeekClient, LLMError
    from pelica.llm import persona
    from pelica.pipeline.router import GroupBot
    from pelica.retrieval.cache import QACache
    from pelica.retrieval.retriever import Retriever
    from pelica.graph.matcher import EntityMatcher
    from pelica.graph.walker import GraphWalker

    env = build_core_env(db, data_dir)
    settings = _persona_settings(db, data_dir, env)
    apply_character_patch(data_dir)
    from pelica.character import apply_character
    apply_character(settings)  # 注入人设/别名到 pelica.llm.persona

    scratch_path = data_dir / "sandbox.db"
    scratch = Database(scratch_path)

    character_db_path = _resolve_character_db(data_dir, settings.character)
    corpus_db = Database(character_db_path) if character_db_path else scratch
    retriever = Retriever(corpus_db, EntityMatcher(corpus_db), GraphWalker(corpus_db))

    if settings.deepseek_api_key:
        client = DeepSeekClient(
            settings.deepseek_api_key, settings.deepseek_base_url,
            settings.deepseek_model, temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            reasoning_effort=settings.deepseek_reasoning_effort,
            timeout=45.0, retries=1,
        )
    else:
        class _NoKeyClient:
            """无 Key 沙箱：LLM 调用直接抛错，管道走人设兜底（§11 测试口径）。"""

            def chat(self, messages, temperature=None, max_tokens=None):
                raise LLMError("沙箱未配置 API Key")

        client = _NoKeyClient()

    answerer = Answerer(client, retriever)

    bridge = MockBridge(bot_name="佩丽卡", echo=False)
    # mock 房间补 @chatroom 后缀，让 GroupBot 按群聊路径处理（私聊语义留给 private 模式）
    chat_room = room + "@chatroom"
    bot = GroupBot(
        bridge=bridge,
        db=scratch,
        answerer=answerer,
        qa_cache=QACache(scratch),
        douyin=None,
        whitelist=None,  # 群聊沙箱全放行（本地目录，不影响真实白名单）
        at_aliases=settings.at_aliases,
        matcher=EntityMatcher(scratch),
        private_whitelist=[sender] if private else [],
    )
    bot.start()
    bridge.start()
    try:
        bridge.feed(
            text,
            room=chat_room if not private else ("private-" + sender),
            sender=sender,
            is_at=is_at,
            sender_id="sandbox-user",
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if bridge.outbox:
                # 拆条气泡间隔 0.9-1.9s，稍等收齐
                time.sleep(2.5)
                break
            time.sleep(0.15)
        replies = [entry["text"] for entry in bridge.outbox]
    finally:
        bot.stop()
        bridge.stop()
        scratch.close()
        if corpus_db is not scratch:
            corpus_db.close()

    # 双轨：单独跑一次检索取证据 + 重建提示词展示
    question = text
    for alias in sorted(settings.at_aliases, key=len, reverse=True):
        if question.startswith("@" + alias):
            question = question[len(alias) + 1:]
            break
        if question.startswith(alias):
            question = question[len(alias):]
            break
    question = question.strip(" ，,。：:！!？?")
    evidence = retriever.retrieve(question) if question else None
    snippets = []
    if evidence is not None:
        for s in evidence.snippets[:5]:
            snippets.append({
                "title": s.title, "citation": s.citation, "speaker": s.speaker,
                "text": s.text[:300], "category": s.category,
            })
    evidence_block = build_evidence_block(evidence) if evidence is not None else ""
    system_prompt = persona.PERSONA_SYSTEM
    if evidence_block:
        user_prompt = ("【群里的管理员问你】\n" + question + "\n\n"
                       "【可以参考的资料】\n" + evidence_block + "\n")
    else:
        user_prompt = "【群里的管理员对你说】\n" + question + "\n"

    elapsed = time.time() - started
    hub.emit("sandbox", "INFO",
             "沙箱执行完成：回复 %d 条，证据 %d 条，耗时 %.1fs"
             % (len(replies), len(snippets), elapsed))
    return {
        "replies": replies,
        "evidence": snippets,
        "evidence_covered": bool(evidence.covered) if evidence else False,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "question": question,
        "corpus_db": str(character_db_path) if character_db_path else "",
        "character": settings.character,
        "llm_key_configured": bool(settings.deepseek_api_key),
        "elapsed_s": round(elapsed, 2),
        "gateway_version": __version__,
    }
