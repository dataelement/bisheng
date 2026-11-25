"""Deleted conversations must not supply history or titles to user-facing reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.workstation import ConversationNotFoundError
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.workstation.api.endpoints.chat import get_agent_chat_history, get_chat_history


@pytest.mark.parametrize("read_history", [get_agent_chat_history, get_chat_history])
@pytest.mark.parametrize("is_shared", [False, True])
async def test_deleted_workstation_history_never_loads_messages(monkeypatch, read_history, is_shared):
    session = SimpleNamespace(is_delete=True, user_id=7, flow_id="example-flow")
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(return_value=session))
    read_messages = AsyncMock()
    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", read_messages)
    share_link = SimpleNamespace(resource_id="example-conversation") if is_shared else None

    with pytest.raises(ConversationNotFoundError):
        caller = SimpleNamespace(user_id=8 if is_shared else 7)
        await read_history("example-conversation", login_user=caller, share_link=share_link)

    read_messages.assert_not_awaited()


async def test_deleted_session_name_is_unavailable_but_missing_draft_stays_empty(monkeypatch):
    load_session = AsyncMock(side_effect=[SimpleNamespace(is_delete=True), None])
    monkeypatch.setattr(MessageSessionDao, "async_get_one", load_session)

    assert await ChatSessionService.get_session_info("example-conversation") is None
    assert await ChatSessionService.get_session_info("new-draft") is None


async def test_deleted_session_is_not_read_through_legacy_history(monkeypatch):
    session = SimpleNamespace(is_delete=True, user_id=7, flow_id="example-flow")
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(return_value=session))
    read_messages = AsyncMock()
    monkeypatch.setattr(ChatMessageDao, "afilter_message_by_chat_id", read_messages)

    assert await ChatSessionService.get_chat_history("example-conversation", "example-flow") == []
    read_messages.assert_not_awaited()
