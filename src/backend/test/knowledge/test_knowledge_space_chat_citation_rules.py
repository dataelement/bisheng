# ruff: noqa: RUF001 - the yaml prompt and the admin prompt under test carry full-width CJK punctuation
"""Citation-rule backstop on the knowledge-space RAG system prompt.

``KnowledgeSpaceChatService._render_rag_response`` builds its SystemMessage as
``ensure_citation_rules(system_text)`` for both prompt sources: the admin-saved
``space_conf.system_prompt`` (``str.format`` placeholders) and the yaml fallback
``knowledge_space.yaml`` (``$``-syntax rendered by ``PromptLoader``), which no
longer carries the citation rules itself. These tests pin down that the rules are
appended exactly once on each branch, that ``cur_date`` is substituted on both,
and that a prompt already spelling the rules in their literal ``\\ue200`` form is
handed to the LLM untouched.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from bisheng.api.v1.schemas import KnowledgeSpaceConfig
from bisheng.citation.domain.services.citation_prompt_helper import CITATION_PROMPT_RULES
from bisheng.core.prompts.prompt_loader import PromptLoader
from bisheng.knowledge.domain.services import knowledge_space_chat_service as chat_module

_RULES_HEADING = "# Citation Rules"
_START_MARKER = chr(0xE200)
# The six-character literal form (backslash + "ue200"), NOT the real U+E200 char.
_LITERAL_START_MARKER = chr(92) + "ue200"

_FROZEN_NOW = datetime(2026, 1, 2, 3, 4, 5)
_FROZEN_DATE = "2026-01-02"

_QUESTION = "what is bisheng"
_CHUNK = "chunk body about bisheng"

_CUSTOM_PROMPT = "你是一个严谨的AI问答助手。当前时间是{cur_date}。"
_USER_PROMPT = "{retrieved_file_content}\n{question}"
# A prompt that already teaches the markers in their visible form, the way the
# default admin template spells them. ``prompt_has_citation_rules`` must treat
# the literal backslash-u-e-2-0-0 text as "rules present" so nothing gets appended.
_PROMPT_WITH_LITERAL_RULES = (
    "你是知识空间助手。当前时间是{cur_date}。\n\n"
    "# 引用规则\n"
    "- `\\ue200`：引用开始标记\n"
    "- `\\ue201`：多个来源之间的分隔符\n"
    "- `\\ue202`：引用结束标记\n"
)


class _FrozenDatetime(datetime):
    """``datetime`` stand-in with a fixed ``now()`` so the substituted date is exact."""

    @classmethod
    def now(cls, tz=None):
        return _FROZEN_NOW


def _service() -> chat_module.KnowledgeSpaceChatService:
    user = MagicMock()
    user.user_id = 7
    user.tenant_id = 1
    return chat_module.KnowledgeSpaceChatService(request=MagicMock(), login_user=user)


async def _real_prompt_loader() -> PromptLoader:
    """Return a real ``PromptLoader`` regardless of test ordering.

    ``test_knowledge_space_chat_permissions.py`` installs a fake
    ``bisheng.core.prompts.manager`` (whose ``render_prompt`` yields empty
    strings) into ``sys.modules`` when the real module has not been imported yet.
    The fake exposes only ``get_prompt_manager``; the real module also exposes
    ``PromptManager``. When the real module is present, derive the loader through
    the real manager's initialisation path; otherwise build the loader directly —
    ``prompt_loader`` is a module the fake never touches.
    """
    manager_module = importlib.import_module("bisheng.core.prompts.manager")
    if hasattr(manager_module, "PromptManager"):
        loader = await manager_module.PromptManager()._async_initialize()
    else:
        loader = PromptLoader()
    assert isinstance(loader, PromptLoader)
    assert loader.render_prompt.__func__ is PromptLoader.render_prompt
    return loader


async def _drive_render(monkeypatch, space_conf, prompt_loader) -> list[BaseMessage]:
    """Run ``_render_rag_response`` with every collaborator stubbed.

    Returns the messages handed to the (fake) LLM. Retrieval, history, persistence
    and title generation are all replaced; only prompt assembly runs for real.
    """
    service = _service()
    monkeypatch.setattr(service, "get_space_llm_config", AsyncMock(return_value=(MagicMock(), space_conf)))
    monkeypatch.setattr(service, "_prepare_rag_citation_context", AsyncMock(return_value=(_CHUNK, [])))
    monkeypatch.setattr(service, "_resolve_workbench_visual", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "get_history", AsyncMock(return_value=[]))
    # ``_render_rag_response`` resolves ``get_prompt_manager`` through the service
    # module's own binding, so patch that name explicitly instead of relying on
    # whatever ``bisheng.core.prompts.manager`` happens to be in ``sys.modules``.
    monkeypatch.setattr(chat_module, "get_prompt_manager", AsyncMock(return_value=prompt_loader))
    monkeypatch.setattr(chat_module, "datetime", _FrozenDatetime)

    captured: list[list[BaseMessage]] = []

    async def fake_loop(model, messages, registry, *, visual):
        captured.append(list(messages))
        yield AIMessage(content="ok")

    monkeypatch.setattr(chat_module, "run_react_vision_stream", fake_loop)
    monkeypatch.setattr(chat_module.ChatMessageDao, "ainsert_batch", AsyncMock())
    monkeypatch.setattr(chat_module, "save_message_citations", AsyncMock())

    session = SimpleNamespace(chat_id="c1", flow_id="f1", name="named")
    async for _ in service._render_rag_response(session, [], _QUESTION, 11):
        pass

    assert len(captured) == 1
    return captured[0]


def _split(messages: list[BaseMessage]) -> tuple[str, str]:
    """Return (system_text, human_text) and assert the two-message shape."""
    assert len(messages) == 2
    system, human = messages
    assert isinstance(system, SystemMessage)
    assert isinstance(human, HumanMessage)
    return str(system.content), str(human.content)


async def test_admin_prompt_branch_gets_rules_once(monkeypatch):
    space_conf = KnowledgeSpaceConfig(system_prompt=_CUSTOM_PROMPT, user_prompt=_USER_PROMPT)
    prompt_loader = MagicMock()

    system_text, human_text = _split(await _drive_render(monkeypatch, space_conf, prompt_loader))

    formatted = _CUSTOM_PROMPT.format(cur_date=_FROZEN_DATE)
    assert system_text.startswith(formatted)
    assert "{cur_date}" not in system_text
    assert system_text.count(CITATION_PROMPT_RULES) == 1
    assert system_text.count(_RULES_HEADING) == 1
    assert system_text == f"{formatted}\n\n{CITATION_PROMPT_RULES}"
    assert _QUESTION in human_text
    assert _CHUNK in human_text
    # The admin branch never renders the yaml prompt.
    prompt_loader.render_prompt.assert_not_called()


async def test_yaml_fallback_branch_gets_rules_once_and_cur_date_substituted(monkeypatch):
    space_conf = KnowledgeSpaceConfig(system_prompt="", user_prompt="")
    prompt_loader = await _real_prompt_loader()

    system_text, human_text = _split(await _drive_render(monkeypatch, space_conf, prompt_loader))

    # The real yaml was rendered: its role header and the substituted date are there.
    assert "BISHENG 智能问答助手" in system_text
    assert f"当前时间：{_FROZEN_DATE}" in system_text
    assert "{cur_date}" not in system_text
    assert "${cur_date}" not in system_text
    # Rules appended by the backstop exactly once, carrying the real marker char.
    assert system_text.count(_RULES_HEADING) == 1
    assert system_text.count(CITATION_PROMPT_RULES) == 1
    assert _START_MARKER in system_text
    assert _QUESTION in human_text
    assert _CHUNK in human_text
    assert "${question}" not in human_text
    assert "${retrieved_file_content}" not in human_text


async def test_default_ai_prompt_with_literal_markers_is_not_double_appended(monkeypatch):
    assert _LITERAL_START_MARKER in _PROMPT_WITH_LITERAL_RULES
    assert _START_MARKER not in _PROMPT_WITH_LITERAL_RULES
    space_conf = KnowledgeSpaceConfig(system_prompt=_PROMPT_WITH_LITERAL_RULES, user_prompt=_USER_PROMPT)
    prompt_loader = MagicMock()

    system_text, human_text = _split(await _drive_render(monkeypatch, space_conf, prompt_loader))

    assert system_text == _PROMPT_WITH_LITERAL_RULES.format(cur_date=_FROZEN_DATE)
    assert CITATION_PROMPT_RULES not in system_text
    assert system_text.count(_RULES_HEADING) == 0
    assert "{cur_date}" not in system_text
    assert _QUESTION in human_text
    prompt_loader.render_prompt.assert_not_called()
