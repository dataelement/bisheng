from fastapi.exceptions import HTTPException
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter, set_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.tenant import UserTenant, UserTenantDao
from bisheng.user.domain.models.user import UserDao


def _get_active_tenant_id_sync(user_id: int) -> int:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            row = session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.is_active == 1,
                )
            ).first()
            return row.tenant_id if row else DEFAULT_TENANT_ID


def get_default_operator() -> UserPayload:
    """Resolve the default operator and seed the per-request tenant ContextVar.

    The HTTP middleware only sets ``current_tenant_id`` from JWT cookies, so
    OpenAPI calls (which authenticate via the configured default_operator
    instead of a JWT) leave the ContextVar unset. Any DB query touching a
    tenant-aware table then raises ``NoTenantContextError`` under
    ``multi_tenant.enabled=true``. Seed the ContextVar here so every
    ``/api/v2/*`` endpoint that depends on this helper is multi-tenant safe.
    """
    user_id = settings.get_from_db('default_operator').get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='Not configureddefault_operatorIIuserConfigure')
    # Find default user information
    login_user = UserDao.get_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='not founddefault_operatorIIuserUser Information')
    tenant_id = _get_active_tenant_id_sync(login_user.user_id)
    login_user = UserPayload.init_login_user_sync(
        user_id=login_user.user_id,
        user_name=login_user.user_name,
        tenant_id=tenant_id,
    )
    set_current_tenant_id(tenant_id)
    return login_user


async def get_default_operator_async() -> UserPayload:
    """Async counterpart of :func:`get_default_operator` — see its docstring.

    Seeding the tenant ContextVar here is what makes default-operator-backed
    OpenAPI endpoints work under ``multi_tenant.enabled=true``.
    """
    user_id = (await settings.aget_from_db('default_operator')).get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='Not configureddefault_operatorIIuserConfigure')
    # Find default user information
    login_user = await UserDao.aget_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='not founddefault_operatorIIuserUser Information')
    active = await UserTenantDao.aget_active_user_tenant(login_user.user_id)
    tenant_id = active.tenant_id if active else DEFAULT_TENANT_ID
    login_user = await UserPayload.init_login_user(
        user_id=login_user.user_id,
        user_name=login_user.user_name,
        tenant_id=tenant_id,
    )
    set_current_tenant_id(tenant_id)
    return login_user
