"""Tenant user management API endpoints.

Part of F010-tenant-management-ui.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import TenantUserAdd
from bisheng.tenant.domain.services.tenant_service import TenantService

router = APIRouter()


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
async def add_users(
    tenant_id: int,
    data: TenantUserAdd,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aadd_users(tenant_id, data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{tenant_id}/users/{user_id}')
async def remove_user(
    tenant_id: int,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        await TenantService.aremove_user(tenant_id, user_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()
