"""User-facing tenant endpoints: list my tenants, switch tenant.

Part of F010-tenant-management-ui.
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import SwitchTenantRequest
from bisheng.tenant.domain.services.tenant_service import TenantService
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.services.auth import AuthJwt

router = APIRouter()


@router.get('/tenants')
async def get_my_tenants(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await TenantService.aget_user_tenants(login_user.user_id)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/switch-tenant')
async def switch_tenant(
    data: SwitchTenantRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    auth_jwt: AuthJwt = Depends(),
):
    try:
        db_user = await UserDao.aget_user(login_user.user_id)
        access_token = await TenantService.aswitch_tenant(
            user_id=login_user.user_id,
            tenant_id=data.tenant_id,
            db_user=db_user,
            auth_jwt=auth_jwt,
        )
        return resp_200({'access_token': access_token})
    except BaseErrorCode as e:
        return e.return_resp_instance()
