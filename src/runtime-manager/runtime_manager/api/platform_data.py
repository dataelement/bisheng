"""Existing owner-authorized SQLite protocol, executed with a one-app filesystem view."""

import asyncio
import base64
import binascii
import copy
import hashlib
import json
import re
import shutil
from threading import Lock

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from runtime_manager.api.operations import authorized, executor
from runtime_manager.appdb import DataBusyError
from runtime_manager.data_executor import DataExecutor


class _KubernetesWorker:
    def __init__(self, service, operation, ticket):
        self.service, self.operation, self.ticket = service, operation, ticket

    def call(self, app_id, action, parameters):
        if app_id != self.operation["app_id"]:
            raise DataBusyError("Application data scope mismatch")
        operation = copy.deepcopy(self.operation)
        operation["data_grant"] = self.ticket
        return self.service.runtime.data(operation, action, parameters)


async def scoped_data(request: Request):
    await authorized(request)
    service = executor()
    app_id = request.path_params["app_id"]
    if service.config.executor_kind == "kubernetes":
        try:
            raw = request.headers.get("X-Runtime-Data-Grant", "")
            if not raw or len(raw) > 8192:
                raise ValueError()
            ticket = json.loads(base64.b64decode(raw, altchars=b"-_", validate=True))
            if not isinstance(ticket, dict) or set(ticket) != {"key_id", "claims", "signature"}:
                raise ValueError()
            operation_id = ticket["claims"]["operation_id"]
            if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", operation_id):
                raise ValueError()
            operation = await asyncio.to_thread(service.platform.operation, operation_id)
            if (
                operation["kind"] != "data"
                or operation["app_id"] != app_id
                or operation["node_id"] != service.config.node_id
            ):
                raise ValueError()
        except (ValueError, TypeError, KeyError, binascii.Error):
            raise DataBusyError("Owner data grant is required") from None
        # The durable backend mutex and helper flock serialize this path. The
        # operation thread holds the local app lock while awaiting this RPC.
        yield _KubernetesWorker(service, operation, ticket)
        return
    scope = await asyncio.to_thread(service.platform.application, app_id)
    if scope.get("node_id") != service.config.node_id:
        raise DataBusyError("Application belongs to a different execution node")
    if scope.get("phase") == "maintenance" and request.method != "GET":
        raise DataBusyError("Application data is under maintenance")
    with service._guard:
        lock = service._apps.setdefault(app_id, Lock())
    if not lock.acquire(blocking=False):
        raise DataBusyError("Application data operation is busy; please retry")
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

    def digest():
        result = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                result.update(chunk)
        return result.hexdigest()

    return FileResponse(
        path,
        headers={"X-Content-Sha256": await asyncio.to_thread(digest)},
        media_type="text/csv",
        filename=table + ".csv",
        background=BackgroundTask(shutil.rmtree, root, ignore_errors=True),
    )


@router.post("/result")
async def result(app_id: str, parameters: dict = Body(...), worker=Depends(scoped_data)):
    return await asyncio.to_thread(worker.call, app_id, "result", parameters)
