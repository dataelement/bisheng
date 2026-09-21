from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import and_, func, or_
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.repositories.interfaces.knowledge_chat_session_repository import (
    MAX_KNOWLEDGE_CHAT_REHOME_FLOWS,
    KnowledgeChatSessionRehomeResult,
    KnowledgeChatSessionRepository,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeChatSessionRepositoryImpl(KnowledgeChatSessionRepository):
    """SQLModel implementation of F068 session entry queries and updates."""

    def __init__(self, session_factory: SessionFactory = get_async_db_session):
        self._session_factory = session_factory

    @staticmethod
    def _effective_entry_clause(entry_flow_id: str):
        return or_(
            MessageSession.entry_flow_id == entry_flow_id,
            and_(
                MessageSession.entry_flow_id.is_(None),
                MessageSession.flow_id == entry_flow_id,
            ),
        )

    @classmethod
    def _active_user_entry_statement(cls, entry_flow_id: str, user_id: int):
        return select(MessageSession).where(
            MessageSession.user_id == user_id,
            MessageSession.flow_type == FlowType.KNOLEDGE_SPACE.value,
            MessageSession.is_delete == False,  # noqa: E712
            cls._effective_entry_clause(entry_flow_id),
        )

    async def list_by_effective_entry(
        self,
        entry_flow_id: str,
        user_id: int,
    ) -> list[MessageSession]:
        statement = self._active_user_entry_statement(entry_flow_id, user_id).order_by(
            MessageSession.create_time.desc()
        )
        async with self._session_factory() as session:
            result = await session.exec(statement)
            return list(result.all())

    async def get_by_chat_and_effective_entry(
        self,
        chat_id: str,
        entry_flow_id: str,
        user_id: int,
    ) -> MessageSession | None:
        statement = self._active_user_entry_statement(entry_flow_id, user_id).where(MessageSession.chat_id == chat_id)
        async with self._session_factory() as session:
            result = await session.exec(statement)
            return result.first()

    async def find_first_by_effective_entry(
        self,
        entry_flow_id: str,
        user_id: int,
    ) -> MessageSession | None:
        statement = (
            self._active_user_entry_statement(entry_flow_id, user_id)
            .order_by(MessageSession.create_time.desc())
            .limit(1)
        )
        async with self._session_factory() as session:
            result = await session.exec(statement)
            return result.first()

    async def rehome_by_flows(
        self,
        source_root_flow_id: str,
        source_flow_ids: list[str],
    ) -> KnowledgeChatSessionRehomeResult:
        unique_flow_ids = sorted(set(source_flow_ids))
        if not unique_flow_ids:
            return KnowledgeChatSessionRehomeResult(matched_count=0, updated_count=0)
        if len(unique_flow_ids) > MAX_KNOWLEDGE_CHAT_REHOME_FLOWS:
            raise ValueError(f"source_flow_ids exceeds {MAX_KNOWLEDGE_CHAT_REHOME_FLOWS}")

        conditions = (
            col(MessageSession.flow_id).in_(unique_flow_ids),
            MessageSession.flow_type == FlowType.KNOLEDGE_SPACE.value,
            MessageSession.is_delete == False,  # noqa: E712
            MessageSession.entry_flow_id.is_(None),
        )
        count_statement = select(func.count(MessageSession.chat_id)).where(*conditions)
        update_statement = update(MessageSession).where(*conditions).values(entry_flow_id=source_root_flow_id)

        # A resource operation can affect sessions owned by users in several leaf
        # tenants. The exact server-generated flow set is the authorization fence.
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                matched = (await session.exec(count_statement)).one()
                result = await session.exec(update_statement)
                await session.commit()

        rowcount = getattr(result, "rowcount", None)
        updated = matched if rowcount is None or rowcount < 0 else rowcount
        return KnowledgeChatSessionRehomeResult(
            matched_count=int(matched),
            updated_count=int(updated),
        )
