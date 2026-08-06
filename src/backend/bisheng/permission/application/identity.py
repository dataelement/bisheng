"""Resolve authenticated identity facts for F048 authorization."""

from __future__ import annotations

from typing import Protocol

from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class LoginPermissionIdentity(Protocol):
    user_id: int
    tenant_id: int
    is_global_super: bool


async def resolve_permission_actor(
    login_user: LoginPermissionIdentity,
) -> PermissionActor:
    """Resolve only identity roles; resource facts remain business-owned."""

    tenant_id = int(login_user.tenant_id)
    is_global_super = bool(getattr(login_user, "is_global_super", False))
    tenant_admin_tenant_ids: frozenset[int] = frozenset()
    if not is_global_super and tenant_id != DEFAULT_TENANT_ID:
        from bisheng.permission.application.relation_api import is_tenant_admin

        if await is_tenant_admin(login_user.user_id, tenant_id):
            tenant_admin_tenant_ids = frozenset({tenant_id})

    return PermissionActor(
        user_id=login_user.user_id,
        current_tenant_id=tenant_id,
        super_admin=is_global_super,
        tenant_admin_tenant_ids=tenant_admin_tenant_ids,
    )
