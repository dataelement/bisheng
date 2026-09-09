"""Compatibility identities for legacy v2 business services.

Authorization never comes from these payloads. The router dependency has
already installed a typed ``PermissionActor``; this module only supplies the
natural-person fields still required by legacy persistence and telemetry APIs.
"""

from fastapi.exceptions import HTTPException
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.tenant import UserTenant, UserTenantDao
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.user.domain.models.user import UserDao


def _principal_user_id() -> tuple[int, bool]:
    principal = get_current_open_api_principal()
    if principal is None:
        raise HTTPException(status_code=500, detail="Open API execution identity is missing")
    user_id = principal.effective_user_id or principal.resource_owner_user_id
    if user_id is None:
        raise HTTPException(status_code=500, detail="Open API execution has no compatible resource owner")
    return user_id, principal.actor_kind == "service_account" and principal.mode == "S"


def _get_active_tenant_id_sync(user_id: int) -> int | None:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            row = session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.is_active == 1,
                )
            ).first()
            return row.tenant_id if row else None


def get_open_api_operator() -> UserPayload:
    user_id, force_non_admin = _principal_user_id()
    user = UserDao.get_user(user_id)
    tenant_id = _get_active_tenant_id_sync(user_id)
    if user is None or user.delete or tenant_id != get_current_tenant_id():
        raise HTTPException(status_code=404, detail="Open API resource owner is unavailable")
    if force_non_admin:
        return UserPayload(
            user_id=user.user_id,
            user_name=user.user_name,
            user_role=[],
            tenant_id=tenant_id,
            is_global_super=False,
        )
    return UserPayload.init_login_user_sync(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id,
    )


async def get_open_api_operator_async() -> UserPayload:
    user_id, force_non_admin = _principal_user_id()
    user = await UserDao.aget_user(user_id)
    active = await UserTenantDao.aget_active_user_tenant(user_id)
    tenant_id = active.tenant_id if active else None
    if user is None or user.delete or tenant_id != get_current_tenant_id():
        raise HTTPException(status_code=404, detail="Open API resource owner is unavailable")
    if force_non_admin:
        return UserPayload(
            user_id=user.user_id,
            user_name=user.user_name,
            user_role=[],
            tenant_id=tenant_id,
            is_global_super=False,
        )
    return await UserPayload.init_login_user(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id,
    )


__all__ = ["get_open_api_operator", "get_open_api_operator_async"]
