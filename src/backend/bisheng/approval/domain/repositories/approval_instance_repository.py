from __future__ import annotations

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalOutbox,
    ApprovalTask,
)
from bisheng.core.database import get_async_db_session


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
