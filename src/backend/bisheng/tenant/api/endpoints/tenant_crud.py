"""Tenant CRUD + status + quota API endpoints.

Part of F010-tenant-management-ui.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import (
    TenantCreate,
    TenantQuotaUpdate,
    TenantStatusUpdate,
    TenantUpdate,
)
from bisheng.tenant.domain.services.tenant_service import TenantService

router = APIRouter()


@router.post('/')
async def create_tenant(
    data: TenantCreate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantService.acreate_tenant(data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


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
