# Wechaty 桥接端（生产）

Python 主进程通过 `pelica/bridge/wechaty_bridge.py` 拉起本目录的 `bridge.js`，
用 stdin/stdout JSON 行协议通信。**本地开发不需要本目录**，直接用 mock 桥接。

## 上线步骤（在云服务器上）

```bash
cd bridges/wechaty
npm install            # 安装 wechaty + wechaty-puppet-padlocal
```

`.env` 中配置：

```
BRIDGE_MODE=wechaty
WECHATY_TOKEN=<你的 PadLocal token>
BOT_WXID=<机器人小号的微信 ID，用于过滤自发消息>
GROUP_WHITELIST=<允许的群名或群 ID，逗号分隔>
```

然后 `python main.py` 即可。首次登录需要扫码：二维码链接会打进日志
（`https://wechaty.js.org/qrcode/<...>`），扫码一次后会话缓存在
`bridges/wechaty/pelica-session` 目录，重启不用重复扫码（掉线重连由
Python 侧 watchdog 自动完成，连续失败会触发告警）。

## 协议

见 `bridge.js` 头部注释。发送视频用 `FileBox.fromFile`，视频能力依赖
PadLocal puppet 支持；若个别客户端版本不支持发视频，机器人会退化为
发送文字说明。

## 已知风险（今晚未实测项）

- 今晚没有真实 token，`bridge.js` 只做了语法检查（node --check），
  未实机登录验证；上线前建议先用一个小群灰度。
- wechaty 1.x 与新版 Node 的兼容性在部分环境需要 `--openssl-legacy-provider`，
  如启动报 OpenSSL 错误，在 Dockerfile/启动命令中补该参数。
- PadLocal 对微信多开与风控敏感：生产建议专用小号、固定 IP（云服务器）。
