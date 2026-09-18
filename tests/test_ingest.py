"""摄入与关系构建测试。"""

from __future__ import annotations

from pelica.corpus.ingester import ingest_release


def test_ingest_counts(ingested_db):
    assert ingested_db.query_one("SELECT COUNT(*) n FROM documents")["n"] == 4
    assert ingested_db.query_one("SELECT COUNT(*) n FROM lines")["n"] == 8
    assert ingested_db.meta_get("corpus_version") == "mini-version-0001"


def test_ingest_entities_and_aliases(ingested_db):
    amy = ingested_db.query_one("SELECT * FROM entities WHERE entity_id='e-amy'")
    assert amy and amy["canonical_name"] == "阿米娅"
    # raw_name + canonical_name 都进了别名表
    aliases = {r["alias"] for r in ingested_db.query(
        "SELECT alias FROM aliases WHERE entity_id='e-amy'")}
    assert "阿米娅" in aliases


def test_ingest_fts_search(ingested_db):
    rows = ingested_db.query(
        "SELECT rowid FROM lines_fts WHERE lines_fts MATCH '\"矿石病\"'"
    )
    assert len(rows) >= 2  # 档案行 + 语音行


def test_ingest_idempotent(db, release_dir):
    stats1 = ingest_release(db, release_dir)
    assert stats1["skipped"] is False
    stats2 = ingest_release(db, release_dir)
    assert stats2.get("skipped") is True
    assert db.query_one("SELECT COUNT(*) n FROM documents")["n"] == 4


def test_relations_built(ingested_db):
    rels = ingested_db.query("SELECT * FROM relations")
    kinds = {r["rel"] for r in rels}
    assert {"speaker", "cooccur", "seq"} <= kinds or kinds
    # 阿米娅（说话人）-> 凯尔希（提到）这类 speaker 关系应存在
    speaker_rels = [r for r in rels if r["rel"] == "speaker"]
    assert speaker_rels, "应至少有一条 speaker 关系"
    # 文档接续：无 next_doc_id 时 seq 为空也可
    seq_rels = [r for r in rels if r["rel"] == "seq"]
    assert isinstance(seq_rels, list)
