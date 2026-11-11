"""F009: data-analyst subagent (NL2SQL) and ask-when-necessary clarification.

Spec: features/v3.1.0-beta1/009-taskmode-data-analyst/spec.md. These tests pin the
deterministic side (assembly, tools, middleware order, prompt text); whether the
model asks sparingly (AC-07b) is observed end to end, not here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import tool

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.binary_content_guard import CODE_INTERPRETER_TOOL
from bisheng_langchain.gpts.tools.code_interpreter.base_executor import EXECUTION_BOUNDARY_RULES


@tool(CODE_INTERPRETER_TOOL)
def _code_interpreter(code: str) -> str:
    """Run Python code."""
    return ""


@tool("search_knowledge_base")
def _kb(query: str, knowledge_id: str) -> str:
    """Search the knowledge base."""
    return ""


@tool("my_mcp_tool")
def _mcp(q: str) -> str:
    """Some MCP tool."""
    return ""


def _session(api_meta=None):
    return SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q", api_meta=api_meta)


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


def _by_name(subagents: list[dict]) -> dict[str, dict]:
    return {s["name"]: s for s in subagents}


# ---------------------------------------------------------------- AC-03 / AC-04


async def test_assembled_with_code_interpreter(factory_env):
    await agent_factory.create_linsight_agent(_session(), [_code_interpreter, _kb, _mcp])

    subagents = _by_name(factory_env["subagents"])
    assert set(subagents) == {"general-purpose", "data-analyst"}
    assert '"data-analyst"' in factory_env["system_prompt"]
    assert 'subagent_type="data-analyst"' in factory_env["system_prompt"]


async def test_not_assembled_without_code_interpreter(factory_env):
    await agent_factory.create_linsight_agent(_session(), [_kb, _mcp])

    assert [s["name"] for s in factory_env["subagents"]] == ["general-purpose"]
    assert "data-analyst" not in factory_env["system_prompt"]
    assert "NEED_CLARIFICATION" not in factory_env["system_prompt"]


def test_data_analyst_tools_are_an_allow_list():
    spec = agent_factory._build_data_analyst_subagent([_code_interpreter, _kb, _mcp])

    assert [t.name for t in spec["tools"]] == [CODE_INTERPRETER_TOOL]
    # Same safety basis as the researcher: no interrupt source, inherits the model.
    assert set(spec) == {"name", "description", "system_prompt", "tools"}


def test_data_analyst_spec_is_none_without_executor():
    assert agent_factory._build_data_analyst_subagent([_kb, _mcp]) is None


# ---------------------------------------------------------------- AC-05


async def test_both_subagents_share_one_stack_shape(factory_env):
    await agent_factory.create_linsight_agent(_session(), [_code_interpreter, _kb])
    subagents = _by_name(factory_env["subagents"])

    def kinds(spec):
        return [type(m).__name__ for m in spec["middleware"]]

    analyst = kinds(subagents["data-analyst"])
    researcher = kinds(subagents["general-purpose"])
    # The researcher adds only the citation layers (it has a KB tool here).
    assert [k for k in researcher if "Citation" not in k] == analyst
    assert not any("Citation" in k for k in analyst)
    assert analyst[-2:] == ["_LanguageTailMiddleware", researcher[-1]]
    # One resilience instance across subagents and the main-graph overflow handler.
    analyst_res = [m for m in subagents["data-analyst"]["middleware"] if "Resilience" in type(m).__name__]
    researcher_res = [m for m in subagents["general-purpose"]["middleware"] if "Resilience" in type(m).__name__]
    assert analyst_res and analyst_res[0] is researcher_res[0]


# ---------------------------------------------------------------- AC-02 / AC-06 / AC-09 prompts


def test_delegation_line_names_the_skill_path_when_skills_are_mounted():
    prompt = agent_factory._build_linsight_system_prompt(
        False, skills_present=True, has_code_interpreter=True, has_data_analyst=True
    )
    assert "/skills/<技能名>/SKILL.md" in prompt
    assert "scratch/<子任务短名>/" in prompt
    assert "__DATA_ANALYST" not in prompt


def test_delegation_line_without_skills_does_not_point_at_a_missing_section():
    prompt = agent_factory._build_linsight_system_prompt(
        False, skills_present=False, has_code_interpreter=True, has_data_analyst=True
    )
    assert "可用技能" not in prompt
    assert "写有连接方式的文件路径" in prompt


def test_data_analyst_prompt_contract():
    prompt = agent_factory._build_data_analyst_subagent([_code_interpreter])["system_prompt"]

    assert "__CODE_INTERPRETER_RULES__" not in prompt
    assert agent_factory._CODE_INTERPRETER_RULES_ZH in prompt
    assert "NEED_CLARIFICATION:" in prompt
    assert "只执行 SELECT" in prompt
    assert "scratch/" in prompt and "顶层" in prompt  # top-level files get harvested
    assert "CSV" in prompt
    assert "没有** ask_user" in prompt
    # RULE-7: no credential literals in code.
    assert "password=" not in prompt.lower()


# ---------------------------------------------------------------- AC-07 / AC-08


FLAG_SETS = [
    {},
    {"has_knowledge_base": True},
    {"has_knowledge_base": True, "skills_present": True, "has_code_interpreter": True, "has_data_analyst": True},
]


@pytest.mark.parametrize("flags", FLAG_SETS)
def test_no_clarification_cap_and_the_judgement_rule_is_stated(flags):
    flags = dict(flags)
    prompt = agent_factory._build_linsight_system_prompt(flags.pop("has_knowledge_base", False), **flags)

    for cap in ("最多澄清一轮", "最多调用一次", "第二次调用 ask_user", "绝不第二次"):
        assert cap not in prompt
    assert "【何时提问】" in prompt
    assert "合并成一次提问" in prompt
    assert "已经回答过的问题不要再问" in prompt
    assert "写明所做假设" in prompt


def test_attended_clarification_loop_goes_through_ask_user():
    prompt = agent_factory._build_linsight_system_prompt(
        False, skills_present=True, has_code_interpreter=True, has_data_analyst=True
    )
    assert agent_factory._DATA_ANALYST_CLARIFY_ZH in prompt


@pytest.mark.parametrize("flags", FLAG_SETS)
def test_unattended_never_mentions_asking(flags):
    flags = dict(flags)
    prompt = agent_factory._build_linsight_system_prompt(
        flags.pop("has_knowledge_base", False), unattended=True, **flags
    )
    assert "ask_user" not in prompt
    assert "何时提问" not in prompt
    if flags.get("has_data_analyst"):
        assert agent_factory._DATA_ANALYST_CLARIFY_UNATTENDED_ZH in prompt


# ---------------------------------------------------------------- AC-10


def test_boundary_exception_is_stated_in_both_twins():
    zh = agent_factory._CODE_INTERPRETER_RULES_ZH
    assert "也不要连接平台的数据库" in zh
    assert "SKILL.md 中明确写有连接方式的外部业务数据库" in zh
    assert "no connecting to the platform's database" in EXECUTION_BOUNDARY_RULES
    assert "connection details are written in a skill's SKILL.md" in EXECUTION_BOUNDARY_RULES


# ---------------------------------------------------------------- E2E finding (114, C7): no credential copying


def test_prompts_forbid_copying_credentials_into_visible_text():
    main = agent_factory._build_linsight_system_prompt(
        False, skills_present=True, has_code_interpreter=True, has_data_analyst=True
    )
    sub = agent_factory._build_data_analyst_subagent([_code_interpreter])["system_prompt"]
    assert "不要把口令、密钥等凭据抄进 description" in main
    assert "凭据只在代码里使用" in sub
    assert "secrets/" in main and "secrets/" in sub
