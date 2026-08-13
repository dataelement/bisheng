from __future__ import annotations

from datetime import datetime, timedelta
from inspect import isawaitable
from typing import Any

from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.database.models.audit_log import AuditLogDao


class ApprovalOutboxService:
    """Execute the three released synchronous Approval handlers.

    Decision-delivery scenarios never enter this service. Their business work
    is owned by Permission or Knowledge after an ApprovalDecisionOutbox event.
    """

    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    async def execute_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f"outbox not found: {outbox_id}")
        if outbox.status == ApprovalOutboxStatus.SUCCESS:
            await self.instance_repository.finalize_outbox_success(outbox_id=outbox_id)
            return True

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
            claimed = await self.instance_repository.claim_outbox(
                outbox_id=outbox_id,
                claim_ttl_seconds=claim_ttl_seconds,
            )
        if claimed is None:
            return False
        outbox = claimed
        claimed_at = outbox.update_time

        execution_result = executor(outbox)
        if isawaitable(execution_result):
            execution_result = await execution_result
        success, error_summary = self.normalize_execution_result(execution_result)
        if success:
            outbox, instance = await self.instance_repository.finalize_outbox_success(
                outbox_id=outbox_id,
                expected_claimed_at=claimed_at,
            )
            await self._write_handler_audit_log(
                outbox=outbox,
                instance=instance,
                action="approval.handler.success",
                reason=None,
                extra_metadata={"business_result": "success"},
            )
            return True

        outbox, instance = await self.instance_repository.finalize_outbox_failure(
            outbox_id=outbox_id,
            error_summary=error_summary,
            expected_claimed_at=claimed_at,
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
        await self._write_handler_audit_log(
            outbox=outbox,
            instance=instance,
            action="approval.handler.failed",
            reason=error_summary,
            extra_metadata={"error_stack_summary": error_summary},
        )
        return False

    @staticmethod
    def normalize_execution_result(result: Any) -> tuple[bool, str | None]:
        """Normalize the released handlers' historic return conventions."""

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
        """Claim synchronous work using instance -> outbox lock order.

        The instance EXECUTING state plus outbox update_time form the lease. The
        legacy outbox itself intentionally remains in its released three-state
        contract: pending, success, or failed.
        """

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
                if instance is None or outbox is None:
                    return None
                if outbox.status not in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED):
                    return None
                if instance.status == ApprovalInstanceStatus.EXECUTING:
                    if outbox.update_time is not None and outbox.update_time >= stale_before:
                        return None
                elif instance.status not in (
                    ApprovalInstanceStatus.APPROVED,
                    ApprovalInstanceStatus.EXECUTE_FAILED,
                ):
                    return None
                outbox.update_time = current_time
                instance.status = ApprovalInstanceStatus.EXECUTING
                session.add(outbox)
                session.add(instance)
                await session.flush()
            await session.refresh(outbox)
        return outbox

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

    async def retry_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f"outbox not found: {outbox_id}")
        return await self.execute_outbox(outbox_id=outbox_id, executor=executor)

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
