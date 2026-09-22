"""生产桥接：WeChat-Hook（微信 4.1.10.27 version.dll 代理注入，免费开源）。

来源：https://github.com/aixed/WeChat-Hook （本机 vendor 同步了源码）
原理：version.dll 以代理方式加载进 PC 微信进程，起本地 HTTP 服务
（默认 http://127.0.0.1:30001），提供：
  - POST /SendTextMsg        {wxidorgid, msg}          发文本（群/私聊）
  - POST /SendImgMsg         {wxidorgid, path}         发图片
  - POST /ForwardXMLMsg      {to_wxid, content}        转发 XML 消息（视频等）
  - POST /GetSelfProfile                               机器人账号资料
  - POST /QueryDB/execute    {optDbName, SQL}          微信内 SQLite 查询
  - POST /QueryDB/GetAllDBName                         数据库列表
  - GET  /QueryDB/status     {IsLogin, ...}            登录状态

接收消息：免费分支没有消息推送，采用**轮询消息数据库**——
启动后自动发现 MSG 库与表结构，按游标增量拉取新消息，
群消息（talker 含 @chatroom）转换成统一 Message 分发给路由。

账号要求：机器人小号登录微信 4.1.10.27（绿色版可与其它版本共存）。
云迁移：整套是 Windows 进程，上云用 Windows 云主机即可，代码不变。
"""

from __future__ import annotations

import logging
import re
import threading
import time
import hashlib
from collections import deque
from pathlib import Path

import requests

from pelica.bridge.base import Bridge, Message, MessageHandler

log = logging.getLogger(__name__)

_APPMSG_URL_RE = re.compile(r"<url><!\[CDATA\[(.*?)\]\]>", re.S)
_URL_RE = re.compile(r"https?://[^\s<\"']+")
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"  # 微信 4.x 消息库对 type49 内容做 zstd 压缩


class WeChatHookError(RuntimeError):
    pass


class WeChatHookBridge(Bridge):
    mode = "wxhook"

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:30001",
        groups: list[str] | None = None,          # 群聊名称白名单（空=全部）
        at_aliases: list[str] | None = None,      # @ 触发词
        poll_interval: float = 2.5,
        on_failure=None,
        max_failures: int = 3,
        video_xml_path: Path | None = None,       # 缓存的可转发视频消息 XML
    ):
        self._api = api_url.rstrip("/")
        # hook 服务只可能跑在本机：拒绝一切非回环地址，防配置被改成 SSRF 跳板
        from urllib.parse import urlparse

        parsed = urlparse(self._api)
        if parsed.scheme not in ("http", "https") or (
            parsed.hostname or ""
        ) not in ("127.0.0.1", "localhost", "::1"):
            raise WeChatHookError(
                f"WXHOOK_API_URL 必须指向本机 hook 服务（http://127.0.0.1:30001），当前：{api_url}"
            )
        self._groups = [g for g in (groups or [])]
        self._at_aliases = at_aliases or []
        self._poll_interval = poll_interval
        self._on_failure = on_failure
        self._max_failures = max_failures
        self._video_xml_path = Path(video_xml_path) if video_xml_path else None

        self._handler: MessageHandler | None = None
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._healthy = False
        self._failures = 0
        self._last_error = ""

        # 自己发的消息回显过滤：SessionTable 不标注发送者是否本人，
        # 记下刚发出的 (群, 文本, 时刻)，轮询回显匹配上就丢弃；
        # 学到的 self_wxid 持久化，重启后立即可用（统计播报也靠它排除自己）
        self._recent_sends: deque[tuple[str, str, float]] = deque(maxlen=64)
        self._self_wxid = ""
        self._self_wxid_path = (video_xml_path.parent / "self_wxid.txt") if video_xml_path else None
        if self._self_wxid_path and self._self_wxid_path.exists():
            try:
                self._self_wxid = self._self_wxid_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # 数据库发现结果（登录后自动填充）
        self._cursor: int = 0                     # 增量游标（按 rowid/localId）
        self._schema_ready = False

    # -- HTTP 基础 -----------------------------------------------------------

    def _call(self, method: str, path: str, payload: dict | None = None,
              timeout: float = 15.0):
        url = f"{self._api}{path}"
        resp = requests.request(method, url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp

    def _post_json(self, path: str, payload: dict, timeout: float = 15.0):
        resp = self._call("POST", path, payload, timeout)
        try:
            return resp.json()
        except ValueError as exc:
            raise WeChatHookError(f"{path} 返回非 JSON：{resp.text[:120]}") from exc

    # -- 生命周期 -------------------------------------------------------------

    def start(self) -> None:
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="wxhook-bridge")
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    def is_healthy(self) -> bool:
        return self._healthy

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def _wait_login(self) -> None:
        """阻塞等待扫码登录（IsLogin==1）。"""
        announced = False
        while not self._stop_flag.is_set():
            try:
                # status 路由只注册了 GET，POST 会 404
                data = self._call("GET", "/QueryDB/status", timeout=5).json()
                if int(data.get("IsLogin", 0)) == 1:
                    log.info("微信已登录，桥接激活")
                    return
                if not announced:
                    log.info("等待微信扫码登录（请在微信 4.1.10.27 登录机器人小号）…")
                    announced = True
            except Exception as exc:  # noqa: BLE001 微信未启动时 HTTP 不可达
                if not announced:
                    log.info("等待微信 4.1.10.27 启动（%s）…", exc)
                    announced = True
            time.sleep(3)

    # -- 主循环 ---------------------------------------------------------------

    def _loop(self) -> None:
        self._wait_login()
        if self._stop_flag.is_set():
            return

        try:
            self._discover_session_db()
        except Exception as exc:  # noqa: BLE001
            log.exception("会话库发现失败：%s", exc)
            self._record_failure("会话库发现失败")
            return

        self._healthy = True
        self._failures = 0
        log.info("WeChat-Hook 桥接激活：轮询 session.db（群白名单=%s）",
                 self._groups or "未配置(全部)")

        while not self._stop_flag.is_set():
            try:
                rows = self._fetch_new_sessions()
                for row in rows:
                    message = self._session_row_to_message(row)
                    if message is not None and self._handler is not None:
                        self._handler(message)
                self._healthy = True
                time.sleep(self._poll_interval)
            except Exception as exc:  # noqa: BLE001
                self._healthy = False
                self._failures += 1
                self._last_error = str(exc)
                log.error("轮询失败（连续 %d 次）：%s", self._failures, exc)
                if self._on_failure is not None and self._failures >= self._max_failures:
                    try:
                        self._on_failure(f"WeChat-Hook 桥接连续 {self._failures} 次轮询失败：{exc}")
                    except Exception:  # noqa: BLE001
                        log.exception("告警回调失败")
                time.sleep(min(10 * self._failures, 60))

    def _record_failure(self, why: str) -> None:
        self._failures += 1
        if self._on_failure is not None and self._failures >= self._max_failures:
            try:
                self._on_failure(why)
            except Exception:  # noqa: BLE001
                log.exception("告警回调失败")

    # -- 库表发现 -------------------------------------------------------------

    def _get_all_db_names(self) -> list[dict]:
        data = self._post_json("/QueryDB/GetAllDBName", {})
        if isinstance(data, list):
            return data
        return data.get("data", []) if isinstance(data, dict) else []

    def _execute(self, db_name: str, sql: str) -> list[dict]:
        data = self._post_json("/QueryDB/execute",
                               {"optDbName": db_name, "SQL": sql}, timeout=20)
        if isinstance(data, dict):
            if data.get("status", 0) not in (0, "0"):
                raise WeChatHookError(f"SQL 执行失败：{data.get('desc')}")
            return data.get("data", []) or []
        if isinstance(data, list):
            return data
        return []

    def _discover_session_db(self) -> None:
        """定位 session.db 并设置初始时间游标。"""
        for entry in self._get_all_db_names():
            db_name = entry.get("dbName", "") if isinstance(entry, dict) else str(entry)
            if db_name == "session.db":
                self._session_db = db_name
                break
        else:
            raise WeChatHookError("session.db 不存在（是否未完成登录？）")
        # 初始游标 = 当前时间-5秒（epoch 秒），只收启动后的新消息
        self._session_cursor = int(time.time()) - 5
        self._schema_ready = True
        log.info("session.db 就绪，游标=%s", self._session_cursor)

    def _fetch_new_sessions(self) -> list[dict]:
        rows = self._execute(
            self._session_db,
            f"SELECT username, summary, last_timestamp, last_msg_sender, "
            f"last_sender_display_name FROM SessionTable "
            f"WHERE is_hidden=0 AND last_timestamp > {int(self._session_cursor)} "
            f"ORDER BY last_timestamp ASC LIMIT 100",
        )
        out = []
        for row in rows:
            try:
                ts = int(float(row.get("last_timestamp", 0) or 0))
            except (TypeError, ValueError):
                continue
            if ts > self._session_cursor:
                self._session_cursor = ts
            out.append(row)
        return out

    def _session_row_to_message(self, row: dict) -> Message | None:
        """session.db 会话行 -> 框架 Message。

        summary 是最后一条消息的预览：文本消息通常为完整内容，
        群消息场景 last_msg_sender / last_sender_display_name 提供发送人。
        """
        username = row.get("username", "") or ""
        summary = (row.get("summary", "") or "").strip()
        if not username or not summary:
            return None

        # 会话类型：群聊 username 形如 xxxxx@chatroom；其余为私聊/官方号
        is_room = username.endswith("@chatroom")
        sender_id = row.get("last_msg_sender", "") or ""
        sender_name = row.get("last_sender_display_name", "") or ""
        if username == "filehelper":
            return None  # 文件传输助手是自己的记事本，不当作对话
        if not is_room and not sender_id:
            sender_id = username  # 私聊里对方就是会话本身

        # 群消息的 summary 常带「发送人：内容」前缀——只在发送人与前缀吻合时剥掉
        #（避免把恰好含冒号的正文误伤），发送人已有独立字段
        text = summary
        if is_room and sender_name and text.startswith(sender_name):
            for sep in ("：", ":"):
                if text.startswith(sender_name + sep):
                    text = text[len(sender_name) + len(sep):].strip()
                    break

        # 卡片/小程序消息的摘要不含 URL——去消息库取原始 XML 提取链接
        # （B 站分享卡片就是这种形态，不补链接则平台检测永远不触发）
        ts = int(float(row.get("last_timestamp", 0) or 0))
        if "http" not in text:
            url = self._peek_message_url(username, ts)
            if url:
                text = f"{text} {url}"
                log.info("卡片/截断消息补链成功：%s -> %s", text[:40], url[:60])
            else:
                log.info("补链未命中（摘要前 40 字）：%s", text[:40])

        # 自己发的回显：按已学到的 wxid 或刚发送的文本匹配，直接丢弃
        # （不过滤会把机器人自己的气泡当群消息记库/进社交记忆/触发自答）
        if self._self_wxid and sender_id == self._self_wxid:
            return None
        now = time.time()
        if any(r == username and t == text and 0 <= now - ts0 <= 120
               for r, t, ts0 in self._recent_sends):
            if sender_id and sender_id != self._self_wxid:
                self._self_wxid = sender_id  # 学到自己的 wxid，之后按发送人过滤
                if self._self_wxid_path:
                    try:
                        self._self_wxid_path.write_text(self._self_wxid, encoding="utf-8")
                    except OSError:
                        pass
            return None

        is_at = any(f"@{alias}" in text for alias in self._at_aliases) if is_room else True
        # 私聊即直聊：is_at=True 让路由跳过 @/窗口/插话规则（白名单在路由层把关）
        if not is_room:
            return Message(
                room_id=username,
                room_name=sender_name or username,  # 私聊没有群名，用对方昵称
                sender_id=sender_id,
                sender_name=sender_name or username,
                text=text,
                is_at=True,
                ts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
                msg_id=f"wxh-{username}-{ts}",
            )
        return Message(
            room_id=username,
            room_name=self._room_name(username),
            sender_id=sender_id,
            sender_name=sender_name or sender_id,
            text=text,
            is_at=is_at,
            ts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
            msg_id=f"wxh-{username}-{ts}",
        )

    @property
    def self_wxid(self) -> str:
        """机器人自己的 wxid（首条回显过滤后学到；学不到为空串）。"""
        return self._self_wxid

    def _peek_message_url(self, room: str, ts: int) -> str:
        """摘要被截断/不含 URL 时，查消息库取完整原文里的链接。

        覆盖两类场景：B 站卡片（type 49 的 XML <url>）、带链接的长文字消息
        （type 1，摘要截断后 URL 丢失）。内容可能是 zstd 压缩的 hex
        （WCDB 压缩），需解压；失败一律返回空串，只损失链接补全能力。
        """
        table = "Msg_" + hashlib.md5(room.encode()).hexdigest()
        try:
            rows = self._execute(
                "message_0.db",
                f"SELECT local_type, message_content FROM {table} "
                f"WHERE create_time BETWEEN {int(ts) - 10} AND {int(ts) + 10} "
                f"AND ((local_type & 4294967295)=1 OR (local_type & 4294967295)=49) "
                f"ORDER BY sort_seq DESC LIMIT 8")
        except Exception:  # noqa: BLE001
            return ""
        for r in rows or []:
            content = r.get("message_content") or ""
            raw = (bytes.fromhex(content)
                   if isinstance(content, str) and re.fullmatch(r"[0-9A-Fa-f]+", content)
                   else content)
            if isinstance(raw, str):
                raw = raw.encode("utf-8", "ignore")
            if raw[:4] == _ZSTD_MAGIC:
                try:
                    from compression.zstd import decompress  # Python 3.14+
                except ImportError:
                    return ""
                try:
                    raw = decompress(raw)
                except Exception:  # noqa: BLE001
                    return ""
            text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
            m = _APPMSG_URL_RE.search(text) or _URL_RE.search(text)
            if m:
                import html

                url = html.unescape((m.group(1) if m.groups() else m.group(0))).strip()
                if url.startswith("http"):
                    return url
        return ""

    def query_wechat_db(self, db_name: str, sql: str) -> list[dict] | None:
        """直查微信内部 SQLite（统计播报用）；失败返回 None 由调用方兜底。"""
        try:
            return self._execute(db_name, sql)
        except Exception as exc:  # noqa: BLE001 表不存在/句柄失效都不该炸播报
            log.warning("query_wechat_db %s 失败：%s", db_name, exc)
            return None

    # -- 名称解析（ChatRoom / Contact 库） --------------------------------------

    def _room_name(self, room_id: str) -> str:
        if not hasattr(self, "_room_cache"):
            self._room_cache: dict[str, str] = {}
            self._room_cache_at = 0.0
        if time.time() - self._room_cache_at > 600 or not self._room_cache:
            try:
                for entry in self._get_all_db_names():
                    db_name = entry.get("dbName", "") if isinstance(entry, dict) else str(entry)
                    if db_name != "contact.db":
                        continue
                    rows = self._execute(
                        db_name, "SELECT Name, NickName FROM chat_room LIMIT 1000")
                    for r in rows:
                        if r.get("Name"):
                            self._room_cache[r["Name"]] = r.get("NickName") or r["Name"]
                    self._room_cache_at = time.time()
                    break
            except Exception as exc:  # noqa: BLE001
                log.debug("群名刷新失败：%s", exc)
        return self._room_cache.get(room_id, room_id)

    def _member_name(self, room_id: str, wxid: str) -> str:
        # v1：直接用 wxid；群成员昵称表后续通过 ChatRoomInfo 精细化
        return wxid

    # -- 发送 -------------------------------------------------------------------

    def send_text(self, room_id: str, text: str) -> None:
        with self._send_lock:
            data = self._post_json("/SendTextMsg",
                                   {"wxidorgid": room_id, "msg": text})
            if isinstance(data, dict) and str(data.get("ret", "0")) not in ("0", "success"):
                raise WeChatHookError(f"SendTextMsg 失败：{data}")
        self._recent_sends.append((room_id, text, time.time()))

    def send_image(self, room_id: str, image_path: Path) -> None:
        with self._send_lock:
            data = self._post_json("/SendImgMsg",
                                   {"wxidorgid": room_id, "path": str(image_path)})
            if isinstance(data, dict) and str(data.get("ret", "0")) not in ("0", "success"):
                raise WeChatHookError(f"SendImgMsg 失败：{data}")

    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None:
        """视频投递（2026-09-19 真实客户端验证）：/SendImgMsg + filetype=43
        会把本地 mp4 以文件消息发进会话（WeChat 自动嗅探为视频/文件）。
        失败向上抛 WeChatHookError，由 pipeline 转人设兜底文案。
        """
        data = self._post_json(
            "/SendImgMsg",
            {"wxidorgid": room_id, "path": str(video_path), "filetype": 43},
            timeout=120,
        )
        if isinstance(data, dict) and str(data.get("ret", "0")) not in ("0", "success"):
            raise WeChatHookError(f"SendImgMsg 失败：{data}")
        if caption:
            self.send_text(room_id, caption)
