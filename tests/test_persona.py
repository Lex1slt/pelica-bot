"""人设与回复清洗测试（防机器腔是硬性验收项）。"""

from __future__ import annotations

from pelica.llm import persona
from pelica.llm.answer import Answerer
from pelica.retrieval.retriever import Evidence


def test_sanitize_strips_markdown():
    raw = "## 标题\n**加粗内容**\n- 列表项\n[链接](http://x.com)"
    out = persona.sanitize_reply(raw)
    assert out is not None
    assert "#" not in out and "**" not in out and "](http" not in out


def test_sanitize_blocks_ai_speak():
    for bad in [
        "作为一个AI，我认为",
        "我是AI助手佩丽卡",
        "根据我的语料库显示",
        "正在检索中，请稍候",
        "我是语言模型，无法…",
        "As an AI assistant...",
    ]:
        assert persona.sanitize_reply(bad) is None, f"应拦截：{bad}"


def test_sanitize_truncates_long():
    long_text = "这是一段测试。" * 200
    out = persona.sanitize_reply(long_text)
    assert out is not None and len(out) < 500 and out.endswith(("。", "……"))


def test_identity_detection():
    assert persona.looks_like_identity_question("你是真人吗")
    assert persona.looks_like_identity_question("你是AI吗")
    assert not persona.looks_like_identity_question("今天吃什么")


def test_chase_detection():
    assert persona.looks_like_chase("别装了，承认吧")
    assert not persona.looks_like_chase("佩丽卡好可爱")


def test_source_phrases():
    assert persona.source_phrase("阿米娅 / 干员密录") == "密录里写过"
    assert persona.source_phrase("阿米娅 / 干员档案") == "档案里有"
    assert persona.source_phrase("佩丽卡 / 角色语音") == "语音里提过"


def _stub_evidence(covered: bool) -> Evidence:
    return Evidence(question="q", covered=covered)


class _StubClient:
    def chat(self, messages, **kw):
        # 返回带机器腔的内容，验证清洗/兜底路径
        return "作为AI，我认为答案是……"


class _StubRetriever:
    def retrieve(self, question):
        return _stub_evidence(False)


def test_answer_uncovered_uses_persona_fallback():
    ans = Answerer(_StubClient(), _StubRetriever())  # type: ignore[arg-type]
    reply, ev = ans.answer("完全不知道的问题")
    assert ev.covered is False
    assert persona.find_forbidden(reply) == []


def test_answer_llm_failure_graceful():
    class _BoomRetriever:
        def retrieve(self, question):
            from pelica.retrieval.retriever import Snippet

            s = Snippet(doc_id="d", title="《t》", category="", game="", story_name="",
                        activity_name="", line_number=1, line_type="", speaker="",
                        text="阿米娅是罗德岛领导人这份档案里写过", score=5.0)
            ev = Evidence(question="阿米娅是谁", covered=True, snippets=[s])
            return ev

    class _BoomClient:
        def chat(self, messages, **kw):
            from pelica.llm.client import LLMError

            raise LLMError("network down")

    ans = Answerer(_BoomClient(), _BoomRetriever())  # type: ignore[arg-type]
    reply, _ = ans.answer("阿米娅是谁")
    assert reply  # 拿到兜底话术而不是异常
    assert persona.find_forbidden(reply) == []
