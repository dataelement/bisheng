from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
)
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateResult

PostCommitCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class ApprovalPostCommitEffect:
    """A side effect that must only run after the owner commits its transaction."""

    name: str
    callback: PostCommitCallback

    async def run(self) -> None:
        result = self.callback()
        if inspect.isawaitable(result):
            await result


@dataclass
class ApprovalGateUowResult:
    """Gate result plus effects owned by the caller's commit boundary."""

    result: ApprovalGateResult
    post_commit_effects: list[ApprovalPostCommitEffect] = field(default_factory=list)
    transaction_is_active: Callable[[], bool] | None = field(default=None, repr=False)
    _next_effect_index: int = field(default=0, init=False, repr=False)

    async def run_post_commit_effects(self) -> None:
        if self.transaction_is_active is not None and self.transaction_is_active():
            raise RuntimeError("approval post-commit effects cannot run before transaction completion")
        while self._next_effect_index < len(self.post_commit_effects):
            effect = self.post_commit_effects[self._next_effect_index]
            await effect.run()
            self._next_effect_index += 1


class SessionBoundApprovalInstanceRepository:
    """Approval writes bound to an existing session and transaction.

    This adapter intentionally never commits. The aggregate owner controls the
    transaction so its business request and the Approval instance bundle cannot
    become visible independently.
    """

    _DUPLICATE_ACTIVE_STATUSES = (
        ApprovalInstanceStatus.PENDING,
        ApprovalInstanceStatus.EXCEPTION,
        ApprovalInstanceStatus.EXECUTE_FAILED,
    )
    _INVITE_BLOCKING_STATUSES = (
        ApprovalInstanceStatus.PENDING,
        ApprovalInstanceStatus.APPROVED,
        ApprovalInstanceStatus.EXECUTING,
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_duplicate_active_instance(
        self,
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
                ApprovalInstance.status.in_(self._DUPLICATE_ACTIVE_STATUSES),
            )
            .order_by(ApprovalInstance.id.desc())
        )
        return (await self.session.exec(statement)).first()

    async def find_blocking_invite(
        self,
        *,
        tenant_id: int,
        business_key: str,
        exclude_instance_id: int | None = None,
    ) -> ApprovalInstance | None:
        statement = select(ApprovalInstance).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.scenario_code == "resource_user_invite_confirmation",
            ApprovalInstance.business_key == business_key,
            ApprovalInstance.status.in_(self._INVITE_BLOCKING_STATUSES),
        )
        if exclude_instance_id is not None:
            statement = statement.where(ApprovalInstance.id != exclude_instance_id)
        return (await self.session.exec(statement.order_by(ApprovalInstance.id.asc()))).first()

    async def create_instance(self, row: ApprovalInstance) -> ApprovalInstance:
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_task(self, row: ApprovalTask) -> ApprovalTask:
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_exception(self, row: ApprovalException) -> ApprovalException:
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_outbox(self, row: ApprovalOutbox) -> ApprovalOutbox:
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_action_log(self, row: ApprovalActionLog) -> ApprovalActionLog:
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_instance_bundle(
        self,
        *,
        instance: ApprovalInstance,
        tasks: list[ApprovalTask],
        action_log: ApprovalActionLog,
    ) -> tuple[ApprovalInstance, list[ApprovalTask], ApprovalActionLog]:
        self.session.add(instance)
        await self.session.flush()
        for task in tasks:
            task.instance_id = instance.id
            self.session.add(task)
        action_log.instance_id = instance.id
        self.session.add(action_log)
        await self.session.flush()
        return instance, tasks, action_log

    async def complete_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
    ) -> bool:
        """Complete one token-bound deferred outbox in the caller's UoW."""

        instance, outbox = await self._lock_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
        )
        if instance is None or outbox is None:
            return False
        if instance.status == ApprovalInstanceStatus.EXECUTED and outbox.status == ApprovalOutboxStatus.SUCCESS:
            return True
        if instance.status != ApprovalInstanceStatus.EXECUTING or outbox.status != ApprovalOutboxStatus.DEFERRED:
            return False
        outbox.status = ApprovalOutboxStatus.SUCCESS
        outbox.error_summary = None
        instance.status = ApprovalInstanceStatus.EXECUTED
        self.session.add(outbox)
        self.session.add(instance)
        await self.session.flush()
        return True

    async def require_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
    ) -> bool:
        """Lock and validate one deferred generation without completing it."""

        instance, outbox = await self._lock_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
        )
        return bool(
            instance is not None
            and outbox is not None
            and instance.status == ApprovalInstanceStatus.EXECUTING
            and outbox.status == ApprovalOutboxStatus.DEFERRED
        )

    async def fail_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
        error_summary: str,
    ) -> bool:
        """Fail one deferred generation inside the business-owned UoW."""

        instance, outbox = await self._lock_deferred_execution(
            tenant_id=tenant_id,
            instance_id=instance_id,
            execution_token=execution_token,
        )
        if instance is None or outbox is None:
            return False
        if instance.status == ApprovalInstanceStatus.EXECUTE_FAILED and outbox.status == ApprovalOutboxStatus.FAILED:
            return True
        if instance.status != ApprovalInstanceStatus.EXECUTING or outbox.status != ApprovalOutboxStatus.DEFERRED:
            return False
        outbox.status = ApprovalOutboxStatus.FAILED
        outbox.retry_count += 1
        outbox.error_summary = str(error_summary)[:2000]
        instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
        open_failure = (
            await self.session.exec(
                select(ApprovalException)
                .where(
                    ApprovalException.tenant_id == int(tenant_id),
                    ApprovalException.instance_id == int(instance_id),
                    ApprovalException.exception_type == ApprovalExceptionType.EXECUTE_FAILED,
                    ApprovalException.status == "open",
                )
                .order_by(ApprovalException.id.asc())
                .with_for_update()
            )
        ).first()
        if open_failure is None:
            self.session.add(
                ApprovalException(
                    tenant_id=int(tenant_id),
                    instance_id=int(instance_id),
                    exception_type=ApprovalExceptionType.EXECUTE_FAILED,
                    detail={
                        "error_summary": str(error_summary)[:2000],
                        "execution_token": str(execution_token),
                    },
                )
            )
        self.session.add(outbox)
        self.session.add(instance)
        await self.session.flush()
        return True

    async def _lock_deferred_execution(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        execution_token: str,
    ) -> tuple[ApprovalInstance | None, ApprovalOutbox | None]:
        instance = (
            await self.session.exec(
                select(ApprovalInstance)
                .where(
                    ApprovalInstance.tenant_id == int(tenant_id),
                    ApprovalInstance.id == int(instance_id),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        outbox = (
            await self.session.exec(
                select(ApprovalOutbox)
                .where(
                    ApprovalOutbox.tenant_id == int(tenant_id),
                    ApprovalOutbox.instance_id == int(instance_id),
                    ApprovalOutbox.execution_token == str(execution_token),
                )
                .order_by(ApprovalOutbox.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        return instance, outbox


def build_post_commit_effect(
    name: str,
    callback: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> ApprovalPostCommitEffect:
    return ApprovalPostCommitEffect(name=name, callback=lambda: callback(*args, **kwargs))
