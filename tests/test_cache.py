"""QA 缓存测试。"""

from __future__ import annotations

from pelica.db import Database
from pelica.retrieval.cache import QACache, normalize_question, question_hash


def test_cache_roundtrip(db: Database):
    cache = QACache(db)
    cache.put("阿米娅是谁", "阿米娅是罗德岛领导人。", ["《阿米娅 / 干员档案》第 1 行"])
    hit = cache.get("阿米娅是谁")
    assert hit is not None
    answer, citations = hit
    assert "罗德岛" in answer
    assert citations == ["《阿米娅 / 干员档案》第 1 行"]


def test_cache_normalization(db: Database):
    cache = QACache(db)
    cache.put("阿米娅是谁？", "答案", [])
    # 增删空白/标点/@ 应命中同一条
    assert cache.get("阿米娅是谁") is not None
    assert cache.get("  @佩丽卡 阿米娅是谁?  ") is not None


def test_cache_miss(db: Database):
    cache = QACache(db)
    assert cache.get("从没问过的问题") is None


def test_cache_ttl(db: Database, monkeypatch):
    cache = QACache(db, ttl_hours=0.0001)  # ~0.36s
    cache.put("问题", "答案", [])
    assert cache.get("问题") is not None
    time.sleep(0.5)
    assert cache.get("问题") is None


import time  # noqa: E402
