#!/usr/bin/env python
"""构建语料数据库：摄入 PRTS-Terrachive release + 构建关系表。

用法：
  python scripts/build_db.py            # 增量（版本一致则跳过）
  python scripts/build_db.py --force    # 强制重建语料表
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.config import PROJECT_ROOT, load_settings
from pelica.corpus.ingester import ingest_release
from pelica.db import Database
from pelica.graph.builder import build_relations
from pelica.logging_setup import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="强制重建语料表")
    parser.add_argument("--skip-relations", action="store_true", help="跳过关系构建")
    parser.add_argument(
        "--release",
        default="",
        help="release 目录名（默认取 corpus/releases 下最新一个）",
    )
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_dir, settings.log_level)

    corpus_root = settings.corpus_dir
    if args.release:
        release = corpus_root / args.release
    else:
        candidates = sorted(
            (d for d in corpus_root.iterdir() if d.is_dir()),
            key=lambda d: d.name,
        )
        if not candidates:
            print(f"未找到语料 release：{corpus_root}", file=sys.stderr)
            return 1
        release = candidates[-1]

    db = Database(settings.db_path)
    try:
        stats = ingest_release(db, release, force=args.force)
        if not stats.get("skipped") and not args.skip_relations:
            build_relations(db)
    finally:
        db.close()

    size_mb = settings.db_path.stat().st_size / 1024 / 1024
    print(f"完成：{settings.db_path}（{size_mb:.0f} MB）")
    print(f"语料来源：{release}")
    print(f"项目根：{PROJECT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
