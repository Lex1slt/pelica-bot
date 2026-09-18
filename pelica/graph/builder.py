"""关系表构建：基于已摄入的实体出现数据生成三类关系。

- speaker  说话人 -> 该句话里提到的实体（对话驱动，权重高）
- cooccur  同一篇文档内高权重实体两两共现（跨文档关联的跳板）
- seq      文档接续（document.next_document_id，角色档案等分篇文档的链）

全部写入 relations 表，可重复构建（先清空）。
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path

from pelica.db import Database

log = logging.getLogger(__name__)

MAX_ENTITIES_PER_DOC = 10   # 参与 cooccur 的文档头部实体数
MAX_MENTIONED_PER_LINE = 4  # speaker 关系中每句最多取几个被提及实体
COOCCUR_DECAY = 0.5         # cooccur 权重相对 doc_entities 权重的折扣


def build_relations(db: Database) -> dict:
    t0 = time.time()
    conn = db.conn
    stats = Counter()

    with db.transaction():
        conn.execute("DELETE FROM relations")

        # ---- speaker：说话人实体 -> 句中提到的实体 ----
        # 先收集说话人名，批量反查 entity_id，再流式按 line_id 分组处理（省内存）
        speaker_names = [
            r["speaker"]
            for r in conn.execute("SELECT DISTINCT speaker FROM lines WHERE speaker != ''")
        ]
        name_to_ids: dict[str, list[str]] = {}
        qmarks = lambda n: ",".join("?" * n)  # noqa: E731
        for i in range(0, len(speaker_names), 400):
            chunk = speaker_names[i : i + 400]
            for row in conn.execute(
                f"SELECT alias, entity_id FROM aliases WHERE alias IN ({qmarks(len(chunk))})",
                chunk,
            ):
                name_to_ids.setdefault(row["alias"], []).append(row["entity_id"])

        rel_rows: list[tuple] = []

        def flush_line(line_id: int, speaker: str, occs: list) -> None:
            for spk_id in name_to_ids.get(speaker, [])[:1]:
                mentioned = [
                    o for o in occs
                    if o["entity_id"] != spk_id
                    and o["evidence"] in ("text_mention", "scene_actor")
                ][: MAX_MENTIONED_PER_LINE]
                for o in mentioned:
                    rel_rows.append((spk_id, o["entity_id"], "speaker", 2.0, ""))
                    stats["speaker"] += 1

        current_line = None
        current_speaker = ""
        group: list = []
        cursor = conn.execute(
            """
            SELECT l.line_id, l.speaker, le.entity_id, le.evidence
            FROM lines l JOIN line_entities le ON le.line_id = l.line_id
            WHERE l.speaker != ''
            ORDER BY l.line_id
            """
        )
        for r in cursor:
            if r["line_id"] != current_line:
                if group:
                    flush_line(current_line, current_speaker, group)
                current_line = r["line_id"]
                current_speaker = r["speaker"]
                group = []
            group.append(r)
        if group:
            flush_line(current_line, current_speaker, group)

        # ---- seq：文档接续 ----
        for r in conn.execute(
            "SELECT doc_id, next_doc_id FROM documents WHERE next_doc_id != ''"
        ):
            rel_rows.append((r["doc_id"], r["next_doc_id"], "seq", 1.5, ""))
            stats["seq"] += 1

        conn.executemany(
            "INSERT OR REPLACE INTO relations VALUES (?,?,?,?,?)", rel_rows
        )

        # ---- cooccur：每篇文档头部实体两两共现 ----
        docs = conn.execute(
            """
            SELECT de.doc_id, de.entity_id, de.weight
            FROM doc_entities de
            ORDER BY de.doc_id, de.weight DESC
            """
        )
        current_doc = None
        bucket: list[tuple[str, float]] = []
        cooccur_rows: list[tuple] = []

        def flush_bucket():
            if len(bucket) >= 2:
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        (a, wa), (b, wb) = bucket[i], bucket[j]
                        w = min(wa, wb) * COOCCUR_DECAY
                        cooccur_rows.append((a, b, "cooccur", w, current_doc))
                        stats["cooccur"] += 1

        for row in docs:
            if row["doc_id"] != current_doc:
                flush_bucket()
                bucket = []
                current_doc = row["doc_id"]
            if len(bucket) < MAX_ENTITIES_PER_DOC:
                bucket.append((row["entity_id"], row["weight"]))
        flush_bucket()

        conn.executemany(
            "INSERT OR REPLACE INTO relations VALUES (?,?,?,?,?)", cooccur_rows
        )

    stats["seconds"] = round(time.time() - t0, 1)
    log.info("关系构建完成：%s", dict(stats))
    return dict(stats)
