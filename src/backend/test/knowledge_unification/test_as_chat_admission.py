"""T369: ChatClient preserves the admitted identity and recovers stale caches."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.chat import client as client_module
from bisheng.common.chat.client import ChatClient
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import AssistantNotOnlineError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.database.models.assistant import Assistant, AssistantStatus


@pytest.fixture
def client(monkeypatch):
    instance = object.__new__(ChatClient)
    instance.client_id = "assistant-a"
    instance.client_key = "connection"
    instance.chat_id = "chat-a"
    instance.user_id = 9
    instance.login_user = UserPayload(user_id=9, user_name="actor", tenant_id=101, user_role=[])
    instance.gpts_agent = None
    instance.gpts_async_callback = None
    instance.db_assistant = None
    instance.chat_history = []
    instance.finalizing_tasks = set()
    instance.websocket = object()
    for name in ("init_chat_history", "init_gpts_callback", "clear_stream_queue", "add_message", "send_response"):
        setattr(instance, name, AsyncMock())
    instance.get_latest_history = AsyncMock(return_value=[])
    monkeypatch.setattr(
        client_module.AssistantDao,
        "get_one_assistant",
        MagicMock(return_value=Assistant(id="assistant-a", tenant_id=101, status=AssistantStatus.ONLINE.value)),
    )
    return instance


@pytest.mark.parametrize("chat_id", ["chat-a", ""])
async def test_both_normal_and_debug_agent_construction_pass_the_original_object(client, monkeypatch, chat_id):
    client.chat_id = chat_id
    seen = []

    class Agent:
        def __init__(self, row, supplied_chat, invoke_user_id, *, login_user):
            assert supplied_chat == chat_id and invoke_user_id == 9
            assert login_user is client.login_user
            seen.append(self)

        async def init_assistant(self, callbacks):
            return None

    monkeypatch.setattr(client_module, "AssistantAgent", Agent)
    await client.init_gpts_agent()
    assert client.gpts_agent is seen[0]


async def test_normal_chat_keeps_original_online_requirement(client, monkeypatch):
    monkeypatch.setattr(
        client_module.AssistantDao,
        "get_one_assistant",
        MagicMock(return_value=Assistant(id="assistant-a", status=AssistantStatus.OFFLINE.value)),
    )
    factory = MagicMock()
    monkeypatch.setattr(client_module, "AssistantAgent", factory)
    with pytest.raises(AssistantNotOnlineError):
        await client.init_gpts_agent()
    factory.assert_not_called()


async def test_stale_run_cache_is_cleared_and_next_message_can_initialize(client, monkeypatch):
    from bisheng.common.chat.clients import base

    monkeypatch.setattr(base, "ensure_client_execution_lease", AsyncMock(return_value="accepted"))
    monkeypatch.setattr(KnowledgeOperationPlanConflictError, "websocket_close_message", AsyncMock())
    stale = SimpleNamespace(
        reset_citation_registry_items=MagicMock(),
        run=AsyncMock(side_effect=KnowledgeOperationPlanConflictError()),
    )
    client.gpts_agent = stale
    client.db_assistant = object()
    await client.handle_gpts_message({"inputs": {"input": "question"}})
    assert client.gpts_agent is None and client.db_assistant is None
    assert asyncio.current_task() in client.finalizing_tasks

    class Agent:
        def __init__(self, row, supplied_chat, invoke_user_id, *, login_user):
            assert login_user is client.login_user

        async def init_assistant(self, callbacks):
            return None

    monkeypatch.setattr(client_module, "AssistantAgent", Agent)
    await client.init_gpts_agent()
    assert isinstance(client.gpts_agent, Agent)
