"""Bounded directory queries and idempotent, independently committed projection."""

import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from typing import get_args

from sqlalchemy import and_, case, or_, update
from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation as Group
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState as State
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_title import AuditTitleQueryRepository
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyState
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def naive_utc(value):
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def utc(value):
    return value.replace(tzinfo=UTC) if value and not value.tzinfo else value


def query_filters(filters, now=None):
    explicit = {key: value for key, value in filters.items() if value is not None}
    for key in ("start_at", "end_at"):
        if key in explicit:
            if not isinstance(explicit[key], datetime):
                raise ValueError("Invalid audit query time")
            explicit[key] = naive_utc(explicit[key])
    effective = dict(explicit)
    if now is not None:
        if not isinstance(now, datetime):
            raise ValueError("Invalid audit query clock")
        end = explicit.get("end_at", naive_utc(now))
        start = explicit.get("start_at", end - timedelta(days=7))
        if start >= end or end - start > timedelta(days=31):
            raise ValueError("Audit query window exceeds bounds")
        effective.update(start_at=start, end_at=end)
    if "has_sensitive_hit" in explicit and type(explicit["has_sensitive_hit"]) is not bool:
        raise ValueError("Invalid safety hit filter")
    if "sensitive_direction" in explicit and explicit["sensitive_direction"] not in {"INPUT", "OUTPUT", "BOTH"}:
        raise ValueError("Invalid safety direction")
    if "content_safety_state" in explicit and explicit["content_safety_state"] not in get_args(ContentSafetyState):
        raise ValueError("Invalid safety state")
    return explicit, effective


def request_matches(statement, filters):
    # All predicates target this single correlated request, never separate witnesses.
    for key, value in filters.items():
        if key in {"model_name", "conversation_id"}:
            digest = Request.model_name_digest if key == "model_name" else Request.conversation_id_digest
            statement = statement.where(
                digest == sha256(value.encode("utf8")).hexdigest(), getattr(Request, key) == value
            )
        elif key == "start_at":
            statement = statement.where(Request.started_at >= value)
        elif key == "end_at":
            statement = statement.where(Request.started_at < value)
        elif key == "sensitive_direction":
            if value in {"INPUT", "BOTH"}:
                statement = statement.where(Request.input_sensitive_hit.is_(True))
            if value in {"OUTPUT", "BOTH"}:
                statement = statement.where(Request.output_sensitive_hit.is_(True))
        elif key in {"user_id", "request_id", "audit_status", "has_sensitive_hit", "content_safety_state"}:
            statement = statement.where(getattr(Request, key) == value)
        else:
            raise ValueError("Unsupported audit filter")
    return statement


def positive_safety_filter(filters):
    return (
        filters.get("has_sensitive_hit") is True
        or filters.get("sensitive_direction") is not None
        or filters.get("content_safety_state") == "BLOCKED"
    )


def query_progress(repository, *, tree=True):
    readiness = repository.readiness()
    if tree:
        progress = repository.tree_progress()
        state = repository.tree_state()
        summary_ready = progress["summary_ready"]
    else:
        # Keep sparse conversation scans at one extra bounded metadata query per page.
        pending = select(Request.request_id).where(
            Request.tenant_id == State.tenant_id, Request.hierarchy_indexed.is_(False)
        )
        row = repository.session.exec(select(State, case((pending.exists(), True), else_=False)).limit(1)).first()
        state, hierarchy_pending = row if row is not None else (None, False)
        progress = {}
        summary_ready = bool(
            state
            and state.active
            and not hierarchy_pending
            and state.revision == state.published_revision
            and state.summary_revision == state.published_summary_revision
            and state.safety_summary_revision == state.published_safety_summary_revision
        )
    published = (
        state.published_safety_summary_revision
        if state and state.active and state.published_safety_summary_revision >= 0
        else None
    )
    return {
        **readiness,
        **progress,
        "coverage": "OBSERVABLE_ESTIMATE",
        "safety_ready": bool(
            published is not None
            and state.published_at is not None
            and summary_ready
            and not readiness["indexing_pending"]
            and not state.failed
        ),
        "safety_summary_version": published if published is not None else 0,
        "safety_summary_as_of": utc(state.published_at) if published is not None else None,
    }


def group_binding(row, tenant):
    if row.tenant_id != tenant or conversation_key(tenant, row.user_id, row.conversation_id) != row.conversation_key:
        raise ValueError("Invalid audit group binding")


class AuditConversationRepository(AuditTitleQueryRepository):
    def user_names(self, user_ids):
        """Resolve only identities already present on an authorized bounded page."""
        from bisheng.user.domain.models.user import User

        require_tenant()
        ids = set(user_ids)
        if not ids:
            return {}
        if len(ids) > 100:
            raise ValueError("Audit user lookup exceeds page bounds")
        # Historical ownership stays with the audit, even if membership changes.
        return dict(self.session.exec(select(User.user_id, User.user_name).where(User.user_id.in_(ids))).all())

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
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Audit projection batch exceeds bounds")
        with strict_tenant_filter():
            return self.session.exec(
                select(Request.request_id)
                .where(Request.group_index_pending.is_(True), Request.request_id > cursor)
                .order_by(Request.request_id)
                .limit(limit)
            ).all()

    def _finish_group_projection(self, row, **values):
        # SELECT tenant filtering does not fence writes. The locked source
        # revisions and pending bit make a late completion retryable, not lossy.
        result = self.session.execute(
            update(Request)
            .where(
                Request.tenant_id == require_tenant(),
                Request.request_id == row.request_id,
                Request.state_version == row.state_version,
                Request.safety_projection_version == row.safety_projection_version,
                Request.group_index_pending.is_(True),
            )
            .values(group_index_pending=False, **values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ValueError("Audit projection source changed")
        for key, value in {"group_index_pending": False, **values}.items():
            set_committed_value(row, key, value)

    def project_request(self, request_id, *, now=None):
        """Project one locked request; the caller commits counters and progress together."""
        tenant = require_tenant()
        row = self.request(request_id, lock=True)
        if row is None or row.tenant_id != tenant or not row.group_index_pending:
            return False
        if not row.conversation_key:
            # No association is not a counted entry. Native enrichment can
            # dirty it again later without inheriting a fictitious watermark.
            self._finish_group_projection(row)
            return True
        external = row.record_origin == "EXTERNAL_SAFETY"
        valid_statuses = {"NOT_APPLICABLE"} if external else {"NORMAL", "ABNORMAL"}
        if row.audit_status not in valid_statuses:
            raise ValueError("Audit projection requires prepared associated facts")
        group_binding(row, tenant)
        now = naive_utc(now or datetime.now(UTC))
        started = naive_utc(row.started_at)
        group = self.group(row.conversation_key, lock=True)
        created = group is None
        if created:
            group = Group(
                tenant_id=tenant,
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
        entry_delta = int(row.group_indexed_status is None)
        abnormal_delta = int(row.audit_status == "ABNORMAL") - int(row.group_indexed_status == "ABNORMAL")
        hit_delta = int(row.has_sensitive_hit) - int(row.group_indexed_sensitive_hit)
        values = {
            "request_count": group.request_count + entry_delta,
            "abnormal_count": group.abnormal_count + abnormal_delta,
            "sensitive_hit_count": group.sensitive_hit_count + hit_delta,
            "first_request_at": min(naive_utc(group.first_request_at), started),
            "last_request_at": max(naive_utc(group.last_request_at), started),
            "updated_at": now,
        }
        if not (
            0 <= values["abnormal_count"] <= values["request_count"]
            and 0 <= values["sensitive_hit_count"] <= values["request_count"]
        ):
            raise ValueError("Inconsistent audit group counters")
        values["has_sensitive_hit"] = values["sensitive_hit_count"] > 0
        self._finish_group_projection(
            row, group_indexed_status=row.audit_status, group_indexed_sensitive_hit=row.has_sensitive_hit
        )
        result = self.session.execute(
            update(Group)
            .where(
                Group.tenant_id == tenant,
                Group.conversation_key == row.conversation_key,
                Group.request_count == group.request_count,
                Group.abnormal_count == group.abnormal_count,
                Group.sensitive_hit_count == group.sensitive_hit_count,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ValueError("Audit group projection changed")
        for key, value in values.items():
            set_committed_value(group, key, value)
        self.tree_dirty(structure=created)
        if hit_delta:
            state = self.tree_state(lock=True)
            state.safety_summary_revision += 1
            self.session.add(state)
        return True

    def group_page(self, *, cursor=None, limit=20, now=None, **filters):
        with strict_tenant_filter():
            return self._group_page(cursor=cursor, limit=limit, now=now, **filters)

    def _group_page(self, *, cursor=None, limit=20, now=None, **filters):
        tenant = require_tenant()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Audit conversation page exceeds bounds")
        filters, effective_filters = query_filters(filters, now)
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
        ready = query_progress(self, tree=False)
        if not ready["status_ready"] or not ready["name_ready"]:
            return {
                "items": [],
                "next_cursor": None,
                "scan_limited": False,
                "progress": {**ready, "coverage": "OBSERVABLE_ESTIMATE"},
            }
        items, scanned, exhausted = [], 0, False
        deadline = monotonic() + 1.0
        # Always examine one bounded batch so a scheduling pause cannot masquerade as exhaustion.
        while scanned < 1000 and len(items) < limit and (scanned == 0 or monotonic() < deadline):
            stmt = select(Group).where(Group.listed_at <= upper)
            if not ready["indexing_pending"] and positive_safety_filter(filters):
                stmt = stmt.where(Group.has_sensitive_hit.is_(True))
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
            match = request_matches(match, effective_filters)
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
                            "sensitive_hit_count",
                            "has_sensitive_hit",
                        )
                    }
                    items.append(
                        {
                            **data,
                            "summary_scope": "ALL_INDEXED_REQUESTS",
                            "request_filter_scope": "MATCHING_REQUESTS",
                            "matching_sensitive_hit_count": None,
                        }
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
        names = self.user_names(item["user_id"] for item in items)
        return {
            "items": self.with_titles([{**item, "user_name": names.get(item["user_id"])} for item in items]),
            "next_cursor": next_cursor,
            "scan_limited": bool(next_cursor and len(items) < limit),
            "progress": {**ready, "coverage": "OBSERVABLE_ESTIMATE"},
        }
