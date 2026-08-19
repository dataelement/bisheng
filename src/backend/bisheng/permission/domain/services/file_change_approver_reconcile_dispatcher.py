from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Protocol

from loguru import logger

from bisheng.core.context.tenant import get_current_tenant_id

_FILE_CHANGE_APPROVER_RELATIONS = frozenset({"owner", "manager"})


class _ReconciliationTarget(Protocol):
    instance_id: int
    approver_user_ids: Sequence[int]


KnowledgeResolver = Callable[..., Awaitable[Sequence[_ReconciliationTarget]]]
ApprovalReconciliationPort = Callable[..., Awaitable[object]]
LegacyDispatch = Callable[..., object]


async def _default_knowledge_resolver(**kwargs) -> Sequence[_ReconciliationTarget]:
    from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
        KnowledgeSpaceFileChangeApproverResolver,
    )

    return await KnowledgeSpaceFileChangeApproverResolver.resolve_reconciliation_targets(**kwargs)


async def _default_reconciliation_port(**kwargs) -> object:
    from bisheng.approval.domain.services.approval_dynamic_assignee_service import (
        ApprovalDynamicAssigneeService,
    )

    return await ApprovalDynamicAssigneeService.reconcile_assignees(**kwargs)


def _positive_id(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"file change approver reconciliation requires a positive {label}")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"file change approver reconciliation requires a positive {label}") from exc
    if normalized <= 0:
        raise ValueError(f"file change approver reconciliation requires a positive {label}")
    return normalized


def _matching_tenant_id(tenant_id: object) -> int:
    normalized = _positive_id(tenant_id, "tenant_id")
    current_tenant_id = get_current_tenant_id()
    if current_tenant_id is None or int(current_tenant_id) != normalized:
        raise ValueError("file change approver reconciliation requires the matching tenant context")
    return normalized


def _normalize_approver_user_ids(values: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(sorted({_positive_id(value, "approver user id") for value in values}))
    return normalized


class FileChangeApproverReconcileDispatcher:
    """Orchestrate Knowledge resolution and the application-level F025 port."""

    def __init__(
        self,
        *,
        knowledge_resolver: KnowledgeResolver = _default_knowledge_resolver,
        reconciliation_port: ApprovalReconciliationPort = _default_reconciliation_port,
    ) -> None:
        self._knowledge_resolver = knowledge_resolver
        self._reconciliation_port = reconciliation_port

    async def reconcile_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        reason: str,
    ) -> int:
        normalized_tenant_id = _matching_tenant_id(tenant_id)
        normalized_space_id = _positive_id(space_id, "space id")
        normalized_reason = str(reason).strip()
        if not normalized_reason:
            raise ValueError("file change approver reconciliation requires a reason")

        # Resolver failures, including strict OpenFGA failures, propagate. An
        # unavailable resolver must never be represented as an empty approver set.
        targets = await self._knowledge_resolver(
            tenant_id=normalized_tenant_id,
            space_id=normalized_space_id,
        )
        seen_instance_ids: set[int] = set()
        reconciled = 0
        for target in targets:
            instance_id = _positive_id(getattr(target, "instance_id", None), "instance id")
            if instance_id in seen_instance_ids:
                continue
            seen_instance_ids.add(instance_id)
            approver_user_ids = _normalize_approver_user_ids(tuple(getattr(target, "approver_user_ids", ())))
            await self._reconciliation_port(
                tenant_id=normalized_tenant_id,
                instance_id=instance_id,
                approver_user_ids=approver_user_ids,
                reason=normalized_reason,
            )
            reconciled += 1
        return reconciled


def _contains_approver_relation(items: Iterable[object]) -> bool:
    return any(getattr(item, "relation", None) in _FILE_CHANGE_APPROVER_RELATIONS for item in items)


async def dispatch_file_change_approver_reconcile_for_permission_change(
    *,
    resource_type: str,
    resource_id: str | int,
    grants: Iterable[object] = (),
    revokes: Iterable[object] = (),
    tenant_id: int | None = None,
    dispatcher: FileChangeApproverReconcileDispatcher | None = None,
    dispatch: LegacyDispatch | None = None,
) -> None:
    """Reconcile after an authoritative owner/manager permission mutation."""

    if resource_type != "knowledge_space":
        return
    if not (_contains_approver_relation(grants) or _contains_approver_relation(revokes)):
        return
    try:
        space_id = _positive_id(resource_id, "space id")
    except ValueError:
        logger.warning(
            "F046 approver reconcile skipped invalid space id: resource_id={!r}",
            resource_id,
        )
        return

    if dispatcher is not None:
        await dispatcher.reconcile_space(
            tenant_id=tenant_id,
            space_id=space_id,
            reason="permission_event",
        )
        return
    await dispatch_file_change_approver_reconcile_for_spaces(
        space_ids=[space_id],
        tenant_id=tenant_id,
        dispatch=dispatch,
        reason="permission_event",
    )


async def dispatch_file_change_approver_reconcile_for_spaces(
    *,
    space_ids: Iterable[int],
    tenant_id: int | None = None,
    dispatch: LegacyDispatch | None = None,
    dispatcher: FileChangeApproverReconcileDispatcher | None = None,
    reason: str = "permission_event",
) -> None:
    """Run one explicit-tenant reconciliation per deduplicated space."""

    try:
        normalized_tenant_id = _positive_id(tenant_id, "tenant_id")
    except ValueError:
        logger.error("F046 approver reconcile skipped missing tenant")
        return

    normalized_space_ids = sorted({_positive_id(space_id, "space id") for space_id in space_ids})
    if dispatch is not None:
        for space_id in normalized_space_ids:
            result = dispatch(space_id, tenant_id=normalized_tenant_id)
            if inspect.isawaitable(result):
                await result
        return

    active_dispatcher = dispatcher or FileChangeApproverReconcileDispatcher()
    for space_id in normalized_space_ids:
        await active_dispatcher.reconcile_space(
            tenant_id=normalized_tenant_id,
            space_id=space_id,
            reason=reason,
        )


__all__ = [
    "FileChangeApproverReconcileDispatcher",
    "dispatch_file_change_approver_reconcile_for_permission_change",
    "dispatch_file_change_approver_reconcile_for_spaces",
]
