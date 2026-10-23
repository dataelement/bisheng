"""F073: Open API runs are assembled unattended (spec AC-10, AC-21).

Prompt and tool list must change together (linsight/AGENTS.md lockstep): an
unattended run has neither the ask_user tool nor any text telling the model to
clarify first.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.unattended_run import caller_instructions, is_unattended_run

FLAG_SETS = [
    {},
    {"has_knowledge_base": True},
    {
        "has_knowledge_base": True,
        "skills_present": True,
        "has_code_interpreter": True,
        "has_web_search": True,
        "citation_handles": True,
    },
]


def _meta(**kwargs):
    return SimpleNamespace(api_meta={"channel": "open_api_v2", **kwargs})


@pytest.mark.parametrize("flags", FLAG_SETS)
def test_workbench_prompt_keeps_the_clarify_step(flags):
    prompt = agent_factory._build_linsight_system_prompt(flags.pop("has_knowledge_base", False), **flags)
    assert "ask_user" in prompt
    assert agent_factory._CLARIFY_STEP_START in prompt


@pytest.mark.parametrize("flags", FLAG_SETS)
def test_unattended_prompt_never_mentions_asking(flags):
    prompt = agent_factory._build_linsight_system_prompt(
        flags.pop("has_knowledge_base", False), unattended=True, **flags
    )
    assert "ask_user" not in prompt
    assert "先澄清" not in prompt
    assert "向用户的提问" not in prompt
    assert agent_factory._UNATTENDED_STEP_ZH.strip() in prompt
    assert "所做假设" in prompt
    assert "按任务描述要求的输出格式产出" in prompt


def test_template_markers_are_all_present():
    # A template edit that moves a marker must fail here, not ship a prompt
    # that still advertises ask_user.
    agent_factory._to_unattended_prompt(agent_factory._LINSIGHT_SYSTEM_PROMPT_TEMPLATE_ZH)


def test_caller_instructions_are_layered_under_platform_rules():
    prompt = agent_factory._with_caller_instructions("BASE", "只看合同第三章")
    assert prompt.startswith("BASE")
    assert "以平台规则为准" in prompt
    assert prompt.endswith("只看合同第三章")
    assert agent_factory._with_caller_instructions("BASE", None) == "BASE"


def test_channel_detection():
    assert is_unattended_run(_meta()) is True
    assert is_unattended_run(SimpleNamespace(api_meta=None)) is False
    assert is_unattended_run(SimpleNamespace()) is False
    assert caller_instructions(_meta(instructions="  x  ")) == "x"
    assert caller_instructions(_meta(instructions="   ")) is None
    assert caller_instructions(_meta(instructions=3)) is None
    # instructions on a workbench run are ignored
    assert caller_instructions(SimpleNamespace(api_meta={"instructions": "x"})) is None


@pytest.fixture
def factory_env(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(SimpleNamespace(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    return captured


@pytest.mark.parametrize(
    "api_meta,expect_ask_user",
    [(None, True), ({"channel": "open_api_v2", "instructions": "IN"}, False)],
)
async def test_bound_tools_and_prompt_move_together(factory_env, api_meta, expect_ask_user):
    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q", api_meta=api_meta)

    await agent_factory.create_linsight_agent(session, [])

    names = [getattr(t, "name", None) for t in factory_env["tools"]]
    assert ("ask_user" in names) is expect_ask_user
    assert ("ask_user" in factory_env["system_prompt"]) is expect_ask_user
    if not expect_ask_user:
        assert factory_env["system_prompt"].rstrip().endswith("IN")
