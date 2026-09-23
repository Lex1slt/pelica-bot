# Pelica Console —— v1.1.0 发布级开发提示词（一步完成）

> **用法**：将本文档全文发给具备本仓库访问权与命令执行能力的 AI agent（如 Claude Code / Codex CLI 级别）。
> 本提示词自包含全部决策与验收标准。规范细节见 `docs/console-design.md`（必读，与本文冲突时以本文为准）。
> **本版定位**：交付物不是"MVP 尽力而为"，而是**用户可以直接验收并对外发布**的 v1.1.0——确定性打包、干净环境验收、验收清单全 PASS 门槛、GO/NO-GO 结论。

---

## 1. 你的角色与使命

你是资深全栈工程师 + 桌面端发布负责人。你要在**一次连续工作**中，为 `pelica-wechat-bot` 交付 **v1.1.0：带管理控制台的发布版**——完成开发、测试、打包、干净环境验收、报告。**不问任何问题、不停下来等待确认**；遇到本文未覆盖的决策，按 §15 协议处理。

**完成定义（DoD）**：
1. 功能 = 设计文档的 P0 全集（§5），质量 = 发布级（非毛坯：三态齐备、文案统一、无报错）。
2. 交付 `dist/pelica-console-1.1.0-x64-setup.exe` 安装包：**零 Python 依赖、自包含**，非开发者双击即用。
3. §14 验收清单 A–E 五组**全部 PASS**。任何一项无法 PASS，按 §15 修复重试；仍失败则报告 NO-GO 并给出根因证据，**禁止静默降级交付形态**。
4. 合格标准：干净安装的普通用户 10 分钟内完成首次配置并测试成功（沙箱收到第一条角色回复 + 启用一个群）。

## 2. 硬环境事实（不许重新探测后推翻）

- Windows 11，Git Bash 可用；UAC 静默提权已开启（winget 静默安装可用）。
- Python **3.14.7**，虚拟环境在 `.venv/`（开发模式用 `.venv/Scripts/python`）。
- Node **v26**（npm 可用；统一用 npm，不引入 pnpm）。
- 本仓库是生产在跑的机器人项目：微信接入走 wxhook（微信 4.1.10.27 + version.dll 注入）；mock 桥全功能可跑。
- 当前 `.env` 内含**真实有效的 API Key**：导入数据库时加密存放；任何日志/输出/文档/测试/验收报告中不得出现明文；不修改、不删除、不移动该文件。
- 仓库已有 pytest 套件 `tests/`（mock 桩，无需真实 Key 即可通过）。
- 现有发布流：`scripts/package_release.py` 产 `dist/` 两资产（代码 zip + 预构建语料 zip），`docs/RELEASE_v1.0.0.md` 是发布说明模板，tag v1.0.0 已存在。**本任务的发布版 = v1.1.0，但 git commit/push/发 Release 一律由用户手动执行，你不做。**

## 3. 开工前必读（按序）

1. `docs/console-design.md` —— 完整设计规范（本提示词实现其 P0 子集 × 发布级质量）
2. `main.py` —— Core 入口（`--bridge mock|wxhook|wechaty|pyweixin`、`--smoke`、`--no-weekly/--no-douyin`）
3. `pelica/config.py`（Settings/load_settings）、`pelica/character.py`（apply_character，`CHARACTER` env 切角色）
4. `pelica/pipeline/router.py`（GroupBot）——只读理解，不修改默认行为
5. `pelica/bridge/mock_bridge.py`、`scripts/run_mock_chat.py`（沙箱复用的装配方式）
6. `characters/*.toml` + `*.persona.md`（角色包双文件格式，必须保持兼容）
7. `.env.example`、`tests/conftest.py`
8. `scripts/package_release.py`、`docs/RELEASE_v1.0.0.md`（发布资产组织与文案风格）

## 4. 发布形态定义（铁律，不可自行变更）

### 4.1 安装包与自包含

```
pelica-console-1.1.0-x64-setup.exe        (Tauri 2 + NSIS, 安装语言 zh-CN)
  ├─ Tauri 壳（WebView2——Win11 内置，随安装器引导旧系统装运行时）
  ├─ resources/gateway-dist/              (PyInstaller onedir：FastAPI 网关 + pelica 核心
  │                                          + 全部依赖，零 Python 依赖)
  └─ resources/characters/                (内置三角色包：pelica/kaltsit/paimon)
```

### 4.2 数据目录解析（网关启动时按序取第一个可用）

1. env `PELICA_HOME`
2. `%APPDATA%\pelica-console\` —— **发布版默认**（`config.db`、日志、备份、导入的语料）
3. `<仓库根>\data\` —— 开发模式（与现有 `main.py` 共存，不冲突）

角色包/语料发现顺序：数据目录 → 安装包 resources 内置 → 仓库目录（仅开发）。**写入永远进数据目录，不改安装目录**（Program Files 不可写）。开发模式若 `%APPDATA%\pelica-console` 已存在则优先用仓库 `data/`——判定规则：CWD 是本仓库即开发模式。

### 4.3 双入口

- **发布**：安装 exe → 开始菜单/桌面「Pelica Console」→ 壳拉起 gateway-dist 网关。
- **开发/本项目用户**：仓库根 `控制台.bat`：`.venv` 直跑网关 + dev 前端 + 开浏览器（**这是开发调试形态，不作为发布交付物**）。

### 4.4 语料不内嵌安装包（260MB+，独立更新）

- 已有项目用户：首启从数据目录/仓库发现 `data/*.db`，零摩擦。
- 全新用户：沙箱在无语料时走人设直答路径（router 的自由对话路径），**照样有角色化回复**；语料库页提供 [导入本地 zip / 指向已有 db]；向导完成页提示"完整剧情问答需导入语料包"。

## 5. 交付范围（功能 = P0 全集，质量 = 发布级）

功能 16 项与排除清单见 `docs/console-design.md` §7 P0 段（**逐条实现，不得增删**：网关/前端与设计系统/首启向导 8 步/仪表盘/方案中心/人设/语料库与检索测试台/群与私聊白名单/模型与 API/功能开关三套餐/测试沙箱/实时日志/本地备份/诊断体检/启动器/Tauri 壳与托盘 + 网关 pytest）。补充发布级要求：

- **Tauri 壳为必须项**（托盘三态、开机自启询问、最小化到托盘）；工具链按 §6 安装。
- **每个页面三态齐备**：加载（骨架屏）、空态（插图+引导动作）、错误态（翻译文案+重试）。
- 中文文案全站统一（「。」结尾、按钮动词开头）；快捷键 Ctrl+K 面板、Ctrl+Shift+S 快速沙箱。
- 浏览器控制台零 error 零 warning；TypeScript strict + eslint 零错误。
- 设计令牌照设计文档 §2（暗色默认 + 亮色跟随系统；佩丽卡橙 #FF7A1A）。
- 首启第②步风险文案**一字不改**：
  > 本程序的微信接入方式（WeChat-Hook）通过 DLL 注入修改微信客户端行为，不属于微信官方支持的接口。使用本程序存在账号被限制或封禁的风险。强烈建议：仅使用小号运行本程序；不要在承载重要账号的电脑上同时使用 hook。
  配勾选框「我已了解上述风险，将使用小号」，不勾不能下一步。

架构/schema/API/错误翻译表：分别照设计文档 §1、§4、及 `docs/console-design.md` §5.5 的翻译表实现（401→密钥无效→[去修改]；429→频控；insufficient_balance→余额不足；ECONNREFUSED 127.0.0.1→桥接未启动→[查看诊断]；timeout→重试；其他→原文+[复制]）。API 端点清单见下。

```
GET /api/health|/api/bootstrap|/api/settings  PUT /api/settings
GET/POST /api/profiles  POST /api/profiles/{id}/apply|/duplicate  POST /api/profiles/export|/import
GET/POST/PUT/DELETE /api/personas[/{id}]  POST /api/personas/{id}/rollback  PUT /api/personas/{id}/enable
GET /api/corpora  POST /api/corpora/{id}/reindex  GET /api/corpora/tasks/{tid}  POST /api/corpora/test-query
GET/POST/PUT/DELETE /api/groups[/{id}]  POST /api/groups/export|/import
GET/POST/PUT/DELETE /api/private-users[/{id}]
GET/POST /api/providers[/{id}]  POST /api/providers/{id}/test
GET/PUT /api/flags  GET /api/flags/presets  POST /api/flags/presets/{name}/apply
POST /api/sandbox/run  GET /api/logs/ws(WS)  GET /api/logs/recent
GET /api/audit  POST /api/audit/{id}/undo
POST /api/backup  POST /api/restore  GET /api/diagnostics
POST /api/core/start|stop|restart  POST /api/wizard/step
```

## 6. 打包与发布流水线（必须完成，不是加分项）

### 6.1 工具链（一次安装，全部静默；新开 shell 使 PATH 生效）

```
winget install --id Rustlang.Rustup -e --silent
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --silent \
  --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --quiet --norestart"
```

WebView2 Win11 自带；NSIS 由 Tauri 构建器自动下载。

### 6.2 网关打包（PyInstaller onedir）

- 入口 `gateway/__main__.py`；产物 `gateway-dist/pelica-gateway.exe`（onedir 目录）。
- 已知坑预案：curl_cffi / opencv-headless / compression.zstd 需 `--collect-all`/hidden imports/数据文件钩子；逐个验证 import 直到纯净 shell 下可跑。
- **纯净验证**：在剥离 `.venv` 的 PATH（`env -u` 等效方式或新 cmd 会话仅系统 PATH）下运行 `pelica-gateway.exe`，必须输出 `PELICA_GATEWAY_READY {...}` 握手行。

### 6.3 壳与安装包（Tauri 2）

- `console/src-tauri/tauri.conf.json`：productName `Pelica Console`，version **1.1.0**，identifier 如 `com.pelica.console`；resources 带 `gateway-dist/` 与 `characters/`；壳从 resource 目录 spawn 网关 exe 并读 stdout 握手行取 port/token；NSIS 安装语言 zh-CN，允许自定义安装目录。
- 托盘三态（运行/静默/离线）；关闭按钮=最小化到托盘（右键可退出）；开机自启默认关、向导完成页询问一次。

### 6.4 编排脚本 `scripts/package_console.py`

1. 构建 gateway-dist（调 PyInstaller）；
2. `npm run tauri build`；
3. 产出 `dist/pelica-console-1.1.0-x64-setup.exe` + 生成 `.sha256`；
4. 生成 `docs/RELEASE_v1.1.0.md` 草稿（风格对齐 `RELEASE_v1.0.0.md`：新功能、安装三步、升级说明、已知限制）；
5. 更新 `README.md` 增加「图形控制台」章节（安装、三步上手、截图占位、控制台.bat 开发入口）。
- 版本一致性：gateway `__version__` = package.json = tauri.conf.json = **1.1.0**，RELEASE 文档同步。

## 7. 架构铁律

1. 三进程：壳（Tauri）↕ 网关（gateway-dist 或 .venv）↕ Core（`main.py` 子进程）。壳零直接文件访问。
2. 网关仅 127.0.0.1 随机端口 + Bearer token；CORS 仅放行本机 dev 端口；启动握手行 `PELICA_GATEWAY_READY {"port":..,"token":".."}`。
3. 配置主存储 `<数据目录>/config.db`（SQLite WAL，schema 照设计文档 §4 全表）；`.env` 为导入源/导出物，永不被网关改写。
4. 不修改 `pelica/` 现有默认行为（例外仅：纯增量函数/带默认值参数，且全量测试保持绿）。新依赖只进 `requirements.txt`（fastapi/uvicorn/pyinstaller 及必需项，最小化）。
5. 网关自身日志落 `<数据目录>/logs/gateway.log`。
6. PowerShell 脚本（如需）不写中文注释；任何 `RedirectStandard*` 前先备份旧日志。
7. 重建语料索引前必须先停 Core（防 sqlite locked）。

## 8. 工程红线（违反任一即返工）

1. SQL 一律参数绑定；禁止拼接/format/f-string 组装 SQL。
2. 源码/示例/测试/报告中**不得出现任何可用凭据字面量**；测试只用显式假占位（如 `sk-TEST-FAKE`）。
3. Key 只存 DPAPI 密文（ctypes `CryptProtectData`，失败拒绝落库）；任何 API 响应、日志、WS、导出文件不出现明文；导出前扫描剥离并明示"已自动去除 N 个密钥"。
4. 私聊空表 = 私聊关闭（继承现有语义）；管理员行不可删。
5. 发布版数据只写数据目录，不写安装目录。
6. 不自动 `git commit/push`、不发布 GitHub Release——留给用户。
7. 现有 `tests/` 全绿是每次阶段检查的门槛。

## 9. 开发顺序（建议 DAG）

网关骨架（握手/token/config.db/审计）→ 前端脚手架 + 设计系统组件 →（并行）方案中心+人设 / 白名单 / API 配置 → 功能开关 → 沙箱+检索测试台 → 向导 → 日志/备份/诊断 → `控制台.bat` 开发入口全量自测 → 工具链安装 → PyInstaller 打包+纯净验证 → Tauri 壳+托盘+安装包 → `package_console.py` → 干净环境验收剧本（§13）→ 全清单自检（§14）→ 报告（§16）。

## 10. 沙箱实现要点

`gateway/sandbox.py` 进程内构造 MockBridge + GroupBot（参考 `run_mock_chat.py` 装配），注入当前有效配置；若 GroupBot 不暴露中间态，允许双轨：`Retriever` 单独跑一次取证据展示 + GroupBot 取回复。无语料时自由对话路径必须仍出角色化回复（§4.4）。

## 11. 测试要求

- `gateway/tests/` pytest：config.db CRUD / 审计与 undo / DPAPI 加解密往返 / 白名单 env 注入语义（群空=全放行、私聊空=关闭）/ 沙箱端到端（mock："@佩丽卡 你好"→非空回复；无 Key 时跳过 LLM 断言只验管道不炸）/ 日志脱敏（假 `sk-` 记录验证已掩码）/ 数据目录解析优先级。
- 现有 `tests/` 全量保持绿。
- 前端：构建零 TS/eslint 错误（组件单测不强制，纯函数工具最小覆盖）。

## 12. 歧义处理协议

- 设计未覆盖且**不影响**发布形态/安全/验收标准的决策：选最保守、向后兼容方案，记入仓库根 `DECISIONS.md`（`#序号 决策 理由`），继续。
- **影响发布形态、安全红线、验收清单的歧义不允许自行决定**——按默认实现（本文档口径），记 DECISIONS.md 说明按哪条口径执行。

## 13. 干净环境验收剧本（必须实际执行，不是纸面检查）

用 `PELICA_HOME=%TEMP%\pelica-console-clean`（或安装器自定义数据目录）隔离，全程留证据（命令+输出摘要）：

1. **纯净安装**：`setup.exe /S /D=<临时目录>`（NSIS 静默）→ 安装完成无报错。
2. **无 Python 验证**：临时重命名 `.venv`（验收后恢复）→ 启动「Pelica Console」→ 托盘运行态 → 握手成功 → **网关不依赖仓库任何路径**。
3. **10 分钟剧本**（计时，从双击图标起）：向导 8 步——跳过③(连接微信，mock) → ④选佩丽卡 → ⑤导入真实 Key(.env 内容手工粘贴，界面不回显) → 测试连接绿 → ⑥沙箱「@佩丽卡 你好」收到角色化回复 → ⑦启用示例群(默认仅@触发+冷却) → ⑧完成。**目标 ≤10 分钟**。
4. **功能抽查**：改人设昵称保存→版本历史+1→undo 恢复；群白名单增删；备份→删配置→恢复；诊断页体检全绿(微信版本项允许橙警——开发机版本非 4.1.10.27 属预期)。
5. **升级剧本**：`PELICA_HOME` 指向仓库 `data/` 备份副本 → 首启自动导入 `.env`（真实 Key→密文）→ 测试连接绿 → `grep` 不到明文。
6. **卸载**：卸载器跑完 → 安装目录清除 → `%APPDATA%\pelica-console`（用户数据）保留。
7. **安装包体检**：setup.exe 存在 + SHA256 文件正确；VirusTotal 不强制（无网关限制时上传哈希即可，失败不阻塞）。

## 14. 验收自检全清单（五组全部 PASS 才算完成；逐项记录命令与结果）

```
A 构建（6）
 A1 npm 构建前端零 TS/eslint 错误          A2 pytest tests/ 全绿
 A3 pytest gateway/tests/ 全绿             A4 gateway-dist 纯净 shell 握手成功
 A5 tauri build 产 setup.exe               A6 版本号四处一致 = 1.1.0

B 功能（11）
 B1 网关握手行 + 无 token 请求 401          B2 向导 8 步全程走通(mock)
 B3 沙箱@佩丽卡→角色化回复+证据+提示词      B4 Key 导入→测试连接绿
 B5 日志与 WS 中无明文 sk-                 B6 群白名单增删→Core 重启 env 注入正确(群空=全放行验证)
 B7 人设保存双文件同步→undo 恢复            B8 备份→删→恢复闭环
 B9 三套餐一键应用生效                      B10 托盘三态+最小化到托盘     B11 全页面无 console 报错

C 发布（5）
 C1 静默安装成功                            C2 .venv 重命名后发布版仍可跑(零 Python 依赖)
 C3 10 分钟剧本达标(计时)                   C4 升级剧本(.env 导入)通过    C5 卸载干净+用户数据保留

D 安全（4）
 D1 data/config.db 内无明文 sk-            D2 导出文件剥离密钥并提示
 D3 日志脱敏验证(假 Key 注入)               D4 SQL 参数绑定代码走查(全部数据访问点)

E 文档（3）
 E1 README 控制台章节                       E2 docs/RELEASE_v1.1.0.md 草稿  E3 DECISIONS.md 完整
```

## 15. 失败处理协议

- 任何验收项 FAIL：定位→修复→重跑该项及其依赖项，**最多 3 轮**。
- 3 轮后仍 FAIL：最终报告标 **NO-GO**，列阻塞项根因 + 已尝试方案 + 建议人工介入点；其余 PASS 项照常报告。
- **禁止的降级**：Tauri→纯浏览器、PyInstaller→.venv 直跑、砍验收项。这些是发布形态本身，降了就是 NO-GO。

## 16. 完成报告格式（最后输出给用户）

1. **结论：GO / NO-GO**（一句话）
2. §14 清单逐项结果（组-编号 + PASS/FAIL + 关键证据一行）
3. 干净环境剧本执行记录（步骤、计时、截图/输出摘要说明）
4. DECISIONS.md 全文
5. 交付物清单（目录树 + 安装包路径 + SHA256）
6. 用户 3 步上手（安装→向导→沙箱）与 3 步开发入口（控制台.bat）
7. 给用户的发布操作指引（建议的 git tag、Release 资产清单——提醒：需用户手动执行）
8. 已知限制与 P1 建议（各 ≤5 条）
