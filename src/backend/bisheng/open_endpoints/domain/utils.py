from fastapi.exceptions import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.tenant import UserTenant, UserTenantDao
from bisheng.user.domain.models.user import UserDao
from sqlmodel import select


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
    user_id = settings.get_from_db('default_operator').get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='Not configureddefault_operatorIIuserConfigure')
    # Find default user information
    login_user = UserDao.get_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='not founddefault_operatorIIuserUser Information')
    login_user = UserPayload.init_login_user_sync(
        user_id=login_user.user_id,
        user_name=login_user.user_name,
        tenant_id=_get_active_tenant_id_sync(login_user.user_id),
    )
    return login_user


async def get_default_operator_async() -> UserPayload:
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

    return login_user
