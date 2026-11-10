from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.dsh_market import (
    MarketBundleError,
    MarketConflictError,
    MarketNotFoundError,
    MarketWorkbenchArtifactError,
    MarketWorkbenchBundleError,
    MarketWorkbenchConflictError,
    MarketWorkbenchNotFoundError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.dsh_market.domain.bundle import MAX_UPLOAD_BYTES, BundleError
from bisheng.dsh_market.domain.repository import ConflictError
from bisheng.dsh_market.domain.workbench_bundle import (
    MAX_WORKBENCH_UPLOAD_BYTES,
    WorkbenchBundleError,
)
from bisheng.dsh_market.domain.workbench_repository import WorkbenchConflictError
from bisheng.dsh_market.domain.workbench_service import WorkbenchArtifactError
from bisheng.dsh_market.infrastructure import get_market_service, get_workbench_service

from .auth import MarketActor, market_actor, market_admin

router = APIRouter(prefix="/dsh/market", tags=["DSH enterprise plugin market"])


async def call(function, *args, **kwargs):
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except BundleError as exc:
        raise MarketBundleError(msg=str(exc)) from exc
    except ConflictError as exc:
        raise MarketConflictError() from exc
    except LookupError as exc:
        raise MarketNotFoundError() from exc


async def call_workbench(function, *args, **kwargs):
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except WorkbenchBundleError as exc:
        raise MarketWorkbenchBundleError(msg=str(exc)) from exc
    except WorkbenchConflictError as exc:
        raise MarketWorkbenchConflictError(msg=str(exc)) from exc
    except WorkbenchArtifactError as exc:
        raise MarketWorkbenchArtifactError(msg=str(exc)) from exc
    except LookupError as exc:
        raise MarketWorkbenchNotFoundError() from exc


class ChangeRequest(BaseModel):
    revision: int = Field(ge=1)
    action: Literal["publish", "unpublish", "disable"]
    version_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class InstalledPlugin(BaseModel):
    plugin_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    version_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: Literal["enabled", "disabled", "pending_restart", "failed", "uninstalled"]
    revision: int = Field(ge=0)


class DeviceReport(BaseModel):
    device_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,64}$")
    plugins: list[InstalledPlugin] = Field(max_length=500)


class InstallPolicyChange(BaseModel):
    field: Literal["allow_third_party_plugins", "allow_third_party_workbenches"]
    allowed: bool


@router.get("/capabilities")
async def capabilities(
    response: Response, actor: MarketActor = Depends(market_actor), service=Depends(get_market_service)
):
    response.headers["Cache-Control"] = "no-store"
    policy = await call(service.install_policy, actor.tenant_id)
    return resp_200(
        {
            "enabled": True,
            "contract_version": 2,
            "tenant_id": str(actor.tenant_id),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "sync_seconds": 60,
            "allow_third_party_plugins": policy["allow_third_party_plugins"],
            "allow_third_party_workbenches": policy["allow_third_party_workbenches"],
        }
    )


@router.get("/admin/install-policy")
async def read_install_policy(actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)):
    return resp_200(await call(service.install_policy, actor.tenant_id))


@router.patch("/admin/install-policy")
async def change_install_policy(
    body: InstallPolicyChange, actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)
):
    return resp_200(await call(service.set_install_policy, actor.tenant_id, body.field, body.allowed))


@router.get("/catalog")
async def catalog(
    response: Response,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_market_service),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(await call(service.list_plugins, actor.tenant_id, q.strip(), page=page, size=size, employee=True))


@router.get("/plugins/{plugin_id}/versions/{version_id}/artifact")
async def artifact(
    plugin_id: str, version_id: str, actor: MarketActor = Depends(market_actor), service=Depends(get_market_service)
):
    data, digest = await call(service.download, actor.tenant_id, plugin_id, version_id)
    gzip_archive = data.startswith(b"\x1f\x8b")
    return Response(
        data,
        media_type="application/gzip" if gzip_archive else "application/zip",
        headers={
            "ETag": f'"{digest}"',
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="plugin.tgz"'
            if gzip_archive
            else 'attachment; filename="plugin.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sync")
async def sync(
    report: DeviceReport,
    response: Response,
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_market_service),
):
    response.headers["Cache-Control"] = "no-store"
    receipt = await call(
        service.synchronize,
        actor.tenant_id,
        actor.user_id,
        report.device_id,
        [v.model_dump() for v in report.plugins],
    )
    return resp_200(receipt)


@router.get("/admin/plugins")
async def plugins(
    q: str = Query(default="", max_length=200),
    status: Literal["all", "published", "unpublished"] = "all",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: MarketActor = Depends(market_admin),
    service=Depends(get_market_service),
):
    return resp_200(await call(service.list_plugins, actor.tenant_id, q.strip(), status, page, size))


@router.get("/admin/context")
async def admin_context(actor: MarketActor = Depends(market_admin)):
    return resp_200({"tenant_id": actor.tenant_id})


@router.get("/admin/plugins/{plugin_id}")
async def detail(plugin_id: str, actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)):
    return resp_200(await call(service.detail, actor.tenant_id, plugin_id))


@router.delete("/admin/plugins/{plugin_id}")
async def delete_plugin(
    plugin_id: str,
    revision: int = Query(ge=1),
    actor: MarketActor = Depends(market_admin),
    service=Depends(get_market_service),
):
    return resp_200(await call(service.change, actor.tenant_id, actor.user_id, plugin_id, revision, "delete"))


@router.post("/admin/plugins/{plugin_id}/transition")
async def change(
    plugin_id: str, body: ChangeRequest, actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)
):
    return resp_200(
        await call(
            service.change, actor.tenant_id, actor.user_id, plugin_id, body.revision, body.action, body.version_id
        )
    )


@router.post("/admin/imports/preview")
async def preview_bundle(
    file: UploadFile = File(), actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)
):
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise MarketBundleError(msg="Upload exceeds 512 MiB")
        return resp_200(await call(service.preview_bundle, actor.tenant_id, data))
    finally:
        await file.close()


@router.post("/admin/imports")
async def import_bundle(
    file: UploadFile = File(), actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)
):
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise MarketBundleError(msg="Upload exceeds 512 MiB")
        return resp_200(await call(service.import_bundle, actor.tenant_id, actor.user_id, data))
    finally:
        await file.close()


@router.get("/admin/imports")
async def imports(actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)):
    return resp_200(await call(service.imports, actor.tenant_id))


@router.post("/admin/imports/{task_id}/resume")
async def resume_import(task_id: str, actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)):
    return resp_200(await call(service.validate_import, actor.tenant_id, task_id))


@router.get("/admin/devices")
async def devices(actor: MarketActor = Depends(market_admin), service=Depends(get_market_service)):
    return resp_200(await call(service.devices, actor.tenant_id))


@router.post("/admin/workbenches/imports/preview")
async def preview_workbench(
    file: UploadFile = File(), actor: MarketActor = Depends(market_admin), service=Depends(get_workbench_service)
):
    try:
        data = await file.read(MAX_WORKBENCH_UPLOAD_BYTES + 1)
        return resp_200(await call_workbench(service.preview, actor.tenant_id, data))
    finally:
        await file.close()


@router.post("/admin/workbenches/imports")
async def import_workbench(
    file: UploadFile = File(),
    display_name: str | None = Form(default=None),
    actor: MarketActor = Depends(market_admin),
    service=Depends(get_workbench_service),
):
    try:
        data = await file.read(MAX_WORKBENCH_UPLOAD_BYTES + 1)
        return resp_200(await call_workbench(service.import_bundle, actor.tenant_id, actor.user_id, data, display_name))
    finally:
        await file.close()


@router.get("/admin/workbenches/imports")
async def workbench_imports(actor: MarketActor = Depends(market_admin), service=Depends(get_workbench_service)):
    return resp_200(await call_workbench(service.imports, actor.tenant_id))


@router.post("/admin/workbenches/imports/{task_id}/resume")
async def resume_workbench_import(
    task_id: str, actor: MarketActor = Depends(market_admin), service=Depends(get_workbench_service)
):
    return resp_200(await call_workbench(service.resume, actor.tenant_id, task_id))


@router.get("/admin/workbenches")
async def admin_workbenches(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: MarketActor = Depends(market_admin),
    service=Depends(get_workbench_service),
):
    return resp_200(await call_workbench(service.list, actor.tenant_id, page, size))


@router.get("/workbenches")
async def workbenches(
    response: Response,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_workbench_service),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(await call_workbench(service.list, actor.tenant_id, page, size))


@router.get("/workbenches/{workbench_id}")
async def workbench_detail(
    workbench_id: str,
    response: Response,
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_workbench_service),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(await call_workbench(service.detail, actor.tenant_id, workbench_id))


@router.get("/workbenches/{workbench_id}/versions/{version_id}/artifact")
async def workbench_artifact(
    workbench_id: str,
    version_id: str,
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_workbench_service),
):
    data, digest = await call_workbench(service.download, actor.tenant_id, workbench_id, version_id)
    return Response(
        data,
        media_type="application/gzip",
        headers={
            "ETag": f'"{digest}"',
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="workbench.tgz"',
            "X-Content-Type-Options": "nosniff",
        },
    )
