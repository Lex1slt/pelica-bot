"""SQLite 持久化：语料库、轻量图谱、消息记录、QA 缓存的统一存储层。

所有连接使用 WAL 模式，check_same_thread=False + 内部串行锁，
供桥接线程 / 调度线程 / 主线程共享。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 文档（一篇 = 语料里一个 document，引用时写作《篇章名》）
CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    pack           TEXT NOT NULL,
    title          TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT '',
    game           TEXT NOT NULL DEFAULT '',   -- arknights | endfield
    story_code     TEXT NOT NULL DEFAULT '',
    story_name     TEXT NOT NULL DEFAULT '',
    activity_name  TEXT NOT NULL DEFAULT '',
    char_id        TEXT NOT NULL DEFAULT '',
    character_name TEXT NOT NULL DEFAULT '',
    collection_id  TEXT NOT NULL DEFAULT '',
    line_count     INTEGER NOT NULL DEFAULT 0,
    next_doc_id    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);
CREATE INDEX IF NOT EXISTS idx_documents_char ON documents(char_id);

-- 行（检索与引用的最小单位）
CREATE TABLE IF NOT EXISTS lines (
    line_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id),
    line_number INTEGER NOT NULL,
    line_type   TEXT NOT NULL DEFAULT '',
    speaker     TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL,
    UNIQUE(doc_id, line_number)
);

-- 实体（直接来自语料内置 entity_occurrences 标注）
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);

-- 别名 -> 实体（raw_name / canonical_name 都算别名）
CREATE TABLE IF NOT EXISTS aliases (
    alias     TEXT NOT NULL,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    PRIMARY KEY (alias, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_entity ON aliases(entity_id);

-- 行级实体出现（证据类型用于排序：speaker > metadata_link > scene_actor > text_mention）
CREATE TABLE IF NOT EXISTS line_entities (
    line_id    INTEGER NOT NULL REFERENCES lines(line_id),
    entity_id  TEXT NOT NULL REFERENCES entities(entity_id),
    evidence   TEXT NOT NULL DEFAULT 'text_mention',
    presence   TEXT NOT NULL DEFAULT 'mentioned',
    confidence REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (line_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_line_entities_entity ON line_entities(entity_id);

-- 文档级实体汇总（图游走的文档层跳板）
CREATE TABLE IF NOT EXISTS doc_entities (
    doc_id    TEXT NOT NULL REFERENCES documents(doc_id),
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    weight    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (doc_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_doc_entities_entity ON doc_entities(entity_id);

-- 关系表：cooccur=同文档共现 / speaker=说话人提到 / seq=文档接续
CREATE TABLE IF NOT EXISTS relations (
    src          TEXT NOT NULL,   -- entity_id 或 doc_id
    dst          TEXT NOT NULL,
    rel          TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    evidence_doc TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (src, dst, rel)
);
CREATE INDEX IF NOT EXISTS idx_relations_src ON relations(src);
CREATE INDEX IF NOT EXISTS idx_relations_dst ON relations(dst);

-- 行全文索引（中文 trigram）
CREATE VIRTUAL TABLE IF NOT EXISTS lines_fts USING fts5(
    text,
    tokenize='trigram',
    content='lines',
    content_rowid='line_id'
);

-- 高频问答缓存（命中则不调模型）
CREATE TABLE IF NOT EXISTS qa_cache (
    qhash      TEXT PRIMARY KEY,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    citations  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0
);

-- 群消息流水（统计播报数据源；任何模式下都记录）
CREATE TABLE IF NOT EXISTS messages (
    msg_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     TEXT NOT NULL,
    room_name   TEXT NOT NULL DEFAULT '',
    sender_id   TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '',
    ts          TEXT NOT NULL,
    is_at       INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL DEFAULT 'text',
    text        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room_id, ts);

-- 机器人已发送记录
CREATE TABLE IF NOT EXISTS sent_log (
    msg_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL,
    kind    TEXT NOT NULL,
    ts      TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT ''
);

-- 对群成员的长期印象（佩丽卡口吻，定时刷新）
CREATE TABLE IF NOT EXISTS social_notes (
    room_id     TEXT NOT NULL,
    sender_id   TEXT NOT NULL,
    sender_name TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (room_id, sender_id)
);
"""


class Database:
    """线程安全的 SQLite 封装。写操作串行，读操作并发。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.path, check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- 通用 --------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def executemany(self, sql: str, rows) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def transaction(self):
        """返回一个 with 上下文：进入时加锁，退出时提交/回滚。"""
        return _Txn(self)

    def meta_get(self, key: str) -> str | None:
        row = self.query_one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()


class _Txn:
    def __init__(self, db: Database):
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db._lock.acquire()
        return self._db._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._db._conn.commit()
            else:
                self._db._conn.rollback()
        finally:
            self._db._lock.release()
