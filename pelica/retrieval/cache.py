"""高频问答缓存：命中则完全不调模型。"""

from __future__ import annotations

import hashlib
import json
import re
import time

from pelica.db import Database

DEFAULT_TTL_HOURS = 24 * 7


def normalize_question(q: str) -> str:
    """归一化问题：去 @ 前缀、空白与标点差异，让相似问法命中同一缓存。"""
    q = q.strip().lower()
    q = re.sub(r"@[^\s，。,]+", "", q)  # 去掉 @某某
    q = re.sub(r"[\s，。！？？！、~～@…·,.!??:：;；\"'「」『』（）()\[\]]+", "", q)
    return q


def question_hash(q: str) -> str:
    return hashlib.sha256(normalize_question(q).encode("utf-8")).hexdigest()


class QACache:
    def __init__(self, db: Database, ttl_hours: float = DEFAULT_TTL_HOURS):
        self._db = db
        self._ttl = ttl_hours * 3600

    def get(self, question: str) -> tuple[str, str] | None:
        row = self._db.query_one(
            "SELECT answer, citations, created_at, hits FROM qa_cache WHERE qhash=?",
            (question_hash(question),),
        )
        if row is None:
            return None
        try:
            created = float(row["created_at"])
        except (TypeError, ValueError):
            return None
        if time.time() - created > self._ttl:
            self._db.execute("DELETE FROM qa_cache WHERE qhash=?", (question_hash(question),))
            return None
        self._db.execute(
            "UPDATE qa_cache SET hits=hits+1 WHERE qhash=?", (question_hash(question),)
        )
        try:
            citations = json.loads(row["citations"])
        except (TypeError, ValueError):
            citations = []
        return row["answer"], citations

    def put(self, question: str, answer: str, citations: list[str]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO qa_cache VALUES (?,?,?,?,?,?)",
            (
                question_hash(question),
                question.strip(),
                answer,
                json.dumps(citations, ensure_ascii=False),
                repr(time.time()),
                0,
            ),
        )
