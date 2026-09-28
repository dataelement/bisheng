from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from bisheng.eplus.domain.schemas.protocol import EPlusContentBlock, EPlusContentKind
from bisheng.eplus.domain.services.media_service import (
    DownloadedEncryptedMedia,
    EPlusMediaService,
    MediaIngestionError,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


class FakeDownloader:
    def __init__(self, payload: DownloadedEncryptedMedia | Exception) -> None:
        self.payload = payload
        self.calls = []

    async def download(self, url: str, *, ca_pem: bytes | None, timeout_seconds: float, max_bytes: int):
        self.calls.append((url, ca_pem, timeout_seconds, max_bytes))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        self.objects[object_key] = data

    async def get(self, *, object_key: str) -> bytes:
        return self.objects[object_key]


@dataclass
class FakeExtractor:
    available: bool
    text: str = "OCR result"

    async def extract(self, *, data: bytes, mime_type: str, user_id: int) -> str:
        assert data == PNG
        return self.text


def _download(*, peer="10.0.0.8", resolved=("10.0.0.8",), redirected=False, body=b"encrypted"):
    return DownloadedEncryptedMedia(
        ciphertext=body,
        resolved_ips=resolved,
        peer_ip=peer,
        redirected=redirected,
    )


def _service(payload=None, *, extractor=None):
    store = MemoryStore()
    downloader = FakeDownloader(payload or _download())
    service = EPlusMediaService(downloader=downloader, store=store, text_extractor=extractor)
    return service, downloader, store


async def test_exact_host_allowlist_and_tls_ca_are_enforced():
    service, downloader, _ = _service()
    with patch("bisheng.eplus.domain.services.media_service.decrypt_media", return_value=PNG):
        ref = await service.ingest_image(
            tenant_id=9,
            url="https://media.example/path?id=secret",
            aes_key="key",
            allowed_hosts=("media.example",),
            ca_pem=b"customer-ca",
        )

    assert ref.object_key.startswith("eplus/media/9/")
    assert downloader.calls[0][1] == b"customer-ca"

    with pytest.raises(MediaIngestionError, match="host is not allowed"):
        await service.ingest_image(
            tenant_id=9,
            url="https://evilmedia.example/path",
            aes_key="key",
            allowed_hosts=("media.example",),
            ca_pem=None,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_download(peer="10.0.0.9", resolved=("10.0.0.8",)), "peer address changed"),
        (_download(redirected=True), "redirect"),
    ],
)
async def test_dns_rebinding_and_unverified_redirects_fail_closed(payload, message):
    service, _, _ = _service(payload)
    with pytest.raises(MediaIngestionError, match=message):
        await service.ingest_image(
            tenant_id=9,
            url="https://media.example/path",
            aes_key="key",
            allowed_hosts=("media.example",),
            ca_pem=None,
        )


async def test_timeout_oversize_bad_magic_and_aes_failures_are_classified():
    common = {
        "tenant_id": 9,
        "url": "https://media.example/path?token=must-not-leak",
        "aes_key": "secret-aes-key",
        "allowed_hosts": ("media.example",),
        "ca_pem": None,
    }

    service, _, _ = _service(TimeoutError())
    with pytest.raises(MediaIngestionError, match="timed out") as timeout_error:
        await service.ingest_image(**common)
    assert "token" not in str(timeout_error.value)

    service, _, _ = _service(_download(body=b"x" * (20 * 1024 * 1024 + 33)))
    with pytest.raises(MediaIngestionError, match="too large"):
        await service.ingest_image(**common)

    service, _, _ = _service()
    with patch("bisheng.eplus.domain.services.media_service.decrypt_media", return_value=b"not-an-image"):
        with pytest.raises(MediaIngestionError, match="unsupported image"):
            await service.ingest_image(**common)

    service, _, _ = _service()
    with patch("bisheng.eplus.domain.services.media_service.decrypt_media", side_effect=ValueError("bad key")):
        with pytest.raises(MediaIngestionError, match="decrypt") as aes_error:
            await service.ingest_image(**common)
    assert "secret-aes-key" not in str(aes_error.value)


async def test_content_addressed_object_is_persisted_with_hash_type_and_size():
    service, _, store = _service()
    with patch("bisheng.eplus.domain.services.media_service.decrypt_media", return_value=PNG):
        first = await service.ingest_image(
            tenant_id=9,
            url="https://media.example/1",
            aes_key="key",
            allowed_hosts=("media.example",),
            ca_pem=None,
        )
        second = await service.ingest_image(
            tenant_id=9,
            url="https://media.example/2",
            aes_key="key",
            allowed_hosts=("media.example",),
            ca_pem=None,
        )

    assert first == second
    assert first.mime_type == "image/png"
    assert first.size == len(PNG)
    assert store.objects[first.object_key] == PNG


async def test_visual_ocr_and_no_capability_paths_materialize_from_object_storage():
    service, _, _ = _service(extractor=FakeExtractor(available=True))
    with patch("bisheng.eplus.domain.services.media_service.decrypt_media", return_value=PNG):
        prepared = await service.ingest_blocks(
            tenant_id=9,
            blocks=(EPlusContentBlock(kind=EPlusContentKind.IMAGE, url="https://media.example/1", aes_key="key"),),
            allowed_hosts=("media.example",),
            ca_pem=None,
        )

    visual = await service.materialize(prepared.blocks, supports_vision=True, user_id=88)
    assert visual[0]["type"] == "image_url"
    assert visual[0]["image_url"]["url"].startswith("data:image/png;base64,")

    ocr = await service.materialize(prepared.blocks, supports_vision=False, user_id=88)
    assert ocr == [{"type": "text", "text": "[图片文字]\nOCR result"}]

    no_capability, _, _ = _service(extractor=FakeExtractor(available=False))
    no_capability.store = service.store
    unavailable = await no_capability.materialize(prepared.blocks, supports_vision=False, user_id=88)
    assert "无法理解图片" in unavailable[0]["text"]


async def test_mixed_blocks_keep_order_and_one_bad_image_does_not_drop_text():
    service, _, _ = _service()
    blocks = (
        EPlusContentBlock(kind=EPlusContentKind.TEXT, text="before"),
        EPlusContentBlock(kind=EPlusContentKind.IMAGE, url="https://bad.example/1", aes_key="key"),
        EPlusContentBlock(kind=EPlusContentKind.TEXT, text="after"),
    )

    prepared = await service.ingest_blocks(
        tenant_id=9,
        blocks=blocks,
        allowed_hosts=("media.example",),
        ca_pem=None,
    )
    content = await service.materialize(prepared.blocks, supports_vision=True, user_id=88)

    assert [part["type"] for part in content] == ["text", "text", "text"]
    assert content[0]["text"] == "before"
    assert "无法读取图片" in content[1]["text"]
    assert content[2]["text"] == "after"
    assert len(prepared.errors) == 1
