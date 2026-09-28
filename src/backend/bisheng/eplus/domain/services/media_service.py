"""Secure E+ media ingestion and assistant content materialization."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from loguru import logger

from bisheng.assistant.domain.schemas.execution import AssistantMessageContent
from bisheng.eplus.domain.schemas.protocol import EPlusContentBlock, EPlusContentKind
from bisheng.eplus.infrastructure.protocol import decrypt_media

MAX_IMAGE_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 300.0


class MediaIngestionError(ValueError):
    """Safe, stable media failure suitable for user-facing fallback text."""


@dataclass(frozen=True, slots=True)
class DownloadedEncryptedMedia:
    ciphertext: bytes
    resolved_ips: tuple[str, ...]
    peer_ip: str
    redirected: bool = False


@dataclass(frozen=True, slots=True)
class EPlusMediaRef:
    object_key: str
    sha256: str
    mime_type: str
    size: int


@dataclass(frozen=True, slots=True)
class EPlusPreparedBlock:
    kind: str
    text: str | None = None
    media: EPlusMediaRef | None = None


@dataclass(frozen=True, slots=True)
class EPlusPreparedMessage:
    blocks: tuple[EPlusPreparedBlock, ...]
    media_refs: tuple[EPlusMediaRef, ...]
    errors: tuple[str, ...]


class EncryptedMediaDownloader(Protocol):
    async def download(
        self,
        url: str,
        *,
        ca_pem: bytes | None,
        timeout_seconds: float,
        max_bytes: int,
    ) -> DownloadedEncryptedMedia: ...


class MediaObjectStore(Protocol):
    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, *, object_key: str) -> bytes: ...


class ImageTextExtractor(Protocol):
    available: bool

    async def extract(self, *, data: bytes, mime_type: str, user_id: int) -> str: ...


class EPlusMediaService:
    def __init__(
        self,
        *,
        downloader: EncryptedMediaDownloader,
        store: MediaObjectStore,
        text_extractor: ImageTextExtractor | None = None,
    ) -> None:
        self.downloader = downloader
        self.store = store
        self.text_extractor = text_extractor

    async def ingest_image(
        self,
        *,
        tenant_id: int,
        url: str,
        aes_key: str,
        allowed_hosts: tuple[str, ...],
        ca_pem: bytes | None,
    ) -> EPlusMediaRef:
        _validate_download_url(url, allowed_hosts)
        try:
            downloaded = await self.downloader.download(
                url,
                ca_pem=ca_pem,
                timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
                max_bytes=MAX_IMAGE_BYTES + 64,
            )
        except TimeoutError as exc:
            raise MediaIngestionError("image download timed out") from exc
        except MediaIngestionError:
            raise
        except Exception as exc:
            raise MediaIngestionError("image download failed") from exc

        if downloaded.redirected:
            raise MediaIngestionError("image download redirect is not allowed")
        if _normalize_ip(downloaded.peer_ip) not in {_normalize_ip(value) for value in downloaded.resolved_ips}:
            raise MediaIngestionError("image download peer address changed after DNS resolution")
        if len(downloaded.ciphertext) > MAX_IMAGE_BYTES + 32:
            raise MediaIngestionError("encrypted image is too large")

        try:
            plaintext = decrypt_media(downloaded.ciphertext, aes_key)
        except Exception as exc:
            raise MediaIngestionError("image decrypt failed") from exc
        if len(plaintext) > MAX_IMAGE_BYTES:
            raise MediaIngestionError("decrypted image is too large")
        mime_type, extension = _detect_image_type(plaintext)

        digest = hashlib.sha256(plaintext).hexdigest()
        object_key = f"eplus/media/{int(tenant_id)}/{digest[:2]}/{digest}.{extension}"
        await self.store.put(object_key=object_key, data=plaintext, content_type=mime_type)
        return EPlusMediaRef(
            object_key=object_key,
            sha256=digest,
            mime_type=mime_type,
            size=len(plaintext),
        )

    async def ingest_blocks(
        self,
        *,
        tenant_id: int,
        blocks: tuple[EPlusContentBlock, ...],
        allowed_hosts: tuple[str, ...],
        ca_pem: bytes | None,
    ) -> EPlusPreparedMessage:
        prepared: list[EPlusPreparedBlock] = []
        refs: list[EPlusMediaRef] = []
        errors: list[str] = []
        for block in blocks:
            if block.kind == EPlusContentKind.TEXT:
                prepared.append(EPlusPreparedBlock(kind="text", text=block.text or ""))
                continue
            try:
                if not block.url or not block.aes_key:
                    raise MediaIngestionError("image callback is missing download data")
                media_ref = await self.ingest_image(
                    tenant_id=tenant_id,
                    url=block.url,
                    aes_key=block.aes_key,
                    allowed_hosts=allowed_hosts,
                    ca_pem=ca_pem,
                )
            except MediaIngestionError as exc:
                errors.append(str(exc))
                prepared.append(EPlusPreparedBlock(kind="error", text=f"[无法读取图片: {exc}]"))
            else:
                refs.append(media_ref)
                prepared.append(EPlusPreparedBlock(kind="image", media=media_ref))
        return EPlusPreparedMessage(tuple(prepared), tuple(refs), tuple(errors))

    async def materialize(
        self,
        blocks: tuple[EPlusPreparedBlock, ...],
        *,
        supports_vision: bool,
        user_id: int,
    ) -> AssistantMessageContent:
        content: list[dict[str, object]] = []
        for block in blocks:
            if block.kind in {"text", "error"}:
                content.append({"type": "text", "text": block.text or ""})
                continue
            if block.media is None:
                content.append({"type": "text", "text": "[无法读取图片: 媒体引用缺失]"})
                continue

            try:
                data = await self.store.get(object_key=block.media.object_key)
            except Exception:
                logger.opt(exception=True).warning(
                    "E+ media object read failed for sha256={}",
                    block.media.sha256,
                )
                content.append({"type": "text", "text": "[无法读取图片: 媒体对象不可用]"})
                continue
            if hashlib.sha256(data).hexdigest() != block.media.sha256:
                content.append({"type": "text", "text": "[无法读取图片: 媒体内容校验失败]"})
                continue
            if supports_vision:
                encoded = base64.b64encode(data).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{block.media.mime_type};base64,{encoded}"},
                    }
                )
                continue

            extractor = self.text_extractor
            if extractor is None or not extractor.available:
                content.append({"type": "text", "text": "[当前助手无法理解图片, 请补充文字描述]"})
                continue
            try:
                extracted = await extractor.extract(
                    data=data,
                    mime_type=block.media.mime_type,
                    user_id=user_id,
                )
            except Exception:
                logger.opt(exception=True).warning(
                    "E+ image text extraction failed for sha256={}",
                    block.media.sha256,
                )
                content.append({"type": "text", "text": "[图片文字提取失败, 请补充文字描述]"})
                continue
            content.append({"type": "text", "text": f"[图片文字]\n{extracted}"})
        return content


def _validate_download_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    normalized_allowed = {value.lower().rstrip(".") for value in allowed_hosts}
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise MediaIngestionError("image download URL is invalid")
    if host not in normalized_allowed:
        raise MediaIngestionError("image download host is not allowed")


def _normalize_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.split("%", 1)[0]))
    except ValueError as exc:
        raise MediaIngestionError("image download peer address is invalid") from exc


def _detect_image_type(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise MediaIngestionError("decrypted media has unsupported image content")
