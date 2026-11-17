"""Request-scoped public origin; shared configuration never learns a caller's address."""

import asyncio
import ipaddress
import socket

from fastapi import HTTPException
from loguru import logger
from starlette.requests import HTTPConnection

from bisheng.core.config.dsh import DshSettings, normalize_dsh_origin


async def _trusted_proxy(connection: HTTPConnection, hosts: list[str]) -> bool:
    if not connection.client:
        return False
    try:
        peer = ipaddress.ip_address(connection.client.host)
    except ValueError:
        return False
    for host in hosts:
        try:
            if peer in ipaddress.ip_network(host, strict=False):
                return True
            continue
        except ValueError:
            # DNS names are deployment-owned service identities, never request input.
            try:
                async with asyncio.timeout(1):
                    addresses = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            except (OSError, TimeoutError):
                # An absent optional proxy never grants trust. Direct HTTP still works.
                logger.warning("Cannot resolve a configured desktop proxy; ignoring its forwarded scheme")
                continue
            if any(peer == ipaddress.ip_address(address[4][0]) for address in addresses):
                return True
    return False


async def resolve_client_origin(connection: HTTPConnection, settings: DshSettings) -> str:
    if settings.platform_public_url:
        return settings.platform_public_url
    scheme = connection.scope.get("scheme", "http")
    forwarded = connection.headers.getlist("x-forwarded-proto")
    if forwarded and await _trusted_proxy(connection, getattr(settings, "trusted_proxy_hosts", [])):
        if len(forwarded) != 1 or forwarded[0] not in {"http", "https"}:
            raise HTTPException(400, "Invalid forwarded scheme")
        scheme = forwarded[0]
    hosts = connection.headers.getlist("host")
    if len(hosts) != 1:
        raise HTTPException(421, "Invalid Host header")
    try:
        return normalize_dsh_origin(f"{scheme}://{hosts[0]}")
    except ValueError:
        raise HTTPException(421, "Invalid Host header") from None


async def require_client_browser_origin(connection: HTTPConnection, settings: DshSettings) -> None:
    expected = await resolve_client_origin(connection, settings)
    if (
        connection.headers.getlist("origin") != [expected]
        or connection.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise HTTPException(403, "Invalid browser origin")
