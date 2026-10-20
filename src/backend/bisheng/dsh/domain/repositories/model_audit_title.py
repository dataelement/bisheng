"""Scoped title compare-and-set, serialized with tenant audit-mode changes."""

from datetime import UTC, datetime

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_title import DshModelAuditConversationTitle as Title
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


class DshModelAuditTitleRepository(DshModelAuditSettingRepository):
    def update_title(self, user_id, command):
        tenant = require_tenant()
        mode = self._row(lock=True)
        if mode is None or mode.mode not in {"METADATA", "CONTENT"}:
            return {"status": "DISABLED"}
        key = conversation_key(tenant, user_id, command.conversation_id)
        existing = self.session.exec(
            select(Request.conversation_id)
            .where(Request.tenant_id == tenant, Request.user_id == user_id, Request.conversation_key == key)
            .limit(1)
        ).first()
        if existing != command.conversation_id:
            return {"status": "NOT_READY"}
        title = self.session.exec(
            select(Title)
            .where(Title.tenant_id == tenant, Title.conversation_key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if title is not None:
            if (title.user_id, title.conversation_id) != (user_id, command.conversation_id):
                raise ValueError("Audit title binding mismatch")
            if command.title_event_seq < title.title_event_seq:
                return {"status": "STALE"}
            if command.title_event_seq == title.title_event_seq:
                return {
                    "status": "UNCHANGED" if title.title == command.title else "CONFLICT",
                    "title_event_seq": title.title_event_seq,
                }
        else:
            title = Title(
                conversation_key=key, tenant_id=tenant, user_id=user_id, conversation_id=command.conversation_id
            )
        title.title, title.title_event_seq = command.title, command.title_event_seq
        title.received_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.add(title)
        self.session.flush()
        return {"status": "UPDATED", "title_event_seq": title.title_event_seq}


class AuditTitleQueryRepository:
    def with_titles(self, items):
        tenant = require_tenant()
        if len(items) > 100:
            raise ValueError("Audit title page exceeds bounds")
        keys = [item["conversation_key"] for item in items]
        if not keys:
            return items
        titles = {
            row.conversation_key: row
            for row in self.session.exec(
                select(Title).where(Title.tenant_id == tenant, Title.conversation_key.in_(keys))
            ).all()
        }
        result = []
        for item in items:
            title = titles.get(item["conversation_key"])
            if title and (title.tenant_id, title.user_id, title.conversation_id) != (
                tenant,
                item["user_id"],
                item["conversation_id"],
            ):
                raise ValueError("Audit title query binding mismatch")
            result.append(
                {
                    **item,
                    "conversation_title": title.title if title else None,
                    "title_event_seq": title.title_event_seq if title else None,
                }
            )
        return result
