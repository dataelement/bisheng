from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.common.errcode.approval import (
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLog


@dataclass(frozen=True)
class FixedOrNodeDecisionResult:
    instance_id: int
    applicant_user_id: int
    business_name: str
    instance_status: str
    outbox_id: int | None


class ApprovalInstanceRepository:
    _DUPLICATE_ACTIVE_STATUSES = ('pending', 'exception', 'execute_failed')

    @classmethod
    async def create_instance(cls, row: ApprovalInstance) -> ApprovalInstance:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_instance(cls, instance_id: int) -> ApprovalInstance | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalInstance, instance_id)

    @classmethod
    async def get_instances_by_ids(cls, instance_ids: list[int]) -> list[ApprovalInstance]:
        if not instance_ids:
            return []
        statement = select(ApprovalInstance).where(ApprovalInstance.id.in_(instance_ids))
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def update_instance(cls, row: ApprovalInstance) -> ApprovalInstance:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalInstance, row.id)
            if saved is None:
                raise ValueError(f'approval instance not found: {row.id}')
            for key, value in row.model_dump(mode='python', exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def find_duplicate_active_instance(
        cls,
        *,
        tenant_id: int,
        scenario_code: str,
        business_key: str,
        applicant_user_id: int,
        active_statuses: list[str] | tuple[str, ...] | None = None,
    ) -> ApprovalInstance | None:
        statuses = tuple(active_statuses) if active_statuses is not None else cls._DUPLICATE_ACTIVE_STATUSES
        if not statuses:
            return None
        statement = select(ApprovalInstance).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.scenario_code == scenario_code,
            ApprovalInstance.business_key == business_key,
            ApprovalInstance.applicant_user_id == applicant_user_id,
            ApprovalInstance.status.in_(statuses),
        ).order_by(ApprovalInstance.id.desc())
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def find_pending_instance_by_business_resource_id(
        cls,
        *,
        tenant_id: int,
        scenario_code: str,
        business_resource_id: str,
        exclude_applicant_user_id: int | None = None,
        active_statuses: list[str] | tuple[str, ...] | None = None,
    ) -> ApprovalInstance | None:
        statuses = tuple(active_statuses) if active_statuses is not None else cls._DUPLICATE_ACTIVE_STATUSES
        statement = select(ApprovalInstance).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.scenario_code == scenario_code,
            ApprovalInstance.business_resource_id == business_resource_id,
            ApprovalInstance.status.in_(statuses),
        )
        if exclude_applicant_user_id is not None:
            statement = statement.where(ApprovalInstance.applicant_user_id == exclude_applicant_user_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def create_task(cls, row: ApprovalTask) -> ApprovalTask:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def create_tasks(cls, rows: list[ApprovalTask]) -> list[ApprovalTask]:
        if not rows:
            return []
        async with get_async_db_session() as session:
            session.add_all(rows)
            try:
                await session.flush()
                saved_rows = [row.model_copy(deep=True) for row in rows]
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return saved_rows

    @classmethod
    async def get_task(cls, task_id: int) -> ApprovalTask | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalTask, task_id)

    @classmethod
    async def get_tasks_by_ids(cls, task_ids: list[int]) -> list[ApprovalTask]:
        if not task_ids:
            return []
        statement = select(ApprovalTask).where(ApprovalTask.id.in_(task_ids))
        async with get_async_db_session() as session:
            rows = list((await session.exec(statement)).all())
        by_id = {int(row.id): row for row in rows}
        return [by_id[task_id] for task_id in task_ids if task_id in by_id]

    @classmethod
    async def update_task(cls, row: ApprovalTask) -> ApprovalTask:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalTask, row.id)
            if saved is None:
                raise ValueError(f'approval task not found: {row.id}')
            for key, value in row.model_dump(mode='python', exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_tasks(cls, instance_id: int) -> list[ApprovalTask]:
        statement = select(ApprovalTask).where(ApprovalTask.instance_id == instance_id).order_by(
            ApprovalTask.node_order.asc(),
            ApprovalTask.id.asc(),
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_exception(cls, row: ApprovalException) -> ApprovalException:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_exception(cls, exception_id: int) -> ApprovalException | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalException, exception_id)

    @classmethod
    async def update_exception(cls, row: ApprovalException) -> ApprovalException:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalException, row.id)
            if saved is None:
                raise ValueError(f'approval exception not found: {row.id}')
            for key, value in row.model_dump(mode='python', exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_exceptions(cls, instance_id: int) -> list[ApprovalException]:
        statement = select(ApprovalException).where(ApprovalException.instance_id == instance_id).order_by(
            ApprovalException.id.asc(),
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_outbox(cls, row: ApprovalOutbox) -> ApprovalOutbox:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_outbox(cls, outbox_id: int) -> ApprovalOutbox | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalOutbox, outbox_id)

    @classmethod
    async def update_outbox(cls, row: ApprovalOutbox) -> ApprovalOutbox:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalOutbox, row.id)
            if saved is None:
                raise ValueError(f'approval outbox not found: {row.id}')
            for key, value in row.model_dump(mode='python', exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_outbox(cls, instance_id: int) -> list[ApprovalOutbox]:
        statement = select(ApprovalOutbox).where(ApprovalOutbox.instance_id == instance_id).order_by(
            ApprovalOutbox.id.asc(),
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_action_log(cls, row: ApprovalActionLog) -> ApprovalActionLog:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def list_action_logs(cls, instance_id: int) -> list[ApprovalActionLog]:
        statement = select(ApprovalActionLog).where(ApprovalActionLog.instance_id == instance_id).order_by(
            ApprovalActionLog.id.asc(),
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def get_instance_ids_with_action(
        cls,
        instance_ids: list[int],
        action: str,
    ) -> set[int]:
        if not instance_ids:
            return set()
        statement = select(ApprovalActionLog.instance_id).where(
            ApprovalActionLog.instance_id.in_(instance_ids),
            ApprovalActionLog.action == action,
        )
        async with get_async_db_session() as session:
            return {
                int(instance_id)
                for instance_id in (await session.exec(statement)).all()
            }

    @classmethod
    async def decide_fixed_or_node_atomic(
        cls,
        *,
        task_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        operator_tenant_id: int,
        operator_is_admin: bool = False,
        comment: str | None = None,
        ip_address: str | None = None,
    ) -> FixedOrNodeDecisionResult:
        if action not in {"approve", "reject"}:
            raise ValueError(f"unsupported approval action: {action}")

        async with get_async_db_session() as session:
            try:
                task_result = await session.execute(
                    select(ApprovalTask)
                    .where(ApprovalTask.id == task_id)
                    .with_for_update()
                )
                task = task_result.scalars().first()
                if task is None:
                    raise ApprovalRequestNotFoundError()

                instance_result = await session.execute(
                    select(ApprovalInstance)
                    .where(ApprovalInstance.id == task.instance_id)
                    .with_for_update()
                )
                instance = instance_result.scalars().first()
                if instance is None:
                    raise ApprovalRequestNotFoundError()
                if (
                    instance.scenario_code != "department_file_view_request"
                    or task.node_mode != "or"
                ):
                    raise ValueError("task is not a fixed department-file OR-node task")
                if instance.tenant_id != operator_tenant_id:
                    raise ApprovalRequestPermissionDeniedError()
                if (
                    not operator_is_admin
                    and task.approver_user_id != operator_user_id
                ):
                    raise ApprovalRequestPermissionDeniedError()
                if (
                    instance.status != ApprovalInstanceStatus.PENDING
                    or task.status != ApprovalTaskStatus.PENDING
                ):
                    raise ApprovalRequestAlreadyProcessedError()

                siblings_result = await session.execute(
                    select(ApprovalTask)
                    .where(
                        ApprovalTask.instance_id == instance.id,
                        ApprovalTask.node_code == task.node_code,
                    )
                    .with_for_update()
                )
                sibling_tasks = list(siblings_result.scalars().all())
                acted_at = datetime.utcnow()
                approved = action == "approve"
                task.status = (
                    ApprovalTaskStatus.APPROVED
                    if approved
                    else ApprovalTaskStatus.REJECTED
                )
                task.comment = comment
                task.acted_at = acted_at
                for sibling in sibling_tasks:
                    if (
                        sibling.id != task.id
                        and sibling.status == ApprovalTaskStatus.PENDING
                    ):
                        sibling.status = ApprovalTaskStatus.SKIPPED
                        sibling.acted_at = acted_at

                instance.status = (
                    ApprovalInstanceStatus.APPROVED
                    if approved
                    else ApprovalInstanceStatus.REJECTED
                )
                instance.current_node_name = None
                instance.latest_approver_user_id = operator_user_id

                session.add(
                    ApprovalActionLog(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        action="approved" if approved else "rejected",
                        operator_user_id=operator_user_id,
                        operator_user_name=operator_user_name,
                        detail={"task_id": task.id, "comment": comment},
                    )
                )
                session.add(
                    AuditLog(
                        tenant_id=instance.tenant_id,
                        operator_id=operator_user_id,
                        operator_name=operator_user_name,
                        operator_tenant_id=operator_tenant_id,
                        action=(
                            "approval.task.approve"
                            if approved
                            else "approval.task.reject"
                        ),
                        target_type="approval_task",
                        target_id=str(task.id),
                        reason=comment,
                        audit_metadata={
                            "instance_id": instance.id,
                            "task_id": task.id,
                            "scenario_code": instance.scenario_code,
                            "handler": instance.handler_key,
                        },
                        ip_address=ip_address,
                        object_name=instance.business_name,
                    )
                )

                outbox: ApprovalOutbox | None = None
                if approved:
                    outbox = ApprovalOutbox(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        handler_key=instance.handler_key,
                        status=ApprovalOutboxStatus.PENDING,
                        payload_snapshot=instance.payload_snapshot,
                    )
                    session.add(outbox)

                await session.flush()
                result = FixedOrNodeDecisionResult(
                    instance_id=int(instance.id),
                    applicant_user_id=instance.applicant_user_id,
                    business_name=instance.business_name,
                    instance_status=instance.status,
                    outbox_id=int(outbox.id) if outbox is not None else None,
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
