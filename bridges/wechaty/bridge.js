#!/usr/bin/env node
/*
 * 佩丽卡监督 —— Wechaty 桥接端（生产用，Node 18+）
 *
 * 与 Python 主进程通过 stdin/stdout 的 JSON 行协议通信：
 *   Python -> Node: {"type":"send_text","room_id":"...","text":"..."}
 *                   {"type":"send_video","room_id":"...","path":"...","caption":"..."}
 *                   {"type":"shutdown"}
 *   Node -> Python: {"type":"ready","user":"..."}
 *                   {"type":"message","room_id","room_name","sender_id","sender_name","text","is_at","is_self","ts","msg_id"}
 *                   {"type":"heartbeat"} / {"type":"log","message"} / {"type":"error","message"}
 *
 * 启动前置：在本目录 npm install；环境变量 WECHATY_TOKEN = PadLocal token。
 * 本脚本只应由 Python 侧 WechatyBridge 拉起；本地开发请用 mock 桥接。
 */

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}
function log(message) {
  emit({ type: "log", message: String(message) });
}

let Wechaty, FileBox, PuppetPadlocal;
try {
  ({ WechatyBuilder: Wechaty } = require("wechaty"));
  ({ FileBox } = require("file-box"));
  ({ PuppetPadlocal } = require("wechaty-puppet-padlocal"));
} catch (e) {
  emit({
    type: "error",
    message: "wechaty 依赖未安装：请先在 bridges/wechaty 下执行 npm install",
  });
  process.exit(1);
}

const token = process.env.WECHATY_TOKEN;
if (!token) {
  emit({ type: "error", message: "缺少环境变量 WECHATY_TOKEN（PadLocal token）" });
  process.exit(1);
}

let bot = null;

async function main() {
  bot = Wechaty.build({
    name: "pelica-session",
    puppet: new PuppetPadlocal({ token }),
  });

  bot
    .on("scan", (qrcode, status) => {
      log(`扫码登录：status=${status}`);
      log(`如需扫码：https://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`);
    })
    .on("login", (user) => emit({ type: "ready", user: user.name() }))
    .on("logout", (user) => {
      emit({ type: "error", message: `已登出：${user.name()}，进程退出以触发重连` });
      process.exit(0);
    })
    .on("error", (err) => {
      emit({ type: "error", message: err && err.message ? err.message : String(err) });
    })
    .on("message", async (msg) => {
      try {
        const room = msg.room();
        if (!room) return; // 只处理群消息
        const talker = msg.talker();
        const self = msg.self();
        let isAt = false;
        if (!self) {
          try {
            isAt = await msg.mentionSelf();
          } catch (_) {
            isAt = false;
          }
        }
        emit({
          type: "message",
          room_id: room.id,
          room_name: await room.topic(),
          sender_id: talker ? talker.id : "",
          sender_name: talker ? talker.name() : "",
          text: msg.text() || "",
          is_at: isAt,
          is_self: !!self,
          ts: new Date().toISOString(),
          msg_id: msg.id,
        });
      } catch (err) {
        emit({ type: "error", message: `message 处理失败: ${err}` });
      }
    });

  setInterval(() => emit({ type: "heartbeat" }), 60_000);

  await bot.start();
  log("weixin bot 已启动，等待登录回调");
}

async function handleCommand(cmd) {
  if (!bot) throw new Error("bot 未初始化");
  switch (cmd.type) {
    case "send_text": {
      const room = await bot.Room.find({ id: cmd.room_id });
      if (!room) throw new Error(`找不到群 ${cmd.room_id}`);
      await room.say(cmd.text || "");
      break;
    }
    case "send_video": {
      const room = await bot.Room.find({ id: cmd.room_id });
      if (!room) throw new Error(`找不到群 ${cmd.room_id}`);
      await room.say(FileBox.fromFile(cmd.path));
      if (cmd.caption) await room.say(cmd.caption);
      break;
    }
    case "shutdown":
      if (bot) await bot.stop();
      process.exit(0);
    default:
      log(`未知指令: ${cmd.type}`);
  }
}

const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let cmd;
  try {
    cmd = JSON.parse(trimmed);
  } catch (e) {
    log(`无法解析指令: ${trimmed.slice(0, 100)}`);
    return;
  }
  handleCommand(cmd).catch((err) =>
    emit({ type: "error", message: `指令执行失败: ${err}` })
  );
});
rl.on("close", () => {
  // Python 侧关闭了管道（多半被杀），跟随退出，交由其 watchdog 重启
  process.exit(0);
});

// 未捕获异常只上报不退出，由 Python watchdog 决策重启
process.on("uncaughtException", (err) => {
  emit({ type: "error", message: `uncaughtException: ${err}` });
});
process.on("unhandledRejection", (reason) => {
  emit({ type: "error", message: `unhandledRejection: ${reason}` });
});

main().catch((err) => {
  emit({ type: "error", message: `启动失败: ${err}` });
  process.exit(1);
});
