"""One target-bound withdrawn transition; the application never writes approval ORM."""

from datetime import datetime

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import ApprovalActionLog, ApprovalInstance, ApprovalTask
from bisheng.common.errcode.approval import ApprovalInstanceNotPendingError, ApprovalRequestPermissionDeniedError
from bisheng.core.database import get_async_db_session


class AppPublishWithdrawalRepository:
    def __init__(self, factory=None):
        self.factory = factory or get_async_db_session

    async def withdraw(self, expected, *, operator_user_id, operator_user_name, reason, actor_metadata):
        async with self.factory() as session:
            instance = (
                await session.exec(
                    select(ApprovalInstance)
                    .where(
                        ApprovalInstance.id == expected["instance_id"],
                        ApprovalInstance.tenant_id == expected["tenant_id"],
                    )
                    .with_for_update()
                )
            ).first()
            if (
                instance is None
                or instance.scenario_code != "app_publish_request"
                or instance.business_resource_type != "app"
                or instance.business_resource_id != expected["app_id"]
                or instance.business_key != expected["deployment_id"]
                or any(
                    (instance.payload_snapshot or {}).get(key) != expected[key]
                    for key in ("tenant_id", "app_id", "deployment_id", "version_id")
                )
            ):
                raise ApprovalRequestPermissionDeniedError()
            if instance.status != "pending":
                raise ApprovalInstanceNotPendingError()
            tasks = list(
                (
                    await session.exec(
                        select(ApprovalTask)
                        .where(ApprovalTask.instance_id == instance.id, ApprovalTask.tenant_id == instance.tenant_id)
                        .with_for_update()
                    )
                ).all()
            )
            for task in tasks:
                if task.status == "pending":
                    task.status = "cancelled"
                    task.acted_at = datetime.now()
                    session.add(task)
            instance.status = "withdrawn"
            session.add(instance)
            session.add(
                ApprovalActionLog(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    action="withdrawn",
                    operator_user_id=operator_user_id,
                    operator_user_name=operator_user_name,
                    detail={"reason": reason, "business_actor": actor_metadata},
                )
            )
            await session.commit()
            return instance, tasks
