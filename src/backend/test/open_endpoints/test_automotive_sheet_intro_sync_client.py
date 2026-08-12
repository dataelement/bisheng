from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroUpstreamError
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client import (
    AUTOMOTIVE_SHEET_INTRO_MAX_PDF_BYTES,
    AutomotiveSheetIntroSyncClient,
)

_PDF_BODY = b"%PDF-1.4 test"


def _mock_response(*, status_code: int = 200, content: bytes = _PDF_BODY, content_type: str = "application/pdf"):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = content
    response.headers = {"content-type": content_type}
    return response


@pytest.mark.asyncio
async def test_fetch_pdf_success():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response())

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        body = await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)

    assert body == _PDF_BODY
    client_cls.assert_called_once_with(timeout=httpx.Timeout(30.0), follow_redirects=True, verify=True)
    mock_http.request.assert_awaited_once_with("GET", "https://example.com/a.pdf")


@pytest.mark.asyncio
async def test_fetch_pdf_can_disable_ssl_verify():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response())

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        await client.fetch_pdf(
            api_url="https://192.168.1.1/a.pdf",
            method="GET",
            timeout_seconds=30,
            api_ssl_verify=False,
        )

    client_cls.assert_called_once_with(timeout=httpx.Timeout(30.0), follow_redirects=True, verify=False)


@pytest.mark.asyncio
async def test_fetch_pdf_accepts_octet_stream_when_magic_valid():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(content_type="application/octet-stream"))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        body = await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)

    assert body == _PDF_BODY


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_non_pdf_content_type():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(content_type="text/html", content=b"<html"))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="not application/pdf"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_empty_body():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(content=b""))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="empty"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_invalid_magic():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(content=b"NOTPDF"))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="magic"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_5xx():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(status_code=503, content=b"err"))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="status 503"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_timeout():
    client = AutomotiveSheetIntroSyncClient()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="timed out"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="POST", timeout_seconds=5)


@pytest.mark.asyncio
async def test_fetch_pdf_rejects_oversized_body():
    client = AutomotiveSheetIntroSyncClient()
    oversized = b"%PDF-" + b"x" * (AUTOMOTIVE_SHEET_INTRO_MAX_PDF_BYTES - 5 + 1)
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_mock_response(content=oversized))

    with patch("bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = mock_http
        with pytest.raises(AutomotiveSheetIntroUpstreamError, match="size limit"):
            await client.fetch_pdf(api_url="https://example.com/a.pdf", method="GET", timeout_seconds=30)
