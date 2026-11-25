"""Load canonical resources for assistant reference and conversation authorization."""

from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.models.knowledge import Knowledge


class AssistantBoundaryRepository:
    @staticmethod
    async def knowledge(knowledge_ids):
        async with get_async_db_session() as session:
            return (await session.exec(select(Knowledge).where(col(Knowledge.id).in_(knowledge_ids)))).all()

    @staticmethod
    async def flows(flow_ids):
        async with get_async_db_session() as session:
            return (await session.exec(select(Flow).where(col(Flow.id).in_(flow_ids)))).all()

    @staticmethod
    async def assistant(assistant_id):
        async with get_async_db_session() as session:
            return (await session.exec(select(Assistant).where(Assistant.id == assistant_id))).first()

    @staticmethod
    async def session(chat_id):
        async with get_async_db_session() as session:
            return (await session.exec(select(MessageSession).where(MessageSession.chat_id == chat_id))).first()
