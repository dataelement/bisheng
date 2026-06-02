
from fastapi.exceptions import HTTPException
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
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


async def resolve_operator(user_id: int | None = None) -> UserPayload:
    """Resolve the acting identity for v2 filelib endpoints (F030 AD-02).

    - ``user_id`` omitted → fall back to the configured default operator
      (existing behaviour, unchanged).
    - ``user_id`` provided → build a ``UserPayload`` for that target user so
      列表 / 检索 / 文件列表 are filtered by *that user's* visibility scope and
      ``permission_ids`` are computed under the same identity. This is the
      "代用户" protocol F029 deferred for ``/api/v2/filelib/retrieve``.

    Seeds ``current_tenant_id`` with the resolved user's active tenant so
    tenant-aware queries stay multi-tenant safe (mirrors get_default_operator_async).
    """
    if user_id is None:
        return await get_default_operator_async()

    target_user = await UserDao.aget_user(user_id)
    if not target_user:
        raise NotFoundError.http_exception()
    active = await UserTenantDao.aget_active_user_tenant(target_user.user_id)
    tenant_id = active.tenant_id if active else DEFAULT_TENANT_ID
    login_user = await UserPayload.init_login_user(
        user_id=target_user.user_id,
        user_name=target_user.user_name,
        tenant_id=tenant_id,
    )
    set_current_tenant_id(tenant_id)
    return login_user
