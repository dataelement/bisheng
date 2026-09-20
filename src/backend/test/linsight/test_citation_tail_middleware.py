"""F069 T008: citation requirement at the prompt tail and in the deliverable step (AC-06).

The rules text itself (citation.yaml) is appended to the kernel prompt and then
buried under the deepagents framework prompts. P0 restates the requirement in
two places that survive that: the deliverable step 3a of the kernel prompt and
a tail middleware placed right before the language tail. Both are gated on the
run actually having a citable retrieval tool, exactly like the rules.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _LINSIGHT_CITATION_TAIL_ZH,
    _build_linsight_system_prompt,
    _CitationTailMiddleware,
)
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase

CITATION_LINE_MARK = "按 Citation Rules 逐字复制来源标识"


class _FakeReq:
    def __init__(self, system_message: SystemMessage):
        self.system_message = system_message

    def override(self, *, system_message):
        return _FakeReq(system_message)


# --------------------------------------------------------------------------
# tail middleware
# --------------------------------------------------------------------------
def test_citation_tail_appends_text_as_last_block():
    mw = _CitationTailMiddleware(_LINSIGHT_CITATION_TAIL_ZH)
    captured: dict = {}

    def handler(req):
        captured["req"] = req
        return "RESP"

    out = mw.wrap_model_call(_FakeReq(SystemMessage("BASE")), handler)

    assert out == "RESP"
    blocks = captured["req"].system_message.content_blocks
    assert _LINSIGHT_CITATION_TAIL_ZH in blocks[-1]["text"]
    assert any("BASE" in b.get("text", "") for b in blocks[:-1])


async def test_citation_tail_async_appends_text():
    mw = _CitationTailMiddleware(_LINSIGHT_CITATION_TAIL_ZH)
    captured: dict = {}

    async def handler(req):
        captured["req"] = req
        return "RESP"

    await mw.awrap_model_call(_FakeReq(SystemMessage("BASE")), handler)

    assert _LINSIGHT_CITATION_TAIL_ZH in captured["req"].system_message.content_blocks[-1]["text"]


def test_citation_tail_identity_and_text():
    mw = _CitationTailMiddleware(_LINSIGHT_CITATION_TAIL_ZH)

    assert mw.name == "LinsightCitationTail"
    assert mw.tools == []
    assert "Citation Rules" in _LINSIGHT_CITATION_TAIL_ZH
    # the tail restates the requirement; it never carries the private-use markers
    assert "" not in _LINSIGHT_CITATION_TAIL_ZH
    # commission-style: no prohibition list
    assert "不得" not in _LINSIGHT_CITATION_TAIL_ZH


# --------------------------------------------------------------------------
# deliverable step 3a gate
# --------------------------------------------------------------------------
def test_deliverable_line_present_with_kb():
    prompt = _build_linsight_system_prompt(True)

    assert CITATION_LINE_MARK in prompt
    assert "__CITATION_DELIVERABLE_LINE__" not in prompt


def test_deliverable_line_present_with_web_only():
    prompt = _build_linsight_system_prompt(False, has_web_search=True)

    assert CITATION_LINE_MARK in prompt


def test_deliverable_line_absent_without_retrieval():
    prompt = _build_linsight_system_prompt(False)

    assert CITATION_LINE_MARK not in prompt
    assert "__CITATION_DELIVERABLE_LINE__" not in prompt


def test_deliverable_line_sits_in_step_3a():
    prompt = _build_linsight_system_prompt(True)
    start = prompt.index("3a（始终）")
    end = prompt.index("3b（仅当选了 html）")

    assert CITATION_LINE_MARK in prompt[start:end]


# --------------------------------------------------------------------------
# middleware stack placement (main graph + researcher)
# --------------------------------------------------------------------------
class _WebIn(BaseModel):
    query: str = Field(default="")


class _FakeWeb(BaseTool):
    name: str = "web_search"
    description: str = "search the web"
    args_schema: type[BaseModel] = _WebIn

    def _run(self, query: str = "") -> str:
        return "[]"

    async def _arun(self, query: str = "") -> str:
        return "[]"


class _FakeOther(BaseTool):
    name: str = "not_web"
    description: str = "other"
    args_schema: type[BaseModel] = _WebIn

    def _run(self, query: str = "") -> str:
        return "other"

    async def _arun(self, query: str = "") -> str:
        return "other"


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


def _names(middlewares) -> list[str]:
    return [getattr(m, "name", type(m).__name__) for m in middlewares]


async def test_main_and_researcher_stacks_carry_citation_tail_before_language_tail(factory_env):
    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q")

    await agent_factory.create_linsight_agent(session, [SearchKnowledgeBase(), _FakeWeb()])

    main = _names(factory_env["middleware"])
    assert "LinsightCitationTail" in main
    assert main.index("LinsightCitationTail") < main.index("LinsightLanguageTail")

    researcher = _names(factory_env["subagents"][0]["middleware"])
    assert "LinsightCitationTail" in researcher
    assert researcher.index("LinsightCitationTail") < researcher.index("LinsightLanguageTail")

    # the deliverable line reached the assembled system prompt too
    assert CITATION_LINE_MARK in factory_env["system_prompt"]


async def test_no_citation_tail_without_retrieval_tools(factory_env):
    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q")

    await agent_factory.create_linsight_agent(session, [_FakeOther()])

    assert "LinsightCitationTail" not in _names(factory_env["middleware"])
    assert "LinsightCitationTail" not in _names(factory_env["subagents"][0]["middleware"])
    assert CITATION_LINE_MARK not in factory_env["system_prompt"]
    # language tail is still the last prompt-appending middleware
    assert "LinsightLanguageTail" in _names(factory_env["middleware"])


# --------------------------------------------------------------------------
# F069 P1: handle-contract wording
# --------------------------------------------------------------------------
def test_deliverable_line_switches_to_handles():
    from bisheng.linsight.domain.services.agent_factory import _LINSIGHT_CITATION_TAIL_HANDLES_ZH

    prompt = _build_linsight_system_prompt(True, citation_handles=True)
    assert "[S3] 或 [S3][S7]" in prompt
    assert CITATION_LINE_MARK not in prompt
    assert "[Sn]" in _LINSIGHT_CITATION_TAIL_HANDLES_ZH
    assert "" not in _LINSIGHT_CITATION_TAIL_HANDLES_ZH


async def test_stacks_use_handle_tail_and_rules_when_scope_enabled(factory_env):
    from bisheng.linsight.domain.services.agent_factory import _LINSIGHT_CITATION_TAIL_HANDLES_ZH

    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q")
    scope = SimpleNamespace(enabled=True, entries=[], handles={}, record_seen=AsyncMock())

    await agent_factory.create_linsight_agent(session, [SearchKnowledgeBase(), _FakeWeb()], citation_scope=scope)

    tails = [m for m in factory_env["middleware"] if getattr(m, "name", "") == "LinsightCitationTail"]
    assert tails and tails[0]._directive == _LINSIGHT_CITATION_TAIL_HANDLES_ZH
    assert "# 来源编号" in factory_env["system_prompt"]
    assert "" not in factory_env["system_prompt"]
    assert "[S3] 或 [S3][S7]" in factory_env["system_prompt"]
    assert "# 来源编号" in factory_env["subagents"][0]["system_prompt"]
