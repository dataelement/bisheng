"""Real HTTP compression and runtime OCR configuration regressions."""

from __future__ import annotations

import asyncio
import base64
import gzip
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bisheng.core.config.settings import KnowledgeConf
from bisheng.eplus.domain.services.media_service import EPlusMediaService, MediaIngestionError
from bisheng.eplus.infrastructure.media_store import DailyChatImageTextExtractor, SecureEPlusMediaDownloader

PNG = b"\x89PNG\r\n\x1a\n" + b"test image pixels"


class _MemoryStore:
    def __init__(self):
        self.objects = {}

    async def put(self, *, object_key, data, content_type):
        self.objects[object_key] = data


@asynccontextmanager
async def _media_response(body: bytes, *, compressed: bool):
    async def handler(request):
        headers = {"Content-Encoding": "gzip"} if compressed else {}
        response = web.StreamResponse(headers=headers)
        await response.prepare(request)
        await response.write(body)
        # Keep the streaming response open while the client captures its peer.
        await asyncio.sleep(0.01)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/image", handler)
    async with TestServer(app) as server:
        yield str(server.make_url("/image"))


@pytest.mark.parametrize("compressed", [False, True])
async def test_downloaded_media_is_decrypted_and_persisted_with_or_without_http_gzip(compressed):
    key = bytes(range(32))
    padding = 32 - len(PNG) % 32
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    ciphertext = encryptor.update(PNG + bytes([padding]) * padding) + encryptor.finalize()
    body = gzip.compress(ciphertext) if compressed else ciphertext
    store = _MemoryStore()
    service = EPlusMediaService(downloader=SecureEPlusMediaDownloader(), store=store)

    async with _media_response(body, compressed=compressed) as url:
        ref = await service.ingest_image(
            tenant_id=9,
            url=url,
            aes_key=base64.b64encode(key).decode().rstrip("="),
            allowed_hosts=(),
            ca_pem=None,
        )

    assert ref.mime_type == "image/png"
    assert ref.size == len(PNG)
    assert store.objects[ref.object_key] == PNG


async def test_gzip_expansion_cannot_bypass_download_size_limit():
    body = gzip.compress(b"x" * 1024)
    assert len(body) < 512
    async with _media_response(body, compressed=True) as url:
        with pytest.raises(MediaIngestionError, match="too large"):
            await SecureEPlusMediaDownloader().download(url, ca_pem=None, timeout_seconds=5, max_bytes=512)


@pytest.mark.parametrize(
    ("provider", "configured", "expected"),
    [
        ("paddle_ocr", True, True),
        ("paddle_ocr", False, False),
        ("mineru", True, True),
        ("etl4lm", True, True),
    ],
)
def test_image_text_extractor_reads_active_runtime_knowledge_configuration(monkeypatch, provider, configured, expected):
    configuration = KnowledgeConf(
        loader_provider=provider,
        **{provider: {"url": "http://ocr.example.test/parse" if configured else ""}},
    )
    monkeypatch.setattr(
        "bisheng.eplus.infrastructure.media_store.settings",
        SimpleNamespace(get_knowledge=lambda: configuration),
    )

    assert DailyChatImageTextExtractor().available is expected
