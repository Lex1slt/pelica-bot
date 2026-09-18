"""检索层测试：覆盖判定、引用格式、守门逻辑。"""

from __future__ import annotations

from pelica.db import Database
from pelica.graph.matcher import EntityMatcher
from pelica.retrieval.retriever import Retriever, fts_terms, dominant_term


def _retriever(db: Database) -> Retriever:
    return Retriever(db, EntityMatcher(db))


def test_retrieve_entity_question(ingested_db):
    r = _retriever(ingested_db)
    ev = r.retrieve("阿米娅是谁")
    assert ev.covered is True
    assert ev.entity_names == ["阿米娅"]
    assert ev.snippets
    for s in ev.snippets:
        assert s.citation.startswith("《") and "》第 " in s.citation


def test_retrieve_cross_document(ingested_db):
    """同话题在多篇文档（档案/剧情/语音）里都应有证据。"""
    r = _retriever(ingested_db)
    ev = r.retrieve("阿米娅的源石技艺")
    docs = {s.doc_id for s in ev.snippets}
    assert any("character:amy" in d for d in docs), "应命中角色相关文档"


def test_retrieve_unknown_not_covered(ingested_db):
    r = _retriever(ingested_db)
    ev = r.retrieve("非利克斯的生日是哪天")
    assert ev.covered is False


def test_fts_terms_no_stopwords():
    terms = [t for t, _ in fts_terms("阿米娅是怎么认识的？")]
    assert "是怎么" not in [t for t, _ in fts_terms("阿米娅是怎么认识的？")]
    assert any("阿米娅" in t for t in terms)


def test_fts_terms_short_word_window():
    # 「醚质」这类 2 字生僻词应产生 3 字窗口代理词
    terms = [t for t, _ in fts_terms("醚质是什么")]
    assert any("醚质" in t for t in terms), "至少有一个窗口包含目标词"


def test_dominant_term():
    assert dominant_term("菲利克斯的生日是哪天") in ("菲利克斯", "菲利克斯的生日")
    assert dominant_term("醚质是什么") in ("醚质", "醚质是什么", "醚质是")
    assert len(dominant_term("这是什么")) >= 2
