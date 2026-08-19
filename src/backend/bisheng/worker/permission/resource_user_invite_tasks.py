from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
)
from bisheng.permission.domain.ports.resource_user_invite_dispatcher import (
    ResourceUserInviteDispatcher,
)
from bisheng.permission.domain.services.resource_grant_executor_registry import (
    ResourceGrantExecutorRegistry,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_GRANT_RESULT_SNAPSHOT_KEY = "grant_result"

_EXECUTION_RETRY_OPTIONS = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 8},
}


class CeleryResourceUserInviteDispatcher(ResourceUserInviteDispatcher):
    """Publish a stable business request; broker acceptance is not completion."""

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        tenant_id = _require_positive_id(tenant_id, field_name="tenant_id")
        request_id = _require_positive_id(request_id, field_name="request_id")
        execute_resource_user_invite.apply_async(
            kwargs={"request_id": request_id},
            headers={"tenant_id": tenant_id},
        )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
    name="bisheng.worker.permission.resource_user_invite_tasks.execute_resource_user_invite",
    **_EXECUTION_RETRY_OPTIONS,
)
def execute_resource_user_invite(self, *, request_id: int) -> dict[str, Any]:
    """Execute one Permission-owned invite using its stable request identity."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _execute_resource_user_invite_async(
            tenant_id=tenant_id,
            request_id=request_id,
        ),
    )


def _run_in_task_tenant(*, request, coroutine_factory):
    tenant_id = _require_tenant_id_header(request)
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        return run_async_task(lambda: coroutine_factory(tenant_id))
    finally:
        current_tenant_id.reset(tenant_token)


def _require_tenant_id_header(request) -> int:
    headers = getattr(request, "headers", None) or {}
    raw_tenant_id = headers.get("tenant_id")
    if raw_tenant_id is None or isinstance(raw_tenant_id, bool):
        raise ValueError("resource user invite worker requires a tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as error:
        raise ValueError("resource user invite worker tenant_id header must be a positive integer") from error
    if tenant_id <= 0:
        raise ValueError("resource user invite worker tenant_id header must be a positive integer")
    return tenant_id


def _build_grant_executor_registry() -> ResourceGrantExecutorRegistry:
    # The T019 composition root owns concrete Knowledge/Channel registrations.
    # This lazy import keeps task module registration free from database/network I/O.
    from bisheng.bootstrap.approval_scenarios import get_resource_grant_executor_registry

    return get_resource_grant_executor_registry()


def _build_business_notification_service():
    from bisheng.permission.domain.services.resource_user_invite_application_service import (
        ResourceUserInviteBusinessNotificationService,
    )

    return ResourceUserInviteBusinessNotificationService()


async def _execute_resource_user_invite_async(
    *,
    tenant_id: int,
    request_id: int,
    notification_service=None,
) -> dict[str, Any]:
    tenant_id = _require_execution_tenant(tenant_id)
    request_id = _require_positive_id(request_id, field_name="request_id")
    row, execution_token, resuming = await _claim_or_resume(
        tenant_id=tenant_id,
        request_id=request_id,
    )
    notification_service = notification_service or _build_business_notification_service()
    if row.execution_state == ResourceUserInviteExecutionState.APPLIED:
        await notification_service.notify_execution_result(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
        return _execution_result(row)

    command = _build_grant_command(row)
    registry = _build_grant_executor_registry()
    execution_error: Exception | None = None

    if resuming:
        try:
            verification = await registry.verify(command)
        except Exception as error:
            await _mark_failed(
                tenant_id=tenant_id,
                request_id=request_id,
                execution_token=execution_token,
                error=error,
            )
            await _notify_failed_best_effort(
                notification_service=notification_service,
                tenant_id=tenant_id,
                request_id=request_id,
                execution_token=execution_token,
            )
            raise
        if verification.applied:
            result = await _mark_applied(
                tenant_id=tenant_id,
                request_id=request_id,
                execution_token=execution_token,
                verification=verification,
            )
            await notification_service.notify_execution_result(
                tenant_id=tenant_id,
                request_id=request_id,
                execution_token=execution_token,
            )
            return result

    try:
        await registry.execute(command)
    except Exception as error:
        execution_error = error

    try:
        verification = await registry.verify(command)
    except Exception as verification_error:
        await _mark_failed(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
            error=execution_error or verification_error,
        )
        await _notify_failed_best_effort(
            notification_service=notification_service,
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
        if execution_error is not None:
            raise execution_error
        raise

    if verification.applied:
        result = await _mark_applied(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
            verification=verification,
        )
        await notification_service.notify_execution_result(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
        return result

    failure = execution_error or RuntimeError("resource user invite grant was not authoritatively verified as applied")
    await _mark_failed(
        tenant_id=tenant_id,
        request_id=request_id,
        execution_token=execution_token,
        error=failure,
    )
    await _notify_failed_best_effort(
        notification_service=notification_service,
        tenant_id=tenant_id,
        request_id=request_id,
        execution_token=execution_token,
    )
    raise failure


async def _notify_failed_best_effort(
    *,
    notification_service,
    tenant_id: int,
    request_id: int,
    execution_token: str,
) -> None:
    try:
        await notification_service.notify_execution_result(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
    except Exception as error:
        logger.bind(
            tenant_id=tenant_id,
            business_request_id=request_id,
            execution_token=execution_token,
            notification_error_type=type(error).__name__,
        ).warning("resource user invite business failure notification will retry")


async def _claim_or_resume(
    *,
    tenant_id: int,
    request_id: int,
) -> tuple[ResourceUserInviteRequest, str, bool]:
    async with get_async_db_session() as session, session.begin():
        row = await _load_for_update(session, tenant_id=tenant_id, request_id=request_id)
        if row.execution_state == ResourceUserInviteExecutionState.APPLIED:
            return row, _require_execution_token(row.execution_token), False
        if row.execution_state == ResourceUserInviteExecutionState.APPLYING:
            return row, _require_execution_token(row.execution_token), True
        if row.execution_state not in {
            ResourceUserInviteExecutionState.QUEUED,
            ResourceUserInviteExecutionState.FAILED,
        }:
            raise RuntimeError(f"resource user invite cannot be executed from state {row.execution_state}")
        if row.active_marker != 0 or row.approval_instance_id is None or row.decision_event_id is None:
            raise RuntimeError("resource user invite execution binding is incomplete")

        execution_token = row.execution_token or secrets.token_hex(16)
        row.execution_token = execution_token
        row.execution_state = ResourceUserInviteExecutionState.APPLYING
        row.error_summary = None
        session.add(row)
        await session.flush()
        return row, execution_token, False


async def _mark_applied(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    verification: ResourceGrantVerificationResult,
) -> dict[str, Any]:
    grant_result = _json_snapshot(verification.result_snapshot)
    async with get_async_db_session() as session, session.begin():
        row = await _load_for_update(session, tenant_id=tenant_id, request_id=request_id)
        if (
            row.execution_state != ResourceUserInviteExecutionState.APPLYING
            or row.execution_token != execution_token
        ):
            raise RuntimeError("resource user invite execution claim token ownership was lost")
        result_snapshot = dict(row.result_snapshot or {})
        result_snapshot[_GRANT_RESULT_SNAPSHOT_KEY] = grant_result
        statement = (
            update(ResourceUserInviteRequest)
            .where(
                ResourceUserInviteRequest.tenant_id == tenant_id,
                ResourceUserInviteRequest.id == request_id,
                ResourceUserInviteRequest.execution_state == ResourceUserInviteExecutionState.APPLYING,
                ResourceUserInviteRequest.execution_token == execution_token,
            )
            .values(
                execution_state=ResourceUserInviteExecutionState.APPLIED,
                active_marker=request_id,
                error_summary=None,
                result_snapshot=result_snapshot,
            )
        )
        result = await session.execute(statement)
        _require_cas_ownership(result.rowcount)
        row = await _load_for_update(session, tenant_id=tenant_id, request_id=request_id)
    return _execution_result(row)


async def _mark_failed(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    error: Exception,
) -> None:
    error_summary = _error_summary(error)
    async with get_async_db_session() as session, session.begin():
        statement = (
            update(ResourceUserInviteRequest)
            .where(
                ResourceUserInviteRequest.tenant_id == tenant_id,
                ResourceUserInviteRequest.id == request_id,
                ResourceUserInviteRequest.execution_state == ResourceUserInviteExecutionState.APPLYING,
                ResourceUserInviteRequest.execution_token == execution_token,
            )
            .values(
                execution_state=ResourceUserInviteExecutionState.FAILED,
                active_marker=0,
                error_summary=error_summary,
            )
        )
        result = await session.execute(statement)
        _require_cas_ownership(result.rowcount)
    logger.bind(
        tenant_id=tenant_id,
        business_request_id=request_id,
        execution_token=execution_token,
    ).warning("resource user invite grant execution failed: {}", error_summary)


async def _load_for_update(
    session: AsyncSession,
    *,
    tenant_id: int,
    request_id: int,
) -> ResourceUserInviteRequest:
    statement = (
        select(ResourceUserInviteRequest)
        .where(
            ResourceUserInviteRequest.tenant_id == tenant_id,
            ResourceUserInviteRequest.id == request_id,
        )
        .with_for_update()
    )
    result = await session.execute(statement)
    row = result.scalars().first()
    if row is None:
        raise LookupError("resource user invite request does not exist for tenant")
    return row


def _build_grant_command(row: ResourceUserInviteRequest) -> ResourceGrantCommand:
    if row.id is None or row.tenant_id is None:
        raise RuntimeError("resource user invite execution identity is incomplete")
    return ResourceGrantCommand(
        tenant_id=int(row.tenant_id),
        request_id=int(row.id),
        request_fingerprint=row.request_fingerprint,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        inviter_user_id=row.inviter_user_id,
        target_user_id=row.target_user_id,
        relation=row.relation,
        model_id=row.model_id,
        include_children=row.include_children,
        role_snapshot=row.role_snapshot,
        role_fingerprint=row.role_fingerprint,
    )


def _execution_result(row: ResourceUserInviteRequest) -> dict[str, Any]:
    if row.id is None:
        raise RuntimeError("resource user invite request id is missing")
    return {
        "status": row.execution_state,
        "request_id": int(row.id),
        "execution_token": _require_execution_token(row.execution_token),
    }


def _json_snapshot(snapshot: Mapping[str, object]) -> dict[str, Any]:
    def thaw(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): thaw(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [thaw(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return [thaw(item) for item in sorted(value, key=repr)]
        return value

    normalized = thaw(snapshot)
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parsed = json.loads(canonical)
    if not isinstance(parsed, dict):
        raise ValueError("resource grant result_snapshot must be a JSON object")
    return parsed


def _require_execution_tenant(tenant_id: int) -> int:
    tenant_id = _require_positive_id(tenant_id, field_name="tenant_id")
    current = get_current_tenant_id()
    if current is None or isinstance(current, bool) or int(current) != tenant_id:
        raise ValueError("resource user invite execution requires the matching tenant context")
    return tenant_id


def _require_positive_id(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_execution_token(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("resource user invite execution token is missing")
    return value


def _require_cas_ownership(rowcount: int | None) -> None:
    if rowcount != 1:
        raise RuntimeError("resource user invite execution claim token ownership was lost")


def _error_summary(error: Exception) -> str:
    error_type = type(error).__name__
    error_code = getattr(error, "code", None)
    if isinstance(error_code, int):
        return f"{error_type}(code={error_code})"
    return error_type


__all__ = ["execute_resource_user_invite"]
