from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.chat_session.api.endpoints import chat, session
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.flow import PlatformAgentPermissionError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models import message
from bisheng.database.models.session import MessageSessionDao
from bisheng.user.domain.models.user import UserDao
from bisheng.workflow.application import platform_agent
from test.workflow.test_platform_agent_interaction_wait import FLOW_ID, SESSION
from test.workflow.test_platform_agent_long_task_resume_output import MESSAGE, ready
from test.workflow.test_platform_agent_long_task_resume_reconcile import runtime as runtime
from test.workflow.test_platform_agent_long_task_resume_wait import CALL
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote

CHAT_ID = SESSION.removesuffix("_async_task_id")


async def test_history_and_generic_readers_enforce_resume_receipt_scope(runtime, monkeypatch):
    execution_id, dispatch_id = await ready(runtime, monkeypatch)

    @asynccontextmanager
    async def async_database():
        with runtime.repo.transaction() as db:
            yield SimpleNamespace(exec=AsyncMock(side_effect=db.exec))

    monkeypatch.setattr(message, "get_async_db_session", async_database)
    monkeypatch.setattr(
        MessageSessionDao,
        "async_get_one",
        AsyncMock(
            return_value=SimpleNamespace(
                flow_id=FLOW_ID, user_id=runtime.user.user_id, is_delete=False, name="test", flow_name="test"
            )
        ),
    )
    monkeypatch.setattr(ChatSessionService, "get_subject_session_if_exists", AsyncMock(return_value=None))
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_name="test")))
    monkeypatch.setattr(platform_agent, "PlatformAgentRepository", lambda: runtime.repo)
    with tenant_execution_scope(7):
        context = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        protected_id = await platform_agent.commit_long_task_resume_output(context, MESSAGE)
        with runtime.repo.transaction() as db:
            db.add(
                message.ChatMessage(
                    flow_id=FLOW_ID,
                    chat_id=CHAT_ID,
                    user_id=runtime.user.user_id,
                    tenant_id=7,
                    is_bot=True,
                    category="output_msg",
                    type="over",
                    message='{"msg":"历史消息"}',
                )
            )

        owner = await chat.get_chat_message(chat_id=CHAT_ID, flow_id=FLOW_ID, login_user=runtime.user, share_link=None)
        listing = await session.get_chat_messages_by_conversation_id(conversationId=CHAT_ID, login_user=runtime.user)
        assert any(row.id == protected_id and not row.extra for row in owner.data)
        assert any(row.messageId == str(protected_id) for row in listing.data)
        assert all(row.id != protected_id for row in await ChatSessionService.get_chat_history(CHAT_ID, FLOW_ID))
        assert all(row.id != protected_id for row in await message.ChatMessageDao.aget_messages_by_chat_id(CHAT_ID))
        assert all(
            row.id != protected_id for row in await message.ChatMessageDao.get_all_message_by_chat_ids([CHAT_ID])
        )
        assert not await message.ChatMessageDao.aget_messages_by_ids([protected_id], runtime.user.user_id, CHAT_ID)

        monkeypatch.setattr(runtime.provider, "check_use", AsyncMock(side_effect=PlatformAgentPermissionError))
        for user in (runtime.user, runtime.publisher):
            history = await ChatSessionService.get_chat_history(CHAT_ID, FLOW_ID, login_user=user)
            assert len(history) == 1 and "历史消息" in history[0].message
