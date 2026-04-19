"""Tenant CRUD + status + quota API endpoints.

Part of F010-tenant-management-ui.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.tenant_tree import TenantTreeRootProtectedError
from bisheng.common.schemas.api import resp_200
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.tenant.domain.schemas.tenant_schema import (
    TenantCreate,
    TenantQuotaUpdate,
    TenantStatusUpdate,
    TenantUpdate,
)
from bisheng.tenant.domain.services.tenant_service import TenantService

router = APIRouter()


def _root_protection_response() -> JSONResponse:
    """403 + errcode 22008. Endpoint-level gate per spec §5.5 "进入路由前先校验"."""
    exc = TenantTreeRootProtectedError()
    return JSONResponse(
        status_code=403,
        content=exc.return_resp_instance().model_dump(mode='json'),
    )


@router.post('/')
async def create_tenant():
    """DEPRECATED in v2.5.1 F011 (AC-15): always returns HTTP 410 Gone.

    Root tenant is auto-created by the F011 migration; Child tenants are
    created via ``POST /api/v1/departments/{dept_id}/mount-tenant``. No
    body model, no auth dependency — the gate fires unconditionally
    before any business logic or Pydantic validation.
    """
    return JSONResponse(
        status_code=410,
        content={
            'error': '410 Gone',
            'detail': (
                'Root 由系统初始化自动创建（迁移时）；'
                'Child 通过 POST /api/v1/departments/{dept_id}/mount-tenant 创建'
            ),
        },
    )


@router.get('/')
async def list_tenants(
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.alist_tenants(
            keyword=keyword, status=status, page=page, page_size=page_size,
            login_user=login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{tenant_id}')
async def get_tenant(
    tenant_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aget_tenant(tenant_id, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/{tenant_id}')
async def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aupdate_tenant(tenant_id, data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/{tenant_id}/status')
async def update_tenant_status(
    tenant_id: int,
    data: TenantStatusUpdate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    if tenant_id == ROOT_TENANT_ID:
        return _root_protection_response()
    try:
        result = await TenantService.aupdate_tenant_status(tenant_id, data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{tenant_id}')
async def delete_tenant(
    tenant_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    if tenant_id == ROOT_TENANT_ID:
        return _root_protection_response()
    try:
        await TenantService.adelete_tenant(tenant_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{tenant_id}/quota')
async def get_quota(
    tenant_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aget_quota(tenant_id, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/{tenant_id}/quota')
async def set_quota(
    tenant_id: int,
    data: TenantQuotaUpdate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.aset_quota(tenant_id, data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()
