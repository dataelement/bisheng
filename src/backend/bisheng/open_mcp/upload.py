"""Safe MCP base64 and remote-URL file adaptation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import os
import socket
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain.upload_file_size import get_max_upload_bytes
from bisheng.open_mcp.contracts import KnowledgeFileUploadInput


class McpUploadError(ValueError):
    """A safe, caller-actionable upload adaptation failure."""

    def __init__(self, message: str, *, code: str = "INVALID_FILE_SOURCE") -> None:
        super().__init__(message)
        self.code = code


def _minio_share_origin() -> tuple[str, str, int] | None:
    minio = settings.object_storage.minio
    if minio is None or not minio.sharepoint:
        return None
    default_scheme = "https" if minio.share_schema else "http"
    raw = minio.sharepoint if "://" in minio.sharepoint else f"{default_scheme}://{minio.sharepoint}"
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme, host, port


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified)


async def _resolve_addresses(host: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise McpUploadError("Unable to resolve URL host", code="DOWNLOAD_FAILED") from exc
    return {str(row[4][0]) for row in rows}


async def validate_outbound_url(
    url: str,
    *,
    allowed_hosts: list[str],
    allow_minio_http: bool,
) -> str:
    await _approve_outbound_url(
        url,
        allowed_hosts=allowed_hosts,
        allow_minio_http=allow_minio_http,
    )
    return url


async def _approve_outbound_url(
    url: str,
    *,
    allowed_hosts: list[str],
    allow_minio_http: bool,
) -> tuple[set[str], bool]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    minio_origin = _minio_share_origin()
    if parsed.username or parsed.password or not host:
        raise McpUploadError("URL userinfo and missing hosts are not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise McpUploadError("URL contains an invalid port") from exc
    is_minio = bool(minio_origin and (parsed.scheme, host, port) == minio_origin)
    if host not in set(allowed_hosts) and not is_minio:
        raise McpUploadError("URL host is not allowlisted")
    if parsed.scheme != "https" and not (allow_minio_http and is_minio):
        raise McpUploadError("URL must use HTTPS")
    addresses = await _resolve_addresses(host, port)
    if not addresses or (not is_minio and any(not _is_public_ip(address) for address in addresses)):
        raise McpUploadError("URL resolves to a prohibited network address")
    return addresses, is_minio


def _safe_file_name(value: str) -> str:
    normalized = value.strip()
    base_name = Path(normalized.replace("\\", "/")).name
    if "\x00" in normalized or not normalized or normalized in {".", ".."} or base_name != normalized:
        raise McpUploadError("file_name must be a base name")
    return normalized


def _staged_file_name(file_hash: str, file_name: str) -> str:
    suffix = file_name[-60:]
    while len(suffix.encode("utf-8")) > 180:
        suffix = suffix[1:]
    return f"{file_hash}_{suffix}"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as input_file:
        for chunk in iter(lambda: input_file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_base64_to_file(encoded: str, path: str, limit: int) -> None:
    written = 0
    chunk_size = 4 * 16384
    try:
        padding_at = encoded.find("=")
        if len(encoded) % 4 != 0 or (
            padding_at >= 0
            and (padding_at < len(encoded) - 2 or any(character != "=" for character in encoded[padding_at:]))
        ):
            raise McpUploadError("content_base64 is not valid strict base64")
        with open(path, "wb") as output:
            for offset in range(0, len(encoded), chunk_size):
                chunk = encoded[offset : offset + chunk_size]
                decoded = base64.b64decode(chunk, validate=True)
                written += len(decoded)
                if written > limit:
                    raise McpUploadError(
                        "Decoded file exceeds the configured upload limit",
                        code="FILE_TOO_LARGE",
                    )
                output.write(decoded)
    except (binascii.Error, ValueError) as exc:
        if isinstance(exc, McpUploadError):
            raise
        raise McpUploadError("content_base64 is not valid strict base64") from exc


def _file_name_from_url(url: str) -> str:
    decoded_path = unquote(urlsplit(url).path).replace("\\", "/")
    name = Path(decoded_path).name.strip()
    if not name or name in {".", ".."}:
        raise McpUploadError("file_url must end with a file name")
    return _safe_file_name(name[:255])


async def _download_to_file(url: str, path: str, file_name: str) -> None:
    current = url
    limit = get_max_upload_bytes(file_name)
    timeout = httpx.Timeout(
        connect=settings.open_mcp.connect_timeout_seconds,
        read=settings.open_mcp.read_timeout_seconds,
        write=settings.open_mcp.read_timeout_seconds,
        pool=settings.open_mcp.connect_timeout_seconds,
    )
    limits = httpx.Limits(max_keepalive_connections=0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        limits=limits,
    ) as client:
        for redirect_count in range(settings.open_mcp.max_redirects + 1):
            addresses, _is_minio = await _approve_outbound_url(
                current,
                allowed_hosts=settings.open_mcp.file_url_allowed_hosts,
                allow_minio_http=True,
            )
            parsed = urlsplit(current)
            host = (parsed.hostname or "").lower().rstrip(".")
            redirect_target: str | None = None
            last_connect_error: httpx.HTTPError | None = None
            for address in sorted(addresses):
                pinned_url = _pinned_url(parsed, address)
                try:
                    async with client.stream(
                        "GET",
                        pinned_url,
                        headers={"Host": _host_header(parsed)},
                        extensions={"sni_hostname": host},
                    ) as response:
                        _validate_connected_peer(response, addresses)
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_count >= settings.open_mcp.max_redirects:
                                raise McpUploadError("file_url exceeded the redirect limit")
                            redirect_target = urljoin(current, location)
                            break
                        response.raise_for_status()
                        declared = response.headers.get("content-length")
                        if declared:
                            try:
                                declared_size = int(declared)
                            except ValueError as exc:
                                raise McpUploadError(
                                    "Remote file returned an invalid Content-Length",
                                    code="DOWNLOAD_FAILED",
                                ) from exc
                            if declared_size > limit:
                                raise McpUploadError(
                                    "Remote file exceeds the upload limit",
                                    code="FILE_TOO_LARGE",
                                )
                        written = 0
                        with open(path, "wb") as output:
                            async for chunk in response.aiter_bytes(64 * 1024):
                                written += len(chunk)
                                if written > limit:
                                    raise McpUploadError(
                                        "Remote file exceeds the upload limit",
                                        code="FILE_TOO_LARGE",
                                    )
                                output.write(chunk)
                        return
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_connect_error = exc
                    continue
                except (httpx.HTTPStatusError, httpx.ReadError, httpx.ReadTimeout) as exc:
                    raise McpUploadError("Remote file download failed", code="DOWNLOAD_FAILED") from exc
            if redirect_target is not None:
                current = redirect_target
                continue
            if last_connect_error is not None:
                raise McpUploadError("Remote file download failed", code="DOWNLOAD_FAILED") from last_connect_error
    raise McpUploadError("file_url could not be downloaded")


def _host_header(parsed) -> str:
    host = parsed.hostname or ""
    rendered = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{rendered}:{parsed.port}" if parsed.port is not None else rendered


def _pinned_url(parsed, address: str) -> str:
    rendered = f"[{address}]" if ":" in address else address
    if parsed.port is not None:
        rendered = f"{rendered}:{parsed.port}"
    return urlunsplit((parsed.scheme, rendered, parsed.path, parsed.query, ""))


def _validate_connected_peer(response: httpx.Response, approved_addresses: set[str]) -> None:
    stream = response.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if not isinstance(peer, (tuple, list)) or not peer:
        raise McpUploadError("Unable to verify the remote peer address")
    peer_address = ipaddress.ip_address(str(peer[0]))
    approved = {ipaddress.ip_address(address) for address in approved_addresses}
    if peer_address not in approved:
        raise McpUploadError("Remote peer address changed after validation")


@asynccontextmanager
async def prepared_upload(source: KnowledgeFileUploadInput) -> AsyncIterator[tuple[str, str]]:
    file_name = _safe_file_name(source.file_name) if source.file_name else _file_name_from_url(str(source.file_url))
    with tempfile.TemporaryDirectory(prefix="bisheng-open-mcp-") as directory:
        download_path = os.path.join(directory, "payload")
        if source.content_base64 is not None:
            limit = min(settings.open_mcp.max_inline_upload_bytes, get_max_upload_bytes(file_name))
            await asyncio.to_thread(_decode_base64_to_file, source.content_base64, download_path, limit)
        else:
            await _download_to_file(str(source.file_url), download_path, file_name)
        file_hash = await asyncio.to_thread(_sha256_file, download_path)
        staged_name = _staged_file_name(file_hash, file_name)
        staged_path = os.path.join(directory, staged_name)
        os.replace(download_path, staged_path)
        yield staged_path, file_name


__all__ = [
    "McpUploadError",
    "prepared_upload",
    "validate_outbound_url",
]
