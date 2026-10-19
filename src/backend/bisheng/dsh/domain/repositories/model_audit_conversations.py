"""Bounded directory queries and idempotent, independently committed projection."""

import base64
import json
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation as Group
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def naive_utc(value):
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def utc(value):
    return value.replace(tzinfo=UTC) if value and not value.tzinfo else value


def group_binding(row, tenant):
    if row.tenant_id != tenant or conversation_key(tenant, row.user_id, row.conversation_id) != row.conversation_key:
        raise ValueError("Invalid audit group binding")


class AuditConversationRepository:
    def readiness(self):
        require_tenant()
        missing_status = self.session.exec(
            select(Request.request_id).where(Request.audit_status.is_(None)).limit(1)
        ).first()
        missing_name = self.session.exec(
            select(Request.request_id).where(Request.model_name_digest.is_(None)).limit(1)
        ).first()
        pending = self.session.exec(
            select(Request.request_id).where(Request.group_index_pending.is_(True)).limit(1)
        ).first()
        return {
            "status_ready": missing_status is None,
            "name_ready": missing_name is None,
            "indexing_pending": pending is not None,
        }

    def group(self, key, *, lock=False):
        row = self.one(Group, Group.conversation_key == key, lock=lock)
        if row:
            group_binding(row, require_tenant())
        return row

    def projection_candidates(self, *, cursor="", limit=100):
        require_tenant()
        return self.session.exec(
            select(Request.request_id)
            .where(Request.group_index_pending.is_(True), Request.request_id > cursor)
            .order_by(Request.request_id)
            .limit(limit)
        ).all()

    def project_request(self, request_id, *, now=None):
        tenant = require_tenant()
        row = self.request(request_id, lock=True)
        if row is None or not row.group_index_pending:
            return False
        if not row.conversation_key or row.audit_status not in {"NORMAL", "ABNORMAL"}:
            raise ValueError("Audit projection requires prepared associated facts")
        group_binding(row, tenant)
        now = naive_utc(now or datetime.now(UTC))
        started = naive_utc(row.started_at)
        group = self.group(row.conversation_key, lock=True)
        if group is None:
            group = Group(
                conversation_key=row.conversation_key,
                user_id=row.user_id,
                conversation_id=row.conversation_id,
                listed_at=now,
                first_request_at=started,
                last_request_at=started,
                updated_at=now,
            )
            self.session.add(group)
            self.session.flush()
        if row.group_indexed_status is None:
            group.request_count += 1
        group.abnormal_count += int(row.audit_status == "ABNORMAL") - int(row.group_indexed_status == "ABNORMAL")
        if not 0 <= group.abnormal_count <= group.request_count:
            raise ValueError("Inconsistent audit group counters")
        group.first_request_at = min(naive_utc(group.first_request_at), started)
        group.last_request_at = max(naive_utc(group.last_request_at), started)
        group.updated_at = now
        row.group_indexed_status, row.group_index_pending = row.audit_status, False
        self.session.add(group)
        self.session.add(row)
        return True

    def group_page(self, *, cursor=None, limit=20, **filters):
        tenant = require_tenant()
        filters = {k: v for k, v in filters.items() if v is not None}
        fingerprint = sha256(
            json.dumps([tenant, filters], sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()
        upper, position = naive_utc(datetime.now(UTC)), None
        if cursor:
            try:
                if len(cursor) > 2048:
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded["query"] != fingerprint:
                    raise ValueError()
                upper = datetime.fromisoformat(decoded["upper"])
                position = (datetime.fromisoformat(decoded["listed_at"]), decoded["key"])
                if upper.tzinfo or position[0].tzinfo or not isinstance(position[1], str):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise ValueError("Invalid audit group cursor") from None
        ready = self.readiness()
        if not ready["status_ready"] or not ready["name_ready"]:
            return {
                "items": [],
                "next_cursor": None,
                "scan_limited": False,
                "progress": {**ready, "coverage": "OBSERVABLE_ESTIMATE"},
            }
        items, scanned, exhausted = [], 0, False
        deadline = monotonic() + 1.0
        while scanned < 1000 and len(items) < limit and monotonic() < deadline:
            stmt = select(Group).where(Group.listed_at <= upper)
            if filters.get("user_id") is not None:
                stmt = stmt.where(Group.user_id == filters["user_id"])
            if filters.get("conversation_id") is not None and filters.get("user_id") is not None:
                stmt = stmt.where(
                    Group.conversation_key == conversation_key(tenant, filters["user_id"], filters["conversation_id"])
                )
            if position:
                stmt = stmt.where(
                    or_(
                        Group.listed_at < position[0],
                        and_(Group.listed_at == position[0], Group.conversation_key < position[1]),
                    )
                )
            candidates = self.session.exec(
                stmt.order_by(Group.listed_at.desc(), Group.conversation_key.desc()).limit(100)
            ).all()
            if not candidates:
                exhausted = True
                break
            keys = [g.conversation_key for g in candidates]
            match = select(Request.request_id).where(
                Request.tenant_id == Group.tenant_id,
                Request.user_id == Group.user_id,
                Request.conversation_key == Group.conversation_key,
            )
            for key, value in filters.items():
                if key == "model_name":
                    match = match.where(
                        Request.model_name_digest == sha256(value.encode("utf8")).hexdigest(),
                        Request.model_name == value,
                    )
                elif key == "start_at":
                    match = match.where(Request.started_at >= value)
                elif key == "end_at":
                    match = match.where(Request.started_at < value)
                elif key == "conversation_id":
                    match = match.where(
                        Request.conversation_id_digest == sha256(value.encode("utf8")).hexdigest(),
                        Request.conversation_id == value,
                    )
                else:
                    match = match.where(getattr(Request, key) == value)
            matched = set(
                self.session.exec(
                    select(Group.conversation_key).where(Group.conversation_key.in_(keys), match.exists())
                ).all()
            )
            consumed = 0
            for group in candidates:
                consumed += 1
                scanned += 1
                group_binding(group, tenant)
                position = (naive_utc(group.listed_at), group.conversation_key)
                if group.conversation_key in matched:
                    data = {
                        k: utc(getattr(group, k)) if isinstance(getattr(group, k), datetime) else getattr(group, k)
                        for k in (
                            "conversation_key",
                            "user_id",
                            "conversation_id",
                            "listed_at",
                            "last_request_at",
                            "updated_at",
                            "request_count",
                            "abnormal_count",
                        )
                    }
                    items.append(
                        {**data, "summary_scope": "ALL_INDEXED_REQUESTS", "request_filter_scope": "MATCHING_REQUESTS"}
                    )
                if len(items) == limit:
                    break
            if consumed == len(candidates) and len(candidates) < 100:
                exhausted = True
                break
        next_cursor = None
        if not exhausted and position:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "query": fingerprint,
                        "upper": upper.isoformat(),
                        "listed_at": position[0].isoformat(),
                        "key": position[1],
                    }
                ).encode()
            ).decode()
        return {
            "items": items,
            "next_cursor": next_cursor,
            "scan_limited": bool(next_cursor and len(items) < limit),
            "progress": {**ready, "coverage": "OBSERVABLE_ESTIMATE"},
        }
