from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import ORJSONResponse

from bisheng.common.errcode.filelib_sync import FilelibSyncError, FilelibSyncMultipartError
from bisheng.common.errcode.inspection_standard_sync import InspectionStandardSyncError
from bisheng.common.schemas.api import resp_200
from bisheng.open_endpoints.api.dependencies import (
    get_filelib_sync_service,
    get_inspection_standard_sync_service,
)
from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import InspectionStandardSyncRequest
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService
from bisheng.open_endpoints.domain.services.inspection_standard_sync_service import InspectionStandardSyncService

router = APIRouter(prefix="/filelib", tags=["OpenAPI", "Knowledge"])


def _error_response(error: FilelibSyncError) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=error.http_status,
        content=error.http_response_payload(),
    )


def _inspection_error_response(error: InspectionStandardSyncError) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=error.http_status,
        content=error.http_response_payload(),
    )


async def _sync_file(
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
            raw_params=params,
            upload_file=file,
        )
        return resp_200(result)
    except FilelibSyncError as exc:
        return _error_response(exc)
    finally:
        await file.close()


@router.post("/file/sync")
async def sync_file(
    file: UploadFile | None = File(default=None),
    params: str | None = Form(default=None),
    service: FilelibSyncService = Depends(get_filelib_sync_service),
) -> Any:
    return await _sync_file(file=file, params=params, service=service)


@router.post("/inspection-standard/sync")
async def sync_inspection_standard(
    body: InspectionStandardSyncRequest,
    service: InspectionStandardSyncService = Depends(get_inspection_standard_sync_service),
) -> Any:
    try:
        result = await service.sync(body)
        return resp_200(result.model_dump())
    except InspectionStandardSyncError as exc:
        return _inspection_error_response(exc)
    except FilelibSyncError as exc:
        return _error_response(exc)
