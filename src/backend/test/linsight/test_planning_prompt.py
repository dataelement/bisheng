"""F004 T044: the planning prompt once users can interject mid-run (AC-18).

The ``planned`` prompt used to say, unconditionally, "only flip status, never
rewrite the text of an item". With the inbox mounted (tenant switch on) a user may
ask mid-run to change the plan, so the prompt must let the model rewrite the items
the user asked about and leave every other item's text byte-identical (row ids are
matched by content, ``StreamEventMapper._diff_todos``). Without the inbox (legacy
path, switch off) the prompt stays byte-identical to today's.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _build_direct_system_prompt,
    _build_linsight_system_prompt,
)
from bisheng.linsight.domain.services.inbox_middleware import InboxMiddleware

STEER_PHRASE = "用户在执行中发来新要求时，先调用 write_todos 更新计划，再继续"
REWRITE_ON_REQUEST = "只有用户要求时才改写"
UNCONDITIONAL_NO_REWRITE = "不改写已有文案"
SCOPE_PHRASE = "不改变上文其它任何要求"
# The existing ask_user constraint against fixed-count examples (linsight/AGENTS.md).
NO_FIXED_COUNT = ("不设固定数目", "示例只示意问法，问题数量仍按实际缺口增减")

VARIANTS = [
    {"has_knowledge_base": False},
    {"has_knowledge_base": True},
    {"has_knowledge_base": True, "skills_present": True, "has_code_interpreter": True, "has_web_search": True},
    {"has_knowledge_base": False, "has_data_analyst": True},
]


def _steered(**kwargs: Any) -> str:
    return _build_linsight_system_prompt(steerable=True, **kwargs)


@pytest.mark.parametrize("variant", VARIANTS)
def test_prompt_allows_rewrite_on_user_request(variant: dict):
    prompt = _steered(**variant)

    assert UNCONDITIONAL_NO_REWRITE not in prompt
    assert REWRITE_ON_REQUEST in prompt
    # Both places that used to forbid rewriting now allow it on request: step 2 and the tool line.
    tool_line = next(line for line in prompt.splitlines() if line.startswith("- write_todos(todos)"))
    assert REWRITE_ON_REQUEST in tool_line
    # Items the user did not ask about keep their text exactly (row ids follow the text).
    assert "逐字不变" in prompt


@pytest.mark.parametrize("variant", VARIANTS)
def test_prompt_requires_plan_update_on_steer(variant: dict):
    prompt = _steered(**variant)

    assert prompt.count(STEER_PHRASE) == 1
    steer_line = next(line for line in prompt.splitlines() if STEER_PHRASE in line)
    # Scoped to the plan: it says it changes nothing else, and never claims precedence.
    assert SCOPE_PHRASE in steer_line
    for banned in ("最高优先", "优先级最高", "覆盖之前", "覆盖上文", "忽略上文"):
        assert banned not in steer_line, banned
    # Work already done is kept.
    assert "已完成的条目" in steer_line
    assert "output/" in steer_line
    # It lives in the workflow, after the planning step and before the deliverable step.
    assert prompt.index("1. 【规划】") < prompt.index(STEER_PHRASE) < prompt.index("3. 【产出交付物】")


def test_prompt_keeps_no_fixed_count_rule():
    prompt = _steered(has_knowledge_base=True)

    for phrase in NO_FIXED_COUNT:
        assert phrase in prompt, phrase
    # The new text itself carries no numbered example ("第 3 步改成…") a model could copy.
    added = [
        line for line in prompt.splitlines() if STEER_PHRASE in line or REWRITE_ON_REQUEST in line or "逐字不变" in line
    ]
    assert added
    for line in added:
        assert not re.search(r"第\s*\d+\s*[步项条]", line), line


@pytest.mark.parametrize("variant", VARIANTS + [{"has_knowledge_base": False, "unattended": True}])
def test_prompt_unchanged_without_inbox(variant: dict):
    """Switch off (no inbox): today's wording, byte for byte, and the default is off."""
    legacy = _build_linsight_system_prompt(**variant)

    assert _build_linsight_system_prompt(steerable=False, **variant) == legacy
    assert legacy.count(UNCONDITIONAL_NO_REWRITE) == 2
    assert STEER_PHRASE not in legacy
    assert REWRITE_ON_REQUEST not in legacy


def test_steered_prompt_differs_only_in_the_plan_lines():
    legacy = _build_linsight_system_prompt(True).splitlines()
    steered = _steered(has_knowledge_base=True).splitlines()

    removed = [line for line in legacy if line not in steered]
    added = [line for line in steered if line not in legacy]
    assert len(removed) == 2 and all(UNCONDITIONAL_NO_REWRITE in line for line in removed)
    assert len(added) == 3


DIRECT_TOOLS = frozenset({"ask_user", "write_file", "read_file", "edit_file", "ls", "glob", "grep", "task"})
DIRECT_STEER_PHRASE = "回答过程中用户可能发来新消息"


def test_direct_prompt_mentions_mid_run_messages_only_with_inbox():
    plain = _build_direct_system_prompt(DIRECT_TOOLS)
    steered = _build_direct_system_prompt(DIRECT_TOOLS, steerable=True)

    assert DIRECT_STEER_PHRASE not in plain
    assert steered.count(DIRECT_STEER_PHRASE) == 1
    line = next(line for line in steered.splitlines() if DIRECT_STEER_PHRASE in line)
    assert "不改变其它要求" in line
    # The direct profile has no plan: no plan words leak in.
    for word in ("write_todos", "待办", "计划"):
        assert word not in line, word
    assert [line for line in steered.splitlines() if line not in plain.splitlines()] == [line]


# --------------------------------------------------------------- factory wiring


class _PromptModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        return {"ls_provider": "f004-planning-prompt", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _PromptModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


@tool
def _noop(text: str) -> str:
    """No-op business tool."""
    return text


async def _main_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path, *, profile: str, inbox: Any, api_meta=None) -> str:
    """The system prompt the factory hands to ``create_deep_agent``."""
    import deepagents

    from bisheng.core.config.settings import LinsightConf

    captured: dict = {}

    def fake_create_deep_agent(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(_PromptModel(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(
        id="sv-plan-prompt", session_id="chat-plan-prompt", tenant_id=1, user_id=1, question="q", api_meta=api_meta
    )
    await agent_factory.create_linsight_agent(
        session,
        [_noop],
        backend=None,  # the factory's in-memory default
        file_dir=str(tmp_path),
        profile=profile,
        inbox=inbox,
    )
    return str(captured["system_prompt"])


def _inbox() -> InboxMiddleware:
    async def drain(_cid: str) -> list[dict]:
        return []

    async def emit(_event: dict) -> None:
        return None

    return InboxMiddleware("chat-plan-prompt", drain=drain, emit=emit, record_wait=lambda _ms: None)


async def test_factory_uses_steer_wording_only_with_inbox(monkeypatch: pytest.MonkeyPatch, tmp_path):
    legacy = await _main_prompt(monkeypatch, tmp_path, profile="planned", inbox=None)
    steered = await _main_prompt(monkeypatch, tmp_path, profile="planned", inbox=_inbox())
    unattended = await _main_prompt(
        monkeypatch, tmp_path, profile="planned", inbox=_inbox(), api_meta={"channel": "open_api_v2"}
    )

    assert STEER_PHRASE not in legacy and UNCONDITIONAL_NO_REWRITE in legacy
    assert STEER_PHRASE in steered and UNCONDITIONAL_NO_REWRITE not in steered
    # Unattended runs never mount the inbox, so they keep today's wording.
    assert STEER_PHRASE not in unattended and UNCONDITIONAL_NO_REWRITE in unattended

    direct_plain = await _main_prompt(monkeypatch, tmp_path, profile="direct", inbox=None)
    direct_steered = await _main_prompt(monkeypatch, tmp_path, profile="direct", inbox=_inbox())
    assert DIRECT_STEER_PHRASE not in direct_plain
    assert DIRECT_STEER_PHRASE in direct_steered
