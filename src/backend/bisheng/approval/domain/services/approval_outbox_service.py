from __future__ import annotations

from inspect import isawaitable

from loguru import logger

from bisheng.approval.domain.models.approval_instance import (
    ApprovalOutboxStatus,
)
from bisheng.database.models.audit_log import AuditLogDao


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

        from bisheng.common.services.config_service import settings

        claimed = await self.instance_repository.claim_outbox(
            outbox_id=outbox_id,
            claim_ttl_seconds=settings.approval_invite.outbox_claim_ttl_seconds,
        )
        if claimed is None:
            return False
        outbox = claimed

        try:
            execution_result = executor(outbox)
            if isawaitable(execution_result):
                success, error_summary = await execution_result
            else:
                success, error_summary = execution_result
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
