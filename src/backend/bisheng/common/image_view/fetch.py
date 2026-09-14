"""Fetch registered image bytes, resize long edge to 512, encode as data URI.

Does not import domain modules. Resize stays in-process (C8: no shared disk).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from urllib.parse import urlparse

from loguru import logger

LONG_EDGE = 512
MIN_READABLE_EDGE = 32
_KNOWLEDGE_IMAGES = "knowledge/images/"


@dataclass(frozen=True)
class FetchEncodeResult:
    ok: bool
    data_uri: str | None = None
    error: str | None = None
    reason: str | None = None  # path | host | decode | too_small


def _public_bucket() -> str:
    from bisheng.common.services.config_service import settings

    return (settings.get_minio_conf().public_bucket or "bisheng").strip()


def _share_hosts() -> set[str]:
    from bisheng.common.services.config_service import settings

    conf = settings.get_minio_conf()
    host = (conf.sharepoint or "").strip().lower()
    return {host} if host else set()


def _info_hosts() -> set[str]:
    from bisheng.common.services.config_service import settings

    base = (settings.information_conf.base_url or "").strip()
    if not base:
        return set()
    parsed = urlparse(base if "://" in base else f"https://{base}")
    return {parsed.netloc.lower()} if parsed.netloc else set()


async def _get_object(bucket: str, object_key: str) -> bytes | None:
    from bisheng.core.storage.minio.minio_manager import get_minio_storage

    client = await get_minio_storage()
    return await client.get_object(bucket, object_key)


async def _async_file_download(url: str) -> bytes:
    from bisheng.core.cache.utils import async_file_download

    result = await async_file_download(url)
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    path = result[0] if isinstance(result, tuple) else result
    with open(path, "rb") as handle:
        return handle.read()


def _classify(url: str) -> str:
    """Return minio_path | http | reject. Never follows 3xx off the allow-list."""
    if "X-Amz-Algorithm" in url and url.startswith("/"):
        return "http"
    if url.startswith("http://") or url.startswith("https://"):
        host = urlparse(url).netloc.lower()
        if host in _share_hosts() or host in _info_hosts():
            return "http"
        return "reject"
    prefix = f"/{_public_bucket()}/{_KNOWLEDGE_IMAGES}"
    if url.startswith(prefix):
        return "minio_path"
    return "reject"


def _split_internal_path(url: str) -> tuple[str, str]:
    stripped = url.split("?", 1)[0].lstrip("/")
    bucket, object_key = stripped.split("/", 1)
    return bucket, object_key


def _resize_to_data_uri(raw: bytes) -> tuple[str | None, int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        width, height = image.size
        long_edge = max(width, height)
        if long_edge < MIN_READABLE_EDGE:
            return None, width, height
        if long_edge > LONG_EDGE:
            scale = LONG_EDGE / long_edge
            image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height


async def fetch_and_encode(url: str) -> FetchEncodeResult:
    kind = _classify(url)
    if kind == "reject":
        logger.warning("image_view reject host/path url={!r}", url)
        return FetchEncodeResult(ok=False, error="This image is not available.", reason="host")

    try:
        if kind == "minio_path":
            bucket, object_key = _split_internal_path(url)
            raw = await _get_object(bucket, object_key)
        else:
            raw = await _async_file_download(url)
    except Exception:
        logger.warning("image_view fetch failed kind={}", kind)
        return FetchEncodeResult(ok=False, error="This image is not available.", reason="path")

    if not raw:
        return FetchEncodeResult(ok=False, error="This image is not available.", reason="path")

    try:
        data_uri, width, height = _resize_to_data_uri(raw)
    except Exception:
        logger.warning("image_view decode/resize failed")
        return FetchEncodeResult(ok=False, error="This image is not available.", reason="decode")

    logger.info("image_view fetched url={} raw_bytes={} size={}x{}", url, len(raw), width, height)
    if data_uri is None:
        logger.warning(
            "image_view too small url={} size={}x{} raw_bytes={}",
            url,
            width,
            height,
            len(raw),
        )
        return FetchEncodeResult(ok=False, error="This image is not available.", reason="too_small")

    return FetchEncodeResult(ok=True, data_uri=data_uri)
