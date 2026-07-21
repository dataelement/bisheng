from __future__ import annotations

import json

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    PortalPdfArtifactUnavailableError,
    PortalPdfDownloadBusyError,
    PortalPdfDownloadGenerationError,
    PortalPdfDownloadServiceUnavailableError,
    PortalPdfDownloadTimeoutError,
    SpaceFileNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.api.endpoints.knowledge_space import get_file_download


class _PreparedDownload:
    filename = "设备检修规程.pdf"
    size = 9

    def __init__(self) -> None:
        self.closed = False

    async def iter_bytes(self):
        try:
            yield b"%PDF-1.7\n"
        finally:
            self.closed = True


class _PortalPdfDownloadService:
    def __init__(self, *, error=None) -> None:
        self.error = error
        self.calls = []
        self.prepared = _PreparedDownload()

    async def prepare_download(self, request, login_user):
        self.calls.append((request, login_user))
        if self.error is not None:
            raise self.error
        return self.prepared


@pytest.mark.asyncio
async def test_legacy_download_path_returns_watermarked_pdf_without_object_urls() -> None:
    service = _PortalPdfDownloadService()
    login_user = UserPayload(user_id=7, user_name="张三", tenant_id=5)

    response = await get_file_download(
        space_id=12,
        file_id=1580,
        entry_point="bisheng_knowledge_list",
        login_user=login_user,
        svc=service,
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    request, actual_user = service.calls[0]
    assert request.space_id == 12
    assert request.file_id == 1580
    assert request.entry_point.value == "bisheng_knowledge_list"
    assert request.share_access_grant == ""
    assert actual_user is login_user
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == "9"
    assert (
        "filename*=UTF-8''%E8%AE%BE%E5%A4%87%E6%A3%80%E4%BF%AE%E8%A7%84%E7%A8%8B.pdf"
        in response.headers["content-disposition"]
    )
    assert response.headers["cache-control"] == "private, no-store, no-cache, must-revalidate"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert b"original_url" not in body
    assert b"preview_url" not in body
    assert body == b"%PDF-1.7\n"
    assert service.prepared.closed is True


@pytest.mark.asyncio
async def test_legacy_download_path_normalizes_untrusted_entry_point() -> None:
    service = _PortalPdfDownloadService()
    response = await get_file_download(
        space_id=12,
        file_id=1580,
        entry_point="untrusted",
        login_user=UserPayload(user_id=7, user_name="张三", tenant_id=5),
        svc=service,
    )
    await response.body_iterator.aclose()

    request, _ = service.calls[0]
    assert request.entry_point.value == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "http_status", "business_code"),
    [
        (SpacePermissionDeniedError(), 403, 18040),
        (SpaceFileNotFoundError(), 404, 18020),
        (PortalPdfArtifactUnavailableError(), 409, 18085),
        (PortalPdfDownloadBusyError(), 429, 18086),
        (PortalPdfDownloadServiceUnavailableError(), 503, 18090),
        (PortalPdfDownloadTimeoutError(), 504, 18087),
        (PortalPdfDownloadGenerationError(), 500, 18089),
    ],
)
async def test_legacy_download_path_maps_domain_errors(
    error,
    http_status: int,
    business_code: int,
) -> None:
    response = await get_file_download(
        space_id=12,
        file_id=1580,
        entry_point="bisheng_preview",
        login_user=UserPayload(user_id=7, user_name="张三", tenant_id=5),
        svc=_PortalPdfDownloadService(error=error),
    )

    payload = json.loads(response.body)
    assert response.status_code == http_status
    assert payload["status_code"] == business_code
    assert "original_url" not in response.body.decode()
    assert "preview_url" not in response.body.decode()
