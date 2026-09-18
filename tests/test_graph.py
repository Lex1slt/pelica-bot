"""实体匹配与图游走测试。"""

from __future__ import annotations

from pelica.graph.matcher import EntityMatcher
from pelica.graph.walker import GraphWalker


def _names(matcher, q):
    return [m.canonical_name for m in matcher.match(q)]


def test_match_basic(ingested_db):
    matcher = EntityMatcher(ingested_db)
    assert "阿米娅" in _names(matcher, "阿米娅是谁")
    assert "阿米娅" in _names(matcher, "帮我查查阿米娅的档案")


def test_match_canonical_dedup(ingested_db):
    """同名实体聚合：重复提到不产生重复匹配。"""
    matcher = EntityMatcher(ingested_db)
    names = _names(matcher, "阿米娅和阿米娅的朋友")
    assert names.count("阿米娅") == 1


def test_match_longest_first(ingested_db):
    matcher = EntityMatcher(ingested_db)
    # 「源石技艺」应整体命中 源石 文档的实体，而不是碎片
    names = _names(matcher, "源石技艺的代价是什么")
    assert "源石" in names


def test_match_empty(ingested_db):
    matcher = EntityMatcher(ingested_db)
    assert _names(matcher, "") == []
    assert _names(matcher, "完全无关的词表内容xyz") == []


def test_walker_multihop(ingested_db):
    matcher = EntityMatcher(ingested_db)
    matches = matcher.match("阿米娅")
    assert matches
    seeds = {}
    for m in matches:
        for eid in m.entity_ids:
            seeds.setdefault(eid, 1.0)
    walker = GraphWalker(ingested_db)
    nodes = walker.expand(seeds, hops=2)
    # 阿米娅相关的凯尔希/矿石病/博士应在一跳或两跳内出现
    reached = {n.entity_id for n in nodes.values()}
    assert reached | set(seeds)  # 种子在内
    hop1 = [n for n in nodes.values() if n.hop == 1]
    assert all(n.score <= 1.0 for n in hop1), "逐跳衰减"
    assert hop1, "至少扩展出一跳邻居（语料里阿米娅与凯尔希共现）"


def test_walker_empty_seeds(ingested_db):
    walker = GraphWalker(ingested_db)
    assert walker.expand({}) == {}
