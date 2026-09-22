import os
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.dsh_market import MarketBundleError, MarketConflictError, MarketNotFoundError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh_market.domain.bundle import MAX_UPLOAD_BYTES, BundleError
from bisheng.dsh_market.domain.lease import verification_key
from bisheng.dsh_market.domain.repository import ConflictError
from bisheng.dsh_market.infrastructure import get_market_service

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


@router.get("/capabilities")
async def capabilities(actor: MarketActor = Depends(market_actor)):
    enabled = bool(os.environ.get("BISHENG_DSH_MARKET_SIGNING_KEY"))
    return resp_200(
        {
            "enabled": enabled,
            "public_key": verification_key() if enabled else None,
            "contract_version": 1,
            "tenant_id": str(actor.tenant_id),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "lease_seconds": 3600,
            "sync_seconds": 60,
        }
    )


@router.get("/catalog")
async def catalog(
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: MarketActor = Depends(market_actor),
    service=Depends(get_market_service),
):
    return resp_200(await call(service.list_plugins, actor.tenant_id, q.strip(), page=page, size=size, employee=True))


@router.get("/plugins/{plugin_id}/versions/{version_id}/artifact")
async def artifact(
    plugin_id: str, version_id: str, actor: MarketActor = Depends(market_actor), service=Depends(get_market_service)
):
    data, digest = await call(service.download, actor.tenant_id, plugin_id, version_id)
    return Response(
        data,
        media_type="application/zip",
        headers={
            "ETag": f'"{digest}"',
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="plugin.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sync")
async def sync(report: DeviceReport, actor: MarketActor = Depends(market_actor), service=Depends(get_market_service)):
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
