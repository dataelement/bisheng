"""Resolve the first eligible asset receiver for local member delete."""

from __future__ import annotations

from dataclasses import dataclass

from bisheng.approval.domain.services.approver_resolver import _department_hierarchy_ids_from_path
from bisheng.common.errcode.resource_owner_transfer import ResourceTransferReceiverOutOfTenantError
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao
from bisheng.department.domain.schemas.local_member_delete_schema import (
    LocalMemberDeleteReceiverPreview,
)
from bisheng.tenant.domain.services.resource_ownership_service import ResourceOwnershipService
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao


@dataclass(frozen=True)
class ResolvedTransferReceiver:
    user_id: int
    user_name: str
    source: str
    department_id: int | None = None
    department_name: str | None = None

    def to_preview(self) -> LocalMemberDeleteReceiverPreview:
        return LocalMemberDeleteReceiverPreview(
            user_id=self.user_id,
            user_name=self.user_name,
            source=self.source,
            department_id=self.department_id,
            department_name=self.department_name,
        )


async def _is_active_user(user_id: int) -> bool:
    user = await UserDao.aget_user(user_id)
    return user is not None and int(getattr(user, "delete", 0) or 0) == 0


async def _receiver_visible_for_tenants(receiver_id: int, tenant_ids: list[int]) -> bool:
    for tenant_id in tenant_ids:
        try:
            await ResourceOwnershipService._check_receiver_visible(receiver_id, tenant_id)
        except ResourceTransferReceiverOutOfTenantError:
            return False
    return True


async def _pick_first_visible_candidate(
    candidate_ids: list[int],
    *,
    excluded_user_id: int,
    tenant_ids: list[int],
) -> int | None:
    filtered = sorted(
        {
            int(candidate_id)
            for candidate_id in candidate_ids
            if int(candidate_id) != int(excluded_user_id)
        }
    )
    for candidate_id in filtered:
        if not await _is_active_user(candidate_id):
            continue
        if await _receiver_visible_for_tenants(candidate_id, tenant_ids):
            return candidate_id
    return None


async def _resolve_department_admin_receiver(
    *,
    start_department_id: int,
    excluded_user_id: int,
    tenant_ids: list[int],
) -> ResolvedTransferReceiver | None:
    dept = await DepartmentDao.aget_by_id(start_department_id)
    if dept is None:
        return None

    hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, "path", None), start_department_id)
    for candidate_dept_id in reversed(hierarchy_ids):
        admin_ids = await DepartmentAdminGrantDao.aget_user_ids_by_department(candidate_dept_id)
        if not admin_ids:
            continue
        receiver_id = await _pick_first_visible_candidate(
            [int(uid) for uid in admin_ids],
            excluded_user_id=excluded_user_id,
            tenant_ids=tenant_ids,
        )
        if receiver_id is None:
            continue
        receiver = await UserDao.aget_user(receiver_id)
        candidate_dept = await DepartmentDao.aget_by_id(candidate_dept_id)
        if receiver is None:
            continue
        return ResolvedTransferReceiver(
            user_id=int(receiver.user_id),
            user_name=str(receiver.user_name or ""),
            source="department_admin",
            department_id=int(candidate_dept_id),
            department_name=str(getattr(candidate_dept, "name", "") or ""),
        )
    return None


async def _resolve_platform_admin_receiver(
    *,
    excluded_user_id: int,
    tenant_ids: list[int],
) -> ResolvedTransferReceiver | None:
    rows = await UserRoleDao.aget_roles_user([AdminRole])
    candidate_ids = sorted({int(row.user_id) for row in rows})
    receiver_id = await _pick_first_visible_candidate(
        candidate_ids,
        excluded_user_id=excluded_user_id,
        tenant_ids=tenant_ids,
    )
    if receiver_id is None:
        return None
    receiver = await UserDao.aget_user(receiver_id)
    if receiver is None:
        return None
    return ResolvedTransferReceiver(
        user_id=int(receiver.user_id),
        user_name=str(receiver.user_name or ""),
        source="platform_admin",
    )


async def resolve_local_member_transfer_receiver(
    *,
    user_id: int,
    start_department_id: int | None,
    tenant_ids: list[int],
) -> ResolvedTransferReceiver | None:
    if start_department_id is not None:
        receiver = await _resolve_department_admin_receiver(
            start_department_id=int(start_department_id),
            excluded_user_id=user_id,
            tenant_ids=tenant_ids,
        )
        if receiver is not None:
            return receiver
    return await _resolve_platform_admin_receiver(
        excluded_user_id=user_id,
        tenant_ids=tenant_ids,
    )
