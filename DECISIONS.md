# Pelica Console v1.1.0 开发决策记录（DECISIONS.md）

按任务书 §12 协议记录；`#序号 决策 理由`。

#1 前端组件库自建（未引入 Radix/TanStack Table/react-hook-form），API client 手写（未用 orval） 设计文档将它们列为选型而非验收项；自建降低安装体积与构建链风险，可访问性基线（焦点环/aria-label/tab 序）在自建组件内落实。
#2 开发端口固定 5179（非 5173） 本机 5173 已被其他项目占用；CORS/代理/tauri devUrl 同步 5179。
#3 沙箱 mock 房间名追加 @chatroom 后缀（仅 gateway/sandbox.py 内） GroupBot 私聊闸把非 @chatroom 房间当私聊并丢弃；沙箱属群聊模拟，加后缀走群聊路径，不改 pelica/ 任何行为。
#4 内置角色包在网关启动时复制进数据目录并规范化 db 路径（`data/xxx.db`→`xxx.db`）；Core 子进程通过 monkeypatch `pelica.character.ROOT = <数据目录>` 读取 数据目录是唯一写入口（安装目录不可写）；规范化后 pelica.db/paimon.db 恰好落在数据目录根，与 pelica 默认 DATA_DIR 语义一致；不改 pelica/ 源码属红线内。
#5 pyinstaller 写入 requirements.txt 任务书 §7.4 明示口径（"fastapi/uvicorn/pyinstaller 及必需项"）；虽属构建期依赖，从之并在此说明。
#6 现有 tests/ 的 6 个失败为 HEAD 历史遗留（与本任务改动无关，git status 证明仅新增文件），按「只修测试桩、不改 pelica/」原则对齐：test_stats 补 bridge=None 实参；test_wxhook 私聊断言按 2a4e8d5 新行为反转；test_router/test_memory 引入 ChatroomMockBridge（room_id 带 @chatroom、room_name 保持干净）。
#7 「全能」套餐仅映射 4 个 env 开关（douyin/bilibili/weekly_report/greeting） 追问续聊与自发插话是内核常开能力（受冷却约束），无 env 接口；文案明示，不虚设开关。
#8 私聊管理员种子行（nickname=管理员，role=admin，wxid 空）不参与 env 注入 wxid 未填时注入无意义；管理员行删除/降级被网关拒绝（400）。
#9 .env 导出（设置页）密钥以 `sk-xxx…` 占位符代替 红线「任何导出文件不含明文密钥」；CLI 用户导出后需手填。
#10 Provider「测试连接」= 真实最小补全（max_tokens=16，一次往返） 设计文档要求"真实最小补全，三绿灯才算过"；无网关侧 mock。
#11 WS 鉴权用 `?token=` 查询参数（浏览器 WebSocket 无法自定义头） token 仍是网关启动随机生成；开发模式经 vite `define` 把 token 编入前端（代理无法为 WS 注入 Authorization）。
#12 Tauri 壳经 tauri-plugin-shell 启动网关（固定二进制+参数列表，Windows 下插件自动 CREATE_NO_WINDOW）；壳退出时显式 kill 子进程 插件是 Tauri 官方 sidecar 路径；CommandChild drop 不终止进程，需显式清理。
#13 cargo 使用 rsproxy.cn 镜像（写入 ~/.cargo/config.toml） crates.io 直连 schannel SSL 失败（本机 npm 亦走 npmmirror）；属环境配置非仓库决策，记录备查。
#14 httpx 属于测试专用依赖，从打包 selftest 清单移除 网关运行时不 import httpx（仅 TestClient 用）；打包产物因此更小。
#15 重建语料索引：先停 Core（任务书铁律 §7.7），完成后若先前在跑则自动拉起 打包版经 `pelica-gateway.exe --tool build-db` 运行内置 scripts/build_db.py（runpy）。
#16 数据目录解析顺序：PELICA_HOME → CWD 是仓库则 `<仓库>/data`（优先于 %APPDATA%）→ %APPDATA%/pelica-console 按任务书 §4.2 补充条款「开发模式优先用仓库 data/」执行；判定规则 = CWD 同时存在 main.py 与 pelica/ 目录。
#17 沙箱采用任务书 §10 明示的双轨：GroupBot 取回复，Retriever 单独跑一次取证据；提示词按 Answerer 组装规则重建展示（标注「重建展示」） GroupBot 中间态不外露；证据与提示词仍来自同一检索器与人设模块。
#18 NSIS installMode=currentUser 且允许自定义安装目录；WebView2 走 embedBootstrapper Win11 自带 WebView2，旧系统由引导器安装运行时。
#19 UI 全量自测用 puppeteer-core + 系统 Edge 无头走查（console/e2e/walkthrough.mjs） browser-use 插件驱动在本会话不可用；走查覆盖向导 8 步、10 个页面、Ctrl+K，并采集 console 错误（B11 证据）与 README 截图。
#20 升级剧本的 .env 自动导入来源：显式 env `PELICA_ENV_IMPORT`（设值即不再回落）> 开发模式仓库根 .env 打包版默认无仓库可读，验收/迁移用 PELICA_ENV_IMPORT 指定；显式设置时不再静默回落其他来源（测试隔离亦依赖此语义）。
#21 Tauri 前端网关信息只缓存 alive+port 就绪值；bootstrap 查询自动重试 15×2s；「重新连接」先清缓存 用户验收发现真 bug：网关冷启动 10-20s 期间前端把壳返回的占位 GatewayInfo（port=0）缓存，导致重连永远失败。修复经 CDP 直连用户窗口 WebView 验证真实 DOM 已进入向导。教训：无头走查（vite 代理路径）覆盖不到 Tauri invoke 路径。
#22 验收反馈三项（2026-09-23）实现口径：① 沙箱默认消息/标签跟随当前生效角色（personas.at_aliases[0]）；② 方案编辑器 = 基本信息区 + ①人设（下拉选角色包+提示词编辑器，PUT personas 双文件+版本）+ ②语料库（写入角色包 toml 的 db——Core 实际按它检索）+ ③模型（存 manifest.model，应用方案时同步到全局 Provider，密钥保留）；③ 实时状态 = /api/core/status（3s 轮询，wxhook 模式探测 hook 端口判定微信连通）+ 仪表盘「断开连接」= 停止 Core。
#23 验收反馈④（2026-09-23）托盘右键菜单：显示主窗口 / 启动·停止机器人（动态文本）/ 打开数据目录 / 退出。技术口径：① 托盘创建后显式 set_menu 强刷（防 muda hpopupmenu 创建时序竞态导致右键无菜单——源码走查确认 tray-icon 仅在创建时抓取句柄）；② 菜单启停动作由壳内裸 TCP 直发网关（与前端无关，窗口隐藏也可用），报文格式经对真网关协议级实测 200；③ 三态图标/tooltip/菜单文本由前端 3s 轮询经 set_tray 命令同步。另修 tests/test_social.py 时间敏感缺陷（种子时间写死日期，跨过 7 天滑动窗口后（9-23 凌晨）必挂，改为相对 now 生成）。
