from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.workstation.domain.services import chat_service


def _request(*, parent_message_id: str = "17") -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-07-17T12:00:00+08:00",
        conversationId="chat-1",
        model="model-1",
        text="请解释这份文档",
        overrideParentMessageId=parent_message_id,
    )


async def test_agent_retry_reuses_existing_user_question_without_inserting_duplicate():
    user = SimpleNamespace(user_id=7)
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    existing_question = SimpleNamespace(id=17, user_id=7, chat_id="chat-1", is_bot=False)
    workstation_config = SimpleNamespace(
        models=[SimpleNamespace(id="model-1", displayName="模型一")]
    )

    insert_message = AsyncMock()
    with patch.object(
        chat_service,
        "WorkStationService",
        SimpleNamespace(aget_config=AsyncMock(return_value=workstation_config)),
    ), patch.object(
        chat_service,
        "MessageSessionDao",
        SimpleNamespace(
            async_get_one=AsyncMock(return_value=conversation),
            touch_session=AsyncMock(),
        ),
    ), patch.object(
        chat_service,
        "ChatMessageDao",
        SimpleNamespace(
            aget_message_by_id=AsyncMock(return_value=existing_question),
            ainsert_one=insert_message,
        ),
    ), patch.object(
        chat_service,
        "LLMService",
        SimpleNamespace(get_bisheng_llm=AsyncMock(return_value=SimpleNamespace())),
    ):
        result = await chat_service._agent_initialize_chat(_request(), user)

    assert result[2] is existing_question
    assert result[5] is False
    insert_message.assert_not_awaited()


async def test_agent_retry_rejects_question_from_another_conversation():
    user = SimpleNamespace(user_id=7)
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    foreign_question = SimpleNamespace(id=17, user_id=7, chat_id="chat-2", is_bot=False)
    workstation_config = SimpleNamespace(
        models=[SimpleNamespace(id="model-1", displayName="模型一")]
    )

    insert_message = AsyncMock()
    with patch.object(
        chat_service,
        "WorkStationService",
        SimpleNamespace(aget_config=AsyncMock(return_value=workstation_config)),
    ), patch.object(
        chat_service,
        "MessageSessionDao",
        SimpleNamespace(
            async_get_one=AsyncMock(return_value=conversation),
            touch_session=AsyncMock(),
        ),
    ), patch.object(
        chat_service,
        "ChatMessageDao",
        SimpleNamespace(
            aget_message_by_id=AsyncMock(return_value=foreign_question),
            ainsert_one=insert_message,
        ),
    ), patch.object(
        chat_service,
        "LLMService",
        SimpleNamespace(get_bisheng_llm=AsyncMock(return_value=SimpleNamespace())),
    ):
        with pytest.raises(chat_service.ConversationNotFoundError):
            await chat_service._agent_initialize_chat(_request(), user)

    insert_message.assert_not_awaited()
