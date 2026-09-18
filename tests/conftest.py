"""测试夹具：合成小语料 + 临时数据库。

合成语料内容为手工构造的确定性数据（仅用于测试，不是真实运行数据），
结构遵循 PRTS-Terrachive release 格式。
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.db import Database  # noqa: E402


def _doc(doc_id: str, title: str, **extra) -> dict:
    base = {
        "activity_id": "", "activity_name": "", "char_id": "", "character_name": "",
        "collection_id": "", "display_title": title, "document_category": "",
        "document_id": doc_id, "document_kind": "", "document_type": "",
        "line_count": 0, "next_document_id": "", "part_label": "", "part_type": "body",
        "path": f"{doc_id}.txt", "previous_document_id": "", "sequence_confidence": "",
        "sequence_index": 0, "sequence_source": "", "source_path": "",
        "source_ref_prefix": doc_id, "source_sha256": "", "source_story_id": "",
        "story_code": "", "story_name": "", "text_sha256": "",
    }
    base.update(extra)
    return base


def _occ(entity_id: str, name: str, evidence: str = "text_mention",
         canonical: str | None = None) -> dict:
    return {
        "entity_id": entity_id,
        "canonical_name": canonical or name,
        "entity_type": "测试实体",
        "evidence_kind": evidence,
        "presence_status": "explicit" if evidence != "text_mention" else "mentioned",
        "confidence": 1.0,
        "raw_name": name,
        "occurrence_id": f"occ-{entity_id}-{evidence}",
        "ambiguity_candidates": [],
    }


@pytest.fixture
def release_dir(tmp_path: Path) -> Path:
    """构造一个 mini release：1 个 pack、2 个 shard、4 篇文档。"""
    release = tmp_path / "releases" / "mini-corpus-v1"
    pack = release / "official_game"
    (pack / "catalog").mkdir(parents=True)
    (pack / "shards").mkdir(parents=True)

    # shard0：阿米娅档案 + 一段带说话人的剧情（阿米娅提到 凯尔希）
    shard0 = [
        {
            "document": _doc("character:amy:archives", "阿米娅 / 干员档案",
                             char_id="char_amy", character_name="阿米娅",
                             document_category="干员档案", document_kind="character_material"),
            "lines": [
                {"line_number": 1, "line_type": "narration", "speaker_raw": "",
                 "text": "阿米娅是罗德岛的公开领导人，同时是喀兰贸易的象征。",
                 "entity_occurrences": [_occ("e-amy", "阿米娅", "metadata_link"),
                                        _occ("e-kal", "凯尔希", "text_mention")]},
                {"line_number": 2, "line_type": "narration", "speaker_raw": "",
                 "text": "她对抗矿石病，也牵挂着源石技艺感染者。",
                 "entity_occurrences": [_occ("e-amy", "阿米娅", "text_mention")]},
                {"line_number": 3, "line_type": "narration", "speaker_raw": "",
                 "text": "档案记录：阿米娅的源石技艺适应性为sui Generis。",
                 "entity_occurrences": [_occ("e-amy", "阿米娅", "text_mention")]},
            ],
            "speakers": [], "search_index_id": 1, "local_integrity": {}, "record_index": 0,
        },
        {
            "document": _doc("story:test1", "测试剧情 · 第一幕", story_code="TEST",
                             story_name="测试剧情", document_category="剧情"),
            "lines": [
                {"line_number": 1, "line_type": "dialogue", "speaker_raw": "阿米娅",
                 "text": "凯尔希医生说过，罗德岛不能停下。",
                 "entity_occurrences": [_occ("e-kal", "凯尔希", "text_mention"),
                                        _occ("e-amy", "阿米娅", "scene_actor")]},
                {"line_number": 2, "line_type": "dialogue", "speaker_raw": "凯尔希",
                 "text": "阿米娅，你需要了解更多关于源石技艺的代价。",
                 "entity_occurrences": [_occ("e-amy", "阿米娅", "text_mention")]},
            ],
            "speakers": ["阿米娅", "凯尔希"], "search_index_id": 2, "local_integrity": {},
            "record_index": 1,
        },
    ]

    # shard1：语音 + 独立文档（制造 cooccur / 跨文档关联）
    shard1 = [
        {
            "document": _doc("character:amy:voices", "阿米娅 / 角色语音",
                             char_id="char_amy", character_name="阿米娅",
                             document_category="角色语音"),
            "lines": [
                {"line_number": 1, "line_type": "voice", "speaker_raw": "阿米娅",
                 "text": "为了让这片大地挣脱矿石病的阴霾，我们会一直努力下去。",
                 "entity_occurrences": [_occ("e-amy", "阿米娅", "speaker"),
                                        _occ("e-disease", "矿石病", "text_mention")]},
                {"line_number": 2, "line_type": "voice", "speaker_raw": "阿米娅",
                 "text": "凯尔希向我保证过，博士一定会回来的。",
                 "entity_occurrences": [_occ("e-kal", "凯尔希", "text_mention"),
                                        _occ("e-doctor", "博士", "text_mention")]},
            ],
            "speakers": ["阿米娅"], "search_index_id": 3, "local_integrity": {},
            "record_index": 0,
        },
        {
            "document": _doc("knowledge:ori", "源石技艺 · 名词解释",
                             document_category="名词解释"),
            "lines": [
                {"line_number": 1, "line_type": "narration", "speaker_raw": "",
                 "text": "源石技艺是以源石为基础的术式，使用者会承受相应的代价。",
                 "entity_occurrences": [_occ("e-originium", "源石", "metadata_link")]},
            ],
            "speakers": [], "search_index_id": 4, "local_integrity": {}, "record_index": 1,
        },
    ]

    catalog_entries = []
    for name, records in (("00000", shard0), ("00001", shard1)):
        with gzip.open(pack / "shards" / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for i, rec in enumerate(records):
            catalog_entries.append({
                "document": rec["document"], "record_index": i,
                "search_index_id": i, "shard_path": f"shards/{name}.jsonl.gz",
                "speakers": rec["speakers"],
            })
    # catalog 一次性写入（包含全部分片的条目）
    with gzip.open(pack / "catalog" / "documents.jsonl.gz", "wt", encoding="utf-8") as f:
        for entry in catalog_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    manifest = {
        "corpus_version": "mini-version-0001",
        "packs": [{"pack_id": "official_game"}],
    }
    (release / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return release


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def ingested_db(db: Database, release_dir: Path) -> Database:
    from pelica.corpus.ingester import ingest_release
    from pelica.graph.builder import build_relations

    ingest_release(db, release_dir, force=True)
    build_relations(db)
    return db
