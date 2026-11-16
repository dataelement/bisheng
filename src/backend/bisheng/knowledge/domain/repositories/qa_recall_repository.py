"""Persistence boundary for recall rows and their tenant-aware parents."""

from sqlmodel import col, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class QaRecallRepository:
    @staticmethod
    def parent(message_id: int):
        with strict_tenant_filter(), get_sync_db_session() as session:
            message = session.exec(select(ChatMessage).where(ChatMessage.id == message_id)).first()
            if message is None or not message.chat_id:
                return None
            parent = session.exec(select(MessageSession).where(MessageSession.chat_id == message.chat_id)).first()
            return (message, parent) if parent is not None else None

    @staticmethod
    def chunks(message_id: int, chat_id: str):
        # RecallChunk has no tenant column: both keys come from the authorized parent.
        with get_sync_db_session() as session:
            return session.exec(
                select(RecallChunk).where(RecallChunk.message_id == message_id, RecallChunk.chat_id == chat_id)
            ).all()

    @staticmethod
    def files(file_ids: set[int]):
        if not file_ids:
            return []
        with get_sync_db_session() as session:
            return session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids))).all()
