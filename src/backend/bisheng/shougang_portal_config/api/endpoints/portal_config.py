from fastapi import APIRouter, Depends

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
    redact_portal_admin_config,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)

router = APIRouter(prefix='/shougang-portal/config', tags=['shougang-portal-config'])


@router.get('')
async def get_shougang_portal_config(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    config = await ShougangPortalConfigService.get_config()
    return resp_200(redact_portal_admin_config(config) if config else None)


@router.get('/internal')
async def get_shougang_portal_config_internal(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    return resp_200(await ShougangPortalConfigService.get_config())


@router.put('')
async def save_shougang_portal_config(
    payload: ShougangPortalAdminConfig,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    saved = await ShougangPortalConfigService.save_config(payload)
    return resp_200(redact_portal_admin_config(saved))
