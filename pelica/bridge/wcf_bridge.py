"""生产桥接：wcferry（Windows PC 微信客户端 Hook）。

适用场景：零成本、行为最像真人（挂在真实客户端上），部署在本项目所在的
Windows 机器。强依赖：
  1. Windows 系统 + 已登录的 PC 版微信（wcferry 39.x 要求微信 3.9.x，
     版本不匹配时 wcferry 自身会报错提示，需按其说明安装对应版本）；
  2. pip install wcferry（见 requirements-windows.txt）。

与 MockBridge/WechatyBridge 实现完全相同的 Bridge 接口。掉线看门狗：
微信退出/崩溃时按指数退避重连（重新 attach），连续失败触发告警回调。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from pelica.bridge.base import Bridge, Message, MessageHandler

log = logging.getLogger(__name__)

RESTART_BACKOFF_MIN = 15.0
RESTART_BACKOFF_MAX = 180.0
CONTACT_REFRESH_SEC = 600
MEMBER_REFRESH_SEC = 1800


class WcfBridge(Bridge):
    mode = "wcf"

    def __init__(self, on_failure=None, max_failures: int = 3, debug: bool = False):
        self._on_failure = on_failure
        self._max_failures = max_failures
        self._debug = debug

        self._wcf = None                 # wcferry.Wcf 实例（延迟创建）
        self._self_wxid = ""
        self._handler: MessageHandler | None = None
        self._stop_flag = threading.Event()
        self._listener: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._rpc_lock = threading.Lock()
        self._failures = 0
        self._healthy = False

        self._room_names: dict[str, str] = {}
        self._room_names_at = 0.0
        self._member_names: dict[str, dict[str, str]] = {}  # room -> {wxid: 昵称}
        self._member_at: dict[str, float] = {}

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        self._stop_flag.clear()
        self._attach()
        self._listener = threading.Thread(target=self._listen, daemon=True,
                                          name="wcf-listener")
        self._watchdog = threading.Thread(target=self._watchdog, daemon=True,
                                          name="wcf-watchdog")
        self._listener.start()
        self._watchdog.start()

    def _attach(self) -> None:
        from wcferry import Wcf  # Windows + wcferry 已安装才有

        log.info("连接 PC 微信（wcferry）…")
        self._wcf = Wcf(debug=self._debug)
        if not self._wcf.is_login():
            raise RuntimeError("微信未登录：请先在 PC 微信上完成登录")
        self._self_wxid = self._wcf.get_self_wxid()
        self._refresh_rooms()
        self._wcf.enable_receiving_msg()
        self._healthy = True
        self._failures = 0
        log.info("wcferry 桥接就绪，机器人 wxid=%s", self._self_wxid)

    def stop(self) -> None:
        self._stop_flag.set()
        self._healthy = False
        if self._wcf is not None:
            try:
                self._wcf.disable_recv_msg()
                self._wcf.cleanup()
            except Exception:  # noqa: BLE001
                log.exception("wcf cleanup 失败")
            self._wcf = None

    def is_healthy(self) -> bool:
        return self._healthy and self._wcf is not None

    # -- 消息 ---------------------------------------------------------------

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def send_text(self, room_id: str, text: str) -> None:
        with self._send_lock:
            self._wcf.send_text(text, room_id)

    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None:
        """mp4 以文件消息发出（wcferry 不支持视频卡片消息），随后补一条文案。"""
        with self._send_lock:
            self._wcf.send_file(str(video_path), room_id)
            if caption:
                self._wcf.send_text(caption, room_id)

    # -- 接收循环 -------------------------------------------------------------

    def _listen(self) -> None:
        log.info("消息接收线程启动")
        while not self._stop_flag.is_set():
            try:
                msg = self._wcf.get_msg(block=True)
            except Exception as exc:  # noqa: BLE001
                if self._stop_flag.is_set():
                    break
                log.error("get_msg 失败：%s", exc)
                self._healthy = False
                time.sleep(2)
                continue
            if msg is None:
                continue
            message = self._to_message(msg)
            if message is None:
                continue
            try:
                if self._handler is not None:
                    self._handler(message)
            except Exception:  # noqa: BLE001
                log.exception("消息回调异常")

    def _to_message(self, msg):
        """wcferry WxMsg -> 框架 Message。非白名单判断交给上层路由。"""
        try:
            if not msg.from_group() or msg.from_self():
                return None
            text = (msg.content or "").strip()
            if not text:
                return None
            sender_name = self._member_name(msg.roomid, msg.sender)
            return Message(
                room_id=msg.roomid,
                room_name=self._room_names.get(msg.roomid, msg.roomid),
                sender_id=msg.sender,
                sender_name=sender_name,
                text=text,
                is_at=bool(msg.is_at(self._self_wxid)),
                is_self=False,
                ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
                msg_id=str(msg.id),
            )
        except Exception:  # noqa: BLE001
            log.exception("消息转换失败")
            return None

    # -- 名字解析（通讯录 / 群成员，带缓存） -------------------------------------

    def _refresh_rooms(self) -> None:
        try:
            with self._rpc_lock:
                contacts = self._wcf.get_contacts()
            self._room_names = {
                c.get("wxid", ""): c.get("name", "") or c.get("wxid", "")
                for c in contacts
                if str(c.get("wxid", "")).endswith("@chatroom")
            }
            self._room_names_at = time.time()
            log.info("通讯录刷新：群 %d 个", len(self._room_names))
        except Exception as exc:  # noqa: BLE001
            log.warning("通讯录刷新失败：%s", exc)

    def _member_name(self, room_id: str, wxid: str) -> str:
        now = time.time()
        if now - self._member_at.get(room_id, 0) > MEMBER_REFRESH_SEC:
            try:
                with self._rpc_lock:
                    members = self._wcf.get_chatroom_members(room_id)
                self._member_names[room_id] = {
                    m.get("wxid", ""): (m.get("room_nick") or m.get("name") or m.get("wxid", ""))
                    for m in (members or [])
                }
                self._member_at[room_id] = now
            except Exception as exc:  # noqa: BLE001
                log.debug("群成员获取失败 %s：%s", room_id, exc)
                self._member_at[room_id] = now  # 失败也冷却，避免每条消息都打 RPC
        return self._member_names.get(room_id, {}).get(wxid, wxid)

    # -- 看门狗 -----------------------------------------------------------------

    def _watchdog(self) -> None:
        last_room_refresh = 0.0
        while not self._stop_flag.is_set():
            time.sleep(10)
            if time.time() - self._room_names_at > CONTACT_REFRESH_SEC:
                if self._wcf is not None and self._healthy:
                    self._refresh_rooms()
                last_room_refresh = time.time()
            ok = False
            try:
                with self._rpc_lock:
                    ok = self._wcf is not None and self._wcf.is_login()
            except Exception as exc:  # noqa: BLE001
                log.debug("is_login 检查失败：%s", exc)
            if ok:
                if not self._healthy:
                    log.info("wcferry 恢复健康")
                self._healthy = True
                self._failures = 0
                continue
            if self._healthy or self._failures == 0:
                self._healthy = False
                self._failures += 1
                log.error("wcferry 不健康（微信退出或注入失效）")
                if self._on_failure is not None and self._failures >= self._max_failures:
                    try:
                        self._on_failure(
                            f"PC 微信桥接连续 {self._failures} 次失联，请检查微信是否在线"
                        )
                    except Exception:  # noqa: BLE001
                        log.exception("告警回调失败")
                self._restart_with_backoff()
                return

    def _restart_with_backoff(self) -> None:
        delay = min(RESTART_BACKOFF_MIN * (2 ** max(self._failures - 1, 0)),
                    RESTART_BACKOFF_MAX)
        log.info("%.0f 秒后尝试重新连接微信…", delay)
        time.sleep(delay)
        if self._stop_flag.is_set():
            return
        while not self._stop_flag.is_set():
            try:
                try:
                    if self._wcf is not None:
                        self._wcf.cleanup()
                except Exception:  # noqa: BLE001
                    pass
                self._attach()
                self._listener = threading.Thread(target=self._listen, daemon=True,
                                                  name="wcf-listener")
                self._listener.start()
                self._watchdog = threading.Thread(target=self._watchdog, daemon=True,
                                                  name="wcf-watchdog")
                self._watchdog.start()
                return
            except Exception as exc:  # noqa: BLE001
                self._failures += 1
                log.error("重连失败：%s", exc)
                if self._on_failure is not None and self._failures >= self._max_failures:
                    try:
                        self._on_failure(f"PC 微信桥接连续 {self._failures} 次重连失败")
                    except Exception:  # noqa: BLE001
                        log.exception("告警回调失败")
                time.sleep(min(RESTART_BACKOFF_MIN * (2 ** max(self._failures - 1, 0)),
                               RESTART_BACKOFF_MAX))
