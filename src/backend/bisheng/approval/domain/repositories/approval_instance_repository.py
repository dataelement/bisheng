from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.core.database import get_async_db_session


@dataclass(frozen=True)
class SingleTaskDecisionResult:
    instance: ApprovalInstance
    task: ApprovalTask
    outbox: ApprovalOutbox | None


class ApprovalInstanceRepository:
    _DUPLICATE_ACTIVE_STATUSES = ("pending", "exception", "execute_failed")
    _INVITE_BLOCKING_STATUSES = (
        ApprovalInstanceStatus.PENDING,
        ApprovalInstanceStatus.APPROVED,
        ApprovalInstanceStatus.EXECUTING,
    )

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
                raise ValueError(f"approval instance not found: {row.id}")
            for key, value in row.model_dump(mode="python", exclude_unset=False).items():
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
    ) -> ApprovalInstance | None:
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.tenant_id == tenant_id,
                ApprovalInstance.scenario_code == scenario_code,
                ApprovalInstance.business_key == business_key,
                ApprovalInstance.applicant_user_id == applicant_user_id,
                ApprovalInstance.status.in_(cls._DUPLICATE_ACTIVE_STATUSES),
            )
            .order_by(ApprovalInstance.id.desc())
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def find_blocking_invite(
        cls,
        *,
        tenant_id: int,
        business_key: str,
        exclude_instance_id: int | None = None,
    ) -> ApprovalInstance | None:
        statement = select(ApprovalInstance).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.scenario_code == "resource_user_invite_confirmation",
            ApprovalInstance.business_key == business_key,
            ApprovalInstance.status.in_(cls._INVITE_BLOCKING_STATUSES),
        )
        if exclude_instance_id is not None:
            statement = statement.where(ApprovalInstance.id != exclude_instance_id)
        statement = statement.order_by(ApprovalInstance.id.asc())
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def list_resource_invites(
        cls,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        statuses: tuple[str, ...] | None = None,
    ) -> list[ApprovalInstance]:
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.tenant_id == tenant_id,
                ApprovalInstance.scenario_code == "resource_user_invite_confirmation",
                ApprovalInstance.business_resource_type == resource_type,
                ApprovalInstance.business_resource_id == str(resource_id),
                ApprovalInstance.status.in_(statuses or cls._INVITE_BLOCKING_STATUSES),
            )
            .order_by(ApprovalInstance.id.asc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def create_instance_bundle(
        cls,
        *,
        instance: ApprovalInstance,
        tasks: list[ApprovalTask],
        action_log: ApprovalActionLog,
    ) -> tuple[ApprovalInstance, list[ApprovalTask], ApprovalActionLog]:
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(instance)
                await session.flush()
                for task in tasks:
                    task.instance_id = instance.id
                    session.add(task)
                action_log.instance_id = instance.id
                session.add(action_log)
                await session.flush()
            await session.refresh(instance)
            for task in tasks:
                await session.refresh(task)
            await session.refresh(action_log)
        return instance, tasks, action_log

    @classmethod
    async def decide_single_task(
        cls,
        *,
        task_id: int,
        operator_user_id: int,
        action: str,
        operator_user_name: str,
        comment: str | None,
    ) -> SingleTaskDecisionResult | None:
        now = datetime.utcnow()
        async with get_async_db_session() as session:
            async with session.begin():
                task = (
                    await session.exec(select(ApprovalTask).where(ApprovalTask.id == task_id).with_for_update())
                ).first()
                if task is None or task.status != ApprovalTaskStatus.PENDING:
                    return None
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == task.instance_id).with_for_update()
                    )
                ).first()
                if (
                    instance is None
                    or instance.status != ApprovalInstanceStatus.PENDING
                    or task.approver_user_id != operator_user_id
                ):
                    return None

                task.comment = comment
                task.acted_at = now
                outbox = None
                if action == "approve":
                    task.status = ApprovalTaskStatus.APPROVED
                    instance.status = ApprovalInstanceStatus.APPROVED
                    instance.latest_approver_user_id = operator_user_id
                    outbox = ApprovalOutbox(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        handler_key=instance.handler_key or instance.scenario_code,
                        status=ApprovalOutboxStatus.PENDING,
                        payload_snapshot=instance.payload_snapshot or {},
                    )
                    session.add(outbox)
                elif action == "reject":
                    task.status = ApprovalTaskStatus.REJECTED
                    instance.status = ApprovalInstanceStatus.REJECTED
                    instance.latest_approver_user_id = operator_user_id
                else:
                    raise ValueError(f"unsupported approval action: {action}")
                session.add(task)
                session.add(instance)
                session.add(
                    ApprovalActionLog(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        action="approved" if action == "approve" else "rejected",
                        operator_user_id=operator_user_id,
                        operator_user_name=operator_user_name,
                        detail={"task_id": task.id, "comment": comment},
                    )
                )
                await session.flush()
            await session.refresh(task)
            await session.refresh(instance)
            if outbox is not None:
                await session.refresh(outbox)
        return SingleTaskDecisionResult(instance=instance, task=task, outbox=outbox)

    @classmethod
    async def withdraw_pending_instance(
        cls,
        *,
        instance_id: int,
        applicant_user_id: int,
        operator_user_name: str | None,
        reason: str | None,
    ) -> ApprovalInstance | None:
        now = datetime.utcnow()
        async with get_async_db_session() as session:
            async with session.begin():
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == instance_id).with_for_update()
                    )
                ).first()
                if (
                    instance is None
                    or instance.status != ApprovalInstanceStatus.PENDING
                    or instance.applicant_user_id != applicant_user_id
                ):
                    return None
                pending_tasks = list(
                    (
                        await session.exec(
                            select(ApprovalTask).where(
                                ApprovalTask.instance_id == instance_id,
                                ApprovalTask.status == ApprovalTaskStatus.PENDING,
                            )
                        )
                    ).all()
                )
                for task in pending_tasks:
                    task.status = ApprovalTaskStatus.CANCELLED
                    task.acted_at = now
                    session.add(task)
                instance.status = ApprovalInstanceStatus.WITHDRAWN
                session.add(instance)
                session.add(
                    ApprovalActionLog(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        action="withdrawn",
                        operator_user_id=applicant_user_id,
                        operator_user_name=operator_user_name,
                        detail={"reason": reason},
                    )
                )
                await session.flush()
            await session.refresh(instance)
        return instance

    @classmethod
    async def claim_outbox(
        cls,
        *,
        outbox_id: int,
        claim_ttl_seconds: int,
    ) -> ApprovalOutbox | None:
        now = datetime.utcnow()
        stale_before = now - timedelta(seconds=claim_ttl_seconds)
        async with get_async_db_session() as session:
            async with session.begin():
                outbox = (
                    await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.id == outbox_id).with_for_update())
                ).first()
                if outbox is None or outbox.status == ApprovalOutboxStatus.SUCCESS:
                    return None
                claimable = outbox.status in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED)
                if outbox.status == ApprovalOutboxStatus.PROCESSING:
                    claimable = outbox.update_time is None or outbox.update_time < stale_before
                if not claimable:
                    return None
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == outbox.instance_id).with_for_update()
                    )
                ).first()
                if instance is None or instance.status not in (
                    ApprovalInstanceStatus.APPROVED,
                    ApprovalInstanceStatus.EXECUTE_FAILED,
                    ApprovalInstanceStatus.EXECUTING,
                ):
                    return None
                outbox.status = ApprovalOutboxStatus.PROCESSING
                outbox.update_time = now
                instance.status = ApprovalInstanceStatus.EXECUTING
                session.add(outbox)
                session.add(instance)
                await session.flush()
            await session.refresh(outbox)
        return outbox

    @classmethod
    async def release_outbox_claim(
        cls,
        *,
        outbox_id: int,
        claim_ttl_seconds: int,
        error_summary: str | None,
    ) -> bool:
        """Keep uncertain execution in-flight while making its claim immediately stale."""

        stale_time = datetime.utcnow() - timedelta(seconds=claim_ttl_seconds + 1)
        async with get_async_db_session() as session:
            async with session.begin():
                outbox = (
                    await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.id == outbox_id).with_for_update())
                ).first()
                if outbox is None or outbox.status != ApprovalOutboxStatus.PROCESSING:
                    return False
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == outbox.instance_id).with_for_update()
                    )
                ).first()
                if instance is None or instance.status != ApprovalInstanceStatus.EXECUTING:
                    return False
                outbox.retry_count += 1
                outbox.error_summary = error_summary
                outbox.update_time = stale_time
                session.add(outbox)
                session.add(instance)
                await session.flush()
        return True

    @classmethod
    async def finalize_outbox_success(
        cls,
        *,
        outbox_id: int,
    ) -> tuple[ApprovalOutbox, ApprovalInstance]:
        """Commit the outbox and instance success terminals together."""

        async with get_async_db_session() as session:
            async with session.begin():
                outbox = (
                    await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.id == outbox_id).with_for_update())
                ).first()
                if outbox is None:
                    raise ValueError(f"approval outbox not found: {outbox_id}")
                if outbox.status not in (ApprovalOutboxStatus.PROCESSING, ApprovalOutboxStatus.SUCCESS):
                    raise ValueError(f"approval outbox is not executing: {outbox_id}")
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == outbox.instance_id).with_for_update()
                    )
                ).first()
                if instance is None:
                    raise ValueError(f"approval instance not found: {outbox.instance_id}")
                outbox.status = ApprovalOutboxStatus.SUCCESS
                outbox.error_summary = None
                if instance.status not in (
                    ApprovalInstanceStatus.EXECUTED,
                    ApprovalInstanceStatus.CANCELLED,
                    ApprovalInstanceStatus.REJECTED,
                    ApprovalInstanceStatus.WITHDRAWN,
                ):
                    instance.status = ApprovalInstanceStatus.EXECUTED
                session.add(outbox)
                session.add(instance)
                await session.flush()
            await session.refresh(outbox)
            await session.refresh(instance)
        return outbox, instance

    @classmethod
    async def finalize_outbox_failure(
        cls,
        *,
        outbox_id: int,
        error_summary: str | None,
    ) -> tuple[ApprovalOutbox, ApprovalInstance]:
        """Commit the outbox, instance, and exception failure facts together."""

        async with get_async_db_session() as session:
            async with session.begin():
                outbox = (
                    await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.id == outbox_id).with_for_update())
                ).first()
                if outbox is None:
                    raise ValueError(f"approval outbox not found: {outbox_id}")
                if outbox.status == ApprovalOutboxStatus.SUCCESS:
                    raise ValueError(f"successful approval outbox cannot be failed: {outbox_id}")
                if outbox.status != ApprovalOutboxStatus.PROCESSING:
                    raise ValueError(f"approval outbox is not executing: {outbox_id}")
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == outbox.instance_id).with_for_update()
                    )
                ).first()
                if instance is None:
                    raise ValueError(f"approval instance not found: {outbox.instance_id}")
                if instance.status in (
                    ApprovalInstanceStatus.EXECUTED,
                    ApprovalInstanceStatus.CANCELLED,
                    ApprovalInstanceStatus.REJECTED,
                    ApprovalInstanceStatus.WITHDRAWN,
                ):
                    raise ValueError(f"terminal approval instance cannot be failed: {instance.id}")
                outbox.status = ApprovalOutboxStatus.FAILED
                outbox.retry_count += 1
                outbox.error_summary = error_summary
                instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
                session.add(outbox)
                session.add(instance)
                session.add(
                    ApprovalException(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
                        detail={"error_summary": error_summary},
                    )
                )
                await session.flush()
            await session.refresh(outbox)
            await session.refresh(instance)
        return outbox, instance

    @classmethod
    async def record_outbox_setup_failure(cls, *, outbox_id: int, error_summary: str) -> bool:
        """Record worker setup failure without ever downgrading a successful outbox."""

        async with get_async_db_session() as session:
            async with session.begin():
                outbox = (
                    await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.id == outbox_id).with_for_update())
                ).first()
                if outbox is None or outbox.status not in (
                    ApprovalOutboxStatus.PENDING,
                    ApprovalOutboxStatus.FAILED,
                ):
                    return False
                instance = (
                    await session.exec(
                        select(ApprovalInstance).where(ApprovalInstance.id == outbox.instance_id).with_for_update()
                    )
                ).first()
                outbox.status = ApprovalOutboxStatus.FAILED
                outbox.retry_count += 1
                outbox.error_summary = error_summary
                session.add(outbox)
                if instance is None or instance.status in (
                    ApprovalInstanceStatus.EXECUTED,
                    ApprovalInstanceStatus.CANCELLED,
                    ApprovalInstanceStatus.REJECTED,
                    ApprovalInstanceStatus.WITHDRAWN,
                ):
                    await session.flush()
                    return True
                instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
                session.add(instance)
                session.add(
                    ApprovalException(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
                        detail={"error_summary": error_summary},
                    )
                )
                await session.flush()
        return True

    @classmethod
    async def create_task(cls, row: ApprovalTask) -> ApprovalTask:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_task(cls, task_id: int) -> ApprovalTask | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalTask, task_id)

    @classmethod
    async def update_task(cls, row: ApprovalTask) -> ApprovalTask:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalTask, row.id)
            if saved is None:
                raise ValueError(f"approval task not found: {row.id}")
            for key, value in row.model_dump(mode="python", exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_tasks(cls, instance_id: int) -> list[ApprovalTask]:
        statement = (
            select(ApprovalTask)
            .where(ApprovalTask.instance_id == instance_id)
            .order_by(
                ApprovalTask.node_order.asc(),
                ApprovalTask.id.asc(),
            )
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
                raise ValueError(f"approval exception not found: {row.id}")
            for key, value in row.model_dump(mode="python", exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_exceptions(cls, instance_id: int) -> list[ApprovalException]:
        statement = (
            select(ApprovalException)
            .where(ApprovalException.instance_id == instance_id)
            .order_by(
                ApprovalException.id.asc(),
            )
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
                raise ValueError(f"approval outbox not found: {row.id}")
            for key, value in row.model_dump(mode="python", exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
        return saved

    @classmethod
    async def list_outbox(cls, instance_id: int) -> list[ApprovalOutbox]:
        statement = (
            select(ApprovalOutbox)
            .where(ApprovalOutbox.instance_id == instance_id)
            .order_by(
                ApprovalOutbox.id.asc(),
            )
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
        statement = (
            select(ApprovalActionLog)
            .where(ApprovalActionLog.instance_id == instance_id)
            .order_by(
                ApprovalActionLog.id.asc(),
            )
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())
