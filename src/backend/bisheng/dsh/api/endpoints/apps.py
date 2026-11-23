"""Hosted app Desktop endpoints authenticated by the existing Desktop session.

Only the catalog is served (v3.1.0-alpha1 F001). Desktop opens a hosted app
with its embedded web session, so no Desktop-only ticket, session, publish or
source download exists any more. The retired routes stay as shells that answer
16149: BISHENG Desktop 1.3.0 still calls them and shows ``status_message``.
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from bisheng.app_runtime.domain.repositories.desktop_app_repository import DesktopAppRepository
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.common.errcode.app_factory import AppDesktopClientUpgradeRequiredError
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.schemas.api import resp_200
from bisheng.common.services.config_service import settings
from bisheng.dsh.api.dependencies import desktop_principal, get_runtime
from bisheng.dsh.api.responses import DshRoute


class DesktopAppsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def respond(request):
            request.state.request_id = str(uuid4())
            try:
                response = await handler(request)
            except RequestValidationError:
                response = DshRoute.error(DshInvalidRequestError(), request.state.request_id)
            except BaseErrorCode as error:
                if hasattr(error, "ClientCode"):
                    response = DshRoute.error(error, request.state.request_id)
                else:
                    # Plain envelope on purpose: 1.3.0 reads status_message from it (design §5 坑 3).
                    response = JSONResponse(error.to_dict(), status_code=400)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Request-ID"] = request.state.request_id
            return response

        return respond


router = APIRouter(prefix="/dsh/apps", route_class=DesktopAppsRoute)


def app_service(runtime=Depends(get_runtime)):
    return DesktopAppsService(runtime, DesktopAppRepository())


@router.get("")
async def list_apps(
    principal=Depends(desktop_principal),
    service=Depends(app_service),
    cursor: str | None = Query(default=None, max_length=36),
    managed: bool = False,
):
    if managed:
        # Only the retired Agent development flow listed editable apps.
        raise AppDesktopClientUpgradeRequiredError()
    runtime_enabled = bool(settings.app_runtime.enabled)
    if not runtime_enabled:
        await service.actor(principal)
        return resp_200(data={"items": [], "next_cursor": None, "runtime_enabled": False})
    page = await service.page(principal, after=cursor)
    return resp_200(data={**page, "runtime_enabled": True})


@router.post("/{app_id}/launch")
async def launch(app_id: str, principal=Depends(desktop_principal)):
    raise AppDesktopClientUpgradeRequiredError()


@router.get("/deploy-limits")
async def limits(principal=Depends(desktop_principal)):
    raise AppDesktopClientUpgradeRequiredError()


@router.post("/deploy")
async def deploy(principal=Depends(desktop_principal)):
    raise AppDesktopClientUpgradeRequiredError()


@router.get("/{app_id}/deployments/{deployment_id}")
async def progress(app_id: str, deployment_id: str, principal=Depends(desktop_principal)):
    raise AppDesktopClientUpgradeRequiredError()


@router.get("/{app_id}/versions/{version_id}/source")
async def source(app_id: str, version_id: str, principal=Depends(desktop_principal)):
    raise AppDesktopClientUpgradeRequiredError()
