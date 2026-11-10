"""The workbench names conversations with the configured title model when set."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.llm.domain import LLMService
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.workstation.domain.services.chat_helpers import resolve_title_llm

USER = SimpleNamespace(user_id=1)
CHAT_LLM = object()
TITLE_LLM = object()


@pytest.mark.parametrize("slot", [None, WSModel(id="")])
async def test_unset_title_model_names_with_the_chat_model(monkeypatch, slot):
    monkeypatch.setattr(
        LLMService, "get_workbench_llm", AsyncMock(return_value=WorkbenchModelConfig(chat_title_llm=slot))
    )
    getter = AsyncMock(return_value=TITLE_LLM)
    monkeypatch.setattr(LLMService, "get_bisheng_llm", getter)

    assert await resolve_title_llm(CHAT_LLM, USER) is CHAT_LLM
    getter.assert_not_awaited()


async def test_configured_title_model_wins(monkeypatch):
    monkeypatch.setattr(
        LLMService, "get_workbench_llm", AsyncMock(return_value=WorkbenchModelConfig(chat_title_llm=WSModel(id="7")))
    )
    getter = AsyncMock(return_value=TITLE_LLM)
    monkeypatch.setattr(LLMService, "get_bisheng_llm", getter)

    assert await resolve_title_llm(CHAT_LLM, USER) is TITLE_LLM
    assert getter.await_args.kwargs["model_id"] == "7"


async def test_unloadable_title_model_falls_back_to_the_chat_model(monkeypatch):
    monkeypatch.setattr(
        LLMService, "get_workbench_llm", AsyncMock(return_value=WorkbenchModelConfig(chat_title_llm=WSModel(id="7")))
    )
    monkeypatch.setattr(LLMService, "get_bisheng_llm", AsyncMock(side_effect=RuntimeError("model offline")))

    assert await resolve_title_llm(CHAT_LLM, USER) is CHAT_LLM
