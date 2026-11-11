"""Hosted app Desktop endpoints authenticated by the existing Desktop session."""

from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.desktop_publish_service import DesktopPublishService
from bisheng.app_publish.domain.services.source_export import source_export
from bisheng.app_runtime.domain.repositories.desktop_app_repository import DesktopAppRepository
from bisheng.app_runtime.domain.repositories.desktop_app_sessions import desktop_app_sessions
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import desktop_principal, get_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.services.access import principal_scope


class DesktopAppsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def respond(request):
            request.state.request_id = str(uuid4())
            try:
                # Authenticate before FastAPI parses a potentially large multipart body.
                if request.url.path.endswith("/dsh/apps/deploy"):
                    from bisheng.dsh.api.dependencies import get_settings

                    runtime = await get_runtime(request, get_settings())
                    await desktop_principal(request, runtime)
                response = await handler(request)
            except RequestValidationError:
                response = DshRoute.error(DshInvalidRequestError(), request.state.request_id)
            except BaseErrorCode as error:
                if hasattr(error, "ClientCode"):
                    response = DshRoute.error(error, request.state.request_id)
                else:
                    response = JSONResponse(error.to_dict(), status_code=400)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Request-ID"] = request.state.request_id
            return response

        return respond


router = APIRouter(prefix="/dsh/apps", route_class=DesktopAppsRoute)


def app_service(runtime=Depends(get_runtime), sessions=Depends(desktop_app_sessions)):
    return DesktopAppsService(runtime, DesktopAppRepository(), sessions)


@router.get("")
async def list_apps(
    principal=Depends(desktop_principal),
    service=Depends(app_service),
    cursor: str | None = Query(default=None, max_length=36),
    managed: bool = False,
):
    return resp_200(data=await service.page(principal, after=cursor, managed=managed))


@router.post("/{app_id}/launch")
async def launch(app_id: str, principal=Depends(desktop_principal), service=Depends(app_service)):
    return resp_200(data=await service.launch(principal, app_id))


@router.get("/deploy-limits")
async def limits(principal=Depends(desktop_principal), service=Depends(app_service)):
    await service.actor(principal)
    return resp_200(data=package_service.deploy_limits())


@router.post("/deploy")
async def deploy(
    package: UploadFile = File(...),
    app_id: str | None = Form(default=None),
    base_version_id: str | None = Form(default=None),
    release_notes: str | None = Form(default=None),
    confirm_schema_change: bool = Form(default=False),
    principal=Depends(desktop_principal),
    service=Depends(app_service),
):
    spooled = await package_service.spool_upload(package)
    try:
        result = await DesktopPublishService(service).accept(
            principal,
            spooled,
            app_id=app_id,
            base_version_id=base_version_id,
            release_notes=release_notes,
            confirm_schema_change=confirm_schema_change,
        )
    finally:
        spooled.unlink(missing_ok=True)
    return resp_200(
        data={"app_id": result.app_id, "deployment_id": result.deployment_id, "version_id": result.version_id}
    )


@router.get("/{app_id}/deployments/{deployment_id}")
async def progress(app_id: str, deployment_id: str, principal=Depends(desktop_principal), service=Depends(app_service)):
    return resp_200(data=await DesktopPublishService(service).status(principal, app_id, deployment_id))


@router.get("/{app_id}/versions/{version_id}/source")
async def source(app_id: str, version_id: str, principal=Depends(desktop_principal), service=Depends(app_service)):
    await service.require(principal, app_id, "edit")
    with principal_scope(principal):
        archive, digest = await source_export(app_id, version_id)
    return Response(
        archive,
        media_type="application/gzip",
        headers={
            "Cache-Control": "no-store",
            "X-Source-SHA256": digest,
            "X-App-Id": app_id,
            "X-Base-Version-Id": version_id,
            "Content-Disposition": 'attachment; filename="workbench-source.tar.gz"',
        },
    )
