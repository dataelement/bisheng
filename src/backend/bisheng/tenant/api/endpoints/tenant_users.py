"""Tenant user management API endpoints.

Part of F010-tenant-management-ui. Modified by F024 (v2.5.1):
``POST /tenants/{id}/users`` and ``DELETE /tenants/{id}/users/{user_id}``
return 410 Gone — tenant membership is derived from the user's primary
department (F012). The ``GET`` endpoint is preserved with its public
contract, but its data source is switched to a primary-dept-subtree query
inside the service layer (UserTenant residue rows no longer surface).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.services.tenant_service import TenantService

router = APIRouter()


# F024: shared 410 response body for both deprecated mutating endpoints.
_GONE_RESPONSE = {
    'error': '410 Gone',
    'detail': (
        'Tenant membership is derived from the user\'s primary department '
        '(F012). Update the user\'s primary department to alter membership.'
    ),
    'migration': (
        'POST /api/v1/department/{dept_id}/members/{user_id}/apply-edit'
    ),
    'deprecated_since': 'v2.5.1',
    'removed_in': 'v2.6.0',
}


@router.get('/{tenant_id}/users')
async def get_tenant_users(
    tenant_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aget_tenant_users(
            tenant_id, page=page, page_size=page_size,
            keyword=keyword, login_user=login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{tenant_id}/users')
async def add_users_deprecated(tenant_id: int):
    """**DEPRECATED in v2.5.1 (F024)**: returns 410 Gone unconditionally.

    No auth dependency so SDK retries cannot land on 401/403 instead.
    Mirrors the ``switch-tenant`` 410 pattern from F011.
    """
    return JSONResponse(status_code=410, content=_GONE_RESPONSE)


@router.delete('/{tenant_id}/users/{user_id}')
async def remove_user_deprecated(tenant_id: int, user_id: int):
    """**DEPRECATED in v2.5.1 (F024)**: returns 410 Gone unconditionally.

    See ``add_users_deprecated``.
    """
    return JSONResponse(status_code=410, content=_GONE_RESPONSE)
