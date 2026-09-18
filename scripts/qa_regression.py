#!/usr/bin/env python
"""检索回归问答集：换语料 / 调排序参数后一键回归。

用法：
  python scripts/qa_regression.py             # 只看检索覆盖与证据（不调 LLM，零成本）
  python scripts/qa_regression.py --llm       # 连真实 API 生成回答（花 token）

每条用例声明期望：
  covered=True   期望佩丽卡能答（语料里有据）
  covered=False  期望她坦白不知道（语料无据，绝不能编）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pelica.config import load_settings  # noqa: E402
from pelica.db import Database  # noqa: E402
from pelica.graph.matcher import EntityMatcher  # noqa: E402
from pelica.llm import persona  # noqa: E402
from pelica.logging_setup import setup_logging  # noqa: E402
from pelica.retrieval.retriever import Retriever  # noqa: E402

# (问题, 期望) —— 期望基于 agent-corpus-v2-20260906 语料内容
#   "answer"   期望佩丽卡能答（语料里有据）
#   "reject"   期望她坦白不知道（语料无据，绝不能编）
#   "offtopic" 现实世界话题：路由层谜语人带过，不应进检索问答
CASES = [
    ("佩丽卡和陈千语是怎么认识的？", "answer"),
    ("醚质是什么", "answer"),
    ("帝江号是什么船", "answer"),
    ("佩丽卡为什么会骑摩托车", "answer"),
    ("源石技艺在终末地叫什么", "answer"),
    ("阿米娅是谁", "answer"),
    ("博士是谁", "answer"),
    ("弑君者的真实身份", "answer"),
    ("M3 和佩丽卡是什么关系", "answer"),
    ("陈千语是谁", "answer"),
    ("佩丽卡喜欢什么", "answer"),
    ("帝江号在哪里", "answer"),
    ("菲利克斯的生日是哪天", "reject"),      # 语料中无此角色
    ("幕刃哥是谁", "reject"),               # 现实梗，语料无
    ("明天的天气怎么样", "offtopic"),        # 现实话题
    ("你喜欢我吗", "social"),               # 社交话题 → 人设直答
    ("今天心情怎么样", "social"),            # 社交话题
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="连真实 API 生成回答")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_dir, "WARNING")
    db = Database(settings.db_path)
    retriever = Retriever(db, EntityMatcher(db))

    answerer = None
    if args.llm:
        from pelica.graph.walker import GraphWalker
        from pelica.llm.answer import Answerer
        from pelica.llm.client import DeepSeekClient

        answerer = Answerer(
            DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url,
                           settings.deepseek_model),
            Retriever(db, EntityMatcher(db), GraphWalker(db)),
        )

    passed = 0
    for question, expected in CASES:
        if expected == "offtopic":
            ok = persona.looks_like_offtopic(question)
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] 应拒(现实话题) | {question}")
            passed += ok
            continue
        if expected == "social":
            ok = persona.looks_like_social(question)
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] 应答(社交直答) | {question}")
            passed += ok
            continue
        ev = retriever.retrieve(question)
        ok = ev.covered == (expected == "answer")
        passed += ok
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {'应答' if expected == 'answer' else '应拒'} | 实际"
              f"{'答' if ev.covered else '拒'} | {question}")
        if args.llm:
            reply, _ = answerer.answer(question)
            bad = persona.find_forbidden(reply)
            print(f"       回复: {reply[:80]}{'…' if len(reply) > 80 else ''}"
                  + (f"  !!机器腔:{bad}" if bad else ""))
        else:
            for s in ev.snippets[:2]:
                print(f"       证据: {s.citation} {s.text[:44]}")

    print(f"\n回归结果：{passed}/{len(CASES)} 通过")
    db.close()
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
