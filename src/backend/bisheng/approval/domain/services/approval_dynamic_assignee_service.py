from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_uow import ApprovalPostCommitEffect, build_post_commit_effect
from bisheng.core.context.tenant import get_current_tenant_id

ApproverResolver = Callable[[ApprovalInstance], Awaitable[Sequence[int]] | Sequence[int]]


@dataclass(frozen=True)
class ApprovalDynamicAssigneeResult:
    instance_id: int
    added_user_ids: tuple[int, ...] = ()
    removed_user_ids: tuple[int, ...] = ()
    cancelled_task_ids: tuple[int, ...] = ()
    entered_approver_empty: bool = False
    resolved_approver_empty: bool = False
    post_commit_effects: tuple[ApprovalPostCommitEffect, ...] = field(default_factory=tuple, repr=False)

    async def run_post_commit_effects(self) -> None:
        for effect in self.post_commit_effects:
            try:
                await effect.run()
            except Exception:
                logger.exception("dynamic approval post-commit effect failed: effect={}", effect.name)


@dataclass(frozen=True)
class _CurrentNode:
    flow_version_id: int
    code: str
    name: str
    order: int
    mode: str


class ApprovalDynamicAssigneeService:
    """Reconcile materialized approval tasks with a dynamic source of truth."""

    @classmethod
    async def reconcile_assignees(
        cls,
        *,
        tenant_id: int,
        instance_id: int,
        approver_user_ids: Sequence[int],
        reason: str,
    ) -> ApprovalDynamicAssigneeResult:
        """Reconcile business-precomputed assignees in an Approval-owned UoW."""

        normalized_tenant_id = int(tenant_id)
        current_tenant_id = get_current_tenant_id()
        if normalized_tenant_id <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized_tenant_id:
            raise ValueError("approval assignee reconciliation requires the matching tenant context")
        normalized_instance_id = int(instance_id)
        if normalized_instance_id <= 0:
            raise ValueError("approval assignee reconciliation requires a positive instance_id")
        normalized_reason = str(reason).strip()
        if not normalized_reason:
            raise ValueError("approval assignee reconciliation reason must not be empty")
        normalized_user_ids: list[int] = []
        for user_id in approver_user_ids:
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
                raise ValueError("approval assignee reconciliation accepts only positive integer user IDs")
            normalized_user_ids.append(user_id)

        async with ApprovalInstanceRepository.decision_session() as session:
            async with session.begin():
                result = await cls.reconcile_resolved_in_uow(
                    session=session,
                    instance_id=normalized_instance_id,
                    approver_user_ids=normalized_user_ids,
                    trigger=normalized_reason,
                    tenant_id=normalized_tenant_id,
                )
                await ApprovalInstanceRepository.flush_decision_in_session(session)
        await result.run_post_commit_effects()
        return result

    @classmethod
    async def reconcile_instance(
        cls,
        *,
        instance_id: int,
        resolver: ApproverResolver,
        trigger: str,
        operator_user_id: int | None = None,
    ) -> ApprovalDynamicAssigneeResult:
        """Own the decision transaction and run effects only after it commits."""

        async with ApprovalInstanceRepository.decision_session() as session:
            async with session.begin():
                result = await cls.resolve_and_reconcile_in_uow(
                    session=session,
                    instance_id=instance_id,
                    resolver=resolver,
                    trigger=trigger,
                    operator_user_id=operator_user_id,
                )
                await ApprovalInstanceRepository.flush_decision_in_session(session)
        await result.run_post_commit_effects()
        return result

    @classmethod
    async def resolve_and_reconcile_in_uow(
        cls,
        *,
        session,
        instance_id: int,
        resolver: ApproverResolver,
        trigger: str,
        operator_user_id: int | None = None,
        tenant_id: int | None = None,
    ) -> ApprovalDynamicAssigneeResult:
        """Lock instance-first, resolve strictly, and reconcile without commit.

        Resolver failures propagate before any row is mutated. The enclosing
        transaction owns rollback and the returned post-commit effects.
        """

        instance = await ApprovalInstanceRepository.lock_instance_in_session(
            session,
            instance_id,
            tenant_id=tenant_id,
        )
        if instance is None:
            raise ValueError(f"approval instance not found: {instance_id}")
        tasks = await ApprovalInstanceRepository.lock_tasks_in_session(
            session,
            instance_id,
            tenant_id=tenant_id,
        )
        open_exceptions, _ = await ApprovalInstanceRepository.lock_open_exceptions_and_outboxes_in_session(
            session,
            instance_id,
            tenant_id=tenant_id,
        )
        node = cls._find_current_node(instance, tasks, open_exceptions)
        if not cls._is_reconcilable(instance, node, open_exceptions):
            return ApprovalDynamicAssigneeResult(instance_id=instance_id)

        resolved = resolver(instance)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        return await cls._reconcile_resolved_locked(
            session=session,
            instance=instance,
            tasks=tasks,
            open_exceptions=open_exceptions,
            node=node,
            approver_user_ids=resolved,
            trigger=trigger,
            operator_user_id=operator_user_id,
        )

    @classmethod
    async def reconcile_resolved_in_uow(
        cls,
        *,
        session,
        instance_id: int,
        approver_user_ids: Sequence[int],
        trigger: str,
        operator_user_id: int | None = None,
        tenant_id: int | None = None,
    ) -> ApprovalDynamicAssigneeResult:
        """Reconcile pre-resolved users under the same instance-first lock."""

        return await cls.resolve_and_reconcile_in_uow(
            session=session,
            instance_id=instance_id,
            resolver=lambda _instance: approver_user_ids,
            trigger=trigger,
            operator_user_id=operator_user_id,
            tenant_id=tenant_id,
        )

    @classmethod
    async def _reconcile_resolved_locked(
        cls,
        *,
        session,
        instance: ApprovalInstance,
        tasks: list[ApprovalTask],
        open_exceptions: list[ApprovalException],
        node: _CurrentNode,
        approver_user_ids: Sequence[int],
        trigger: str,
        operator_user_id: int | None,
    ) -> ApprovalDynamicAssigneeResult:
        desired_user_ids = tuple(sorted({int(user_id) for user_id in approver_user_ids}))
        pending_tasks = [
            task
            for task in tasks
            if task.node_code == node.code
            and task.node_order == node.order
            and task.status == ApprovalTaskStatus.PENDING
        ]
        pending_by_user: dict[int, list[ApprovalTask]] = {}
        for task in pending_tasks:
            pending_by_user.setdefault(task.approver_user_id, []).append(task)

        desired_set = set(desired_user_ids)
        pending_set = set(pending_by_user)
        removed_user_ids = tuple(sorted(pending_set - desired_set))
        added_user_ids = tuple(sorted(desired_set - pending_set))
        cancelled_tasks: list[ApprovalTask] = []
        now = datetime.utcnow()

        for user_id, user_tasks in pending_by_user.items():
            tasks_to_cancel = user_tasks if user_id not in desired_set else user_tasks[1:]
            for task in tasks_to_cancel:
                task.status = ApprovalTaskStatus.CANCELLED
                task.acted_at = now
                session.add(task)
                cancelled_tasks.append(task)

        entered_approver_empty = False
        resolved_approver_empty = False
        created_tasks: list[ApprovalTask] = []
        if not desired_user_ids:
            _, entered_approver_empty = await ApprovalExceptionService.ensure_approver_empty_locked(
                session=session,
                instance=instance,
                node_code=node.code,
                node_name=node.name,
                node_order=node.order,
                node_mode=node.mode,
                open_exceptions=open_exceptions,
            )
        else:
            for user_id in added_user_ids:
                task = ApprovalTask(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    flow_version_id=node.flow_version_id,
                    node_code=node.code,
                    node_name=node.name,
                    node_order=node.order,
                    approver_user_id=user_id,
                    approver_source_type="dynamic_reconciled",
                    node_mode=node.mode,
                    status=ApprovalTaskStatus.PENDING,
                )
                session.add(task)
                created_tasks.append(task)
            resolved_approver_empty = await ApprovalExceptionService.resolve_approver_empty_locked(
                session=session,
                instance=instance,
                node_code=node.code,
                node_order=node.order,
                open_exceptions=open_exceptions,
            )

        if added_user_ids or removed_user_ids:
            session.add(
                ApprovalActionLog(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    action="approval.approvers.reconciled",
                    operator_user_id=operator_user_id,
                    operator_user_name=None,
                    detail={
                        "added_user_ids": list(added_user_ids),
                        "removed_user_ids": list(removed_user_ids),
                        "trigger": trigger,
                        "operator_user_id": operator_user_id,
                    },
                )
            )
        await session.flush()

        effects: list[ApprovalPostCommitEffect] = []
        for task in created_tasks:
            effects.append(
                build_post_commit_effect(
                    f"notify_dynamic_approval_task:{task.id}",
                    cls._notify_created_task,
                    tenant_id=instance.tenant_id,
                    sender=instance.applicant_user_id,
                    receiver_user_id=task.approver_user_id,
                    business_name=instance.business_name or "",
                    instance_id=instance.id,
                    scenario_code=instance.scenario_code,
                    task_id=task.id,
                )
            )
        if entered_approver_empty:
            effects.append(
                build_post_commit_effect(
                    f"notify_dynamic_approver_empty:{instance.id}:{node.code}",
                    cls._notify_approver_empty,
                    tenant_id=instance.tenant_id,
                    applicant_user_id=instance.applicant_user_id,
                    business_name=instance.business_name or "",
                    instance_id=instance.id,
                    scenario_code=instance.scenario_code,
                )
            )
        return ApprovalDynamicAssigneeResult(
            instance_id=instance.id,
            added_user_ids=added_user_ids,
            removed_user_ids=removed_user_ids,
            cancelled_task_ids=tuple(task.id for task in cancelled_tasks),
            entered_approver_empty=entered_approver_empty,
            resolved_approver_empty=resolved_approver_empty,
            post_commit_effects=tuple(effects),
        )

    @staticmethod
    def _is_reconcilable(
        instance: ApprovalInstance,
        node: _CurrentNode,
        open_exceptions: list[ApprovalException],
    ) -> bool:
        if instance.status == ApprovalInstanceStatus.PENDING:
            return True
        if instance.status != ApprovalInstanceStatus.EXCEPTION:
            return False
        return any(
            row.exception_type == ApprovalExceptionType.APPROVER_EMPTY
            and ApprovalExceptionService._exception_matches_node(row, node.code, node.order)
            for row in open_exceptions
        )

    @staticmethod
    def _find_current_node(
        instance: ApprovalInstance,
        tasks: list[ApprovalTask],
        open_exceptions: list[ApprovalException],
    ) -> _CurrentNode:
        candidates = [task for task in tasks if task.node_name == instance.current_node_name]
        if not candidates:
            candidates = [task for task in tasks if task.status == ApprovalTaskStatus.PENDING]
        if not candidates:
            for exception in open_exceptions:
                if exception.exception_type != ApprovalExceptionType.APPROVER_EMPTY:
                    continue
                detail = exception.detail or {}
                return _CurrentNode(
                    flow_version_id=instance.flow_version_id or 0,
                    code=str(detail.get("node_code") or ""),
                    name=str(detail.get("node_name") or instance.current_node_name or ""),
                    order=int(detail.get("node_order") or 0),
                    mode=str(detail.get("node_mode") or "or"),
                )
            raise ValueError(f"current approval node not found: instance_id={instance.id}")

        task = max(candidates, key=lambda row: (row.node_order, row.id or 0))
        return _CurrentNode(
            flow_version_id=task.flow_version_id,
            code=task.node_code,
            name=task.node_name,
            order=task.node_order,
            mode=task.node_mode,
        )

    @staticmethod
    async def _notify_created_task(*, tenant_id: int, task_id: int, **kwargs) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        if not await ApprovalInstanceRepository.is_task_pending_for_tenant(
            task_id=task_id,
            tenant_id=tenant_id,
        ):
            return
        await ApprovalNotificationService.notify_user(
            action_code="approval_task_pending",
            task_id=task_id,
            **kwargs,
        )

    @staticmethod
    async def _notify_approver_empty(**kwargs) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_admins(action_code="approval_exception_approver_empty", **kwargs)
