"""Resolve persisted attachment evidence without letting object keys choose rows."""

from sqlmodel import select

from bisheng.chat_session.domain.repositories.workflow_file_repository import WorkflowFileRepository
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.core.database import get_async_db_session
from bisheng.database.models.session import MessageSession


class ObjectDownloadRepository:
    @staticmethod
    async def owned_attachment_rows(subject: SessionSubject):
        async with get_async_db_session() as session:
            sessions = list((await session.exec(subject.filter_statement(select(MessageSession)))).all())
        rows = []
        for owner in sessions:
            if subject.matches(owner):
                rows.extend(await WorkflowFileRepository.attachment_messages(owner.chat_id))
        return rows
