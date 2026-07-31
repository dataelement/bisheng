"""Translate authenticated HTTP identity into permission-domain identity."""

from __future__ import annotations

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


async def permission_actor(login_user: UserPayload) -> PermissionActor:
    """Resolve the authenticated identity facts used by F048 services."""

    return await resolve_permission_actor(login_user)
