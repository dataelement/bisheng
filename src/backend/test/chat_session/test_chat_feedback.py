from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import select

from bisheng.chat_session.domain.services import chat_feedback_service as feedback
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession


@pytest.fixture()
async def feedback_db(async_db_session, monkeypatch):
    db = async_db_session
    await db.run_sync(lambda session: ChatMessage.__table__.create(session.connection(), checkfirst=True))
    await db.run_sync(lambda session: MessageSession.__table__.create(session.connection(), checkfirst=True))
    db.add(MessageSession(chat_id="feedback-chat", user_id=7, tenant_id=1, flow_type=15))
    db.add(
        ChatMessage(
            id=321,
            chat_id="feedback-chat",
            flow_id="",
            user_id=7,
            tenant_id=1,
            is_bot=True,
            type="end",
            category="agent_answer",
            message='{"msg":"回答"}',
            extra="{}",
        )
    )
    await db.commit()

    @asynccontextmanager
    async def session_scope():
        yield db

    monkeypatch.setattr(feedback, "get_async_db_session", session_scope)
    monkeypatch.setattr(feedback, "get_current_tenant_id", lambda: 1)
    # 全局 conftest 把错误码模块替换为 MagicMock; 此处恢复 HTTP 异常契约。
    monkeypatch.setattr(
        feedback,
        "UnAuthorizedError",
        SimpleNamespace(http_exception=lambda msg=None: HTTPException(403, msg or "forbidden")),
    )
    monkeypatch.setattr(
        feedback,
        "NotFoundError",
        SimpleNamespace(http_exception=lambda msg=None: HTTPException(404, msg or "not found")),
    )
    yield db


async def test_rating_transitions_and_comment_survive_refresh(feedback_db):
    user = SimpleNamespace(user_id=7, tenant_id=1)
    for rating, counts in [(1, (1, 0)), (1, (1, 0)), (2, (0, 1)), (0, (0, 0)), (2, (0, 1))]:
        result = await feedback.ChatFeedbackService.update(321, user, liked=rating)
        assert result["liked"] == rating
        row = (await feedback_db.exec(select(MessageSession))).one()
        assert (row.like, row.dislike) == counts
        await feedback_db.rollback()
    await feedback.ChatFeedbackService.update(321, user, comment="  缺少依据  ")
    result = await feedback.ChatFeedbackService.update(321, user, liked=1)
    assert result == {"liked": 1, "comment": "缺少依据"}


@pytest.mark.parametrize(
    "changes,user_id,tenant_id",
    [
        ({}, 8, 1),
        ({}, 7, 2),
        ({"is_bot": False}, 7, 1),
        ({"extra": '{"error":true}'}, 7, 1),
        ({"type": "stream"}, 7, 1),
        ({"remark": "break_answer"}, 7, 1),
    ],
)
async def test_rejects_foreign_or_invalid_answers(feedback_db, changes, user_id, tenant_id, monkeypatch):
    message = await feedback_db.get(ChatMessage, 321)
    for key, value in changes.items():
        setattr(message, key, value)
    await feedback_db.commit()
    monkeypatch.setattr(feedback, "get_current_tenant_id", lambda: tenant_id)
    with pytest.raises(HTTPException):
        await feedback.ChatFeedbackService.update(321, SimpleNamespace(user_id=user_id, tenant_id=tenant_id), liked=1)
    message = await feedback_db.get(ChatMessage, 321)
    assert message.liked == 0


async def test_transaction_failure_rolls_back_message_and_counts(feedback_db, monkeypatch):
    original = feedback.ChatFeedbackRepositoryImpl.flush

    async def fail_after_flush(self):
        await original(self)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(feedback.ChatFeedbackRepositoryImpl, "flush", fail_after_flush)
    with pytest.raises(RuntimeError, match="injected failure"):
        await feedback.ChatFeedbackService.update(321, SimpleNamespace(user_id=7, tenant_id=1), liked=1)
    feedback_db.expire_all()
    message = await feedback_db.get(ChatMessage, 321)
    chat = await feedback_db.get(MessageSession, "feedback-chat")
    assert (message.liked, chat.like, chat.dislike) == (0, 0, 0)


@pytest.mark.parametrize(
    "kind,category", [("bot", "answer"), ("answer", "answer"), ("end_cover", "stream_msg"), ("over", "output_msg")]
)
async def test_existing_completed_application_answers_remain_rateable(feedback_db, kind, category):
    message = await feedback_db.get(ChatMessage, 321)
    message.type = kind
    message.category = category
    await feedback_db.commit()
    result = await feedback.ChatFeedbackService.update(321, SimpleNamespace(user_id=7, tenant_id=1), liked=1)
    assert result["liked"] == 1


async def test_audit_history_returns_saved_feedback(feedback_db, monkeypatch):
    from bisheng.workstation.domain.schemas import workstation_schema as schema

    async def get_user(user_id):
        return SimpleNamespace(user_name="测试用户")

    async def get_chat(chat_id):
        return SimpleNamespace(name="反馈会话")

    monkeypatch.setattr(schema.UserDao, "aget_user", get_user)
    monkeypatch.setattr(schema.MessageSessionDao, "async_get_one", get_chat)
    await feedback.ChatFeedbackService.update(321, SimpleNamespace(user_id=7, tenant_id=1), liked=2, comment="缺少依据")
    message = await feedback_db.get(ChatMessage, 321)
    result = await schema.WorkstationMessage.from_chat_message(message)
    assert (result.messageId, result.liked, result.comment, result.feedback_allowed) == ("321", 2, "缺少依据", True)
