"""Narrow durable-subject lookups for the legacy moderation callbacks."""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.org_snapshot import stamp_session
from bisheng.database.models.session import MessageSession
from bisheng.database.models.tenant import Tenant
from bisheng.database.models.user_group import UserGroupDao


@dataclass(frozen=True)
class ModerationSubject:
    tenant_id: int | None
    user_id: int
    chat_id: str
    flow_id: str
    is_delete: bool = False
    api_subject_type: str | None = None


class ModerationRepository:
    @staticmethod
    def message_subjects(chat_id):
        with bypass_tenant_filter(), get_sync_db_session() as db:
            return db.exec(
                select(ChatMessage.user_id, ChatMessage.flow_id, ChatMessage.tenant_id)
                .where(ChatMessage.chat_id == chat_id)
                .distinct()
                .limit(2)
            ).all()

    @staticmethod
    def save_message(message, new_session=None):
        from bisheng.common.errcode.http_error import UnAuthorizedError
        from bisheng.core.context.tenant import get_current_tenant_id

        target = get_current_tenant_id()
        with get_sync_db_session() as db:
            # Recheck the exact global ID while locked: a row created by a
            # competing callback must not be mistaken for an absent session.
            with bypass_tenant_filter():
                conversation = db.exec(
                    select(MessageSession).where(MessageSession.chat_id == message.chat_id).with_for_update()
                ).one_or_none()
            created = None
            if conversation is not None:
                if (
                    conversation.user_id != message.user_id
                    or conversation.flow_id != message.flow_id
                    or conversation.tenant_id != target
                    or conversation.is_delete
                    or conversation.api_subject_type is not None
                ):
                    raise UnAuthorizedError.http_exception()
            elif new_session is not None:
                if (
                    new_session.user_id != message.user_id
                    or new_session.flow_id != message.flow_id
                    or new_session.chat_id != message.chat_id
                    or new_session.api_subject_type is not None
                ):
                    raise UnAuthorizedError.http_exception()
                new_session.tenant_id = target
                if not new_session.group_ids:
                    new_session.group_ids = [row.group_id for row in UserGroupDao.get_user_group(new_session.user_id)]
                stamp_session(new_session)
                db.add(new_session)
                db.flush()
                created = new_session
            else:
                raise UnAuthorizedError.http_exception()
            message.tenant_id = target
            db.add(message)
            db.commit()
            db.refresh(message)
            if created is not None:
                db.refresh(created)
            return message, created

    @staticmethod
    def session_subject(chat_id):
        # An exact unique-ID lookup establishes ownership before any scoped
        # business read/write. No message text or list is exposed by this port.
        statement = select(
            MessageSession.tenant_id,
            MessageSession.user_id,
            MessageSession.chat_id,
            MessageSession.flow_id,
            MessageSession.is_delete,
            MessageSession.api_subject_type,
        ).where(MessageSession.chat_id == chat_id)
        with bypass_tenant_filter(), get_sync_db_session() as db:
            row = db.exec(statement).one_or_none()
            return ModerationSubject(*row) if row is not None else None

    @staticmethod
    def message_subject(message_id):
        statement = select(ChatMessage.tenant_id, ChatMessage.user_id, ChatMessage.chat_id, ChatMessage.flow_id).where(
            ChatMessage.id == message_id
        )
        with bypass_tenant_filter(), get_sync_db_session() as db:
            row = db.exec(statement).one_or_none()
            return ModerationSubject(*row) if row is not None else None

    @staticmethod
    def tenant_status(tenant_id):
        with bypass_tenant_filter(), get_sync_db_session() as db:
            return db.exec(select(Tenant.status).where(Tenant.id == tenant_id)).one_or_none()

    @staticmethod
    def has_messages(chat_id):
        # An orphaned historic message is not a new conversation. Do not
        # fabricate a Home-owned session around a conflicting historic ID.
        with bypass_tenant_filter(), get_sync_db_session() as db:
            return db.exec(select(ChatMessage.id).where(ChatMessage.chat_id == chat_id).limit(1)).first() is not None

    @staticmethod
    def resource(resource_id):
        # Resource ownership is not the conversation's tenant. The caller
        # must run the existing use permission check before creating a session.
        with bypass_tenant_filter(), get_sync_db_session() as db:
            flow = db.exec(select(Flow).where(Flow.id == resource_id)).one_or_none()
            if flow is not None:
                return "workflow", flow
            assistant = db.exec(select(Assistant).where(Assistant.id == resource_id)).one_or_none()
            return "assistant", assistant
