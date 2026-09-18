"""多跳图游走：从问题命中的种子实体出发，沿关系表扩展相关实体。

每跳保留 top-K 邻居，分数逐跳衰减；记录路径用于解释「这条证据怎么来的」。
seq 关系是文档级接续，不参与实体游走（由检索层单独使用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pelica.db import Database

REL_TYPES_ENTITY = ("speaker", "cooccur")
HOP_DECAY = 0.5
REL_WEIGHT = {"speaker": 1.0, "cooccur": 0.6}


@dataclass
class GraphNode:
    entity_id: str
    hop: int
    score: float
    path: list[tuple[str, str]] = field(default_factory=list)  # [(rel, via_entity_id)]


class GraphWalker:
    def __init__(self, db: Database):
        self._db = db

    def _neighbors(self, entity_id: str) -> list[tuple[str, str, float]]:
        rows = self._db.query(
            """
            SELECT dst AS other, rel, weight FROM relations
             WHERE src=? AND rel IN ('speaker','cooccur')
            UNION ALL
            SELECT src AS other, rel, weight FROM relations
             WHERE dst=? AND rel IN ('speaker','cooccur')
            """,
            (entity_id, entity_id),
        )
        return [(r["other"], r["rel"], r["weight"]) for r in rows]

    def expand(
        self,
        seeds: dict[str, float],
        hops: int = 2,
        top_per_hop: int = 6,
    ) -> dict[str, GraphNode]:
        """seeds: entity_id -> 初始分数。返回 entity_id -> GraphNode（含种子）。"""
        nodes: dict[str, GraphNode] = {
            eid: GraphNode(eid, 0, score, []) for eid, score in seeds.items()
        }
        frontier = dict(seeds)
        for hop in range(1, hops + 1):
            candidates: dict[str, tuple[float, list[tuple[str, str]]]] = {}
            for parent_id, parent_score in frontier.items():
                for other, rel, weight in self._neighbors(parent_id):
                    if other in seeds or other in nodes:
                        continue
                    score = (
                        parent_score
                        * HOP_DECAY
                        * REL_WEIGHT.get(rel, 0.5)
                        * min(weight, 4.0) / 4.0
                    )
                    if other not in candidates or score > candidates[other][0]:
                        candidates[other] = (
                            score,
                            nodes[parent_id].path + [(rel, parent_id)],
                        )
            if not candidates:
                break
            ranked = sorted(candidates.items(), key=lambda kv: kv[1][0], reverse=True)
            frontier = {}
            for eid, (score, path) in ranked[:top_per_hop]:
                nodes[eid] = GraphNode(eid, hop, score, path)
                frontier[eid] = score
        return nodes

    def path_label(self, node: GraphNode, names: dict[str, str]) -> str:
        """把路径渲染成人话：佩丽卡 —同篇→ 陈千语 —提及→ 菲奥娜。"""
        rel_cn = {"speaker": "提及", "cooccur": "同篇", "seq": "接续"}
        if not node.path:
            return names.get(node.entity_id, node.entity_id)
        parts = [names.get(node.path[0][1], node.path[0][1])]
        for rel, _via in node.path:
            parts.append(rel_cn.get(rel, rel))
            parts.append(names.get(node.entity_id, node.entity_id))
        return " —".join(parts)
