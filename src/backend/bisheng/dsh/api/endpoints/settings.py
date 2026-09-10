"""Management remains accessible when the deployed DSH business gate is off."""

from fastapi import APIRouter, Depends, Response

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshDshDisabledError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_settings
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.settings import DshManagementSettings
from bisheng.dsh.domain.services.settings import DshSettingsService

router = APIRouter(route_class=DshRoute)
settings_admin = UserPayload.get_admin_user


def settings_service() -> DshSettingsService:
    return DshSettingsService()


def require_deployment(config: DshSettings = Depends(get_settings)) -> DshSettings:
    if not config.enabled:
        raise DshDshDisabledError()
    return config


@router.get("/dsh/browser-config")
async def browser_config(
    response: Response,
    config: DshSettings = Depends(get_settings),
    service: DshSettingsService = Depends(settings_service),
):
    response.headers["Cache-Control"] = "no-store"
    if not config.enabled:
        return resp_200(data={"management_enabled": False, **DshManagementSettings().model_dump()})
    current = await service.read()
    return resp_200(data={"management_enabled": True, **current.model_dump()})


@router.get("/dsh/admin/settings")
async def read_settings(
    response: Response,
    user=Depends(settings_admin),
    config=Depends(require_deployment),
    service: DshSettingsService = Depends(settings_service),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.read())


@router.put("/dsh/admin/settings")
async def save_settings(
    body: DshManagementSettings,
    user=Depends(settings_admin),
    config=Depends(require_deployment),
    service: DshSettingsService = Depends(settings_service),
):
    return resp_200(data=await service.save(body))
