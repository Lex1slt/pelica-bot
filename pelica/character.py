"""角色包：把「人设 + 触发词 + 专用语料库」打包成一份配置，换角色不改代码。

角色包 = characters/<id>.toml + characters/<id>.persona.md：
  [character]
  id / display_name / wechat_name / signature / at_aliases / db / corpus_release
  [persona]
  file = "characters/<id>.persona.md"   # 系统提示词全文，支持 {name}/{signature}

main.py 在 load_settings() 之后调用 apply_character(settings)：
角色包里的字段会覆盖 settings（db 路径、at_aliases），并把人设注入
pelica.llm.persona 的模块全局（Answerer 每次调用时动态读取）。
没有角色包时（如 CHARACTER=pelica 但文件缺失）保持内置佩丽卡默认值。
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from pelica.config import Settings
from pelica.llm import persona

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def _render_persona(text: str, name: str, signature: str) -> str:
    """把 persona 文本中的 {name}/{signature} 占位渲染掉；原文含其他花括号不受影响。"""
    return text.replace("{name}", name).replace("{signature}", signature)


def apply_character(settings: Settings) -> Settings:
    """按 settings.character 加载角色包，就地覆盖 settings 并注入人设。"""
    cid = (settings.character or "pelica").strip()
    toml_path = ROOT / "characters" / f"{cid}.toml"
    if not toml_path.exists():
        if cid != "pelica":
            log.warning("角色包不存在：%s（保持内置佩丽卡默认）", toml_path)
        return settings

    with open(toml_path, "rb") as f:
        pack = tomllib.load(f)

    char = pack.get("character") or {}
    name = char.get("wechat_name") or "佩丽卡"
    signature = char.get("signature") or ""

    if char.get("db"):
        db = Path(char["db"])
        settings._db_override = db if db.is_absolute() else (ROOT / db)

    if char.get("at_aliases"):
        settings.at_aliases = list(char["at_aliases"])

    persona_cfg = pack.get("persona") or {}
    persona_file = persona_cfg.get("file")
    if persona_file:
        md_path = ROOT / persona_file
        system_text = md_path.read_text(encoding="utf-8")
        persona.apply_character(
            name=name,
            signature=signature,
            system_text=_render_persona(system_text, name, signature),
        )

    settings.character_pack = {
        "id": char.get("id", cid),
        "display_name": char.get("display_name", name),
        "corpus_release": char.get("corpus_release", ""),
        "toml": str(toml_path),
    }
    log.info("角色包已加载：%s（%s，语料库 %s）",
             cid, name, settings.db_path)
    return settings
