"""Metadata-only keyset queries and durable original-body access attempts."""

import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.model_audit_content import DshModelAuditBodyAccess
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditEvidence, DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.content_safety_queries import naive_utc
from bisheng.dsh.domain.repositories.model_audit_conversations import AuditConversationRepository
from bisheng.dsh.domain.repositories.model_audit_tree_queries import AuditTreeQueryRepository
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.model_audit import AuditRequestMetadata
from bisheng.dsh.domain.schemas.model_audit_status import audit_status_facts
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def as_utc(value):
    return value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value


class DshModelAuditQueryRepository(AuditTreeQueryRepository, AuditConversationRepository, DshModelAuditWriteRepository):
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

    def metadata(self, row, *, user_names=None, usage_by_request=None, failures_by_request=None):
        usage = (
            self.one(DshModelCall, DshModelCall.request_id == row.request_id)
            if usage_by_request is None
            else usage_by_request.get(row.request_id)
        )
        names = AuditRequestMetadata.model_fields
        data = {
            key: as_utc(getattr(row, key))
            for key in names
            if key
            not in {
                "usage",
                "status_reasons",
                "status_pending",
                "user_name",
                "model_error_code",
                "response_error_code",
                "source_id",
                "gateway_request_id",
                "stage_results",
                "stage_versions",
                "safety_observed_at",
                "details_status",
            }
        }
        data.update(
            source_id=row.safety_source_id,
            gateway_request_id=row.safety_gateway_request_id,
            stage_results={"input": row.input_safety_state, "output": row.output_safety_state},
            stage_versions={"input": row.input_safety_version, "output": row.output_safety_version},
            safety_observed_at=as_utc(row.content_safety_updated_at),
            details_status="PENDING"
            if (
                row.content_safety_state != "UNREPORTED"
                or row.has_sensitive_hit
                or row.input_safety_version
                or row.output_safety_version
            )
            else "UNREPORTED",
        )
        failure = None
        if row.response_result in {"ERROR", "INTERRUPTED", "UNKNOWN"}:
            failure = (
                self.one(
                    DshModelAuditEvidence,
                    DshModelAuditEvidence.request_id == row.request_id,
                    DshModelAuditEvidence.event_type == "RESPONSE_FAILURE",
                )
                if failures_by_request is None
                else failures_by_request.get(row.request_id)
            )
        data["model_error_code"] = getattr(usage, "error_code", None)
        data["response_error_code"] = failure.reason if failure else None
        names_by_id = self.user_names([row.user_id]) if user_names is None else user_names
        data["user_name"] = names_by_id.get(row.user_id)
        if row.record_origin == "EXTERNAL_SAFETY":
            data.update(audit_status="NOT_APPLICABLE", status_reasons=[], status_pending=False)
        else:
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

    def page(self, *, cursor=None, limit=20, now=None, exclude_auxiliary=False, **filters):
        tenant = require_tenant()
        if type(limit) is not int or not 1 <= limit <= 100 or type(exclude_auxiliary) is not bool:
            raise ValueError("Audit request page exceeds bounds")
        filters = {key: value for key, value in filters.items() if value is not None}
        window = None
        if now is not None:
            for key in ("start_at", "end_at"):
                if key in filters:
                    filters[key] = naive_utc(filters[key])
            end = filters.get("end_at", naive_utc(now))
            start = filters.get("start_at", end - timedelta(days=7))
            if start >= end or end - start > timedelta(days=31):
                raise ValueError("Audit request window exceeds bounds")
            window = start, end
        # Bind only explicit filters. A moving default window is not a user edit.
        fingerprint = sha256(
            json.dumps(
                [tenant, {**filters, "exclude_auxiliary": True} if exclude_auxiliary else filters],
                sort_keys=True,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        statement = select(DshModelAuditRequest)
        if exclude_auxiliary:
            statement = statement.where(
                or_(
                    DshModelAuditRequest.request_kind.is_(None),
                    DshModelAuditRequest.request_kind.not_in(("session-title", "compaction")),
                )
            )
        if window is not None:
            statement = statement.where(
                DshModelAuditRequest.started_at >= window[0], DshModelAuditRequest.started_at < window[1]
            )
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
            elif key == "sensitive_direction":
                if value not in {"INPUT", "OUTPUT", "BOTH"}:
                    raise ValueError("Invalid safety direction")
                if value in {"INPUT", "BOTH"}:
                    statement = statement.where(DshModelAuditRequest.input_sensitive_hit.is_(True))
                if value in {"OUTPUT", "BOTH"}:
                    statement = statement.where(DshModelAuditRequest.output_sensitive_hit.is_(True))
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
        with strict_tenant_filter():
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
        names_by_id = self.user_names(row.user_id for row in page)
        ids = [row.request_id for row in page]
        failure_ids = [row.request_id for row in page if row.response_result in {"ERROR", "INTERRUPTED", "UNKNOWN"}]
        with strict_tenant_filter():
            usage = (
                {
                    row.request_id: row
                    for row in self.session.exec(select(DshModelCall).where(DshModelCall.request_id.in_(ids))).all()
                }
                if ids
                else {}
            )
            failures = {}
            if failure_ids:
                evidence = self.session.exec(
                    select(DshModelAuditEvidence).where(
                        DshModelAuditEvidence.request_id.in_(failure_ids),
                        DshModelAuditEvidence.event_type == "RESPONSE_FAILURE",
                    )
                ).all()
                failures = {row.request_id: row for row in evidence}
        return {
            "items": [
                self.metadata(row, user_names=names_by_id, usage_by_request=usage, failures_by_request=failures)
                for row in page
            ],
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
