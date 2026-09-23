"""Tenant-scoped durable operations. The caller owns the transaction."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError, DshOperationInProgressError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation


def require_tenant() -> int:
    """Reject missing/bypassed contexts, including administrative unscoped access."""
    tenant_id = get_current_tenant_id()
    if type(tenant_id) is not int or tenant_id < 1 or is_tenant_filter_bypassed():
        raise DshOperationConflictError()
    return tenant_id


def payload_digest(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class DshOperationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, operation_id: str, *, lock: bool = False) -> DshAdminOperation | None:
        tenant_id = require_tenant()
        statement = select(DshAdminOperation).where(DshAdminOperation.operation_id == operation_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            result = self.session.exec(statement).one_or_none()
        if result is not None and result.tenant_id != tenant_id:
            raise DshOperationConflictError()
        return result

    def locate_instance_operation(self, operation_id: str) -> int:
        """Called only after the application has verified global instance administration."""
        from bisheng.core.context.tenant import bypass_tenant_filter

        with bypass_tenant_filter():
            tenant_id = self.session.exec(
                select(DshAdminOperation.tenant_id).where(DshAdminOperation.operation_id == operation_id)
            ).one_or_none()
        if type(tenant_id) is not int or tenant_id < 1:
            raise DshOperationConflictError()
        return tenant_id

    def list_for_user(self, user_id: int, *, after_id: str | None = None, limit: int = 100):
        require_tenant()
        statement = select(DshAdminOperation).where(DshAdminOperation.user_id == user_id)
        if after_id is not None:
            statement = statement.where(DshAdminOperation.operation_id > after_id)
        with strict_tenant_filter():
            return list(self.session.exec(statement.order_by(DshAdminOperation.operation_id).limit(min(limit, 500))))

    def claim(self, operation_id: str, *, now: datetime, lease_seconds: int = 30) -> DshAdminOperation:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        operation = self.get(operation_id, lock=True)
        if operation is None or operation.status in {"SUCCEEDED", "FAILED"}:
            raise DshOperationConflictError()
        if operation.lease_until is not None and operation.lease_until > now:
            raise DshOperationInProgressError()
        operation.lease_generation += 1
        operation.attempts += 1
        operation.lease_until = now + timedelta(seconds=lease_seconds)
        operation.status = "PROCESSING"
        self.session.flush()
        return operation

    def owned(self, operation_id: str, generation: int, *, now: datetime) -> DshAdminOperation:
        operation = self.get(operation_id, lock=True)
        if (
            operation is None
            or operation.lease_generation != generation
            or operation.status != "PROCESSING"
            or operation.lease_until is None
            or operation.lease_until <= now
        ):
            raise DshOperationConflictError()
        return operation

    def set_phase(self, operation_id: str, generation: int, phase: str, *, now: datetime) -> DshAdminOperation:
        operation = self.owned(operation_id, generation, now=now)
        result = deepcopy(operation.result_payload or {})
        result["phase"] = phase
        operation.result_payload = result
        self.session.flush()
        return operation

    def retry(self, operation_id: str, generation: int, *, code: str, now: datetime, retry_at: datetime):
        operation = self.owned(operation_id, generation, now=now)
        operation.result_code = code
        operation.next_retry_at = retry_at
        operation.lease_until = now
        self.session.flush()
        return operation

    def register_intent(
        self,
        *,
        operation_id: str,
        user_id: int,
        actor_user_id: int | None,
        action: str,
        payload: dict,
        expected_grant_version: int | None = None,
    ):
        """Register a non-policy intent inside the caller's existing transaction."""
        require_tenant()
        if action not in {"REVOKE", "REASSIGN", "SYNC_PROFILE"}:
            raise ValueError("Unsupported operation action")
        if action != "SYNC_PROFILE" and (
            actor_user_id is None or type(expected_grant_version) is not int or expected_grant_version < 1
        ):
            raise ValueError("Seat commands require a real actor and grant version")
        digest = payload_digest(payload)
        existing = self.get(operation_id, lock=True)
        if existing is not None:
            if (
                existing.user_id,
                existing.actor_user_id,
                existing.action,
                existing.payload_hash,
                existing.expected_grant_version,
            ) != (user_id, actor_user_id, action, digest, expected_grant_version):
                raise DshOperationConflictError()
            return existing
        operation = DshAdminOperation(
            operation_id=operation_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            action=action,
            payload_hash=digest,
            payload=deepcopy(payload),
            expected_grant_version=expected_grant_version,
            before_values={"grant_version": expected_grant_version} if action != "SYNC_PROFILE" else None,
            result_payload={"phase": "REGISTERED"},
        )
        try:
            with self.session.begin_nested():
                self.session.add(operation)
                self.session.flush()
        except IntegrityError:
            existing = self.get(operation_id, lock=True)
            if existing is None:
                raise DshOperationConflictError() from None
            return self.register_intent(
                operation_id=operation_id,
                user_id=user_id,
                actor_user_id=actor_user_id,
                action=action,
                payload=payload,
                expected_grant_version=expected_grant_version,
            )
        return operation

    def due(self, *, now: datetime, limit: int = 100):
        require_tenant()
        if not 1 <= limit <= 100:
            raise ValueError("A dispatch batch must be between 1 and 100")
        statement = (
            select(DshAdminOperation)
            .where(
                DshAdminOperation.status.in_(["PENDING", "PROCESSING"]),
                or_(DshAdminOperation.lease_until.is_(None), DshAdminOperation.lease_until <= now),
                or_(DshAdminOperation.next_retry_at.is_(None), DshAdminOperation.next_retry_at <= now),
            )
            .order_by(DshAdminOperation.create_time, DshAdminOperation.operation_id)
            .limit(limit)
        )
        with strict_tenant_filter():
            return list(self.session.exec(statement))

    def finish(
        self, operation_id: str, generation: int, *, now: datetime, status: str, result: dict, code: str | None = None
    ):
        if status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("A terminal result is required")
        operation = self.owned(operation_id, generation, now=now)
        operation.status, operation.result_code = status, code
        operation.result_payload = deepcopy(result)
        if operation.action in {"REVOKE", "REASSIGN"} and status == "SUCCEEDED":
            # Successful Gateway commands enforce the exact ASSIGNED/REVOKED transition.
            before_state, after_state = (
                ("ASSIGNED", "REVOKED") if operation.action == "REVOKE" else ("REVOKED", "ASSIGNED")
            )
            operation.before_values = {"grant_version": operation.expected_grant_version, "state": before_state}
            operation.after_values = {"grant_version": result["result_grant_version"], "state": after_state}
        operation.effective_at = now if status == "SUCCEEDED" else None
        operation.next_retry_at = None
        self.session.flush()
        return operation
