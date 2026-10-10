"""Resolve authenticated identity facts for F048 authorization."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Protocol

from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class LoginPermissionIdentity(Protocol):
    user_id: int
    tenant_id: int
    is_global_super: bool


current_permission_actor: ContextVar[PermissionActor | None] = ContextVar("current_permission_actor", default=None)


def get_current_permission_actor() -> PermissionActor | None:
    return current_permission_actor.get()


def set_current_permission_actor(actor: PermissionActor | None) -> Token:
    return current_permission_actor.set(actor)


def reset_current_permission_actor(token: Token) -> None:
    current_permission_actor.reset(token)


async def resolve_permission_actor(
    login_user: LoginPermissionIdentity,
) -> PermissionActor:
    """Resolve only identity roles; resource facts remain business-owned."""

    contextual_actor = get_current_permission_actor()
    if contextual_actor is not None:
        return contextual_actor

    tenant_id = int(login_user.tenant_id)
    is_global_super = bool(getattr(login_user, "is_global_super", False))
    tenant_admin_tenant_ids: frozenset[int] = frozenset()
    if not is_global_super and tenant_id != DEFAULT_TENANT_ID:
        from bisheng.permission.application.relation_api import is_tenant_admin

        if await is_tenant_admin(login_user.user_id, tenant_id):
            tenant_admin_tenant_ids = frozenset({tenant_id})

    return PermissionActor(
        subject_type="user",
        subject_id=login_user.user_id,
        tenant_id=tenant_id,
        super_admin=is_global_super,
        tenant_admin_tenant_ids=tenant_admin_tenant_ids,
    )
