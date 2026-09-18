# 佩丽卡监督 (Pelica Bot)

基于 PRTS 语料库的明日方舟：终末地人设微信群 AI 机器人（免费 · 开源 · 本机部署）。

她的微信昵称是**佩丽卡监督**，签名是「基于 PRTS 的 AI 机器人」。
在群里像一位真人群友：被 @ 时基于 PRTS-Terrachive 语料回答明日方舟 / 终末地
剧情问题；群里出现抖音链接自动解析发视频；每周五 18:00 播报群聊统计；
不被 @ 绝不说话；不提自己是 AI——她就是佩丽卡，终末地的监督。

> ⚠️ **免责声明**：本项目通过第三方 hook 与微信客户端交互，存在违反微信用户协议、
> 账号被处罚的风险。请使用**小号**，仅供个人学习研究；与鹰角网络及腾讯无关，
> 游戏素材版权归鹰角网络所有。

## 核心特性

- 🧠 **语料图谱问答**：PRTS-Terrachive 语料（3.2 万文档 / 98 万行）+ 实体图谱 +
  trigram FTS + DeepSeek 生成——回答引用出处（「密录里写过」「档案里有」）
- 💬 **人设闲聊**：「你喜欢我吗」「今天心情怎么样」以佩丽卡口吻直答，
  附带群近况感知（成员画像、长期印象、她的「近期状态」）
- 🔄 **多轮对话**：每群记忆最近 4 轮，「那她的呢」这类追问接得住
- 📹 **抖音链接**：解析 → 下载 mp4 → 首帧缩略图 + 文件消息发进群
- 📊 **定时问候与周五播报**：每天 07:30 问早 / 23:00 查岗；周五 18:00 群统计周报
  （文本/图片/视频/表情包/拍了拍/发言 Top5，微信消息库直查）
- 🔇 **克制设计**：不被 @ 保持沉默、频控、白名单、告警通知
- 🆓 **完全免费**：LLM 走 DeepSeek API（自备 key），微信接入走本机 hook（无需付费协议）

## 快速开始

### Windows 一键安装（推荐）

到 [Releases](../../releases) 下载两个文件：`win64-setup.zip`（代码+安装器）与
`pelica.db.zip`（预构建语料数据库）。解压后双击 `安装.bat`，按
`快速开始-Windows.txt` 装好微信 4.1.10.27 + version.dll，双击 `启动机器人.bat` 上线。

### 开发者路径（本机 mock 模式，不登录微信）

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows
# Linux/macOS: .venv/bin/pip install ...

# 1) 配置 .env（参考 .env.example，至少要有 DEEPSEEK_API_KEY）
# 2) 建库：摄入语料 + 构建关系（约 1-5 分钟，语料 188MB 解压后建 572MB 数据库）
.venv/Scripts/python scripts/build_db.py

# 3) 交互式 mock 群聊（「测试群|管理员|@佩丽卡 帝江号是什么」）
.venv/Scripts/python scripts/run_mock_chat.py

# 或者一次性冒烟：
.venv/Scripts/python main.py --smoke
```

## 架构

```
微信群 ⇄ 桥接层(Bridge) ⇄ 消息路由(GroupBot) ⇄ 管道
            │                    │            ├─ 剧情问答：缓存 → 检索 → DeepSeek → 人设清洗
            │                    │            │   （每群记忆最近 4 轮，「那她呢」这类追问接得住）
            │                    │            ├─ 抖音管道：检测→解析→下载→发视频（无 LLM）
            │                    │            ├─ 现实话题：谜语人带过（不调模型）
            │                    │            └─ 每周播报：SQLite 统计 → 本地生成文案
            │                    └─ 过滤：自发消息 / 群白名单 / 未@沉默 / 频控
            ├─ MockBridge（本地开发，控制台收发）
            ├─ WcfBridge（Windows 本机挂真实 PC 微信，免费 —— 当前推荐路线）
            └─ WechatyBridge（云服务器 + PadLocal，付费备选）
```

**像人一样社交**：`pelica/social.py` 把消息流水变成社交认知——每次回复注入
群近况（7 天活跃度、最活跃的人）、提问者画像（夜聊比例、@ 次数、最近一句）、
长期印象（每周播报时 LLM 以佩丽卡口吻给活跃成员写一句话印象，存
`social_notes` 表）和她自己的「近期状态」（由群活跃度与时刻推导）。
「你喜欢我吗」「今天心情怎么样」这类日常话题走自由对话路径：不查语料、
人设直答；剧情设定类问题无证据时依旧守门，绝不现编。

检索是 GraphRAG 思路的本地轻量实现：
1. **实体锚定**：问题 → 别名表最长匹配 → 语料实体（语料自带 55 万条实体标注）；
2. **图扩展**：沿 `speaker`（说话人→提到）与 `cooccur`（同文档共现）关系游走 1-2 跳；
3. **证据召回**：实体 → 原文行；同时 jieba 分词 + 3 字滑窗走 SQLite FTS5 trigram；
4. **融合排序**：图分数 × 证据类型 × 问题词重合度 × FTS 稀有度加权 × 长度归一；
5. **守门**：证据不足或全文线索与问题对不上时，按人设坦白说不清楚——不编造。

所有引用在证据包里都是《篇章名》第 N 行格式，回给用户时口语化成
「密录里写过」「档案里有」「语音里提过」。

人设提示词固定在 messages 首位（利用 DeepSeek Context Cache）；回复经
`sanitize_reply` 清洗：去 markdown、机器腔黑名单（「作为AI」「我的语料库」
等）直接打回重写或换人设兜底句。

## 目录

| 路径 | 说明 |
|---|---|
| `pelica/` | 主包（config/db/corpus/graph/retrieval/llm/pipeline/bridge/douyin/stats） |
| `bridges/wechaty/` | 生产桥接端（Node + wechaty-puppet-padlocal，上线时 `npm install`） |
| `corpus/releases/` | PRTS-Terrachive 语料（不入 git，服务器只读挂载） |
| `data/` | `pelica.db`（语料+图谱+消息+缓存）、抖音下载缓存、心跳文件 |
| `scripts/` | build_db / run_mock_chat / healthcheck |
| `deploy/` | 部署脚本（docker / bare-metal + systemd） |
| `analysis/persona_samples.txt` | 佩丽卡台词样本（人设依据） |

## 配置（.env）

全部配置见 `.env.example`：LLM Key、桥接模式（mock/wechaty）、PadLocal
token、群白名单、@ 触发词、路径、抖音开关、每周播报时刻、告警 webhook。
代码里不写死任何密钥、路径、群 ID；`.env` 已被 .gitignore 排除。

## 部署（Ubuntu 22.04，2核4G）

```bash
# 方式一：Docker（推荐）
./deploy/deploy.sh docker

# 方式二：裸机 + systemd
./deploy/deploy.sh bare
```

- 语料目录只读挂载（`./corpus:/app/corpus:ro`），`data/`、`logs/` 为持久卷；
- 掉线重连：WechatyBridge watchdog 指数退避重启（30s→5min 封顶）；
- 连续失败 ≥3 次触发告警（企业微信机器人 webhook 或任意 JSON webhook）；
- 容器 HEALTHCHECK 基于心跳文件 + 数据库只读探测。

首次部署需要：把 `corpus/releases/` 同步到服务器，先跑一次
`python scripts/build_db.py` 建库（或直接把本机 `data/pelica.db` 传上去）。
`.env` 设 `BRIDGE_MODE=wechaty` 并填 `WECHATY_TOKEN`，首次启动扫码一次。

## 测试

```bash
.venv/Scripts/python -m pytest tests/ -q        # 全量（不联网）
PELICA_LIVE=1 python -m pytest tests/test_live.py -s   # 真机 DeepSeek 冒烟
```

## 已知边界

- **抖音解析（已打通，2026-09 真实链接实测）**：零成本自研方案 = curl_cffi
  Chrome TLS 指纹（绕 Argus 拦截）+ ttwid 注册并显式设到 .douyin.com/.iesdouyin.com
  域 + 移动 UA 访问分享页取 `_ROUTER_DATA.videoInfoRes.item_list` + playwm→play
  去水印。踩坑记录全在 `pelica/douyin/parser.py` 头注释。`abogus.py`（a_bogus
  签名逆向实现，来源 amxsa/douyin_abogus_python）作为被签 API 的预留件保留。
  抖音反爬再变时，可启用 `DOUYIN_RESOLVER_API` 指向第三方服务兜底；
- `bridge.js` 已通过语法检查与协议测试（桩进程），未做实机微信登录验证；
- 检索排序阈值（`retriever.py` 顶部常量）是按当前语料调的，换语料后跑
  `scripts/qa_regression.py` 回归（12 条基线，2026-09-18 全过）再微调。
