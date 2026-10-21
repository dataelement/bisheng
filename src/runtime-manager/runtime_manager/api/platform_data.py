"""Existing owner-authorized SQLite protocol, executed with a one-app filesystem view."""

import asyncio
import shutil
from threading import Lock

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from runtime_manager.api.operations import authorized, executor
from runtime_manager.appdb import DataBusyError
from runtime_manager.data_executor import DataExecutor


async def scoped_data(request: Request):
    await authorized(request)
    service = executor()
    app_id = request.path_params["app_id"]
    scope = await asyncio.to_thread(service.platform.application, app_id)
    if scope.get("node_id") != service.config.node_id:
        raise DataBusyError("Application belongs to a different execution node")
    if scope.get("phase") == "maintenance" and request.method != "GET":
        raise DataBusyError("Application data is under maintenance")
    with service._guard:
        lock = service._apps.setdefault(app_id, Lock())
    if not lock.acquire(blocking=False):
        raise DataBusyError("Application data is under maintenance")
    try:
        yield DataExecutor(
            service.config.with_overrides(
                data_helper_uid=int(scope.get("runtime_user", {}).get("uid", 10001)),
                data_helper_gid=int(scope.get("runtime_user", {}).get("gid", 10001)),
            ),
            service.docker,
        )
    finally:
        lock.release()


router = APIRouter(prefix="/v2/apps/{app_id}/db")


@router.get("/tables")
async def tables(app_id: str, worker=Depends(scoped_data)):
    return await asyncio.to_thread(worker.call, app_id, "tables", {})


@router.get("/tables/{table}/schema")
async def schema(app_id: str, table: str, worker=Depends(scoped_data)):
    return await asyncio.to_thread(worker.call, app_id, "schema", {"table": table})


@router.get("/tables/{table}/rows")
async def rows(
    app_id: str, table: str, page: int = 1, size: int = 50, order: str | None = None, worker=Depends(scoped_data)
):
    return await asyncio.to_thread(
        worker.call, app_id, "rows", {"table": table, "page": page, "size": size, "order": order}
    )


@router.patch("/tables/{table}/rows/{key}")
async def update(app_id: str, table: str, key: str, values: dict = Body(..., embed=True), worker=Depends(scoped_data)):
    return await asyncio.to_thread(worker.call, app_id, "update", {"table": table, "key": key, "values": values})


@router.get("/export")
async def export(app_id: str, table: str, worker=Depends(scoped_data)):
    path, root = await asyncio.to_thread(worker.call, app_id, "export", {"table": table})
    return FileResponse(
        path,
        media_type="text/csv",
        filename=table + ".csv",
        background=BackgroundTask(shutil.rmtree, root, ignore_errors=True),
    )
