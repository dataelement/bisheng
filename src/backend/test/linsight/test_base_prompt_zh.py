"""Task mode's Chinese base prompt is appended to the main graph's prompt, and only there."""

from __future__ import annotations

import inspect

import pytest
from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services.agent_factory import (
    _build_linsight_system_prompt,
    _build_researcher_subagent,
    create_linsight_agent,
)
from bisheng.linsight.domain.services.base_prompt import LINSIGHT_BASE_PROMPT_ZH, with_base_prompt


def test_base_prompt_follows_the_main_prompt():
    assert with_base_prompt("主提示词") == f"主提示词\n\n{LINSIGHT_BASE_PROMPT_ZH}"


async def test_model_sees_the_chinese_base_prompt_and_no_english_one(monkeypatch):
    """The real graph: the Chinese text reaches the model exactly once, and the
    framework adds no English base prompt of its own next to it."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from bisheng.core.config.settings import LinsightConf
    from bisheng.linsight.domain.services import agent_factory

    seen: list[str] = []

    class _Model(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted"

        def _get_ls_params(self, stop=None, **kwargs):
            # Own provider: the factory registers a process-wide profile per provider.
            return {"ls_provider": "f004-base-prompt", "ls_model_name": "scripted"}

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.extend(
                "".join(b.get("text", "") for b in m.content_blocks) for m in messages if isinstance(m, SystemMessage)
            )
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(_Model(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(id="sv-bp", session_id="chat-bp", tenant_id=1, user_id=1, question="q", api_meta=None)

    agent = await create_linsight_agent(session, [])
    await agent.ainvoke({"messages": [("user", "你好")]}, config={"configurable": {"thread_id": "t-bp"}})

    system_text = "".join(seen)
    assert system_text.count(LINSIGHT_BASE_PROMPT_ZH) == 1
    assert "You are a deep agent" not in system_text


@pytest.mark.parametrize("unattended", [False, True])
def test_step_zero_the_question_rule_points_at_exists(unattended):
    prompt = _build_linsight_system_prompt(True, unattended=unattended)
    assert "\n0. 【" in prompt


def test_only_the_main_graph_gets_the_base_prompt():
    source = inspect.getsource(create_linsight_agent)
    assert source.count("with_base_prompt(") == 1
    assert "LINSIGHT_BASE_PROMPT_ZH" not in inspect.getsource(_build_researcher_subagent)
