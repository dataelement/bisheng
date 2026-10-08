"""Bounded merge of existing audit sources with tenant-scoped name resolution."""

import base64
import json
import os
import re
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicyAudit
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.audit import AuditPage, AuditRecord
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.user.domain.models.user import User

SAFE_FIELDS = {
    "model_id",
    "enabled",
    "monthly_token_limit",
    "version",
    "grant_version",
    "state",
    "profile_version",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "event_version",
    "status",
    "usage_month",
}


def snapshot(value):
    """Expose scalar business evidence, never arbitrary payloads or credentials."""
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in SAFE_FIELDS
        and (
            item is None
            or type(item) in (int, bool)
            or (isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item))
        )
    }


class DshAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_records(self, *, cursor=None, limit=20, action=None, status=None):
        tenant = require_tenant()
        binding = [tenant, action, status, limit]
        position = self._cursor(cursor, binding) if cursor else None
        rows = []
        with strict_tenant_filter():
            for source, model, key in (
                ("operation", DshAdminOperation, DshAdminOperation.operation_id),
                ("subject", DshSubjectPolicyAudit, DshSubjectPolicyAudit.id),
            ):
                statement = select(model)
                if source == "operation":
                    if action:
                        statement = statement.where(model.action == action)
                    if status:
                        statement = statement.where(model.status == status)
                else:
                    if status and status != "SUCCEEDED":
                        continue
                    if action:
                        subject_type = {"UPDATE_DEPARTMENT_POLICY": "DEPARTMENT", "UPDATE_ROLE_POLICY": "ROLE"}.get(
                            action
                        )
                        if subject_type is None:
                            continue
                        statement = statement.where(model.subject_type == subject_type)
                if position:
                    at, boundary_source, boundary_key = position
                    before = model.create_time < at
                    if source < boundary_source:
                        before = model.create_time <= at
                    elif source == boundary_source:
                        before = or_(before, and_(model.create_time == at, key < boundary_key))
                    statement = statement.where(before)
                selected = self.session.exec(
                    statement.order_by(model.create_time.desc(), key.desc()).limit(limit + 1)
                ).all()
                # Retain a defense-in-depth check even when automatic filters are installed.
                if any(row.tenant_id != tenant for row in selected):
                    raise DshInvalidRequestError()
                rows.extend((row.create_time, source, getattr(row, key.key), row) for row in selected)
            rows.sort(key=lambda row: row[:3], reverse=True)
            has_more = len(rows) > limit
            selected = rows[:limit]
            records = [self._record(source, row) for _, source, _, row in selected]
            self._names(records, tenant)
        next_cursor = None
        if has_more:
            at, source, key, _ = selected[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps([binding, at.isoformat(), source, key]).encode()).decode()
        return AuditPage(data=records, page_size=limit, has_more=has_more, next_cursor=next_cursor).model_dump(
            mode="json"
        )

    @staticmethod
    def _cursor(value, binding):
        try:
            stored_binding, raw_at, source, key = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
            if stored_binding != binding or source not in {"operation", "subject"}:
                raise ValueError()
            at = datetime.fromisoformat(raw_at)
            if at.tzinfo is not None:
                raise ValueError()
            if source == "subject":
                if type(key) is not int or not 0 < key <= 9223372036854775807:
                    raise ValueError()
            elif str(UUID(key)) != key:
                raise ValueError()
            return at, source, key
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
            raise DshInvalidRequestError() from None

    @staticmethod
    def _record(source, row):
        operation = source == "operation"
        payload = row.payload if operation else {}
        model_id = payload.get("model_id") if isinstance(payload, dict) else None
        if not operation:
            model_id = row.model_id
        if type(model_id) is not int or model_id < 1:
            model_id = None
        result_code = row.result_code if operation else None
        if result_code and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result_code):
            result_code = None
        return AuditRecord(
            id=f"{source}:{row.operation_id if operation else row.id}",
            # SQL CURRENT_TIMESTAMP follows the deployment TZ, unlike model-call UTC timestamps.
            created_at=row.create_time.replace(tzinfo=ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))).astimezone(UTC),
            action=row.action if operation else f"UPDATE_{row.subject_type}_POLICY",
            status=row.status if operation else "SUCCEEDED",
            actor_id=row.actor_user_id,
            actor_name=None,
            target_type="USER" if operation else row.subject_type,
            target_id=row.user_id if operation else row.subject_id,
            target_name=None,
            model_id=model_id,
            model_name=None,
            before_values=snapshot(row.before_values),
            after_values=snapshot(row.after_values),
            requested_values=snapshot(payload) if operation and row.status != "SUCCEEDED" else {},
            result_code=result_code,
        )

    def _names(self, records, tenant):
        user_ids = {row.actor_id for row in records if row.actor_id is not None}
        user_ids.update(row.target_id for row in records if row.target_type == "USER")
        # UserTenant is explicitly excluded from automatic tenant filtering.
        users = (
            dict(
                self.session.exec(
                    select(User.user_id, User.user_name)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .where(UserTenant.tenant_id == tenant, User.user_id.in_(user_ids))
                ).all()
            )
            if user_ids
            else {}
        )
        names = {"USER": users}
        for kind, model, name in (("DEPARTMENT", Department, Department.name), ("ROLE", Role, Role.role_name)):
            ids = {row.target_id for row in records if row.target_type == kind}
            names[kind] = dict(self.session.exec(select(model.id, name).where(model.id.in_(ids))).all()) if ids else {}
        model_ids = {row.model_id for row in records if row.model_id is not None}
        models = {}
        if model_ids:
            for model_id, model_name, name in self.session.exec(
                select(LLMModel.id, LLMModel.model_name, LLMModel.name).where(LLMModel.id.in_(model_ids))
            ).all():
                models[model_id] = model_name.strip() or name
        for row in records:
            row.actor_name = users.get(row.actor_id)
            row.target_name = names[row.target_type].get(row.target_id)
            row.model_name = models.get(row.model_id)
