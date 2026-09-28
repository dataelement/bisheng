"""Network and object-storage adapters for E+ media."""

from __future__ import annotations

import asyncio
import socket
import ssl
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from bisheng.common.services.config_service import settings
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.eplus.domain.services.media_service import (
    DownloadedEncryptedMedia,
    MediaIngestionError,
)


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, host: str, addresses: tuple[str, ...]) -> None:
        self.host = host
        self.addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC) -> list[dict[str, Any]]:
        if host.lower().rstrip(".") != self.host:
            raise OSError("unexpected host during pinned media download")
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self) -> None:
        return None


class SecureEPlusMediaDownloader:
    async def download(
        self,
        url: str,
        *,
        ca_pem: bytes | None,
        timeout_seconds: float,
        max_bytes: int,
    ) -> DownloadedEncryptedMedia:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await _resolve_addresses(host, port)
        if not addresses:
            raise MediaIngestionError("image download host did not resolve")

        ssl_context: ssl.SSLContext | bool = False
        if parsed.scheme == "https":
            ssl_context = ssl.create_default_context()
            if ca_pem:
                try:
                    ssl_context.load_verify_locations(cadata=ca_pem.decode("ascii"))
                except (UnicodeDecodeError, ssl.SSLError) as exc:
                    raise MediaIngestionError("configured image download CA is invalid") from exc

        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(host, addresses),
            ssl=ssl_context,
            use_dns_cache=False,
        )
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, auto_decompress=False) as session:
            async with session.get(url, allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    return DownloadedEncryptedMedia(b"", addresses, addresses[0], redirected=True)
                if response.status != 200:
                    raise MediaIngestionError("image download returned a non-success status")
                content_length = response.content_length
                if content_length is not None and content_length > max_bytes:
                    raise MediaIngestionError("encrypted image is too large")
                peer_ip = _response_peer_ip(response)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise MediaIngestionError("encrypted image is too large")
                    chunks.append(chunk)
                return DownloadedEncryptedMedia(b"".join(chunks), addresses, peer_ip)


class MinioEPlusMediaStore:
    def __init__(self, *, bucket_name: str | None = None) -> None:
        self.bucket_name = bucket_name

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        minio = await get_minio_storage()
        await minio.put_object(
            bucket_name=self.bucket_name,
            object_name=object_key,
            file=data,
            content_type=content_type,
        )

    async def get(self, *, object_key: str) -> bytes:
        minio = await get_minio_storage()
        data = await minio.get_object(bucket_name=self.bucket_name, object_name=object_key)
        if data is None:
            raise FileNotFoundError("E+ media object not found")
        return data


class DailyChatImageTextExtractor:
    @property
    def available(self) -> bool:
        return settings.knowledge.image_parser_enabled

    async def extract(self, *, data: bytes, mime_type: str, user_id: int) -> str:
        from bisheng.workstation.domain.services.chat_service import get_file_content

        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime_type, ".img")
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(data)
                path = Path(temp_file.name)
            return await get_file_content(str(path), f"eplus-image{suffix}", user_id)
        finally:
            if path is not None:
                await asyncio.to_thread(path.unlink, missing_ok=True)


async def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def _response_peer_ip(response: aiohttp.ClientResponse) -> str:
    connection = response.connection
    transport = connection.transport if connection is not None else None
    peer = transport.get_extra_info("peername") if transport is not None else None
    if not peer:
        raise MediaIngestionError("image download peer address is unavailable")
    return str(peer[0])
