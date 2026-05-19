from __future__ import annotations

from bisheng.approval.domain.models.approval_instance import ApprovalExceptionType, ApprovalOutboxStatus


class ApprovalOutboxService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    async def execute_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f'outbox not found: {outbox_id}')

        success, error_summary = executor(outbox)
        if success:
            outbox.status = ApprovalOutboxStatus.SUCCESS
            outbox.error_summary = None
            await self.instance_repository.update_outbox(outbox)
            return True

        outbox.status = ApprovalOutboxStatus.FAILED
        outbox.retry_count += 1
        outbox.error_summary = error_summary
        await self.instance_repository.update_outbox(outbox)

        instance = await self.instance_repository.get_instance(outbox.instance_id)
        if instance is not None:
            instance.status = 'execute_failed'
            await self.instance_repository.update_instance(instance)
            await self.instance_repository.create_exception(
                self._build_execute_failed_exception(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    error_summary=error_summary,
                )
            )
        return False

    async def retry_outbox(self, *, outbox_id: int, executor) -> bool:
        outbox = await self.instance_repository.get_outbox(outbox_id)
        if outbox is None:
            raise ValueError(f'outbox not found: {outbox_id}')
        outbox.status = ApprovalOutboxStatus.PENDING
        await self.instance_repository.update_outbox(outbox)
        return await self.execute_outbox(outbox_id=outbox_id, executor=executor)

    @staticmethod
    def _build_execute_failed_exception(*, tenant_id: int, instance_id: int, error_summary: str | None):
        from bisheng.approval.domain.models.approval_instance import ApprovalException

        return ApprovalException(
            tenant_id=tenant_id,
            instance_id=instance_id,
            exception_type=ApprovalExceptionType.EXECUTE_FAILED,
            detail={'error_summary': error_summary},
        )

