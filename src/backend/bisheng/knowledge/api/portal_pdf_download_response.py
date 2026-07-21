from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi.responses import JSONResponse, StreamingResponse

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    PortalPdfArtifactUnavailableError,
    PortalPdfDownloadBusyError,
    PortalPdfDownloadGenerationError,
    PortalPdfDownloadServiceUnavailableError,
    PortalPdfDownloadTimeoutError,
    PortalShareDownloadGrantInvalidError,
    SpaceFileNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import PortalPdfDownloadRequest

_PORTAL_PDF_DOWNLOAD_STATUS = {
    SpacePermissionDeniedError: 403,
    PortalShareDownloadGrantInvalidError: 403,
    SpaceNotFoundError: 404,
    SpaceFileNotFoundError: 404,
    PortalPdfArtifactUnavailableError: 409,
    PortalPdfDownloadBusyError: 429,
    PortalPdfDownloadServiceUnavailableError: 503,
    PortalPdfDownloadTimeoutError: 504,
    PortalPdfDownloadGenerationError: 500,
}


def _error_response(error: BaseErrorCode) -> JSONResponse:
    status_code = next(
        (status for error_type, status in _PORTAL_PDF_DOWNLOAD_STATUS.items() if isinstance(error, error_type)),
        500,
    )
    return JSONResponse(status_code=status_code, content=error.to_dict(data={}))


async def prepare_portal_pdf_download_response(
    *,
    service: Any,
    request: PortalPdfDownloadRequest,
    login_user: Any,
) -> StreamingResponse | JSONResponse:
    try:
        prepared = await service.prepare_download(request, login_user)
    except BaseErrorCode as error:
        return _error_response(error)

    encoded_filename = quote(prepared.filename, safe="")
    headers = {
        "Content-Disposition": f"attachment; filename=\"document.pdf\"; filename*=UTF-8''{encoded_filename}",
        "Content-Length": str(prepared.size),
        "Cache-Control": "private, no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        prepared.iter_bytes(),
        media_type="application/pdf",
        headers=headers,
    )
