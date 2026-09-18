"""混合检索器。

思路（GraphRAG 本地化）：
1. 实体锚定：问题 -> 别名匹配 -> 种子实体（0 跳）
2. 图扩展：沿 speaker/cooccur 关系游走 1-2 跳，得到关联实体及其路径
3. 证据召回：实体 -> line_entities -> 原文行；同时对问题走 FTS trigram
4. 融合排序：图分数 + 问题词重合度 + FTS 加成 + 文档多样性约束
5. 上下文补全：每条证据带前后各一行，方便模型理解语境
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pelica.db import Database
from pelica.graph.matcher import EntityMatcher
from pelica.graph.walker import GraphNode, GraphWalker

log = logging.getLogger(__name__)

EVIDENCE_MULT = {
    "speaker": 1.3,
    "metadata_link": 1.1,
    "scene_actor": 1.0,
    "text_mention": 0.8,
}
MAX_ENTITIES_USED = 16
LINES_PER_ENTITY = 80
FTS_TOP_K = 25
MAX_SNIPPETS = 10
MAX_PER_DOC = 4
MAX_SEED_IDS = 30
OVERLAY_WEIGHT = 0.6       # 每个问题词在行文中出现的加成
OVERLAY_MAX_TOKENS = 4
FTS_WEIGHT = 2.0

# covered 判定阈值
# 1.1：档案行（metadata_link）+ 名字重合 ≈ 0.5*1.1 + 0.6 ≈ 1.15 应当覆盖
COVERED_WITH_ENTITY = 1.1
COVERED_FTS_ONLY = 0.5

try:  # jieba 可选：缺席时退回二元切词
    import jieba

    jieba.setLogLevel(60)

    def tokenize(text: str) -> list[str]:
        return [t for t in jieba.cut_for_search(text) if len(t.strip()) >= 2]

except Exception:  # pragma: no cover

    def tokenize(text: str) -> list[str]:
        return [text[i : i + 2] for i in range(len(text) - 1)]


@dataclass
class Snippet:
    doc_id: str
    title: str
    category: str
    game: str
    story_name: str
    activity_name: str
    line_number: int
    line_type: str
    speaker: str
    text: str
    before: str = ""
    after: str = ""
    score: float = 0.0
    entity_names: list[str] = field(default_factory=list)
    hop: int = 0

    @property
    def citation(self) -> str:
        return f"《{self.title}》第 {self.line_number} 行"


@dataclass
class Evidence:
    question: str
    covered: bool
    snippets: list[Snippet] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    graph_paths: list[str] = field(default_factory=list)
    reason: str = ""


# 问题里的高频虚词/泛指词：不作为检索词，也不参与重合度加成
_STOPWORDS = frozenset({
    "什么", "怎么", "怎样", "怎么样", "为什么", "为何", "哪里", "哪些", "哪个",
    "多少", "如何", "请问", "想知道", "介绍", "一下", "说说", "讲讲", "到底",
    "究竟", "还是", "以及", "他们", "她们", "它们", "我们", "你们", "自己",
    "这个", "那个", "这些", "那些", "时候", "地方", "东西", "事情", "故事",
    "剧情", "背景", "设定", "是谁", "有谁", "可以", "能够", "是不是", "有没有",
})


def fts_terms(question: str) -> list[tuple[str, float]]:
    """FTS trigram 查询词，返回 (词, 基础权重)。

    trigram 查不到 <3 字的串，且整串查询要求原文连续出现，所以：
    - jieba 词 ==3 字直接查，越长权重越高；
    - >=4 字的词同时拆内部 3 字窗口低权重兜底（jieba 对生僻词会整串
      吞掉或切碎，如「醚质」，必须靠窗口拆开）；
    - 2 字词用它在问题原文里的 3 字上下文窗口作代理；
    - 原问题全文 3 字滑窗作最低权重兜底（0.3），保证生僻组合词也有查询词；
    - 停用词完全跳过，避免「是怎么认识的」这类通用短语压过真证据。
    """
    tokens = [t for t in tokenize(question) if len(t.strip()) >= 2]
    q = question.strip()
    out: dict[str, float] = {}
    for t in tokens:
        if t in _STOPWORDS:
            continue
        if len(t) >= 3:
            w = 1.0 + 0.25 * (len(t) - 3)
            if len(t) <= 5:
                out[t] = max(out.get(t, 0.0), w)
            for i in range(len(t) - 2):  # 内部窗口兜底
                win = t[i : i + 3]
                out[win] = max(out.get(win, 0.0), 0.35)
        else:
            # 2 字词：左右两个 3 字窗口
            start = 0
            while True:
                idx = q.find(t, start)
                if idx < 0:
                    break
                for cand in (q[idx - 1 : idx + 2], q[idx : idx + 3]):
                    cand = cand.strip()
                    if len(cand) == 3 and not cand.isspace():
                        out[cand] = max(out.get(cand, 0.0), 0.8)
                start = idx + 1
    # 原文滑窗兜底：含停用词的窗口跳过（避免「是怎么」这类通用短语回流入权重）
    for i in range(max(len(q) - 2, 0)):
        win = q[i : i + 3].strip()
        if len(win) != 3 or win.isspace():
            continue
        if win in _STOPWORDS or any(sw in win for sw in _STOPWORDS):
            continue
        out[win] = max(out.get(win, 0.0), 0.3)
    return list(out.items())


def dominant_term(question: str) -> str:
    """问题里最「实」的内容子串：最长非停用词 token，退而求其次取最长滑窗。

    用于无实体命中时的守门：它必须出现在证据里，否则视为答非所问。
    """
    tokens = [t for t in tokenize(question) if len(t) >= 2 and t not in _STOPWORDS]
    q = question.strip()
    windows = [q[i : i + 3] for i in range(max(len(q) - 2, 0))]
    windows = [w for w in windows if w not in _STOPWORDS]
    candidates = tokens + windows
    return max(candidates, key=len) if candidates else ""


class Retriever:
    def __init__(self, db: Database, matcher: EntityMatcher, walker: GraphWalker | None = None):
        self._db = db
        self._matcher = matcher
        self._walker = walker or GraphWalker(db)

    # -- 对外入口 -----------------------------------------------------------

    def retrieve(self, question: str) -> Evidence:
        question = question.strip()
        matches = self._matcher.match(question)
        entity_names = [m.canonical_name for m in matches]

        nodes: dict[str, GraphNode] = {}
        snippets: list[Snippet] = []
        if matches:
            seeds: dict[str, float] = {}
            for m in matches:
                for eid in m.entity_ids:
                    seeds.setdefault(eid, 1.0)
            seeds = dict(list(seeds.items())[:MAX_SEED_IDS])
            nodes = self._walker.expand(seeds)
            self._boost_prominent_seeds(nodes)
            snippets = self._collect_by_entities(question, matches, nodes)

        fts_hits = self._fts_search(question)
        snippets = self._merge(question, snippets, fts_hits)

        if not snippets:
            return Evidence(
                question=question,
                covered=False,
                entity_names=entity_names,
                reason="没有命中实体，也没有可用的全文线索",
            )

        best = snippets[0].score
        if matches and best >= COVERED_WITH_ENTITY:
            covered = True
            reason = f"实体命中 {entity_names}，最高分 {best:.2f}"
        elif not matches and best >= COVERED_FTS_ONLY:
            # 无实体时守门：问题的核心内容子串必须真实出现在证据里，
            # 否则容易拿别人的故事张冠李戴（问 A 的生日答成 B 的）
            evidence_text = "".join(s.text for s in snippets[:3])
            dominant = dominant_term(question)
            if dominant and dominant in evidence_text:
                covered = True
                reason = f"仅全文命中，最高分 {best:.2f}"
            else:
                covered = False
                reason = f"全文线索与问题对不上（最高分 {best:.2f}）"
        else:
            covered = False
            reason = f"证据太弱（最高分 {best:.2f}）"

        paths = self._describe_paths(matches, nodes) if matches else []
        return Evidence(
            question=question,
            covered=covered,
            snippets=snippets,
            entity_names=entity_names,
            graph_paths=paths,
            reason=reason,
        )

    # -- 实体路径召回 ---------------------------------------------------------

    def _boost_prominent_seeds(self, nodes: dict[str, GraphNode]) -> None:
        """同一角色的多个语境实体 ID，跨文档越常见的越接近「主实体」。"""
        hop0 = [n for n in nodes.values() if n.hop == 0]
        if not hop0:
            return
        ids = [n.entity_id for n in hop0]
        rows = self._db.query(
            "SELECT entity_id, SUM(weight) AS w FROM doc_entities "
            f"WHERE entity_id IN ({','.join('?' * len(ids))}) GROUP BY entity_id",
            tuple(ids),
        )
        prominence = {r["entity_id"]: float(r["w"]) for r in rows}
        for n in hop0:
            prom = prominence.get(n.entity_id, 0.0)
            n.score *= 0.7 + 0.6 * min(prom, 8.0) / 8.0  # 0.7x ~ 1.3x

    def _collect_by_entities(
        self, question: str, matches, nodes: dict[str, GraphNode]
    ) -> list[Snippet]:
        ranked = sorted(nodes.values(), key=lambda n: n.score, reverse=True)[
            :MAX_ENTITIES_USED
        ]
        id_to_name: dict[str, str] = {}
        for m in matches:
            for eid in m.entity_ids:
                id_to_name[eid] = m.canonical_name
        for n in ranked:
            id_to_name.setdefault(n.entity_id, self._entity_name(n.entity_id))

        qtokens = [t for t in tokenize(question) if len(t) >= 2 and t not in _STOPWORDS]
        candidates: dict[int, Snippet] = {}
        for node in ranked:
            rows = self._db.query(
                """
                SELECT le.evidence, l.line_id, l.doc_id, l.line_number,
                       l.line_type, l.speaker, l.text,
                       d.title, d.category, d.game, d.story_name, d.activity_name
                FROM line_entities le
                JOIN lines l ON l.line_id = le.line_id
                JOIN documents d ON d.doc_id = l.doc_id
                WHERE le.entity_id = ?
                LIMIT ?
                """,
                (node.entity_id, LINES_PER_ENTITY),
            )
            name = id_to_name.get(node.entity_id, node.entity_id)
            for r in rows:
                base = 0.5 * node.score * EVIDENCE_MULT.get(r["evidence"], 0.6)
                overlap = sum(1 for t in qtokens if t in r["text"])
                # 长行（整篇摘要塞一行）天然包含更多词，按长度归一，下限 0.35
                len_factor = min(1.0, max(120.0 / max(len(r["text"]), 1), 0.35))
                score = base + OVERLAY_WEIGHT * min(overlap, OVERLAY_MAX_TOKENS) * len_factor
                if r["speaker"] and r["speaker"] in name:
                    score += 0.3
                if r["line_type"] in ("dialogue", "voice", "sns"):
                    score += 0.2
                if r["speaker"]:
                    score += 0.3  # 有说话人的台词是第一手证据
                text = r["text"]
                if r["line_type"] == "knowledge" or text.startswith("##"):
                    score *= 0.75  # 知识摘要行有用，但不应压过原文台词
                sid = r["line_id"]
                if sid not in candidates or score > candidates[sid].score:
                    candidates[sid] = Snippet(
                        doc_id=r["doc_id"], title=r["title"], category=r["category"],
                        game=r["game"], story_name=r["story_name"],
                        activity_name=r["activity_name"],
                        line_number=r["line_number"], line_type=r["line_type"],
                        speaker=r["speaker"], text=r["text"], score=score,
                        entity_names=[name], hop=node.hop,
                    )
        return list(candidates.values())

    # -- 全文路径召回 ---------------------------------------------------------

    def _fts_search(self, question: str) -> dict[int, float]:
        """按词分别查 FTS，合成加权分。

        每个词的有效权重 = 基础权重 × 稀有度 × 组内归一化排名，
        「醚质」这种稀有个体词能压过偶然共现的普通词。
        """
        terms = fts_terms(question)
        if not terms:
            return {}
        scores: dict[int, float] = {}
        for t, base_weight in terms:
            try:
                rows = self._db.query(
                    """
                    SELECT rowid AS line_id, -bm25(lines_fts) AS rank
                    FROM lines_fts WHERE lines_fts MATCH ? ORDER BY rank LIMIT ?
                    """,
                    (f'"{t}"', FTS_TOP_K),
                )
            except Exception as exc:
                log.debug("FTS 查询 %r 失败：%s", t, exc)
                continue
            if not rows:
                continue
            hits = {r["line_id"]: float(r["rank"]) for r in rows}
            rarity = 1.0 / (1.0 + len(hits) / 150.0)
            max_rank = max(hits.values()) or 1.0
            for line_id, rank in hits.items():
                contribution = base_weight * rarity * (rank / max_rank)
                scores[line_id] = scores.get(line_id, 0.0) + contribution
        return scores

    # -- 融合与组装 -----------------------------------------------------------

    def _merge(
        self, question: str, snippets: list[Snippet], fts_hits: dict[int, float]
    ) -> list[Snippet]:
        if fts_hits:
            rows = self._db.query(
                """
                SELECT l.line_id, l.doc_id, l.line_number, l.line_type, l.speaker, l.text,
                       d.title, d.category, d.game, d.story_name, d.activity_name
                FROM lines l JOIN documents d ON d.doc_id = l.doc_id
                WHERE l.line_id IN (%s)
                """ % ",".join("?" * len(fts_hits)),
                tuple(fts_hits),
            )
            for line_id, composite in fts_hits.items():
                r = next((x for x in rows if x["line_id"] == line_id), None)
                if r is None:
                    continue
                # 长摘要行「包含一切」，FTS 加成同样按长度归一（下限 0.5）
                len_factor = min(1.0, max(120.0 / max(len(r["text"]), 1), 0.5))
                bonus = FTS_WEIGHT * composite * len_factor
                existing = next(
                    (
                        s
                        for s in snippets
                        if s.doc_id == r["doc_id"] and s.line_number == r["line_number"]
                    ),
                    None,
                )
                if existing:
                    existing.score += bonus
                else:
                    snippets.append(
                        Snippet(
                            doc_id=r["doc_id"], title=r["title"], category=r["category"],
                            game=r["game"], story_name=r["story_name"],
                            activity_name=r["activity_name"],
                            line_number=r["line_number"], line_type=r["line_type"],
                            speaker=r["speaker"], text=r["text"],
                            score=bonus, entity_names=[], hop=9,
                        )
                    )

        # 上下文窗口
        for s in snippets:
            s.before, s.after = self._context(s.doc_id, s.line_number)

        # 文档多样性：同文档最多 MAX_PER_DOC 条
        snippets.sort(key=lambda s: s.score, reverse=True)
        per_doc: dict[str, int] = {}
        picked: list[Snippet] = []
        for s in snippets:
            n = per_doc.get(s.doc_id, 0)
            if n >= MAX_PER_DOC:
                continue
            per_doc[s.doc_id] = n + 1
            picked.append(s)
            if len(picked) >= MAX_SNIPPETS:
                break
        return picked

    def _context(self, doc_id: str, line_number: int) -> tuple[str, str]:
        def neighbor(offset: int) -> str:
            row = self._db.query_one(
                "SELECT text FROM lines WHERE doc_id=? AND line_number=?",
                (doc_id, line_number + offset),
            )
            return row["text"] if row else ""

        return neighbor(-1), neighbor(1)

    def _entity_name(self, entity_id: str) -> str:
        row = self._db.query_one(
            "SELECT canonical_name FROM entities WHERE entity_id=?", (entity_id,)
        )
        return row["canonical_name"] if row else entity_id

    def _describe_paths(self, matches, nodes: dict[str, GraphNode]) -> list[str]:
        if not nodes:
            return []
        names = {n.entity_id: self._entity_name(n.entity_id) for n in nodes.values()}
        for m in matches:
            for eid in m.entity_ids:
                names[eid] = m.canonical_name
        labels = []
        seen: set[str] = set()
        for node in sorted(nodes.values(), key=lambda n: (n.hop, -n.score))[:8]:
            if node.hop > 0:
                label = self._walker.path_label(node, names)
                if label not in seen:
                    seen.add(label)
                    labels.append(label)
        return labels
