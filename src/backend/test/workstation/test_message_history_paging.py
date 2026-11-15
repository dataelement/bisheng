"""The DAO's optional backward page keeps deterministic chronological order."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

from sqlmodel import Session, create_engine

from bisheng.database.models import message as message_module
from bisheng.database.models.message import ChatMessage, ChatMessageDao


async def test_message_history_pages_backward_with_same_timestamp(monkeypatch):
    engine = create_engine("sqlite://")
    ChatMessage.__table__.create(engine)
    with Session(engine) as session:
        for index in range(1, 8):
            session.add(
                ChatMessage(
                    id=index,
                    chat_id="chat-1" if index != 7 else "another-chat",
                    is_bot=index % 2 == 0,
                    type="end",
                    category="question" if index % 2 else "agent_answer",
                    flow_id="",
                    message=str(index),
                    tenant_id=1,
                    create_time=datetime(2026, 11, 12),
                    update_time=datetime(2026, 11, 12),
                )
            )
        session.commit()

        async def execute(statement):
            return session.exec(statement)

        @asynccontextmanager
        async def local_session():
            yield SimpleNamespace(exec=execute)

        monkeypatch.setattr(message_module, "get_async_db_session", local_session)
        latest = await ChatMessageDao.aget_messages_by_chat_id("chat-1", limit=2)
        older = await ChatMessageDao.aget_messages_by_chat_id("chat-1", limit=2, offset=2)
        questions = await ChatMessageDao.aget_messages_by_chat_id("chat-1", ["question"], limit=2, offset=1)

        assert [row.id for row in latest] == [5, 6]
        assert [row.id for row in older] == [3, 4]
        assert [row.id for row in questions] == [1, 3]
    engine.dispose()
