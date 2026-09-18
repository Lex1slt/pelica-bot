"""真实 DeepSeek API 冒烟（可选）：PELICA_LIVE=1 时才运行。

不伪造结果：这个测试访问真实网络与 Key，失败即失败。
运行：PELICA_LIVE=1 python -m pytest tests/test_live.py -s
"""

from __future__ import annotations

import os

import pytest

from pelica.config import load_settings
from pelica.llm.client import DeepSeekClient, LLMError
from pelica.llm import persona

pytestmark = pytest.mark.skipif(
    os.environ.get("PELICA_LIVE") != "1", reason="需要 PELICA_LIVE=1（真实 API 冒烟）"
)


def test_live_deepseek_reply_in_persona():
    settings = load_settings()
    assert settings.deepseek_api_key, "未配置 DEEPSEEK_API_KEY"
    client = DeepSeekClient(
        settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model
    )
    reply = client.chat(
        [
            {"role": "system", "content": persona.PERSONA_SYSTEM},
            {"role": "user", "content": "【群里的管理员问你】\n佩丽卡，用一句话介绍一下你自己\n\n"
                                        "【可以参考的资料】\n1. 《佩丽卡 / 角色语音》第 10 行\n"
                                        "   作为监督，我还有很多不成熟的地方，但我已经下定了决心，责无旁贷。"},
        ],
        max_tokens=200,
    )
    assert reply
    assert persona.find_forbidden(reply) == [], f"出现机器腔：{reply}"
    assert len(reply) <= 300
    print("\n[真实回复]", reply)
