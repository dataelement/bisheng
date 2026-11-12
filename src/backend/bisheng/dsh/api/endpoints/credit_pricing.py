"""F016 tenant credit settings and the price summary of user-selectable models."""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.api.endpoints.admin import TenantId, get_management
from bisheng.dsh.domain.schemas.pricing import CreditSettingInput
from bisheng.dsh.domain.services.pricing import admin_model_pricing, credit_settings_view, save_credit_settings
from bisheng.dsh.domain.services.profile import profile_scope

router = APIRouter(prefix="/dsh")
admin_user = UserPayload.get_tenant_admin_user


@router.get("/admin/credit-settings")
async def credit_settings(user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        return resp_200(data=await credit_settings_view())


@router.put("/admin/credit-settings")
async def update_credit_settings(
    body: CreditSettingInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        return resp_200(data=await save_credit_settings(user.user_id, body))


@router.get("/admin/model-pricing")
async def model_pricing(user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        return resp_200(data=await admin_model_pricing())
