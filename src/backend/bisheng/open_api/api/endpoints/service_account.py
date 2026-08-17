"""Service-account management endpoints ``/api/v1/service-accounts/**`` (F049 design §4.2 / D1).

A ``/api/v1`` surface: session-authenticated, tenant-admin gated, and answering
with the platform envelope (HTTP 200 + ``status_code``) — the open face's real
HTTP statuses stop at ``/api/v2`` (K4). Endpoints here only bind parameters and
delegate; every rule (owner validation, lifecycle timestamps, the write-through
``user.delete`` projection, audit) lives in ``ServiceAccountService``.

The tenant a write lands in is **never** read from the request body: it comes
from the acting admin's scope, which for a super admin is whatever the F019
ScopeBar switched to (AC-23, pit 23 — hence this prefix is registered in
``MANAGEMENT_API_PREFIXES``).
"""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountDetail,
    ServiceAccountPage,
    ServiceAccountUpdate,
)
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService

router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])


@router.get("", response_model=UnifiedResponseModel[ServiceAccountPage])
async def list_service_accounts(
    keyword: str | None = Query(default=None, description="Fuzzy match on the account name"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    admin: UserPayload = Depends(get_service_account_admin),
):
    """One page of this tenant's service accounts with every AC-42 column resolved."""
    return resp_200(data=await ServiceAccountService.list_page(admin, keyword=keyword, page=page, page_size=page_size))


@router.post("", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def create_service_account(
    data: ServiceAccountCreate,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Create principal + companion + active tenant row in one transaction (AC-19 / AC-23)."""
    account = await ServiceAccountService.create(admin, data)
    return resp_200(data=await ServiceAccountService.get_detail(admin, account.user_id))


@router.get("/{service_account_id}", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def get_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(data=await ServiceAccountService.get_detail(admin, service_account_id))


@router.patch("/{service_account_id}", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def update_service_account(
    service_account_id: int,
    data: ServiceAccountUpdate,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Edit name / description / resource owner. Owner changes are not retroactive (AC-27)."""
    await ServiceAccountService.update(admin, service_account_id, data)
    return resp_200(data=await ServiceAccountService.get_detail(admin, service_account_id))


@router.post("/{service_account_id}/enable", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def enable_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await ServiceAccountService.enable(admin, service_account_id)
    return resp_200(data=await ServiceAccountService.get_detail(admin, service_account_id))


@router.post("/{service_account_id}/disable", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def disable_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Keys stop working within 5s; grants and configuration are kept (AC-21 / AC-47)."""
    await ServiceAccountService.disable(admin, service_account_id)
    return resp_200(data=await ServiceAccountService.get_detail(admin, service_account_id))


@router.delete("/{service_account_id}")
async def delete_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Delete without blocking, and report what the deletion took down (AC-48).

    ``grants`` is the account's resource authorizations at deletion time — the
    list the confirmation dialog shows. Wave 1 has no subject-side reverse lookup
    yet, so it is structurally empty; T065 fills it in place. The field ships
    empty rather than absent so the front end never branches on its presence.
    """
    await ServiceAccountService.delete(admin, service_account_id)
    return resp_200(data={"id": service_account_id, "grants": []})
