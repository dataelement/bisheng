"""Conversation naming is optional; its configuration never admits the actual chat model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.chat.client import ChatClient
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel


@pytest.mark.parametrize("synchronous", [False, True])
@pytest.mark.parametrize("failure", ["unset", "configuration", "model", "none"])
async def test_title_model_is_optional(monkeypatch, synchronous, failure):
    config = WorkbenchModelConfig(chat_title_llm=None if failure == "unset" else WSModel(id="7"))
    client = object()
    config_reader = Mock(return_value=config) if synchronous else AsyncMock(return_value=config)
    loader = Mock(return_value=client) if synchronous else AsyncMock(return_value=client)
    if failure == "configuration":
        config_reader.side_effect = RuntimeError("configuration unavailable")
    if failure == "model":
        loader.side_effect = RuntimeError("model offline")
    monkeypatch.setattr(LLMService, "get_workbench_llm_sync" if synchronous else "get_workbench_llm", config_reader)
    monkeypatch.setattr(LLMService, "get_bisheng_llm_sync" if synchronous else "get_bisheng_llm", loader)

    if synchronous:
        result = LLMService.get_optional_chat_title_llm_sync(user_id=1, app_name="workflow_chat_title", tenant_id=101)
    else:
        result = await LLMService.get_optional_chat_title_llm(user_id=1, app_name="assistant_chat_title", tenant_id=101)
    assert result is (client if failure == "none" else None)
    assert config_reader.call_args.kwargs == {"tenant_id": 101, "slots": ("chat_title_llm.id",)}
    if failure in {"unset", "configuration"}:
        loader.assert_not_called()
    else:
        assert loader.call_args.kwargs["model_id"] == "7"
        assert loader.call_args.kwargs["user_id"] == 1


@pytest.mark.parametrize("consumer", ["knowledge", "assistant"])
@pytest.mark.parametrize("failure", ["unset", "configuration", "model"])
async def test_non_workbench_conversations_skip_unavailable_naming(monkeypatch, consumer, failure):
    reader = AsyncMock(
        return_value=WorkbenchModelConfig(chat_title_llm=None if failure == "unset" else WSModel(id="7"))
    )
    loader = AsyncMock()
    if failure == "configuration":
        reader.side_effect = RuntimeError("title configuration unavailable")
    if failure == "model":
        loader.side_effect = RuntimeError("title model offline")
    monkeypatch.setattr(LLMService, "get_workbench_llm", reader)
    monkeypatch.setattr(LLMService, "get_bisheng_llm", loader)
    update = AsyncMock()
    monkeypatch.setattr("bisheng.database.models.session.MessageSessionDao.update_session_name", update)

    if consumer == "knowledge":
        await KnowledgeSpaceChatService.generate_conversation(1, "chat-1", "Question")
    else:
        client = ChatClient.__new__(ChatClient)
        client.user_id = 1
        client.new_session = SimpleNamespace(name="", chat_id="chat-1")
        await client.generate_session_title("Question")
    update.assert_not_awaited()
