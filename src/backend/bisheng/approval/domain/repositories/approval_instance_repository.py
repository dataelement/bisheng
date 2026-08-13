from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
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
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.ports.decision_subscriber import APPROVAL_DECISION_EVENT_VERSION
from bisheng.approval.domain.ports.scenario_policy import DECISION_DELIVERY_COMPLETION_MODE
from bisheng.core.context.tenant import get_current_tenant_id
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
    def decision_session(cls):
        """Return a session owned by a decision UoW.

        The repository primitives below never commit.  Keeping the factory on
        the repository also lets tests replace the database boundary once for
        both legacy methods and the decision UoW.
        """

        return get_async_db_session()

    @staticmethod
    def _resolve_lock_tenant_id(tenant_id: int | None) -> int:
        """Resolve the tenant before constructing any decision lock query."""

        resolved = get_current_tenant_id() if tenant_id is None else tenant_id
        if resolved is None or int(resolved) <= 0:
            raise ValueError("a positive tenant_id is required for approval decision locks")
        return int(resolved)

    @classmethod
    async def get_task_instance_id_in_session(
        cls,
        session: AsyncSession,
        task_id: int,
        *,
        tenant_id: int | None = None,
    ) -> int | None:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = select(ApprovalTask.instance_id).where(
            ApprovalTask.id == task_id,
            ApprovalTask.tenant_id == resolved_tenant_id,
        )
        return (await session.exec(statement)).first()

    @classmethod
    async def is_task_pending_for_tenant(cls, *, task_id: int, tenant_id: int) -> bool:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        async with get_async_db_session() as session:
            statement = select(ApprovalTask.id).where(
                ApprovalTask.id == task_id,
                ApprovalTask.tenant_id == resolved_tenant_id,
                ApprovalTask.status == ApprovalTaskStatus.PENDING,
            )
            return (await session.exec(statement)).first() is not None

    @classmethod
    async def lock_instance_in_session(
        cls,
        session: AsyncSession,
        instance_id: int,
        *,
        tenant_id: int | None = None,
    ) -> ApprovalInstance | None:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.id == instance_id,
                ApprovalInstance.tenant_id == resolved_tenant_id,
            )
            .with_for_update()
        )
        return (await session.exec(statement)).first()

    @classmethod
    async def lock_tasks_in_session(
        cls,
        session: AsyncSession,
        instance_id: int,
        *,
        tenant_id: int | None = None,
    ) -> list[ApprovalTask]:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = (
            select(ApprovalTask)
            .where(
                ApprovalTask.instance_id == instance_id,
                ApprovalTask.tenant_id == resolved_tenant_id,
            )
            .order_by(ApprovalTask.node_order.asc(), ApprovalTask.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list((await session.exec(statement)).all())

    @classmethod
    async def lock_open_exceptions_and_outboxes_in_session(
        cls,
        session: AsyncSession,
        instance_id: int,
        *,
        tenant_id: int | None = None,
    ) -> tuple[list[ApprovalException], list[ApprovalOutbox]]:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        exceptions = list(
            (
                await session.exec(
                    select(ApprovalException)
                    .where(
                        ApprovalException.instance_id == instance_id,
                        ApprovalException.tenant_id == resolved_tenant_id,
                        ApprovalException.status == "open",
                    )
                    .order_by(ApprovalException.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        outboxes = list(
            (
                await session.exec(
                    select(ApprovalOutbox)
                    .where(
                        ApprovalOutbox.instance_id == instance_id,
                        ApprovalOutbox.tenant_id == resolved_tenant_id,
                    )
                    .order_by(ApprovalOutbox.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        return exceptions, outboxes

    @classmethod
    async def list_flow_nodes_in_session(
        cls,
        session: AsyncSession,
        *,
        tenant_id: int,
        flow_version_id: int,
    ) -> list[ApprovalNodeDefinition]:
        statement = (
            select(ApprovalNodeDefinition)
            .where(
                ApprovalNodeDefinition.tenant_id == tenant_id,
                ApprovalNodeDefinition.flow_version_id == flow_version_id,
            )
            .order_by(ApprovalNodeDefinition.node_order.asc(), ApprovalNodeDefinition.id.asc())
        )
        return list((await session.exec(statement)).all())

    @classmethod
    async def get_submission_scenario_in_session(
        cls,
        session: AsyncSession,
        *,
        tenant_id: int,
        scenario_code: str,
    ) -> ApprovalScenario | None:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = select(ApprovalScenario).where(
            ApprovalScenario.tenant_id == resolved_tenant_id,
            ApprovalScenario.scenario_code == scenario_code,
        )
        return (await session.exec(statement)).first()

    @classmethod
    async def lock_submission_scenario_in_session(
        cls,
        session: AsyncSession,
        *,
        tenant_id: int,
        scenario_code: str,
    ) -> ApprovalScenario | None:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = (
            select(ApprovalScenario)
            .where(
                ApprovalScenario.tenant_id == resolved_tenant_id,
                ApprovalScenario.scenario_code == scenario_code,
            )
            .with_for_update()
        )
        return (await session.exec(statement)).first()

    @classmethod
    async def list_submission_routes_in_session(
        cls,
        session: AsyncSession,
        *,
        tenant_id: int,
        scenario_id: int,
    ) -> list[ApprovalRouteRule]:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = (
            select(ApprovalRouteRule)
            .where(
                ApprovalRouteRule.tenant_id == resolved_tenant_id,
                ApprovalRouteRule.scenario_id == scenario_id,
                ApprovalRouteRule.enabled == True,  # noqa: E712 — DM8 rejects `IS 1`
            )
            .order_by(ApprovalRouteRule.sort_order.asc(), ApprovalRouteRule.id.asc())
        )
        return list((await session.exec(statement)).all())

    @classmethod
    async def get_submission_flow_version_in_session(
        cls,
        session: AsyncSession,
        *,
        tenant_id: int,
        flow_definition_id: int,
    ) -> ApprovalFlowVersion | None:
        resolved_tenant_id = cls._resolve_lock_tenant_id(tenant_id)
        statement = (
            select(ApprovalFlowVersion)
            .where(
                ApprovalFlowVersion.tenant_id == resolved_tenant_id,
                ApprovalFlowVersion.flow_definition_id == flow_definition_id,
                ApprovalFlowVersion.is_active == True,  # noqa: E712 — DM8 rejects `IS 1`
            )
            .order_by(ApprovalFlowVersion.version_no.desc(), ApprovalFlowVersion.id.desc())
        )
        return (await session.exec(statement)).first()

    @classmethod
    async def create_submission_bundle_in_session(
        cls,
        session: AsyncSession,
        *,
        instance: ApprovalInstance,
        tasks: list[ApprovalTask],
        action_log: ApprovalActionLog,
        exception: ApprovalException | None = None,
    ) -> tuple[ApprovalInstance, list[ApprovalTask]]:
        session.add(instance)
        await session.flush()
        if instance.id is None:
            raise RuntimeError("approval instance id was not assigned during submission")
        for task in tasks:
            task.instance_id = instance.id
            session.add(task)
        action_log.instance_id = instance.id
        session.add(action_log)
        if exception is not None:
            exception.instance_id = instance.id
            session.add(exception)
        await session.flush()
        return instance, tasks

    @staticmethod
    def is_decision_delivery_instance(instance: ApprovalInstance) -> bool:
        payload = instance.payload_snapshot or {}
        return payload.get("completion_mode") == DECISION_DELIVERY_COMPLETION_MODE

    @classmethod
    def require_decision_delivery_binding(cls, instance: ApprovalInstance) -> tuple[str, str, str]:
        if not cls.is_decision_delivery_instance(instance):
            raise ValueError(f"approval instance is not a decision-delivery instance: {instance.id}")
        payload = instance.payload_snapshot or {}
        business_request_type = str(payload.get("business_request_type") or "").strip()
        business_request_id = str(payload.get("business_request_id") or "").strip()
        request_fingerprint = str(payload.get("request_fingerprint") or "").strip()
        if not business_request_type or not business_request_id or not request_fingerprint:
            raise ValueError(f"approval decision binding is incomplete: instance_id={instance.id}")
        if business_request_type != instance.business_resource_type:
            raise ValueError(f"approval decision request type mismatch: instance_id={instance.id}")
        if business_request_id != str(instance.business_resource_id):
            raise ValueError(f"approval decision request id mismatch: instance_id={instance.id}")
        return business_request_type, business_request_id, request_fingerprint

    @classmethod
    async def create_terminal_decision_event_in_session(
        cls,
        session: AsyncSession,
        *,
        instance: ApprovalInstance,
        decision: str,
        operator_user_id: int | None,
    ) -> ApprovalDecisionOutbox | None:
        """Write one terminal decision fact without committing the caller UoW."""

        if not cls.is_decision_delivery_instance(instance):
            return None
        if instance.id is None or instance.tenant_id is None:
            raise ValueError("persisted approval instance identity is required for a terminal decision")
        if decision not in {"approved", "rejected", "withdrawn", "cancelled"}:
            raise ValueError(f"unsupported approval terminal decision: {decision}")
        business_request_type, business_request_id, request_fingerprint = cls.require_decision_delivery_binding(
            instance
        )
        existing = (
            await session.exec(
                select(ApprovalDecisionOutbox)
                .where(
                    ApprovalDecisionOutbox.tenant_id == int(instance.tenant_id),
                    ApprovalDecisionOutbox.instance_id == int(instance.id),
                    ApprovalDecisionOutbox.decision_version == 1,
                )
                .with_for_update()
            )
        ).first()
        if existing is not None:
            if existing.decision != decision:
                raise ValueError(f"approval terminal decision conflicts with existing event: instance_id={instance.id}")
            return existing
        subscriber_key = str(instance.handler_key or "").strip()
        if not subscriber_key:
            raise ValueError(f"approval decision subscriber key is missing: instance_id={instance.id}")
        event = ApprovalDecisionOutbox(
            tenant_id=int(instance.tenant_id),
            instance_id=int(instance.id),
            scenario_code=instance.scenario_code,
            subscriber_key=subscriber_key,
            business_request_type=business_request_type,
            business_request_id=business_request_id,
            business_key=instance.business_key,
            request_fingerprint=request_fingerprint,
            decision=decision,
            decision_version=1,
            event_version=APPROVAL_DECISION_EVENT_VERSION,
            decided_at=datetime.utcnow(),
            operator_user_id=operator_user_id,
            status=ApprovalDecisionOutboxStatus.PENDING,
        )
        session.add(event)
        await session.flush()
        return event

    @classmethod
    async def flush_decision_in_session(cls, session: AsyncSession) -> None:
        await session.flush()

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
                instance_id = await cls.get_task_instance_id_in_session(session, task_id)
                if instance_id is None:
                    return None
                instance = await cls.lock_instance_in_session(session, instance_id)
                tasks = await cls.lock_tasks_in_session(session, instance_id)
                await cls.lock_open_exceptions_and_outboxes_in_session(session, instance_id)
                task = next((row for row in tasks if row.id == task_id), None)
                if (
                    task is None
                    or task.status != ApprovalTaskStatus.PENDING
                    or instance is None
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
                await cls.flush_decision_in_session(session)
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
                instance = await cls.lock_instance_in_session(session, instance_id)
                if (
                    instance is None
                    or instance.status != ApprovalInstanceStatus.PENDING
                    or instance.applicant_user_id != applicant_user_id
                ):
                    return None
                tasks = await cls.lock_tasks_in_session(session, instance_id)
                await cls.lock_open_exceptions_and_outboxes_in_session(session, instance_id)
                pending_tasks = [task for task in tasks if task.status == ApprovalTaskStatus.PENDING]
                for task in pending_tasks:
                    task.status = ApprovalTaskStatus.CANCELLED
                    task.comment = reason
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
                await cls.flush_decision_in_session(session)
            await session.refresh(instance)
        return instance

    @classmethod
    async def cancel_pending_instance(
        cls,
        *,
        instance_id: int,
        operator_user_id: int,
        operator_user_name: str | None,
        reason: str,
    ) -> ApprovalInstance | None:
        """Cancel a pending/exception instance using the decision lock order."""

        now = datetime.utcnow()
        async with get_async_db_session() as session:
            async with session.begin():
                instance = await cls.lock_instance_in_session(session, instance_id)
                if instance is None or instance.status not in (
                    ApprovalInstanceStatus.PENDING,
                    ApprovalInstanceStatus.EXCEPTION,
                ):
                    return None
                tasks = await cls.lock_tasks_in_session(session, instance_id)
                exceptions, _outboxes = await cls.lock_open_exceptions_and_outboxes_in_session(
                    session,
                    instance_id,
                )
                for task in tasks:
                    if task.status == ApprovalTaskStatus.PENDING:
                        task.status = ApprovalTaskStatus.CANCELLED
                        task.acted_at = now
                        session.add(task)
                for exception in exceptions:
                    exception.status = "resolved"
                    exception.resolved_action = "cancel"
                    exception.resolved_by_user_id = operator_user_id
                    exception.resolved_at = now
                    session.add(exception)
                instance.status = ApprovalInstanceStatus.CANCELLED
                session.add(instance)
                session.add(
                    ApprovalActionLog(
                        tenant_id=instance.tenant_id,
                        instance_id=instance.id,
                        action="cancelled",
                        operator_user_id=operator_user_id,
                        operator_user_name=operator_user_name,
                        detail={"reason": reason},
                    )
                )
                await cls.flush_decision_in_session(session)
            await session.refresh(instance)
        return instance

    @staticmethod
    async def _lock_instance_and_outbox_by_outbox_id(
        session: AsyncSession,
        *,
        outbox_id: int,
    ) -> tuple[ApprovalInstance | None, ApprovalOutbox | None]:
        identity = (
            await session.exec(
                select(ApprovalOutbox.tenant_id, ApprovalOutbox.instance_id).where(ApprovalOutbox.id == outbox_id)
            )
        ).first()
        if identity is None:
            return None, None
        tenant_id, instance_id = int(identity[0]), int(identity[1])
        instance = (
            await session.exec(
                select(ApprovalInstance)
                .where(
                    ApprovalInstance.tenant_id == tenant_id,
                    ApprovalInstance.id == instance_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        outbox = (
            await session.exec(
                select(ApprovalOutbox)
                .where(
                    ApprovalOutbox.tenant_id == tenant_id,
                    ApprovalOutbox.instance_id == instance_id,
                    ApprovalOutbox.id == outbox_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        return instance, outbox

    @classmethod
    async def finalize_outbox_success(
        cls,
        *,
        outbox_id: int,
        expected_claimed_at: datetime | None = None,
    ) -> tuple[ApprovalOutbox, ApprovalInstance]:
        """Commit the outbox and instance success terminals together."""

        async with get_async_db_session() as session:
            async with session.begin():
                instance, outbox = await cls._lock_instance_and_outbox_by_outbox_id(
                    session,
                    outbox_id=outbox_id,
                )
                if outbox is None:
                    raise ValueError(f"approval outbox not found: {outbox_id}")
                if instance is None:
                    raise ValueError(f"approval instance not found for outbox: {outbox_id}")
                if outbox.status == ApprovalOutboxStatus.SUCCESS:
                    if instance.status not in (
                        ApprovalInstanceStatus.CANCELLED,
                        ApprovalInstanceStatus.REJECTED,
                        ApprovalInstanceStatus.WITHDRAWN,
                    ):
                        instance.status = ApprovalInstanceStatus.EXECUTED
                    session.add(instance)
                    await session.flush()
                elif (
                    outbox.status not in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED)
                    or instance.status != ApprovalInstanceStatus.EXECUTING
                    or expected_claimed_at is None
                    or outbox.update_time != expected_claimed_at
                ):
                    raise ValueError(f"approval outbox claim is no longer owned: {outbox_id}")
                else:
                    outbox.status = ApprovalOutboxStatus.SUCCESS
                    outbox.error_summary = None
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
        expected_claimed_at: datetime | None = None,
    ) -> tuple[ApprovalOutbox, ApprovalInstance]:
        """Commit the outbox, instance, and exception failure facts together."""

        async with get_async_db_session() as session:
            async with session.begin():
                instance, outbox = await cls._lock_instance_and_outbox_by_outbox_id(
                    session,
                    outbox_id=outbox_id,
                )
                if outbox is None:
                    raise ValueError(f"approval outbox not found: {outbox_id}")
                if outbox.status == ApprovalOutboxStatus.SUCCESS:
                    raise ValueError(f"successful approval outbox cannot be failed: {outbox_id}")
                if instance is None:
                    raise ValueError(f"approval instance not found for outbox: {outbox_id}")
                if (
                    outbox.status not in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED)
                    or instance.status != ApprovalInstanceStatus.EXECUTING
                    or expected_claimed_at is None
                    or outbox.update_time != expected_claimed_at
                ):
                    raise ValueError(f"approval outbox claim is no longer owned: {outbox_id}")
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
                instance, outbox = await cls._lock_instance_and_outbox_by_outbox_id(
                    session,
                    outbox_id=outbox_id,
                )
                if outbox is None or outbox.status not in (
                    ApprovalOutboxStatus.PENDING,
                    ApprovalOutboxStatus.FAILED,
                ):
                    return False
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
