"""Resolve authenticated identity facts for F048 authorization."""

from __future__ import annotations

import inspect
from typing import Protocol

from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class LoginPermissionIdentity(Protocol):
    user_id: int
    tenant_id: int
    is_global_super: bool

    async def has_tenant_admin(self, tenant_id: int) -> bool: ...


async def resolve_permission_actor(
    login_user: LoginPermissionIdentity,
) -> PermissionActor:
    """Resolve only identity roles; resource facts remain business-owned."""

    tenant_id = int(login_user.tenant_id)
    is_global_super = bool(getattr(login_user, "is_global_super", False))
    tenant_admin_tenant_ids: frozenset[int] = frozenset()
    if not is_global_super and tenant_id != DEFAULT_TENANT_ID:
        has_tenant_admin = getattr(login_user, "has_tenant_admin", None)
        if callable(has_tenant_admin):
            result = has_tenant_admin(tenant_id)
            if inspect.isawaitable(result):
                result = await result
            if result:
                tenant_admin_tenant_ids = frozenset({tenant_id})

    return PermissionActor(
        user_id=login_user.user_id,
        current_tenant_id=tenant_id,
        super_admin=is_global_super,
        tenant_admin_tenant_ids=tenant_admin_tenant_ids,
    )
