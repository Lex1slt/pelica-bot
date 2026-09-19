"""群消息路由：过滤、记录、分流到抖音管道 / 剧情问答。

核心规则（与验收一致）：
- 机器人自己发的消息：忽略；
- 白名单外的群：完全忽略（不记录）；
- 白名单内的群：每条消息先落库（统计播报的数据源），但不代表要回复；
- 只有「被 @」（原生 @ 或文本触发词）才走问答；抖音链接是唯一的例外功能；
- 连续对话：被 @ 且回复后的 CONVO_WINDOW 秒内，群里不带 @ 的短追问也接
  （聊完就散，不粘人）；窗口内没接住的消息先缓存，之后光杆 @（只 @ 不说话）
  会把缓存的那句捡起来当问题，不丢上下文；
- 喊名即触发：消息以别名开头、句中提到别名、甚至只喊一声名字都算
  （只喊名字时空拾取缓存的问题）；
- 自发插话：群里聊到语料实体（泰拉/终末地相关人名地名）时，按概率搭话，
  受群/人双重冷却约束，宁缺毋滥；
- 其余未被 @ 的普通消息：永远沉默。

问答分流优先级：身份问题 > 高频缓存 > 检索问答（LLM，带每群最近 4 轮
上下文；无证据但有上下文时走追问续聊）。
全部消息处理在一个 worker 线程里串行执行，天然防止 LLM 并发爆炸。
"""

from __future__ import annotations

import logging
import queue
import random
import re
import threading
import time
from collections import deque

from pelica.alerts import Alerter
from pelica.bridge.base import Bridge, Message
from pelica.db import Database
from pelica.douyin.pipeline import DouyinPipeline
from pelica.llm.answer import Answerer
from pelica.llm import persona
from pelica.retrieval.cache import QACache

log = logging.getLogger(__name__)

REPLY_COOLDOWN_ROOM = 2.0     # 同群两次回复最小间隔
REPLY_COOLDOWN_SENDER = 10.0  # 同一人连续追问冷却
IDENTITY_MEMORY = 180         # 秒；这个窗口内再追问身份 -> 「简介不是写了吗」
HISTORY_TURNS = 4             # 每群记住的最近问答轮数（追问要靠它）
CONVO_WINDOW = 180            # 连续对话窗口：回复后 N 秒内无 @ 的追问也接
PENDING_TTL = 120             # 光杆 @/只喊名字 拾取缓存消息的有效期（秒）
PENDING_MAX_LEN = 60          # 只缓存像日常对话的短消息
FOLLOWUP_COOLDOWN = 8.0       # 同一人无 @ 追问的最小间隔
AUTO_JOIN_CHANCE = 0.4        # 聊到语料实体时自发插话的概率
AUTO_JOIN_ROOM_COOLDOWN = 300.0   # 同群两次自发插话最小间隔
AUTO_JOIN_SENDER_COOLDOWN = 60.0  # 同一人被自发搭话的最小间隔
AUTO_JOIN_MIN_LEN = 4         # 太短不像话题
AUTO_JOIN_MAX_LEN = 120       # 太长像私聊记录/转发，不掺和
MAX_LLM_PER_SENDER = 8        # 单人 5 分钟窗口内 LLM 回复上限（防刷屏烧 token）
_LLM_WINDOW_SECONDS = 300.0
_FOLLOWUP_RE = re.compile(
    r"什么关系|关系是|为什么|怎么|如何|是谁|什么来头|什么背景|哪来的|出自哪"
    r"|对吧|对吗|是吗|真的吗|还有|所以|然后|继续|接着|再说说|展开|讲讲|聊聊"
    r"|(?:它|她|他|你|黍|望)呢$"
)


class GroupBot:
    def __init__(
        self,
        bridge: Bridge,
        db: Database,
        answerer: Answerer,
        qa_cache: QACache,
        douyin: DouyinPipeline | None,
        whitelist: list[str] | None,
        at_aliases: list[str],
        social=None,
        matcher=None,
    ):
        self._bridge = bridge
        self._db = db
        self._answerer = answerer
        self._cache = qa_cache
        self._douyin = douyin
        self._social = social
        self._matcher = matcher
        self._whitelist = [w for w in (whitelist or [])]
        self._at_aliases = at_aliases
        self._queue: queue.Queue[Message | None] = queue.Queue()
        self._worker = threading.Thread(target=self._work, daemon=True, name="groupbot")
        self._last_reply_room: dict[str, float] = {}
        self._last_reply_sender: dict[str, float] = {}
        self._identity_at: dict[str, float] = {}  # room_id -> 上次身份回应时间
        self._history: dict[str, deque] = {}      # room_id -> 最近问答轮次
        self._convo_until: dict[str, float] = {}  # room_id -> 连续对话窗口截止时刻
        self._pending: dict[str, tuple] = {}      # room_id -> (ts, text, sender_id, sender_name)
        self._last_bot_reply: dict[str, float] = {}   # room_id -> 上次机器人开口
        self._last_followup: dict[str, float] = {}    # sender_id -> 上次无 @ 追问
        self._last_autojoin_room: dict[str, float] = {}
        self._last_autojoin_sender: dict[str, float] = {}
        self._insult_strikes: dict[tuple[str, str], list[float]] = {}  # (群,人)->时刻
        self._llm_calls_sender: dict[str, list[float]] = {}  # 单人 LLM 调用限流

    # -- 入口 ---------------------------------------------------------------

    def start(self) -> None:
        self._bridge.on_message(self._on_message)
        self._worker.start()

    def stop(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5)

    def _on_message(self, msg: Message) -> None:
        if msg.is_self:
            return
        if not self._allowed(msg):
            return
        self._record(msg)
        self._queue.put(msg)

    def _allowed(self, msg: Message) -> bool:
        if not self._whitelist:
            return True  # 未配置白名单：全放行（仅建议开发环境）
        return msg.room_name in self._whitelist or msg.room_id in self._whitelist

    def _record(self, msg: Message) -> None:
        self._db.execute(
            "INSERT INTO messages(room_id,room_name,sender_id,sender_name,ts,is_at,kind,text)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                msg.room_id,
                msg.room_name,
                msg.sender_id,
                msg.sender_name,
                msg.ts,
                1 if msg.is_at else 0,
                "text",
                msg.text[:2000],
            ),
        )

    # -- 处理 ---------------------------------------------------------------

    def _work(self) -> None:
        while True:
            msg = self._queue.get()
            try:
                if msg is None:
                    return
                self._process(msg)
            except Exception:  # noqa: BLE001 单条消息的任何异常不拖垮整个 worker
                log.exception("消息处理失败：%r", msg)
            finally:
                self._queue.task_done()

    def _process(self, msg: Message) -> None:
        # 1) 抖音链接（不 @ 也处理；纯本地，不调模型）
        if self._douyin is not None:
            if self._douyin.handle(msg.text, msg.room_id):
                self._mark_replied(msg)
                return

        now = time.time()
        room_id = msg.room_id
        text = msg.text.strip()
        convo_open = now < self._convo_until.get(room_id, 0)

        # 1.5) 人身攻击（仅限点名机器人的场合——群友互相骂不归它管）：
        #     首次回应一次，24h 内再犯一律沉默。
        #     不调模型、不进历史/缓存/待拾取——陪骂只会喂养刷屏的人
        if self._is_at_me(msg) and persona.looks_like_insult(text):
            self._handle_insult(msg, now)
            return

        # 2) 被 @ / 喊名：正席问答
        if self._is_at_me(msg):
            question = self._extract_question(msg.text)
            if not question:
                # 光杆 @ / 只喊了一声名字：捡起窗口内最近一条没接住的话当问题
                picked = self._pickup_pending(room_id, now)
                if picked:
                    question, sid, sname = picked
                    self._answer(msg, question, social_sender=(sid, sname))
                else:
                    self._reply(room_id, "嗯？管理员，有什么事吗？")
                return
            self._answer(msg, question)
            return

        if not text or text.startswith(("http", "www")) or "@" in text:
            return  # 空/链接/在 @ 别人：不掺和

        # 3) 连续对话窗口内：像追问的短消息直接接，其余短消息缓存待拾取
        if (convo_open and len(text) <= PENDING_MAX_LEN
                and not persona.looks_like_insult(text)):
            looks_followup = bool(
                _FOLLOWUP_RE.search(text) or text.endswith(("？", "?", "吗", "呢", "么"))
            )
            if looks_followup and self._followup_allowed(msg, now):
                self._last_followup[msg.sender_id] = now
                self._answer(msg, text)
                return
            self._pending[room_id] = (now, text, msg.sender_id, msg.sender_name)

        # 4) 自发插话：聊到语料实体时按概率搭话（冷却约束，宁缺毋滥）
        if (
            self._matcher is not None
            and AUTO_JOIN_MIN_LEN <= len(text) <= AUTO_JOIN_MAX_LEN
            and now - self._last_autojoin_room.get(room_id, 0) >= AUTO_JOIN_ROOM_COOLDOWN
            and now - self._last_autojoin_sender.get(msg.sender_id, 0)
            >= AUTO_JOIN_SENDER_COOLDOWN
            and not persona.looks_like_offtopic(text)
            and random.random() < AUTO_JOIN_CHANCE
            and self._matcher.match(text)
        ):
            self._last_autojoin_room[room_id] = now
            self._last_autojoin_sender[msg.sender_id] = now
            self._pending.pop(room_id, None)  # 已接话，别再被光杆 @ 重复拾取
            self._answer(msg, text, unprompted=True)

    def _answer(
        self,
        msg: Message,
        question: str,
        social_sender: tuple[str, str] | None = None,
        unprompted: bool = False,
    ) -> None:
        """问答正流程：身份 > 现实话题 > 频控 > 检索 + LLM。"""
        room_id = msg.room_id
        # 身份问题（不调模型）：刚回应过身份且对方继续纠缠，用「简介不是写了吗」打发
        recently_identity = time.time() - self._identity_at.get(room_id, 0) < IDENTITY_MEMORY
        if persona.looks_like_identity_question(question) or (
            recently_identity and persona.looks_like_chase(question)
        ):
            if recently_identity and persona.looks_like_chase(question):
                self._reply(room_id, persona.pick(persona.REPLY_CHASED))
            else:
                self._identity_at[room_id] = time.time()
                self._reply(room_id, persona.pick(persona.REPLY_IDENTITY))
            return

        # 现实世界话题：语料答不了也不该答，谜语人话术带过；
        # 自发插话场合则直接沉默——没人问就不泼冷水
        if persona.looks_like_offtopic(question):
            if not unprompted:
                self._reply(room_id, persona.pick(persona.REPLY_OFFTOPIC))
            return

        # 频控
        now = time.time()
        if now - self._last_bot_reply.get(room_id, 0) < REPLY_COOLDOWN_ROOM:
            return
        if not unprompted and now - self._last_reply_sender.get(
            msg.sender_id, 0
        ) < REPLY_COOLDOWN_SENDER:
            return
        # 单人 LLM 限流：5 分钟窗口内最多 MAX_LLM_PER_SENDER 次，防 token 被刷爆
        calls = [t for t in self._llm_calls_sender.get(msg.sender_id, ())
                 if now - t < _LLM_WINDOW_SECONDS]
        if len(calls) >= MAX_LLM_PER_SENDER:
            return  # 超限直接沉默——再回一句反而又给了互动
        calls.append(now)
        self._llm_calls_sender[msg.sender_id] = calls

        # 检索 + LLM（带每群最近几轮上下文与社交记忆，闲聊/追问都接得住）
        history = list(self._history.get(room_id, ()))
        social = ""
        if self._social is not None:
            sid, sname = social_sender or (msg.sender_id, msg.sender_name)
            social = self._social.room_context(room_id, sid, sname)
        answer, evidence = self._answerer.answer(question, history=history, social=social)
        if evidence.covered or history:
            # LLM 生成的回复进群聊记忆（追问模式产生的回复也记，保持连贯）
            self._history.setdefault(room_id, deque(maxlen=HISTORY_TURNS)).append(
                (question, answer)
            )
        self._reply(room_id, answer)

    # -- 工具 ---------------------------------------------------------------

    def _is_at_me(self, msg: Message) -> bool:
        """被点名：原生 @、别名开头（喊名）、句中提到别名都算。"""
        if msg.is_at:
            return True
        t = msg.text.strip()
        if not t:
            return False
        for alias in self._at_aliases:
            if t.startswith("@" + alias):
                return True
            if t.startswith(alias):
                return True  # 只喊一声名字也算；空问题走缓存拾取
            if alias in t and len(t) <= 40:
                return True  # 「问问佩丽卡」这类句中提及
        return False

    def _extract_question(self, text: str) -> str:
        t = text.strip()
        t = re.sub(r"@[^\s，。,]+\s*", "", t)  # 去掉所有 @xxx
        for alias in sorted(self._at_aliases, key=len, reverse=True):
            if t.startswith(alias):
                t = t[len(alias):]
                break
        return t.strip(" ，,。：:！!？?")

    def _reply(self, room_id: str, text: str) -> None:
        """按真人节奏发送：长回复拆成多条气泡连发，间隔随机。"""
        bubbles = persona.split_reply_to_bubbles(text)
        for i, bubble in enumerate(bubbles):
            self._bridge.send_text(room_id, bubble)
            if i < len(bubbles) - 1:
                time.sleep(random.uniform(0.9, 1.9))
        now = time.time()
        self._last_bot_reply[room_id] = now
        # 开过口就进入连续对话窗口：接下来一会儿不 @ 也能接着聊
        self._convo_until[room_id] = now + CONVO_WINDOW

    def _pickup_pending(self, room_id: str, now: float) -> tuple[str, str, str] | None:
        """拾取窗口内最近一条没接住的消息：(text, sender_id, sender_name)。"""
        pend = self._pending.get(room_id)
        if pend and now - pend[0] <= PENDING_TTL:
            self._pending.pop(room_id, None)
            return pend[1], pend[2], pend[3]
        return None

    def _handle_insult(self, msg: Message, now: float) -> None:
        """辱骂打击：24h 滚动窗口计数；第一次人设化回应一次，之后沉默。

        不调模型、不写 history/_pending/缓存——骂声与回骂都不留给后续对话，
        陪骂只会喂养刷屏的人。
        """
        key = (msg.room_id, msg.sender_id)
        strikes = [t for t in self._insult_strikes.get(key, ())
                   if now - t < 86400.0]
        strikes.append(now)
        self._insult_strikes[key] = strikes
        if len(strikes) == 1:
            self._reply(msg.room_id, persona.pick(persona.REPLY_INSULT))

    def _followup_allowed(self, msg: Message, now: float) -> bool:
        if now - self._last_bot_reply.get(msg.room_id, 0) < REPLY_COOLDOWN_ROOM:
            return False
        return now - self._last_followup.get(msg.sender_id, 0) >= FOLLOWUP_COOLDOWN

    def _mark_replied(self, msg: Message) -> None:
        now = time.time()
        self._last_reply_room[msg.room_id] = now
        self._last_reply_sender[msg.sender_id] = now
        self._last_bot_reply[msg.room_id] = now
        self._convo_until[msg.room_id] = now + CONVO_WINDOW
