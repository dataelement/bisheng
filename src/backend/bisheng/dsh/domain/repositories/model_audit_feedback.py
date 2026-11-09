"""Compare-and-set ratings for one desktop message, scoped like conversation titles."""

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_feedback import DshModelAuditFeedbackRetraction as Retraction
from bisheng.dsh.domain.models.model_audit_feedback import DshModelAuditMessageFeedback as Feedback
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def _same(row, command) -> bool:
    return (row.rating, row.category, row.note) == (command.rating, command.category, command.note)


class DshModelAuditFeedbackRepository(DshModelAuditSettingRepository):
    def apply_feedback(self, user_id, command):
        tenant = require_tenant()
        mode = self.lock_retention()
        key = conversation_key(tenant, user_id, command.conversation_id)
        statement = select(Request.conversation_id).where(
            Request.tenant_id == tenant, Request.user_id == user_id, Request.conversation_key == key
        )
        if mode is None or mode.mode == "OFF":
            statement = statement.where(
                Request.safety_source_id.is_not(None),
                Request.safety_gateway_request_id.is_not(None),
                or_(
                    Request.input_safety_state.in_(["PASSED", "BLOCKED", "ERROR"]),
                    Request.output_safety_state.in_(["PASSED", "BLOCKED", "ERROR"]),
                ),
            )
        existing = self.session.exec(statement.limit(1)).first()
        if existing != command.conversation_id:
            if mode is None or mode.mode == "OFF":
                retained = self.session.exec(
                    select(Request.conversation_id)
                    .where(Request.tenant_id == tenant, Request.user_id == user_id, Request.conversation_key == key)
                    .limit(1)
                ).first()
                if retained == command.conversation_id:
                    return {"status": "DISABLED"}
            return {"status": "NOT_READY"}
        row = self.session.exec(
            select(Feedback)
            .where(
                Feedback.tenant_id == tenant,
                Feedback.conversation_key == key,
                Feedback.message_id == command.message_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is not None and (row.user_id, row.conversation_id) != (user_id, command.conversation_id):
            raise ValueError("Audit feedback binding mismatch")
        retraction = self.session.exec(
            select(Retraction)
            .where(
                Retraction.tenant_id == tenant,
                Retraction.conversation_key == key,
                Retraction.message_id == command.message_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if retraction is not None and (retraction.user_id, retraction.conversation_id) != (
            user_id,
            command.conversation_id,
        ):
            raise ValueError("Audit feedback retraction binding mismatch")
        if row is not None and retraction is not None:
            raise ValueError("Audit feedback has conflicting states")
        current = row if row is not None else retraction
        if current is not None:
            if command.event_seq < current.event_seq:
                return {"status": "STALE", "event_seq": current.event_seq}
            if command.event_seq == current.event_seq:
                same = (
                    (command.op == "delete")
                    if retraction is not None
                    else (command.op == "put" and _same(row, command))
                )
                return {"status": "UNCHANGED" if same else "CONFLICT", "event_seq": current.event_seq}
        if command.op == "delete":
            # The tenant settings row lock serializes even a first, absent-message
            # deletion. Keep its watermark in the same transaction as the removal.
            if retraction is None:
                retraction = Retraction(
                    conversation_key=key,
                    message_id=command.message_id,
                    tenant_id=tenant,
                    user_id=user_id,
                    conversation_id=command.conversation_id,
                )
            retraction.event_seq = command.event_seq
            retraction.received_at = datetime.now(UTC).replace(tzinfo=None)
            self.session.add(retraction)
            if row is not None:
                self.session.delete(row)
            self.session.flush()
            return {"status": "UPDATED" if row is not None else "UNCHANGED", "event_seq": command.event_seq}
        if retraction is not None:
            self.session.delete(retraction)
        if row is None:
            row = Feedback(
                conversation_key=key,
                message_id=command.message_id,
                tenant_id=tenant,
                user_id=user_id,
                conversation_id=command.conversation_id,
            )
        row.rating = command.rating
        row.category = command.category
        row.note = command.note
        row.event_seq = command.event_seq
        row.received_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.add(row)
        self.session.flush()
        return {"status": "UPDATED", "event_seq": row.event_seq}


class AuditFeedbackQueryRepository:
    def with_feedback(self, items):
        tenant = require_tenant()
        if len(items) > 100:
            raise ValueError("Audit feedback page exceeds bounds")
        keys = [item["conversation_key"] for item in items]
        if not keys:
            return items
        # Count in memory. The conversation directory scan must stay free of online aggregation.
        rows = self.session.exec(
            select(Feedback.conversation_key, Feedback.user_id, Feedback.conversation_id, Feedback.rating).where(
                Feedback.tenant_id == tenant, Feedback.conversation_key.in_(keys)
            )
        ).all()
        likes: dict[str, int] = {}
        dislikes: dict[str, int] = {}
        owners = {item["conversation_key"]: (item["user_id"], item["conversation_id"]) for item in items}
        for key, user_id, conversation_id, rating in rows:
            if owners.get(key) != (user_id, conversation_id):
                raise ValueError("Audit feedback query binding mismatch")
            if rating == "positive":
                target = likes
            elif rating == "negative":
                target = dislikes
            else:
                raise ValueError("Audit feedback rating is invalid")
            target[key] = target.get(key, 0) + 1
        return [
            {
                **item,
                "like_count": likes.get(item["conversation_key"], 0),
                "dislike_count": dislikes.get(item["conversation_key"], 0),
            }
            for item in items
        ]

    def feedback_for(self, key, user_id, conversation_id):
        tenant = require_tenant()
        rows = self.session.exec(
            select(Feedback)
            .where(Feedback.tenant_id == tenant, Feedback.conversation_key == key)
            .order_by(Feedback.event_seq.desc(), Feedback.message_id)
            .limit(100)
        ).all()
        result = []
        for row in rows:
            if (row.user_id, row.conversation_id) != (user_id, conversation_id):
                raise ValueError("Audit feedback query binding mismatch")
            result.append(
                {
                    "message_id": row.message_id,
                    "rating": row.rating,
                    "category": row.category,
                    "note": row.note,
                    "event_seq": row.event_seq,
                }
            )
        return result
