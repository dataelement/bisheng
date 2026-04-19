"""User-facing tenant endpoints: list my tenants, switch tenant.

Part of F010-tenant-management-ui.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import SwitchTenantRequest
from bisheng.tenant.domain.services.tenant_service import TenantService

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
async def switch_tenant_deprecated():
    """DEPRECATED in v2.5.1 F011: tenant switching removed.

    The user's leaf tenant is now derived from their primary department
    (F012 TenantResolver) — there is no user-visible "switch" action. The
    endpoint returns 410 Gone unconditionally and takes no auth dependency
    so it cannot return 401/403 that clients might retry on.
    """
    return JSONResponse(
        status_code=410,
        content={
            'error': '410 Gone',
            'detail': (
                'Tenant switching has been removed — a user\'s tenant is '
                'derived from their primary department in v2.5.1.'
            ),
        },
    )
