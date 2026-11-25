"""F004 design 决策 15: the workbench custom system prompt and a stable prompt prefix.

* The platform admin page fills an empty field with ``chatConfig.customSystemPromptDefault``;
  the backend uses :data:`DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH` for a tenant that never
  saved one. The two must say the same thing.
* The default template is a persona only: platform abilities live in code.
* The knowledge image-viewing rules are in the system prompt from the first model
  call, so the first retrieved picture does not change the prompt mid-thread.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from bisheng.workstation.domain.services.custom_system_prompt import (
    DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH,
    default_custom_system_prompt,
)

LOCALE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "platform" / "public" / "locales"


def _chat_config(lang: str) -> dict:
    return json.loads((LOCALE_DIR / lang / "bs.json").read_text(encoding="utf-8-sig"))["chatConfig"]


def test_admin_page_default_matches_the_backend_default():
    template = _chat_config("zh-Hans")["customSystemPromptDefault"]
    assert template.replace("$t(bisheng)", "{brand}") == DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH


@pytest.mark.parametrize("lang", ["zh-Hans", "en-US", "ja"])
def test_default_template_is_a_persona_only(lang):
    template = _chat_config(lang)["customSystemPromptDefault"]
    assert "$t(bisheng)" in template
    # Platform abilities (time, citations, charts) are not the administrator's to carry.
    for platform_rule in ("{cur_date}", "[S3]", "echarts", "<chunk_id>", "\\ue200"):
        assert platform_rule not in template, platform_rule
    # The legacy template key is gone with the legacy field.
    assert "systemPrompt2" not in _chat_config(lang)


def test_default_persona_names_the_brand():
    assert default_custom_system_prompt("星河").startswith("你是 星河 智能助手")
    assert default_custom_system_prompt("  ").startswith("你是 BISHENG 智能助手")


class _Request:
    def __init__(self, messages, system_message, state):
        self.messages = messages
        self.system_message = system_message
        self.state = state

    def override(self, **kwargs):
        return _Request(
            kwargs.get("messages", self.messages),
            kwargs.get("system_message", self.system_message),
            self.state,
        )


def test_image_rules_are_appended_before_any_picture():
    from bisheng.common.image_view.loop import IMAGE_VIEW_PROMPT_RULES
    from bisheng.linsight.domain.services.kb_image_middleware import VIEW_IMAGE_GUIDE, KbImageViewMiddleware

    middleware = KbImageViewMiddleware(["search_knowledge_base"], main_model_sees_images=True)
    messages = [HumanMessage(content="你好")]
    request = _Request(messages, SystemMessage(content="base"), {"messages": messages})

    prepared = middleware._numbered(request)

    text = "".join(block.get("text", "") for block in prepared.system_message.content_blocks)
    assert text.startswith("base")
    assert IMAGE_VIEW_PROMPT_RULES in text and VIEW_IMAGE_GUIDE in text
    # The same section on every call: the prefix is byte-identical across calls.
    again = middleware._numbered(request)
    assert again.system_message.content_blocks == prepared.system_message.content_blocks
