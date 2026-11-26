"""Manage Desktop access addresses within the configured deployment boundary."""

from fastapi import APIRouter, Depends, Request, Response

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshDshDisabledError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_settings
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.settings import DshManagementSettings
from bisheng.dsh.domain.services.settings import DshSettingsService
from bisheng.dsh.work_mcp import work_transport_security

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
        return resp_200(data={**DshManagementSettings().model_dump(), "management_enabled": False, "enabled": False})
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
    request: Request,
    user=Depends(settings_admin),
    config=Depends(require_deployment),
    service: DshSettingsService = Depends(settings_service),
):
    previous_url = await service.platform_public_url(config.platform_public_url)
    saved = await service.save(body)
    public_url = saved.platform_public_url or config.platform_public_url
    if public_url != previous_url:
        _apply_public_url(request.app, public_url)
    return resp_200(data=saved)


def _apply_public_url(app, public_url: str | None) -> None:
    """Apply a saved origin to the runtimes that captured the previous value.

    The DSH runtime is rebuilt lazily on its next request; the Work MCP session
    manager is long-lived, so its transport security is replaced in place.
    """
    app.state.dsh_runtime = None
    manager = getattr(app.state, "work_mcp_runtime", None)
    if manager is not None:
        manager.security_settings = work_transport_security(public_url)
