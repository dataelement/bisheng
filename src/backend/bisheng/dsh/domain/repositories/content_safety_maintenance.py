"""Caller-owned, bounded safety replay and retention; never reclaim bodies or billing."""

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, update
from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel import select

from bisheng.common.errcode.dsh import DshContentSafetyExpiredError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation as Group
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.content_safety import retention_guard
from bisheng.dsh.domain.repositories.content_safety_projection import merge_audit
from bisheng.dsh.domain.repositories.content_safety_queries import as_utc, naive_utc
from bisheng.dsh.domain.repositories.model_audit_conversations import group_binding
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent


def _limit(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("Safety maintenance batch exceeds bounds")
    return value


def _after(clock, key, at, last):
    return or_(clock > at, and_(clock == at, key > last))


class ContentSafetyMaintenanceRepository:
    def __init__(self, session):
        self.session = session

    def _read(self, statement):
        with strict_tenant_filter():
            return self.session.exec(statement).all()

    def _delete_facts(self, facts, tenant):
        if not facts:
            return 0
        identities = [and_(Fact.id == fact.id, Fact.event_version == fact.event_version) for fact in facts]
        result = self.session.execute(
            delete(Fact).where(Fact.tenant_id == tenant, or_(*identities)).execution_options(synchronize_session=False)
        )
        if result.rowcount != len(facts):
            raise ValueError("Safety cleanup facts changed")
        for fact in facts:
            self.session.expunge(fact)
        return result.rowcount

    def purge_batch(self, *, details_before=None, limit=100, include_audits=True):
        """Apply an explicitly committed checkpoint, at most one bounded unit.

        Coverage AC: AC-39, AC-41, AC-43, AC-48, AC-51, AC-52, AC-53.
        The operations owner commits begin_cleanup in a separate transaction first.
        include_audits=False leaves the main cleanup checkpoint/cursor untouched.
        A NULL details cutoff never enables automatic detail retention. Native body
        metadata, shared objects/keys and model/monthly usage are outside this purge.
        """
        tenant, limit = require_tenant(), _limit(limit)
        cutoff = naive_utc(details_before) if details_before is not None else None
        setting = DshModelAuditSettingRepository(self.session).lock_retention()
        deleted, detail_more = 0, False
        if cutoff is not None:
            facts = self._read(
                select(Fact).where(Fact.received_at < cutoff).order_by(Fact.received_at, Fact.id).limit(limit + 1)
            )
            detail_more = len(facts) > limit
            deleted = self._delete_facts(facts[:limit], tenant)
        if not include_audits or setting.cleanup_before is None:
            return {"details_deleted": deleted, "audits_deleted": 0, "has_more": detail_more}

        statement = select(Request).where(Request.started_at < setting.cleanup_before)
        for column, pending in (
            (Request.model_result, "RUNNING"),
            (Request.response_result, "RUNNING"),
            (Request.usage_settlement, "PENDING"),
            (Request.content_status, "PENDING"),
            (Request.message_sources_status, "PENDING"),
        ):
            statement = statement.where(or_(column.is_(None), column != pending))
        executing = select(DshModelCall.request_id).where(
            DshModelCall.tenant_id == Request.tenant_id,
            DshModelCall.request_id == Request.request_id,
            DshModelCall.status == "RUNNING",
        )
        statement = statement.where(~executing.exists())
        if setting.cleanup_after_started_at is not None and setting.cleanup_after_request_id is not None:
            statement = statement.where(
                _after(
                    Request.started_at,
                    Request.request_id,
                    setting.cleanup_after_started_at,
                    setting.cleanup_after_request_id,
                )
            )
        rows = self._read(
            statement.order_by(Request.started_at, Request.request_id)
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        removable, waiting = [], False
        for row in rows:
            budget = limit - deleted
            facts = self._read(
                select(Fact)
                .where(Fact.audit_request_id == row.request_id)
                .order_by(Fact.occurred_at, Fact.id)
                .limit(budget + 1)
            )
            deleted += self._delete_facts(facts[:budget], tenant)
            if len(facts) > budget:
                waiting = True
                break
            removable.append(row)

        # Lock all selected requests before their groups/state, matching projection
        # order and avoiding a later request wait while this batch owns the tree lock.
        keys = sorted(
            {row.conversation_key for row in removable if row.conversation_key and row.group_indexed_status is not None}
        )
        groups = (
            self._read(
                select(Group)
                .where(Group.conversation_key.in_(keys))
                .order_by(Group.conversation_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if keys
            else []
        )
        by_key = {group.conversation_key: group for group in groups}
        for group in groups:
            group_binding(group, tenant)
        for row in removable:
            if row.conversation_key:
                group_binding(row, tenant)
            result = self.session.execute(
                delete(Request)
                .where(
                    Request.tenant_id == tenant,
                    Request.request_id == row.request_id,
                    Request.state_version == row.state_version,
                    Request.safety_projection_version == row.safety_projection_version,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise ValueError("Audit cleanup source changed")
            self.session.expunge(row)
        for key in keys:
            group = by_key.get(key)
            if group is None:
                raise ValueError("Audit cleanup group is unavailable")
            removed = [row for row in removable if row.conversation_key == key and row.group_indexed_status is not None]
            self._subtract_group(group, removed, tenant)
        if removable:
            queries = DshModelAuditQueryRepository(self.session)
            queries.tree_dirty(structure=True)
            if any(row.group_indexed_sensitive_hit for row in removable):
                state = queries.tree_state(lock=True)
                state.safety_summary_revision += 1
                self.session.add(state)

        more = waiting or len(rows) == limit
        if removable and more:
            last = removable[-1]
            setting.cleanup_after_started_at, setting.cleanup_after_request_id = last.started_at, last.request_id
        elif not more:
            # A completed pass resets its cursor, retaining the checkpoint so a
            # request skipped while running can be revisited after it terminates.
            setting.cleanup_after_started_at = setting.cleanup_after_request_id = None
        self.session.add(setting)
        self.session.flush()
        return {"details_deleted": deleted, "audits_deleted": len(removable), "has_more": detail_more or more}

    def _subtract_group(self, group, removed, tenant):
        values = {
            "request_count": group.request_count - len(removed),
            "abnormal_count": group.abnormal_count - sum(row.group_indexed_status == "ABNORMAL" for row in removed),
            "sensitive_hit_count": group.sensitive_hit_count - sum(row.group_indexed_sensitive_hit for row in removed),
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
        }
        if not (
            0 <= values["abnormal_count"] <= values["request_count"]
            and 0 <= values["sensitive_hit_count"] <= values["request_count"]
        ):
            raise ValueError("Inconsistent audit cleanup counters")
        values["has_sensitive_hit"] = values["sensitive_hit_count"] > 0
        if values["request_count"]:
            remaining = select(Request.started_at).where(
                Request.user_id == group.user_id,
                Request.conversation_key == group.conversation_key,
                Request.group_indexed_status.is_not(None),
            )
            for field, direction in (
                ("first_request_at", Request.started_at.asc()),
                ("last_request_at", Request.started_at.desc()),
            ):
                times = self._read(remaining.order_by(direction).limit(1))
                if not times:
                    raise ValueError("Audit cleanup group count has no source")
                values[field] = times[0]
        statement = update(Group).values(**values) if values["request_count"] else delete(Group)
        result = self.session.execute(
            statement.where(
                Group.tenant_id == tenant,
                Group.conversation_key == group.conversation_key,
                Group.request_count == group.request_count,
                Group.abnormal_count == group.abnormal_count,
                Group.sensitive_hit_count == group.sensitive_hit_count,
            ).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ValueError("Audit cleanup group changed")
        if not values["request_count"]:
            # Tree sources require nonempty groups; its new generation resolves
            # surviving children against the now-missing parent independently.
            self.session.expunge(group)
        else:
            for key, value in values.items():
                set_committed_value(group, key, value)

    def rebuild_batch(self, *, cursor=None, limit=100):
        """Replay retained facts, not policy evaluation or reconstruction of purged data."""
        tenant, limit = require_tenant(), _limit(limit)
        DshModelAuditSettingRepository(self.session).lock_retention()
        statement = select(Fact)
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError()
                binding, stamp, key = json.loads(base64.urlsafe_b64decode(cursor))
                if not isinstance(stamp, str) or not isinstance(key, str):
                    raise ValueError()
                at = datetime.fromisoformat(stamp)
                if type(binding) is not int or binding != tenant or at.tzinfo or str(UUID(key)) != key:
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError):
                raise ValueError("Invalid safety rebuild cursor") from None
            statement = statement.where(_after(Fact.received_at, Fact.id, at, key))
        rows = self._read(statement.order_by(Fact.received_at, Fact.id).limit(limit + 1))
        batch = rows[:limit]
        skipped_expired = 0
        for fact in batch:
            values = {name: getattr(fact, name) for name in ContentSafetyEvent.model_fields}
            for name in ("tenant_id", "user_id", "model_id"):
                values[name] = str(values[name])
            for name in ("request_started_at", "occurred_at"):
                values[name] = as_utc(values[name]).isoformat()
            event = ContentSafetyEvent.model_validate(values)
            try:
                retention_guard(self.session, event)
            except DshContentSafetyExpiredError:
                # A retained receipt never permits recreating an already retired main row.
                skipped_expired += 1
                continue
            merge_audit(self.session, event)
        self.session.flush()
        next_cursor = None
        if len(rows) > limit:
            last = batch[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps([tenant, last.received_at.isoformat(), last.id]).encode()
            ).decode()
        return {"examined": len(batch), "next_cursor": next_cursor, "skipped_expired": skipped_expired}
