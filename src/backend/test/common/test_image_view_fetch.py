"""Unit tests for fetch_and_encode (F061 T003).

Covers AC: AC-06, AC-15
"""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from bisheng.common.image_view.fetch import fetch_and_encode


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _data_uri_size(data_uri: str) -> tuple[int, int]:
    header, b64 = data_uri.split(",", 1)
    raw = base64.b64decode(b64)
    with Image.open(io.BytesIO(raw)) as image:
        return image.size


@pytest.fixture
def fetch_env(monkeypatch):
    get_object = AsyncMock()
    download = AsyncMock()
    monkeypatch.setattr("bisheng.common.image_view.fetch._public_bucket", lambda: "bisheng")
    monkeypatch.setattr("bisheng.common.image_view.fetch._share_hosts", lambda: {"minio.example:9000"})
    monkeypatch.setattr("bisheng.common.image_view.fetch._info_hosts", lambda: {"info.example"})
    monkeypatch.setattr("bisheng.common.image_view.fetch._get_object", get_object)
    monkeypatch.setattr("bisheng.common.image_view.fetch._async_file_download", download)
    return get_object, download


@pytest.mark.asyncio
async def test_internal_knowledge_path_uses_minio_get_object(fetch_env):
    get_object, download = fetch_env
    get_object.return_value = _png_bytes(800, 400)

    result = await fetch_and_encode("/bisheng/knowledge/images/1/2/chart.png")

    assert result.ok is True
    assert result.data_uri.startswith("data:image/png;base64,")
    assert _data_uri_size(result.data_uri) == (512, 256)
    get_object.assert_awaited_once_with("bisheng", "knowledge/images/1/2/chart.png")
    download.assert_not_called()


@pytest.mark.asyncio
async def test_sharepoint_http_uses_download(fetch_env):
    get_object, download = fetch_env
    download.return_value = _png_bytes(100, 80)

    result = await fetch_and_encode("https://minio.example:9000/bisheng/knowledge/images/1/2/a.png")

    assert result.ok is True
    assert _data_uri_size(result.data_uri) == (100, 80)
    download.assert_awaited_once()
    get_object.assert_not_called()


@pytest.mark.asyncio
async def test_intelligence_center_http_uses_download(fetch_env):
    _, download = fetch_env
    download.return_value = _png_bytes(64, 64)

    result = await fetch_and_encode("https://info.example/articles/pic.png")

    assert result.ok is True
    download.assert_awaited_once()


@pytest.mark.asyncio
async def test_signed_relative_path_uses_download(fetch_env):
    _, download = fetch_env
    download.return_value = _png_bytes(32, 32)

    result = await fetch_and_encode("/bisheng/knowledge/images/1/2/a.png?X-Amz-Algorithm=AWS4-HMAC-SHA256")

    assert result.ok is True
    download.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_host_fails_without_raising_or_downloading(fetch_env):
    get_object, download = fetch_env

    result = await fetch_and_encode("https://evil.example/secret.png")

    assert result.ok is False
    assert result.reason == "host"
    assert result.error
    get_object.assert_not_called()
    download.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_follow_redirect_off_whitelist(fetch_env):
    _, download = fetch_env

    result = await fetch_and_encode("https://evil.example/redirected.png")

    assert result.ok is False
    download.assert_not_called()


@pytest.mark.asyncio
async def test_smaller_than_512_is_not_upscaled(fetch_env):
    get_object, _ = fetch_env
    get_object.return_value = _png_bytes(200, 100)

    result = await fetch_and_encode("/bisheng/knowledge/images/1/2/small.png")

    assert result.ok is True
    assert _data_uri_size(result.data_uri) == (200, 100)


@pytest.mark.asyncio
async def test_tiny_image_is_rejected_without_data_uri(fetch_env):
    get_object, _ = fetch_env
    get_object.return_value = _png_bytes(13, 17)

    result = await fetch_and_encode("/bisheng/knowledge/images/1/6/icon.jpeg")

    assert result.ok is False
    assert result.reason == "too_small"
    assert result.data_uri is None


@pytest.mark.asyncio
async def test_get_object_failure_returns_error(fetch_env):
    get_object, _ = fetch_env
    get_object.side_effect = RuntimeError("NoSuchKey")

    result = await fetch_and_encode("/bisheng/knowledge/images/1/2/missing.png")

    assert result.ok is False
    assert result.reason == "path"
    assert result.error == "This image is not available."
    assert result.data_uri is None


@pytest.mark.asyncio
async def test_decode_failure_returns_error(fetch_env):
    get_object, _ = fetch_env
    get_object.return_value = b"not-an-image"

    result = await fetch_and_encode("/bisheng/knowledge/images/1/2/bad.png")

    assert result.ok is False
    assert result.reason == "decode"
    assert result.data_uri is None
