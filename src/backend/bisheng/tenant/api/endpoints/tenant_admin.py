"""Tenant admin endpoints (F013 follow-up to T07).

Wires POST/DELETE/GET /tenants/{tenant_id}/admins to TenantAdminService.
Root tenant grants surface as HTTP 403 + errcode 19204 per AC-13.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.tenant_fga import RootTenantAdminNotAllowedError
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.services.tenant_admin_service import TenantAdminService

router = APIRouter()


class TenantAdminGrant(BaseModel):
    """Request body for POST /tenants/{tenant_id}/admins."""
    user_id: int


def _root_admin_forbidden_response() -> JSONResponse:
    """403 + errcode 19204 — endpoint-level surface of RootTenantAdminNotAllowedError."""
    exc = RootTenantAdminNotAllowedError()
    return JSONResponse(
        status_code=403,
        content=exc.return_resp_instance().model_dump(mode='json'),
    )


@router.get('/{tenant_id}/admins')
async def list_tenant_admins(
    tenant_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """List user ids holding direct tenant#admin tuple on the tenant.

    Root tenant returns an empty list by design (no tuples exist).
    """
    try:
        user_ids = await TenantAdminService.list_tenant_admins(tenant_id)
        return resp_200(data={'user_ids': user_ids})
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{tenant_id}/admins')
async def grant_tenant_admin(
    tenant_id: int,
    data: TenantAdminGrant,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Grant user Child Admin role on the given tenant.

    Root tenant grants return HTTP 403 + errcode 19204 (AC-13).
    """
    try:
        await TenantAdminService.grant_tenant_admin(tenant_id, data.user_id)
        return resp_200()
    except RootTenantAdminNotAllowedError:
        return _root_admin_forbidden_response()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{tenant_id}/admins/{user_id}')
async def revoke_tenant_admin(
    tenant_id: int,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Revoke a user's Child Admin role on the given tenant.

    Root tenant revokes also return HTTP 403 + errcode 19204 (symmetry with grant).
    """
    try:
        await TenantAdminService.revoke_tenant_admin(tenant_id, user_id)
        return resp_200()
    except RootTenantAdminNotAllowedError:
        return _root_admin_forbidden_response()
    except BaseErrorCode as e:
        return e.return_resp_instance()
