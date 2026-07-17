from fastapi import APIRouter, Depends

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
    redact_portal_admin_config,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)

router = APIRouter(prefix="/shougang-portal/config", tags=["shougang-portal-config"])


def _current_admin_tenant_id(admin_user: UserPayload) -> int:
    return int(get_current_tenant_id() or admin_user.tenant_id)


@router.get("")
async def get_shougang_portal_config(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    config = await ShougangPortalConfigService.get_config(
        tenant_id=_current_admin_tenant_id(admin_user),
    )
    return resp_200(redact_portal_admin_config(config) if config else None)


@router.get("/internal")
async def get_shougang_portal_config_internal():
    return resp_200(await ShougangPortalConfigService.get_config())


@router.put("")
async def save_shougang_portal_config(
    payload: ShougangPortalAdminConfig,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    saved = await ShougangPortalConfigService.save_config(
        payload,
        tenant_id=_current_admin_tenant_id(admin_user),
        create_user=admin_user.user_id,
    )
    return resp_200(redact_portal_admin_config(saved))
