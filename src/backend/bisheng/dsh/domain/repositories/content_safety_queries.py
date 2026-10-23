"""Bounded tenant-scoped event details, separate from the main summary list."""

import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.repositories.admin_operation import require_tenant


def naive_utc(value):
    if not isinstance(value, datetime):
        raise ValueError("Invalid safety query time")
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def as_utc(value):
    return value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value


def query_uuid(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Invalid safety query request ID")
    try:
        normalized = str(UUID(value))
        if normalized != value.lower():
            raise ValueError()
    except ValueError:
        raise ValueError("Invalid safety query request ID") from None
    return normalized


def event_metadata(row):
    fields = (
        "schema_version",
        "source_id",
        "event_id",
        "gateway_request_id",
        "backend_request_id",
        "session_id",
        "protocol",
        "event_kind",
        "event_version",
        "request_started_at",
        "occurred_at",
        "received_at",
        "stage_results",
        "stage_versions",
        "policy_version",
        "builtin_digest",
        "hit_count",
        "hit_count_truncated",
        "rule_refs",
        "forwarded",
        "drain_status",
        "conversation",
        "association_status",
        "audit_request_id",
    )
    return {
        **{key: as_utc(getattr(row, key)) for key in fields},
        "user_id": str(row.user_id),
        "model_id": str(row.model_id),
    }


class ContentSafetyQueryRepository:
    def __init__(self, session):
        self.session = session

    def _page(self, statement, *, clock_column, binding, cursor, limit):
        tenant = require_tenant()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Safety event page exceeds bounds")
        fingerprint = sha256(
            json.dumps([tenant, binding], sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        if cursor:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError()
                position = json.loads(base64.urlsafe_b64decode(cursor))
                if not isinstance(position, dict):
                    raise ValueError()
                stamp, key = position["time"], position["id"]
                if not isinstance(stamp, str) or not isinstance(key, str) or len(key) != 36:
                    raise ValueError()
                at = datetime.fromisoformat(stamp)
                if position["query"] != fingerprint or at.tzinfo or str(UUID(key)) != key:
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise ValueError("Invalid safety event cursor") from None
            statement = statement.where(or_(clock_column > at, and_(clock_column == at, Fact.id > key)))
        with strict_tenant_filter():
            rows = self.session.exec(statement.order_by(clock_column, Fact.id).limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "query": fingerprint,
                        "time": getattr(last, clock_column.key).isoformat(),
                        "id": last.id,
                    },
                    separators=(",", ":"),
                ).encode()
            ).decode()
        return {"items": [event_metadata(row) for row in page], "next_cursor": next_cursor}

    def request_events(self, request_id, *, cursor=None, limit=20):
        require_tenant()
        with strict_tenant_filter():
            request = self.session.exec(select(Request).where(Request.request_id == request_id)).one_or_none()
        if request is None:
            raise LookupError("Audit request is unavailable")
        statement = select(Fact).where(Fact.audit_request_id == request.request_id)
        result = self._page(
            statement, clock_column=Fact.occurred_at, binding=["request", request_id], cursor=cursor, limit=limit
        )
        # Availability covers the request, not merely this continuation page.
        with strict_tenant_filter():
            retained = (
                bool(result["items"])
                or self.session.exec(
                    select(Fact.id).where(Fact.audit_request_id == request.request_id).limit(1)
                ).first()
                is not None
            )
        observed = (
            request.content_safety_state != "UNREPORTED"
            or request.has_sensitive_hit
            or request.input_safety_version
            or request.output_safety_version
        )
        result["details_status"] = "AVAILABLE" if retained else "PURGED" if observed else "UNREPORTED"
        return result

    def unassociated_events(
        self,
        *,
        now=None,
        start_at=None,
        end_at=None,
        user_id=None,
        model_id=None,
        gateway_request_id=None,
        backend_request_id=None,
        cursor=None,
        limit=20,
    ):
        require_tenant()
        explicit = {
            "start_at": naive_utc(start_at) if start_at is not None else None,
            "end_at": naive_utc(end_at) if end_at is not None else None,
            "user_id": user_id,
            "model_id": model_id,
            "gateway_request_id": query_uuid(gateway_request_id),
            "backend_request_id": query_uuid(backend_request_id),
        }
        end = explicit["end_at"] if end_at is not None else naive_utc(now or datetime.now(UTC))
        start = explicit["start_at"] if start_at is not None else end - timedelta(days=7)
        if start >= end or end - start > timedelta(days=31):
            raise ValueError("Safety event window exceeds bounds")
        statement = select(Fact).where(
            Fact.association_status == "UNASSOCIATED", Fact.request_started_at >= start, Fact.request_started_at < end
        )
        for field in ("user_id", "model_id", "gateway_request_id", "backend_request_id"):
            value = explicit[field]
            if value is not None:
                if field in {"user_id", "model_id"} and (
                    type(value) is not int or not 1 <= value <= 9223372036854775807
                ):
                    raise ValueError("Invalid safety query identity")
                statement = statement.where(getattr(Fact, field) == value)
        result = self._page(
            statement,
            clock_column=Fact.request_started_at,
            binding=["unassociated", explicit],
            cursor=cursor,
            limit=limit,
        )
        result["details_status"] = "AVAILABLE"
        return result
