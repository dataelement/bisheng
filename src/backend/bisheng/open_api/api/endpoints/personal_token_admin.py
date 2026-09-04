"""Tenant-admin ledger and policy endpoints for personal tokens."""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.schemas.credential import KeyItem
from bisheng.open_api.domain.schemas.personal_token import (
    PersonalTokenLedgerPage,
    PersonalTokenSettingResponse,
    PersonalTokenSettingUpdate,
)
from bisheng.open_api.domain.services.personal_token_service import PersonalTokenService
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService

router = APIRouter(prefix="/personal-tokens", tags=["PersonalToken"])


def _tenant_id(admin: UserPayload) -> int:
    return int(get_current_tenant_id() or admin.tenant_id or DEFAULT_TENANT_ID)


@router.get("/settings", response_model=UnifiedResponseModel[PersonalTokenSettingResponse])
async def get_personal_token_settings(admin: UserPayload = Depends(get_service_account_admin)):
    return resp_200(data=await TenantSettingService.get_response(_tenant_id(admin)))


@router.put("/settings", response_model=UnifiedResponseModel[PersonalTokenSettingResponse])
async def update_personal_token_settings(
    data: PersonalTokenSettingUpdate,
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(data=await TenantSettingService.update(_tenant_id(admin), data))


@router.get("", response_model=UnifiedResponseModel[PersonalTokenLedgerPage])
async def list_personal_tokens(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(
        data=await PersonalTokenService.list_page(
            tenant_id=_tenant_id(admin),
            page=page,
            page_size=page_size,
        )
    )


@router.post("/holders/{user_id}/revoke", response_model=UnifiedResponseModel[dict])
async def revoke_personal_tokens_by_holder(
    user_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    revoked = await PersonalTokenService.revoke_by_holder(
        tenant_id=_tenant_id(admin),
        user_id=user_id,
        operator=admin,
    )
    return resp_200(data={"revoked": revoked})


@router.post("/{credential_id}/revoke", response_model=UnifiedResponseModel[KeyItem])
async def revoke_personal_token(
    credential_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(
        data=await PersonalTokenService.revoke_by_id(
            tenant_id=_tenant_id(admin),
            credential_id=credential_id,
            operator=admin,
        )
    )

