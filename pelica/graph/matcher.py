"""实体匹配：把用户问题里的名字对齐到语料实体（别名最长匹配）。

语料的实体聚类有污染：同一个别名（如「佩丽卡」）会挂在多个
canonical_name 不同的实体簇上（声优、同场景角色，甚至别的角色）。
选择规则：
  1) canonical_name 与别名完全一致者优先（身份匹配）；
  2) 否则取知名度最高者（doc_entities 权重和，跨文档出现最多）。
最终按 canonical_name 去重，一个名字聚合它全部 entity_id 供图游走。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pelica.db import Database

_MIN_ALIAS_LEN = 2        # 过滤单字噪声别名
_MAX_IDS_PER_NAME = 8
_PROMINENCE_FLOOR = 0.1   # 无知名度数据时的兜底分


@dataclass
class EntityMatch:
    alias: str
    canonical_name: str
    entity_type: str
    entity_ids: tuple[str, ...]


_PURE_ASCII_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


class EntityMatcher:
    def __init__(self, db: Database):
        # 预加载实体表，避免逐行查询
        self._canonical: dict[str, tuple[str, str]] = {
            r["entity_id"]: (r["canonical_name"], r["entity_type"])
            for r in db.query("SELECT entity_id, canonical_name, entity_type FROM entities")
        }
        # alias -> canonical_name -> [entity_id]
        # 单字别名仅在「别名 == 实体规范名」时保留——
        # 明日方舟有大量单字名角色（年、夕、令、黍、望…），不能一刀切过滤
        alias_canon: dict[str, dict[str, list[str]]] = {}
        for row in db.query(
            "SELECT a.alias, a.entity_id, e.canonical_name AS canon, "
            "e.entity_type AS etype FROM aliases a "
            "JOIN entities e ON e.entity_id = a.entity_id"
        ):
            alias = row["alias"].strip()
            canon = row["canon"]
            eid = row["entity_id"]
            if len(alias) < 2:
                # 单字别名：仅当它本身就是实体的规范名（如「黍」「年」这类
                # 单字名角色）才保留
                if alias != canon:
                    continue
            elif _PURE_ASCII_ID.match(alias) and len(alias) < 4:
                continue
            alias_canon.setdefault(alias, {}).setdefault(canon, []).append(eid)
        self._alias_canon = alias_canon
        self._aliases_by_len = sorted(alias_canon.keys(), key=len, reverse=True)

        # 知名度：实体在文档级出现的权重和
        self._prominence: dict[str, float] = {
            r["entity_id"]: float(r["w"])
            for r in db.query(
                "SELECT entity_id, SUM(weight) AS w FROM doc_entities GROUP BY entity_id"
            )
        }

    @property
    def alias_count(self) -> int:
        return len(self._alias_canon)

    def _best_canonical(self, alias: str) -> tuple[str, tuple[str, ...], str]:
        """为别名挑一个最佳规范名，返回 (canonical, entity_ids, entity_type)。"""
        candidates = self._alias_canon[alias]

        def rank(canon: str) -> tuple[int, float]:
            identity = 1 if canon == alias else 0
            prom = max(
                (self._prominence.get(eid, _PROMINENCE_FLOOR) for eid in candidates[canon]),
                default=_PROMINENCE_FLOOR,
            )
            return (identity, prom)

        best = max(candidates.keys(), key=rank)
        ids = candidates[best][:_MAX_IDS_PER_NAME]
        etype = ""
        for eid in ids:
            meta = self._canonical.get(eid)
            if meta:
                etype = meta[1]
                break
        return best, tuple(ids), etype

    def match(self, text: str, limit: int = 8) -> list[EntityMatch]:
        """贪心最长匹配，按规范名去重。"""
        if not text:
            return []
        taken = [False] * len(text)
        results: dict[str, EntityMatch] = {}
        for alias in self._aliases_by_len:
            start = 0
            while True:
                idx = text.find(alias, start)
                if idx < 0:
                    break
                end = idx + len(alias)
                if not any(taken[idx:end]):
                    for i in range(idx, end):
                        taken[i] = True
                    canon, ids, etype = self._best_canonical(alias)
                    if canon not in results:
                        results[canon] = EntityMatch(alias, canon, etype, ids)
                start = end
            if len(results) >= limit:
                break
        out = list(results.values())
        out.sort(key=lambda m: text.find(m.alias))
        return out[:limit]
