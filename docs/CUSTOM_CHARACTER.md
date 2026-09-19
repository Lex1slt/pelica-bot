# 定制你自己的角色机器人

pelica-wechat-bot 的机器人代码与「角色」完全解耦：**角色 = 角色包（人设）+ 语料库（知识）**。
换一个角色 = 换一份角色包 +（可选）换一套语料，不需要改任何 Python 代码。

```
characters/
  pelica.toml            # 角色配置：名字/触发词/专用数据库
  pelica.persona.md      # 系统提示词（人设全文）
  kaltsit.toml           # 示例：复用同一套明日方舟语料的另一个角色
  kaltsit.persona.md
```

## 一、角色包（必须）

复制 `characters/pelica.toml` 为 `characters/<你的角色id>.toml`：

```toml
[character]
id = "yourchar"                          # 与文件名一致
display_name = "你的角色名"
wechat_name = "角色名"                    # 人设里 {name} 的值
signature = "微信签名"                    # 人设里 {signature} 的值
at_aliases = ["角色名", "英文名"]          # 群里喊这些词触发（除原生 @ 外）
db = "data/yourchar.db"                  # 该角色专用数据库
corpus_release = "agent-corpus-v2-..."   # 构建数据库用的语料版本

[persona]
file = "characters/yourchar.persona.md"  # 人设全文，支持 {name}/{signature} 占位
```

再写 `<你的角色id>.persona.md`：这个角色的说话方式、性格、经历、红线（参考
`pelica.persona.md` 的结构：你是谁/性格/说话方式/聊天节奏/剧情规矩/不许做的事）。
启用：`.env` 里加一行 `CHARACTER=<你的角色id>`，启动机器人即可。

## 二、语料库（三种来源）

数据库格式与游戏无关——任何题材（小说/动漫/原创世界观）只要整理成
「文档-行」结构就能建库。

### 来源 A：PRTS 语料（明日方舟 / 终末地，自动同步）

```bash
python scripts/sync_corpus.py            # 从 ModelScope 镜像同步最新版本
python scripts/build_db.py               # 重建 data/pelica.db（或 --db 指定其他角色库）
```

上游链路：**PRTS.chat**（版本 API 是唯一真源）→ ModelScope 镜像
（`HTiantian/prts-agent-corpus-arknights` / `-endfield`）→ 本脚本按
dataset-manifest 的 SHA-256 增量下载 bundles 并解包。

### 来源 B：现成 jsonl 语料直接建库

每个 pack 是一个目录：

```
<release>/<pack_id>/pack-manifest.json    # {"pack_id": "...", "shards": [...]}（结构校验用）
<release>/<pack_id>/shards/00000.jsonl.gz # gzip 的 JSON Lines，每行一条记录
```

每条记录：

```json
{
  "document": {
    "document_id": "novel/chapter-001",
    "display_title": "第一章",
    "document_category": "原文",
    "document_kind": "chapter"
  },
  "lines": [
    {"line_number": 1, "line_type": "dialogue", "speaker_raw": "张三", "text": "……"}
  ]
}
```

`line_type` 建议：`dialogue`（台词，权重最高）/ `narration` / `knowledge` /
`summary`。然后：

```bash
python scripts/build_db.py --db data/yourchar.db --release <你的release目录名>
```

### 来源 C：从零写小型世界观

直接手写上面格式的 jsonl.gz（哪怕只有几百行台词也能跑：FTS 检索 + 图谱
都是可选增强，小语料纯文本检索就够用）。

## 三、验证

```bash
python scripts/run_mock_chat.py           # mock 群聊试聊
```

## 四、注意事项

- `SOURCE_PHRASES`（「密录里写过」这类出处话术）目前内置为 PRTS 风格，
  其他题材可在 `pelica/llm/persona.py` 修改或人设中说明引用方式。
- 语料版权归各自上游所有：PRTS 语料 CC BY-NC-SA、游戏文本版权归游戏公司，
  分发数据库前确认权利边界。商业用途需要自行获得授权。
- 免责声明与账号风险见 README。
