"""生产桥接：Wechaty + PadLocal，Node 子进程 + JSON 行管道。

Python 侧职责：
- 以 bridges/wechaty 为工作目录启动 `node bridge.js`（token 从环境变量
  WECHATY_TOKEN 传入，子进程继承）；
- stdin 发送指令（send_text / send_video），stdout 接收事件
  （message / ready / log / heartbeat / error）；
- 掉线自动重连：进程退出后按指数退避重启（1min 起，上限 5min），
  连续失败超过阈值交给告警器。

今晚边界：本模块不实机登录（无 token、不碰真实微信），协议格式与
mock 桥接完全一致，上线只差 WECHATY_TOKEN 与 `npm install`。
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path

from pelica.bridge.base import Bridge, Message, MessageHandler

log = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 300  # 秒；超过视为假死，重启
RESTART_BACKOFF_MIN = 30.0
RESTART_BACKOFF_MAX = 300.0


class WechatyBridge(Bridge):
    mode = "wechaty"

    def __init__(
        self,
        bridge_dir: Path,
        env_extra: dict[str, str] | None = None,
        on_failure=None,
        max_failures: int = 3,
    ):
        self._dir = Path(bridge_dir)
        self._env_extra = env_extra or {}
        self._handler: MessageHandler | None = None
        self._proc: subprocess.Popen | None = None
        self._writer_lock = threading.Lock()
        self._ready = threading.Event()
        self._stop_flag = threading.Event()
        self._last_heartbeat = 0.0
        self._consecutive_failures = 0
        self._max_failures = max_failures
        self._on_failure = on_failure  # 掉线告警回调(message: str)
        self._restart_thread: threading.Thread | None = None
        self._send_lock = threading.Lock()

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        self._stop_flag.clear()
        self._spawn()

    def _spawn(self) -> None:
        if self._stop_flag.is_set():
            return
        env = dict(**__import__("os").environ)
        env.update(self._env_extra)
        log.info("启动 wechaty 桥接进程：%s", self._dir / "bridge.js")
        self._proc = subprocess.Popen(
            ["node", "bridge.js"],
            cwd=str(self._dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._last_heartbeat = time.time()
        threading.Thread(target=self._read_loop, daemon=True,
                         name="wechaty-bridge-read").start()
        threading.Thread(target=self._watchdog, daemon=True,
                         name="wechaty-bridge-watchdog").start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._proc is not None:
            try:
                self._send_raw({"type": "shutdown"})
                time.sleep(1.0)
            except Exception:  # noqa: BLE001
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def is_healthy(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and time.time() - self._last_heartbeat < HEARTBEAT_TIMEOUT
        )

    # -- 消息 ---------------------------------------------------------------

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def send_text(self, room_id: str, text: str) -> None:
        self._send_raw({"type": "send_text", "room_id": room_id, "text": text})

    def send_video(self, room_id: str, video_path: Path, caption: str = "") -> None:
        self._send_raw(
            {
                "type": "send_video",
                "room_id": room_id,
                "path": str(video_path),
                "caption": caption,
            }
        )

    # -- 管道 ----------------------------------------------------------------

    def _send_raw(self, obj: dict) -> None:
        if self._proc is None or self._proc.poll() is not None:
            log.warning("桥接进程未就绪，丢弃发送：%s", obj.get("type"))
            return
        line = json.dumps(obj, ensure_ascii=False)
        with self._send_lock:
            try:
                self._proc.stdin.write(line + "\n")
                self._proc.stdin.flush()
            except Exception as exc:  # noqa: BLE001
                log.error("向桥接进程写入失败：%s", exc)

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.info("[wechaty] %s", line)  # node 侧原始输出当日志
                continue
            self._dispatch(event)
        log.warning("桥接进程输出流关闭（退出码 %s）", proc.poll())

    def _dispatch(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "message":
            self._last_heartbeat = time.time()
            if self._handler is not None:
                msg = Message(
                    room_id=event.get("room_id", ""),
                    room_name=event.get("room_name", ""),
                    sender_id=event.get("sender_id", ""),
                    sender_name=event.get("sender_name", ""),
                    text=event.get("text", ""),
                    is_at=bool(event.get("is_at")),
                    is_self=bool(event.get("is_self")),
                    ts=event.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                    msg_id=event.get("msg_id", ""),
                )
                self._handler(msg)
        elif etype == "ready":
            log.info("微信登录就绪：%s", event.get("user", ""))
            self._last_heartbeat = time.time()
            self._consecutive_failures = 0
            self._ready.set()
        elif etype == "heartbeat":
            self._last_heartbeat = time.time()
        elif etype == "log":
            log.info("[wechaty] %s", event.get("message", ""))
        elif etype == "error":
            log.error("[wechaty] %s", event.get("message", ""))

    # -- 掉线重连 --------------------------------------------------------------

    def _watchdog(self) -> None:
        while not self._stop_flag.is_set():
            time.sleep(5)
            proc = self._proc
            dead = proc is None or proc.poll() is not None
            stale = time.time() - self._last_heartbeat > HEARTBEAT_TIMEOUT
            if dead or stale:
                if stale and not dead:
                    log.error("桥接心跳超时，强制重启")
                    try:
                        proc.terminate()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                self._handle_failure("假死" if stale else "退出")
                self._restart_with_backoff()
                return

    def _handle_failure(self, why: str) -> None:
        self._consecutive_failures += 1
        log.error("桥接%s（连续失败 %d 次）", why, self._consecutive_failures)
        if self._on_failure is not None and self._consecutive_failures >= self._max_failures:
            try:
                self._on_failure(
                    f"微信桥接连续 {self._consecutive_failures} 次异常（{why}），请检查服务器"
                )
            except Exception:  # noqa: BLE001
                log.exception("告警回调失败")

    def _restart_with_backoff(self) -> None:
        if self._stop_flag.is_set():
            return
        delay = min(
            RESTART_BACKOFF_MIN * (2 ** max(self._consecutive_failures - 1, 0)),
            RESTART_BACKOFF_MAX,
        )
        log.info("%.0f 秒后重启桥接进程", delay)
        time.sleep(delay)
        if not self._stop_flag.is_set():
            self._ready.clear()
            self._spawn()
