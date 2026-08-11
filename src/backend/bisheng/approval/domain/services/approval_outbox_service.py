from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from inspect import isawaitable
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.database.models.audit_log import AuditLogDao


@dataclass(frozen=True)
class Completed:
    """A handler result whose business effects completed synchronously."""

    success: bool = True
    error_summary: str | None = None


@dataclass(frozen=True)
class Deferred:
    """A handler result completed later by durable, token-bound execution steps.

    The handler must persist durable steps before returning and must be
    idempotent across a crash between that commit and the outbox transition.
    Once persisted, ``execution_token`` is also the durable marker that keeps
    failed/processing deferred generations out of the ordinary claim path.
    """

    execution_token: str
    deadline: datetime

    def __post_init__(self) -> None:
        if not self.execution_token or len(self.execution_token) > 64:
            raise ValueError("deferred execution_token must contain 1 to 64 characters")


class ApprovalOutboxService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    async def execute_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f"outbox not found: {outbox_id}")
        if outbox.status == ApprovalOutboxStatus.SUCCESS:
            await self.instance_repository.finalize_outbox_success(outbox_id=outbox_id)
            return True
        if outbox.status == ApprovalOutboxStatus.DEFERRED or outbox.execution_token is not None:
            # Deferred work belongs exclusively to its coordinator/watchdog.
            # Its generation marker survives FAILED so neither retry_outbox nor
            # a stale processing claim can bypass prepare_resume(new_token).
            return False

        from bisheng.common.services.config_service import settings

        claim_ttl_seconds = settings.approval_invite.outbox_claim_ttl_seconds
        if hasattr(self.instance_repository, "decision_session"):
            claimed = await self.claim_outbox(
                tenant_id=outbox.tenant_id,
                instance_id=outbox.instance_id,
                outbox_id=outbox_id,
                claim_ttl_seconds=claim_ttl_seconds,
            )
        else:
            # Small injected repositories used by legacy callers/tests keep the
            # old protocol. Production always uses the instance-first UoW above.
            claimed = await self.instance_repository.claim_outbox(
                outbox_id=outbox_id,
                claim_ttl_seconds=claim_ttl_seconds,
            )
        if claimed is None:
            return False
        outbox = claimed

        try:
            execution_result = executor(outbox)
            if isawaitable(execution_result):
                execution_result = await execution_result
        except Exception as error:
            from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
                ApprovalInviteRetryableExecutionError,
            )

            if not isinstance(error, ApprovalInviteRetryableExecutionError):
                raise
            released = await self.instance_repository.release_outbox_claim(
                outbox_id=outbox_id,
                claim_ttl_seconds=settings.approval_invite.outbox_claim_ttl_seconds,
                error_summary=str(error),
            )
            if not released:
                logger.error("failed to release retryable approval outbox claim: outbox_id={}", outbox_id)
            raise
        if isinstance(execution_result, Deferred):
            return await self.defer_execution(
                tenant_id=outbox.tenant_id,
                instance_id=outbox.instance_id,
                outbox_id=outbox.id,
                result=execution_result,
            )
        success, error_summary = self.normalize_execution_result(execution_result)
        if success:
            outbox, instance = await self.instance_repository.finalize_outbox_success(outbox_id=outbox_id)
            audit_action = (
                "resource.user_invite.execute.success"
                if instance.scenario_code == "resource_user_invite_confirmation"
                else "approval.handler.success"
            )
            await self._write_handler_audit_log(
                outbox=outbox,
                instance=instance,
                action=audit_action,
                reason=None,
                extra_metadata={"business_result": "success"},
            )
            if instance is not None and instance.scenario_code == "resource_user_invite_confirmation":
                await self._notify_invite_applicant(
                    instance=instance,
                    action_code="resource_user_invite_effective",
                )
            return True

        outbox, instance = await self.instance_repository.finalize_outbox_failure(
            outbox_id=outbox_id,
            error_summary=error_summary,
        )
        audit_action = (
            "resource.user_invite.execute.failed"
            if instance.scenario_code == "resource_user_invite_confirmation"
            else "approval.handler.failed"
        )
        if instance is not None:
            from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

            await ApprovalNotificationService.notify_admins(
                tenant_id=instance.tenant_id,
                applicant_user_id=instance.applicant_user_id,
                action_code="approval_execute_failed",
                business_name=instance.business_name,
                instance_id=instance.id,
            )
            if instance.scenario_code == "resource_user_invite_confirmation":
                await self._notify_invite_applicant(
                    instance=instance,
                    action_code="resource_user_invite_failed",
                    reason=error_summary,
                )
        await self._write_handler_audit_log(
            outbox=outbox,
            instance=instance,
            action=audit_action,
            reason=error_summary,
            extra_metadata={
                "error_stack_summary": error_summary,
            },
        )
        return False

    @staticmethod
    def normalize_execution_result(result: Any) -> tuple[bool, str | None]:
        """Keep handlers written before Deferred source-compatible.

        Historic handlers returned arbitrary success payloads and the worker
        interpreted a normal return as completion. Explicit ``Completed`` and
        the existing ``(success, error_summary)`` adapter are both accepted.
        """

        if isinstance(result, Completed):
            return result.success, result.error_summary
        if isinstance(result, tuple) and len(result) == 2:
            return bool(result[0]), result[1]
        return True, None

    async def claim_outbox(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        claim_ttl_seconds: int,
        now: datetime | None = None,
    ) -> ApprovalOutbox | None:
        """Claim ordinary work with the global instance -> outbox lock order."""

        current_time = now or datetime.utcnow()
        stale_before = current_time - timedelta(seconds=claim_ttl_seconds)
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if (
                    instance is None
                    or outbox is None
                    or outbox.status == ApprovalOutboxStatus.DEFERRED
                    or outbox.execution_token is not None
                ):
                    return None
                claimable = outbox.status in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED)
                if outbox.status == ApprovalOutboxStatus.PROCESSING:
                    claimable = outbox.update_time is None or outbox.update_time < stale_before
                if not claimable or instance.status not in (
                    ApprovalInstanceStatus.APPROVED,
                    ApprovalInstanceStatus.EXECUTE_FAILED,
                    ApprovalInstanceStatus.EXECUTING,
                ):
                    return None
                outbox.status = ApprovalOutboxStatus.PROCESSING
                outbox.update_time = current_time
                instance.status = ApprovalInstanceStatus.EXECUTING
                session.add(outbox)
                session.add(instance)
                await session.flush()
            await session.refresh(outbox)
        return outbox

    async def defer_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        result: Deferred,
        now: datetime | None = None,
    ) -> bool:
        """Persist a Deferred handler result without releasing it to normal retry."""

        heartbeat_at = now or datetime.utcnow()
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if instance is None or outbox is None:
                    return False
                if outbox.status == ApprovalOutboxStatus.DEFERRED:
                    return outbox.execution_token == result.execution_token
                if (
                    instance.status != ApprovalInstanceStatus.EXECUTING
                    or outbox.status != ApprovalOutboxStatus.PROCESSING
                ):
                    return False
                outbox.status = ApprovalOutboxStatus.DEFERRED
                outbox.execution_token = result.execution_token
                outbox.deferred_deadline = result.deadline
                outbox.heartbeat_at = heartbeat_at
                outbox.error_summary = None
                session.add(outbox)
                session.add(instance)
                await session.flush()
        return True

    async def heartbeat_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        execution_token: str,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or datetime.utcnow()
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if not self._is_current_deferred(instance, outbox, execution_token):
                    return False
                outbox.heartbeat_at = current_time
                session.add(outbox)
                await session.flush()
        return True

    async def complete_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        execution_token: str,
    ) -> bool:
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if not self._is_current_deferred(instance, outbox, execution_token):
                    return False
                outbox.status = ApprovalOutboxStatus.SUCCESS
                outbox.error_summary = None
                instance.status = ApprovalInstanceStatus.EXECUTED
                session.add(outbox)
                session.add(instance)
                await session.flush()
        return True

    @staticmethod
    async def complete_deferred_execution_in_uow(
        *,
        session: AsyncSession,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
    ) -> bool:
        """Complete deferred approval inside a business-owned cutover UoW."""

        from bisheng.approval.domain.services.approval_uow import (
            SessionBoundApprovalInstanceRepository,
        )

        return await SessionBoundApprovalInstanceRepository(session).complete_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
        )

    @staticmethod
    async def require_deferred_execution_in_uow(
        *,
        session: AsyncSession,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
    ) -> bool:
        """Lock and validate a deferred generation without making it terminal."""

        from bisheng.approval.domain.services.approval_uow import (
            SessionBoundApprovalInstanceRepository,
        )

        return await SessionBoundApprovalInstanceRepository(session).require_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
        )

    @staticmethod
    async def fail_deferred_execution_in_uow(
        *,
        session: AsyncSession,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
        error_summary: str,
    ) -> bool:
        """Fail deferred approval and its business request in one owner UoW."""

        from bisheng.approval.domain.services.approval_uow import (
            SessionBoundApprovalInstanceRepository,
        )

        return await SessionBoundApprovalInstanceRepository(session).fail_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
            error_summary=error_summary,
        )

    async def fail_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        execution_token: str,
        error_summary: str,
        watchdog: bool = False,
        heartbeat_timeout_seconds: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Fail the current generation; watchdog calls additionally prove expiry."""

        current_time = now or datetime.utcnow()
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if not self._is_current_deferred(instance, outbox, execution_token):
                    return False
                if watchdog and not self._is_deferred_expired(
                    outbox,
                    now=current_time,
                    heartbeat_timeout_seconds=heartbeat_timeout_seconds,
                ):
                    return False
                outbox.status = ApprovalOutboxStatus.FAILED
                outbox.retry_count += 1
                outbox.error_summary = error_summary
                instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
                open_failure = (
                    await session.exec(
                        select(ApprovalException)
                        .where(
                            ApprovalException.tenant_id == tenant_id,
                            ApprovalException.instance_id == instance_id,
                            ApprovalException.exception_type == ApprovalExceptionType.EXECUTE_FAILED,
                            ApprovalException.status == "open",
                        )
                        .order_by(ApprovalException.id.asc())
                        .with_for_update()
                    )
                ).first()
                if open_failure is None:
                    session.add(
                        ApprovalException(
                            tenant_id=tenant_id,
                            instance_id=instance_id,
                            exception_type=ApprovalExceptionType.EXECUTE_FAILED,
                            detail={"error_summary": error_summary, "execution_token": execution_token},
                        )
                    )
                session.add(outbox)
                session.add(instance)
                await session.flush()
        return True

    async def resume_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
        handler: Any,
        post_commit_dispatch: Callable[[int, str], Any] | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Start a fresh execution generation and restore business steps atomically."""

        current_time = now or datetime.utcnow()
        new_token = uuid4().hex
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                instance = await self._lock_instance(session, tenant_id=tenant_id, instance_id=instance_id)
                outbox = await self._lock_outbox(
                    session,
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    outbox_id=outbox_id,
                )
                if (
                    instance is None
                    or outbox is None
                    or instance.status != ApprovalInstanceStatus.EXECUTE_FAILED
                    or outbox.status != ApprovalOutboxStatus.FAILED
                ):
                    return None
                prepare_resume = getattr(handler, "prepare_resume", None)
                if prepare_resume is None:
                    raise TypeError("deferred handler must implement prepare_resume(session, new_token)")
                bind_deferred_execution = getattr(handler, "bind_deferred_execution", None)
                if bind_deferred_execution is not None:
                    bound = bind_deferred_execution(instance=instance, outbox=outbox)
                    if isawaitable(bound):
                        await bound
                prepared = prepare_resume(session, new_token)
                if isawaitable(prepared):
                    prepared = await prepared
                if not isinstance(prepared, Deferred) or prepared.execution_token != new_token:
                    raise ValueError("prepare_resume must return Deferred for the new execution token")
                outbox.status = ApprovalOutboxStatus.DEFERRED
                outbox.execution_token = new_token
                outbox.deferred_deadline = prepared.deadline
                outbox.heartbeat_at = current_time
                outbox.error_summary = None
                instance.status = ApprovalInstanceStatus.EXECUTING
                open_failures = list(
                    (
                        await session.exec(
                            select(ApprovalException)
                            .where(
                                ApprovalException.tenant_id == tenant_id,
                                ApprovalException.instance_id == instance_id,
                                ApprovalException.exception_type == ApprovalExceptionType.EXECUTE_FAILED,
                                ApprovalException.status == "open",
                            )
                            .order_by(ApprovalException.id.asc())
                            .with_for_update()
                        )
                    ).all()
                )
                for failure in open_failures:
                    failure.status = "resolved"
                    failure.resolved_action = "resume"
                    failure.resolved_at = current_time
                    session.add(failure)
                session.add(outbox)
                session.add(instance)
                await session.flush()

        if post_commit_dispatch is not None:
            effect = post_commit_dispatch(outbox_id, new_token)
            if isawaitable(effect):
                await effect
        return new_token

    @staticmethod
    async def _lock_instance(
        session: AsyncSession,
        *,
        tenant_id: int,
        instance_id: int,
    ) -> ApprovalInstance | None:
        statement = (
            select(ApprovalInstance)
            .where(ApprovalInstance.tenant_id == tenant_id, ApprovalInstance.id == instance_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await session.exec(statement)).first()

    @staticmethod
    async def _lock_outbox(
        session: AsyncSession,
        *,
        tenant_id: int,
        instance_id: int,
        outbox_id: int,
    ) -> ApprovalOutbox | None:
        statement = (
            select(ApprovalOutbox)
            .where(
                ApprovalOutbox.tenant_id == tenant_id,
                ApprovalOutbox.instance_id == instance_id,
                ApprovalOutbox.id == outbox_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await session.exec(statement)).first()

    @staticmethod
    def _is_current_deferred(instance: ApprovalInstance | None, outbox: ApprovalOutbox | None, token: str) -> bool:
        return bool(
            instance is not None
            and outbox is not None
            and instance.status == ApprovalInstanceStatus.EXECUTING
            and outbox.status == ApprovalOutboxStatus.DEFERRED
            and outbox.execution_token == token
        )

    @staticmethod
    def _is_deferred_expired(
        outbox: ApprovalOutbox,
        *,
        now: datetime,
        heartbeat_timeout_seconds: int | None,
    ) -> bool:
        if outbox.deferred_deadline is not None and outbox.deferred_deadline <= now:
            return True
        if heartbeat_timeout_seconds is None:
            return False
        heartbeat_cutoff = now - timedelta(seconds=heartbeat_timeout_seconds)
        return outbox.heartbeat_at is None or outbox.heartbeat_at <= heartbeat_cutoff

    async def retry_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f"outbox not found: {outbox_id}")
        return await self.execute_outbox(outbox_id=outbox_id, executor=executor)

    @staticmethod
    async def _notify_invite_applicant(*, instance, action_code: str, reason: str | None = None) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        try:
            await ApprovalNotificationService.notify_user(
                sender=int((instance.payload_snapshot or {}).get("target_user_id") or 0),
                receiver_user_id=instance.applicant_user_id,
                action_code=action_code,
                business_name=instance.business_name,
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
                reason=reason,
            )
        except Exception:
            # Approval/outbox status is authoritative; reminders are best effort.
            logger.exception(
                "failed to send resource invite terminal reminder: instance_id={} action_code={}",
                instance.id,
                action_code,
            )

    @staticmethod
    async def _write_handler_audit_log(
        *,
        outbox,
        instance,
        action: str,
        reason: str | None,
        extra_metadata: dict | None = None,
    ) -> None:
        if instance is None:
            return
        metadata: dict = {
            "instance_id": instance.id,
            "scenario_code": instance.scenario_code,
            "handler": instance.handler_key or instance.scenario_code,
            "outbox_id": outbox.id,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=instance.tenant_id,
                operator_id=0,
                operator_tenant_id=instance.tenant_id,
                action=action,
                target_type="approval_instance",
                target_id=str(instance.id),
                reason=reason,
                metadata=metadata,
                object_name=instance.business_name,
            )
        except Exception:
            logger.exception("failed to write approval handler audit log: action={} outbox_id={}", action, outbox.id)
