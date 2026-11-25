from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import update
from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalOutbox,
    ApprovalTask,
)
from bisheng.core.database import get_async_db_session


class _DecisionRepository:
    """Session-bound approval operations: flush only, owner commits or rolls back."""

    def __init__(self, session):
        self.session = session

    async def get_task(self, task_id):
        return await self.session.get(ApprovalTask, task_id, populate_existing=True)

    async def get_instance(self, instance_id):
        return await self.session.get(ApprovalInstance, instance_id, populate_existing=True)

    async def list_tasks(self, instance_id):
        return list(
            (await self.session.exec(select(ApprovalTask).where(ApprovalTask.instance_id == instance_id))).all()
        )

    async def list_node_definitions(self, tenant_id, flow_version_id):
        from bisheng.approval.domain.models.approval_scenario import ApprovalNodeDefinition

        return list(
            (
                await self.session.exec(
                    select(ApprovalNodeDefinition).where(
                        ApprovalNodeDefinition.tenant_id == tenant_id,
                        ApprovalNodeDefinition.flow_version_id == flow_version_id,
                    )
                )
            ).all()
        )

    async def _save(self, row):
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_exception(self, exception_id):
        return await self.session.get(ApprovalException, exception_id, populate_existing=True)

    update_exception = _save
    update_task = _save
    update_instance = _save
    create_task = _save
    create_action_log = _save
    create_exception = _save
    create_outbox = _save


class ApprovalInstanceRepository:
    _DUPLICATE_ACTIVE_STATUSES = ("pending", "exception", "execute_failed")

    @classmethod
    @asynccontextmanager
    async def decision_transaction(cls, *, task_id: int, tenant_id: int):
        """Serialize every task of one instance, including AND-node siblings.

        The conditional UPDATE takes a database write lock before reading task
        state. Unlike SELECT FOR UPDATE it also serializes SQLite tests. All
        approval writes use the yielded session; no task-local/process lock can
        protect decisions sent to different API replicas.
        """
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    update(ApprovalInstance)
                    .where(
                        ApprovalInstance.id
                        == select(ApprovalTask.instance_id).where(ApprovalTask.id == task_id).scalar_subquery(),
                        ApprovalInstance.tenant_id == tenant_id,
                    )
                    .values(status=ApprovalInstance.status)
                    .execution_options(synchronize_session=False)
                )
                yield _DecisionRepository(session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    @classmethod
    @asynccontextmanager
    async def instance_transaction(cls, *, instance_id: int, tenant_id: int):
        """All terminal transitions lock instance before tasks, same as decisions."""
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    update(ApprovalInstance)
                    .where(ApprovalInstance.id == instance_id, ApprovalInstance.tenant_id == tenant_id)
                    .values(status=ApprovalInstance.status)
                    .execution_options(synchronize_session=False)
                )
                yield _DecisionRepository(session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    @classmethod
    async def list_active_instances_for_business_keys(
        cls, *, scenario_code: str, applicant_user_id: int, business_keys: list[str]
    ) -> list[ApprovalInstance]:
        if not business_keys:
            return []
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.scenario_code == scenario_code,
                ApprovalInstance.applicant_user_id == applicant_user_id,
                ApprovalInstance.business_key.in_(business_keys),
                ApprovalInstance.status.in_(cls._DUPLICATE_ACTIVE_STATUSES),
            )
            .order_by(ApprovalInstance.id.desc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

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
    async def find_active_instance_by_resource(
        cls,
        *,
        tenant_id: int,
        scenario_code: str,
        business_resource_type: str,
        business_resource_id: str,
        active_only: bool = True,
    ) -> ApprovalInstance | None:
        """The newest request against one business object, open by default.

        Different question from :meth:`find_duplicate_active_instance`, which
        asks "has *this exact submission* already been filed" (it keys on
        ``business_key`` + applicant). This one asks "does this object already
        have something in flight", which is what a caller needs to refuse a
        second submission or to cancel whatever is open because the object is
        being deleted.

        ``_DUPLICATE_ACTIVE_STATUSES`` is reused on purpose: pending, exception
        and execute_failed are exactly the states in which a request still owns
        the object and still has somebody's attention.

        ``active_only=False`` drops that filter and answers "what happened to
        this object's last request" — which is what a read side needs after the
        decision, so that a rejection reason survives the rejection.
        """
        conditions = [
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.scenario_code == scenario_code,
            ApprovalInstance.business_resource_type == business_resource_type,
            ApprovalInstance.business_resource_id == business_resource_id,
        ]
        if active_only:
            conditions.append(ApprovalInstance.status.in_(cls._DUPLICATE_ACTIVE_STATUSES))
        statement = select(ApprovalInstance).where(*conditions).order_by(ApprovalInstance.id.desc())
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def list_instances_by_resource(
        cls,
        *,
        tenant_id: int,
        scenario_code: str,
        business_resource_type: str,
        business_resource_id: str,
    ) -> list[ApprovalInstance]:
        """Every request ever filed against one business object, newest first.

        The plural of :meth:`find_active_instance_by_resource` with no status
        filter: a read side that has to answer "who was ever asked to approve
        *this* version" (F055's review view admits an approver by the task
        they hold) needs the whole history, because the version being reviewed
        is not necessarily the one the newest request is about.
        """
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.tenant_id == tenant_id,
                ApprovalInstance.scenario_code == scenario_code,
                ApprovalInstance.business_resource_type == business_resource_type,
                ApprovalInstance.business_resource_id == business_resource_id,
            )
            .order_by(ApprovalInstance.id.desc())
        )
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

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
    async def fail_pending_outbox(cls, outbox_id: int, error_summary: str) -> bool:
        from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus
        from bisheng.core.context.tenant import get_current_tenant_id

        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise ValueError("Approval execution requires tenant context")
        outbox = await cls.get_outbox(outbox_id)
        if outbox is None or outbox.tenant_id != tenant_id:
            return False
        async with cls.instance_transaction(instance_id=outbox.instance_id, tenant_id=tenant_id) as repo:
            saved = await repo.session.get(ApprovalOutbox, outbox_id, populate_existing=True)
            instance = await repo.get_instance(outbox.instance_id)
            if saved is None or saved.status != ApprovalOutboxStatus.PENDING or instance is None:
                return False
            saved.status = ApprovalOutboxStatus.FAILED
            saved.retry_count += 1
            saved.error_summary = error_summary
            await repo._save(saved)
            if instance.status in ("approved", "execute_failed"):
                instance.status = "execute_failed"
                await repo.update_instance(instance)
                await repo.create_exception(
                    ApprovalException(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        exception_type="execute_failed",
                        detail={"error_summary": error_summary},
                    )
                )
            return True

    @classmethod
    async def claim_outbox(cls, outbox_id: int, *, retry: bool = False) -> ApprovalOutbox | None:
        """Persist execution ownership before the business handler can run.

        Failed work requires an explicit retry. An executing claim is never
        automatically stolen: the previous worker may have completed external
        effects before losing its acknowledgement.
        """
        from datetime import datetime

        from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus
        from bisheng.core.context.tenant import get_current_tenant_id

        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise ValueError("Approval execution requires tenant context")
        async with get_async_db_session() as session:
            # Serialize distinct historical outboxes of the same instance too.
            # Old race-created rows must not each become an execution owner.
            await session.exec(
                update(ApprovalInstance)
                .where(
                    ApprovalInstance.id
                    == select(ApprovalOutbox.instance_id)
                    .where(ApprovalOutbox.id == outbox_id, ApprovalOutbox.tenant_id == tenant_id)
                    .scalar_subquery(),
                    ApprovalInstance.tenant_id == tenant_id,
                )
                .values(status=ApprovalInstance.status)
                .execution_options(synchronize_session=False)
            )
            current = await session.get(ApprovalOutbox, outbox_id)
            if current is None:
                await session.rollback()
                return None
            instance = await session.get(ApprovalInstance, current.instance_id, populate_existing=True)
            if (
                current.tenant_id != tenant_id
                or instance is None
                or instance.tenant_id != tenant_id
                or instance.status != ("execute_failed" if retry else "approved")
            ):
                await session.rollback()
                return None
            peers = (
                await session.exec(
                    select(ApprovalOutbox).where(
                        ApprovalOutbox.instance_id == current.instance_id,
                        ApprovalOutbox.id != outbox_id,
                        ApprovalOutbox.status.in_(
                            (ApprovalOutboxStatus.SUCCESS, ApprovalOutboxStatus.EXECUTING, ApprovalOutboxStatus.FAILED)
                        ),
                    )
                )
            ).all()
            if peers:
                await session.rollback()
                return None
            result = await session.exec(
                update(ApprovalOutbox)
                .where(
                    ApprovalOutbox.id == outbox_id,
                    ApprovalOutbox.tenant_id == tenant_id,
                    ApprovalOutbox.status == (ApprovalOutboxStatus.FAILED if retry else ApprovalOutboxStatus.PENDING),
                )
                .values(
                    status=ApprovalOutboxStatus.EXECUTING,
                    update_time=datetime.now(),
                    error_summary="Execution claimed; if interrupted, business effects are uncertain. Review before recovery.",
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            if result.rowcount != 1:
                return None
            return await session.get(ApprovalOutbox, outbox_id, populate_existing=True)

    @classmethod
    async def finish_outbox(cls, outbox, *, success: bool, error_summary: str | None):
        """Atomically record a claimed result without reviving terminal instances."""
        from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus

        async with get_async_db_session() as session:
            await session.exec(
                update(ApprovalInstance)
                .where(ApprovalInstance.id == outbox.instance_id, ApprovalInstance.tenant_id == outbox.tenant_id)
                .values(status=ApprovalInstance.status)
                .execution_options(synchronize_session=False)
            )
            saved = await session.get(ApprovalOutbox, outbox.id, populate_existing=True)
            instance = await session.get(ApprovalInstance, outbox.instance_id, populate_existing=True)
            if saved is None or saved.status != ApprovalOutboxStatus.EXECUTING or instance is None:
                await session.rollback()
                return None
            saved.status = ApprovalOutboxStatus.SUCCESS if success else ApprovalOutboxStatus.FAILED
            saved.error_summary = None if success else error_summary
            if not success:
                saved.retry_count += 1
            active = instance.status in ("approved", "execute_failed")
            if active:
                instance.status = "executed" if success else "execute_failed"
                session.add(instance)
                if not success:
                    session.add(
                        ApprovalException(
                            tenant_id=instance.tenant_id,
                            instance_id=instance.id,
                            exception_type="execute_failed",
                            detail={"error_summary": error_summary},
                        )
                    )
            session.add(saved)
            await session.commit()
            return saved, instance, active

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
