"""Metadata-only keyset queries and durable original-body access attempts."""

import base64
import json
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_content import DshModelAuditBodyAccess
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditEvidence, DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_conversations import AuditConversationRepository
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.model_audit import AuditRequestMetadata
from bisheng.dsh.domain.schemas.model_audit_status import audit_status_facts
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def as_utc(value):
    return value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value


class DshModelAuditQueryRepository(AuditConversationRepository, DshModelAuditWriteRepository):
    @staticmethod
    def pending_tenants(session, *, cursor=None):
        from bisheng.core.context.tenant import bypass_tenant_filter

        with bypass_tenant_filter():
            return session.exec(
                select(DshModelAuditRequest.tenant_id)
                .where(
                    DshModelAuditRequest.tenant_id > (cursor or 0),
                    or_(
                        DshModelAuditRequest.model_result == "RUNNING",
                        DshModelAuditRequest.response_result == "RUNNING",
                        DshModelAuditRequest.usage_settlement == "PENDING",
                        DshModelAuditRequest.content_status == "PENDING",
                        DshModelAuditRequest.message_sources_status == "PENDING",
                        DshModelAuditRequest.group_index_pending.is_(True),
                    ),
                )
                .distinct()
                .order_by(DshModelAuditRequest.tenant_id)
                .limit(100)
            ).all()

    def stalled(self, *, cursor=None):
        require_tenant()
        statement = select(DshModelAuditRequest).where(
            or_(
                DshModelAuditRequest.model_result == "RUNNING",
                DshModelAuditRequest.response_result == "RUNNING",
                DshModelAuditRequest.usage_settlement == "PENDING",
                DshModelAuditRequest.content_status == "PENDING",
            )
        )
        if cursor:
            statement = statement.where(DshModelAuditRequest.request_id > cursor)
        return self.session.exec(statement.order_by(DshModelAuditRequest.request_id).limit(100)).all()

    def pending_annotations(self, *, cursor=None):
        require_tenant()
        statement = select(DshModelAuditRequest).where(DshModelAuditRequest.message_sources_status == "PENDING")
        if cursor:
            statement = statement.where(
                or_(
                    DshModelAuditRequest.started_at > cursor[0],
                    and_(DshModelAuditRequest.started_at == cursor[0], DshModelAuditRequest.request_id > cursor[1]),
                )
            )
        return self.session.exec(
            statement.order_by(DshModelAuditRequest.started_at, DshModelAuditRequest.request_id).limit(100)
        ).all()

    def metadata(self, row):
        usage = self.one(DshModelCall, DshModelCall.request_id == row.request_id)
        names = AuditRequestMetadata.model_fields
        data = {
            key: as_utc(getattr(row, key)) for key in names if key not in {"usage", "status_reasons", "status_pending"}
        }
        _, data["status_reasons"], data["status_pending"] = audit_status_facts(row)
        data["usage"] = (
            {
                key: as_utc(getattr(usage, key))
                for key in (
                    "status",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "settled_at",
                    "cache_read_tokens",
                    "cache_creation_tokens",
                    "latency_ms",
                )
            }
            if usage is not None
            else None
        )
        return AuditRequestMetadata(**data).model_dump()

    def page(self, *, cursor=None, limit=20, **filters):
        tenant = require_tenant()
        filters = {key: value for key, value in filters.items() if value is not None}
        fingerprint = sha256(
            json.dumps(
                [tenant, filters], sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        statement = select(DshModelAuditRequest)
        for key, value in filters.items():
            if key == "conversation_id":
                statement = statement.where(
                    DshModelAuditRequest.conversation_id_digest == sha256(value.encode("utf8")).hexdigest()
                )
                if filters.get("user_id") is not None:
                    statement = statement.where(
                        DshModelAuditRequest.conversation_key == conversation_key(tenant, filters["user_id"], value)
                    )
            elif key == "user_keyword":
                from bisheng.user.domain.models.user import User

                escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                statement = statement.join(User, User.user_id == DshModelAuditRequest.user_id).where(
                    User.user_name.like("%" + escaped + "%", escape="\\")
                )
            elif key == "start_at":
                statement = statement.where(DshModelAuditRequest.started_at >= value)
            elif key == "end_at":
                statement = statement.where(DshModelAuditRequest.started_at < value)
            elif key == "model_name":
                statement = statement.where(
                    DshModelAuditRequest.model_name_digest == sha256(value.encode("utf8")).hexdigest(),
                    DshModelAuditRequest.model_name == value,
                )
            elif key == "user_ids":
                statement = statement.where(DshModelAuditRequest.user_id.in_(value))
            else:
                statement = statement.where(getattr(DshModelAuditRequest, key) == value)
        if cursor:
            try:
                if len(cursor) > 2048:
                    raise ValueError()
                position = json.loads(base64.urlsafe_b64decode(cursor))
                if position["query"] != fingerprint or not isinstance(position["request_id"], str):
                    raise ValueError()
                started = datetime.fromisoformat(position["started_at"])
            except (ValueError, KeyError, TypeError):
                raise ValueError("Invalid audit cursor") from None
            statement = statement.where(
                or_(
                    DshModelAuditRequest.started_at > started,
                    and_(
                        DshModelAuditRequest.started_at == started,
                        DshModelAuditRequest.request_id > position["request_id"],
                    ),
                )
            )
        rows = self.session.exec(
            statement.order_by(DshModelAuditRequest.started_at, DshModelAuditRequest.request_id).limit(limit + 1)
        ).all()
        if "conversation_id" in filters and any(row.conversation_id != filters["conversation_id"] for row in rows):
            raise ValueError("Audit conversation digest binding mismatch")
        if "model_name" in filters and any(row.model_name != filters["model_name"] for row in rows):
            raise ValueError("Audit model name digest binding mismatch")
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {"query": fingerprint, "started_at": last.started_at.isoformat(), "request_id": last.request_id}
                ).encode()
            ).decode()
        return {
            "items": [self.metadata(row) for row in page],
            "next_cursor": next_cursor,
            "progress": {
                "last_write_at": as_utc(max((row.last_write_at for row in page if row.last_write_at), default=None)),
                "coverage": "OBSERVABLE_ESTIMATE",
                "pending_events": None,
                "limitations": ["buffers_and_evidence_can_both_be_lost", "process_buffers_not_globally_measurable"],
            },
        }

    def missing(self, request_id):
        entered = self.one(
            DshModelAuditEvidence,
            DshModelAuditEvidence.request_id == request_id,
            DshModelAuditEvidence.event_type == "MODEL_ENTERED",
        )
        diagnostic = self.one(
            DshModelAuditEvidence,
            DshModelAuditEvidence.request_id == request_id,
            DshModelAuditEvidence.event_type == "MODE_READ_FAILED",
        )
        business = self.one(DshModelCall, DshModelCall.request_id == request_id)
        return {
            "request_id": request_id,
            "audit_record_missing": True,
            "gap": "CONFIRMED"
            if entered
            else ("DEGRADED_OFF" if diagnostic else ("MODE_UNKNOWN" if business else "UNKNOWN")),
            "model_entered_at": as_utc(entered.observed_at) if entered else None,
            "effective_mode": entered.effective_mode if entered else ("OFF" if diagnostic else None),
            "explanation": "missing_audit_is_not_proof_of_no_model_call",
        }

    def access_attempt(self, *, actor_id, request_id, trace_id):
        row = DshModelAuditBodyAccess(actor_user_id=actor_id, request_id=request_id, trace_id=trace_id)
        self.session.add(row)
        self.session.flush()
        return row.access_id

    def finish_access(self, access_id, status):
        row = self.one(DshModelAuditBodyAccess, DshModelAuditBodyAccess.access_id == access_id, lock=True)
        if row:
            row.transfer_status = status
            self.session.add(row)
