from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import ORJSONResponse

from bisheng.common.errcode.filelib_sync import (
    FilelibSyncError,
    FilelibSyncMultipartError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.open_endpoints.api.dependencies import get_filelib_sync_service
from bisheng.open_endpoints.domain.schemas.filelib_sync import FILELIB_SYNC_RULES
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
)

router = APIRouter(prefix="/filelib", tags=["OpenAPI", "Knowledge"])


def _error_response(error: FilelibSyncError) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=error.http_status,
        content={
            "status_code": error.http_status,
            "status_message": error.message,
            "data": {"error_code": error.code},
        },
    )


async def _sync_file(
    endpoint_code: str,
    *,
    file: UploadFile | None,
    params: str | None,
    service: FilelibSyncService,
) -> Any:
    if file is None or params is None:
        if file is not None:
            await file.close()
        return _error_response(FilelibSyncMultipartError(msg="multipart form requires file and params"))
    try:
        result = await service.sync(
            rule=FILELIB_SYNC_RULES[endpoint_code],
            raw_params=params,
            upload_file=file,
        )
        return resp_200(result)
    except FilelibSyncError as exc:
        return _error_response(exc)
    finally:
        await file.close()


@router.post("/file/sync/03")
async def sync_file_03(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("03", file=file, params=params, service=service)


@router.post("/file/sync/04")
async def sync_file_04(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("04", file=file, params=params, service=service)


@router.post("/file/sync/05")
async def sync_file_05(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("05", file=file, params=params, service=service)


@router.post("/file/sync/06")
async def sync_file_06(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("06", file=file, params=params, service=service)


@router.post("/file/sync/07")
async def sync_file_07(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("07", file=file, params=params, service=service)


@router.post("/file/sync/09")
async def sync_file_09(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("09", file=file, params=params, service=service)


@router.post("/file/sync/10")
async def sync_file_10(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("10", file=file, params=params, service=service)


@router.post("/file/sync/11")
async def sync_file_11(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("11", file=file, params=params, service=service)


@router.post("/file/sync/12")
async def sync_file_12(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("12", file=file, params=params, service=service)


@router.post("/file/sync/14")
async def sync_file_14(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("14", file=file, params=params, service=service)


@router.post("/file/sync/15")
async def sync_file_15(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file("15", file=file, params=params, service=service)
