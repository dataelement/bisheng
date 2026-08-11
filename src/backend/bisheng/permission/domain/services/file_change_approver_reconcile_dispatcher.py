from __future__ import annotations

from collections.abc import Callable, Iterable

from loguru import logger

_FILE_CHANGE_APPROVER_RELATIONS = frozenset({"owner", "manager"})


def _default_dispatch(space_id: int, *, tenant_id: int) -> None:
    from bisheng.worker.approval.file_change_tasks import (
        reconcile_space_file_change_approvers,
    )

    reconcile_space_file_change_approvers.apply_async(
        args=[int(space_id)],
        headers={"tenant_id": int(tenant_id)},
    )


def _contains_approver_relation(items: Iterable[object]) -> bool:
    return any(getattr(item, "relation", None) in _FILE_CHANGE_APPROVER_RELATIONS for item in items)


async def dispatch_file_change_approver_reconcile_for_permission_change(
    *,
    resource_type: str,
    resource_id: str | int,
    grants: Iterable[object] = (),
    revokes: Iterable[object] = (),
    tenant_id: int | None = None,
    dispatch: Callable[..., None] | None = None,
) -> None:
    """Dispatch after a successful owner/manager permission mutation.

    The helper deliberately owns no permission or Approval persistence. Callers
    invoke it only after their authoritative write boundary has succeeded.
    """

    if resource_type != "knowledge_space":
        return
    if not (_contains_approver_relation(grants) or _contains_approver_relation(revokes)):
        return
    try:
        space_id = int(resource_id)
    except (TypeError, ValueError):
        logger.warning(
            "F046 approver reconcile dispatch skipped invalid space id: resource_id={!r}",
            resource_id,
        )
        return
    await dispatch_file_change_approver_reconcile_for_spaces(
        space_ids=[space_id],
        tenant_id=tenant_id,
        dispatch=dispatch,
    )


async def dispatch_file_change_approver_reconcile_for_spaces(
    *,
    space_ids: Iterable[int],
    tenant_id: int | None = None,
    dispatch: Callable[..., None] | None = None,
) -> None:
    """Best-effort post-write dispatch, deduplicated by knowledge-space id."""

    dispatch_one = dispatch or _default_dispatch
    normalized_space_ids = sorted({int(space_id) for space_id in space_ids if int(space_id) > 0})
    for space_id in normalized_space_ids:
        resolved_tenant_id = tenant_id
        if resolved_tenant_id is None or isinstance(resolved_tenant_id, bool) or int(resolved_tenant_id) <= 0:
            logger.error(
                "F046 approver reconcile dispatch skipped missing tenant: space_id={}",
                space_id,
            )
            continue
        try:
            dispatch_one(space_id, tenant_id=int(resolved_tenant_id))
        except Exception:
            # Beat and lazy reconciliation repair missed permission-event dispatches.
            logger.exception(
                "F046 approver reconcile dispatch failed: tenant_id={} space_id={}",
                int(resolved_tenant_id),
                space_id,
            )
