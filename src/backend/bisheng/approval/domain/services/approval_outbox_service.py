from __future__ import annotations

from inspect import isawaitable

from bisheng.approval.domain.models.approval_instance import ApprovalExceptionType, ApprovalOutboxStatus
from bisheng.database.models.audit_log import AuditLogDao


class ApprovalOutboxService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    async def execute_outbox(self, *, outbox_id: int, executor, retry: bool = False) -> bool:
        outbox = await self.instance_repository.claim_outbox(outbox_id, retry=retry)
        if outbox is None:
            existing = await self.instance_repository.get_outbox(outbox_id)
            if existing is None:
                raise ValueError(f"outbox not found: {outbox_id}")
            return existing.status == ApprovalOutboxStatus.SUCCESS

        try:
            execution_result = executor(outbox)
            if isawaitable(execution_result):
                success, error_summary = await execution_result
            else:
                success, error_summary = execution_result
        except Exception as exc:
            from loguru import logger

            logger.exception("approval business execution failed outbox_id={}", outbox_id)
            success, error_summary = False, str(exc)
        finalized = await self.instance_repository.finish_outbox(outbox, success=success, error_summary=error_summary)
        if finalized is None:
            return False
        outbox, instance, active = finalized
        if success:
            await self._write_handler_audit_log(
                outbox=outbox,
                instance=instance,
                action="approval.handler.success",
                reason=None,
                extra_metadata={"business_result": "success"},
            )
            return True

        if active:
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
            extra_metadata={
                "error_stack_summary": error_summary,
                "payload_snapshot": outbox.payload_snapshot,
            },
        )
        return False

    async def retry_outbox(self, *, outbox_id: int, executor) -> bool:
        return await self.execute_outbox(outbox_id=outbox_id, executor=executor, retry=True)

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
                note=instance.scenario_name,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "failed to write approval handler audit log: action=%s outbox_id=%s", action, outbox.id
            )

    @staticmethod
    def _build_execute_failed_exception(*, tenant_id: int, instance_id: int, error_summary: str | None):
        from bisheng.approval.domain.models.approval_instance import ApprovalException

        return ApprovalException(
            tenant_id=tenant_id,
            instance_id=instance_id,
            exception_type=ApprovalExceptionType.EXECUTE_FAILED,
            detail={"error_summary": error_summary},
        )
