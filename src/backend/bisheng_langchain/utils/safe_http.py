"""Pinned, bounded HTTP transport for untrusted OpenAPI destinations."""

import asyncio
import ipaddress
import socket

import aiohttp
from aiohttp.abc import AbstractResolver

from bisheng_langchain.utils.egress_policy import DestinationDenied, resolve_destination
from bisheng_langchain.utils.safe_http_errors import RequestFailed, RequestTimeout, ResponseTooLarge, SafeHttpResponse


class FrozenResolver(AbstractResolver):
    def __init__(self, hostname: str, port: int, ips: tuple[str, ...]):
        self.hostname, self.port, self.ips = hostname, port, ips

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host.lower() != self.hostname.lower() or port != self.port:
            raise DestinationDenied()
        return [
            {
                "hostname": host,
                "host": ip,
                "port": port,
                "family": socket.AF_INET6 if ipaddress.ip_address(ip).version == 6 else socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            }
            for ip in self.ips
        ]

    async def close(self):
        return None


def validate_request(method, headers, timeout, max_bytes):
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        raise RequestFailed()
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise RequestFailed()
    if type(max_bytes) is not int or not 0 < max_bytes <= 2 * 1024 * 1024:
        raise RequestFailed()
    for name, value in (headers or {}).items():
        if name.lower() in {
            "host",
            "proxy-authorization",
            "proxy-connection",
            "connection",
            "transfer-encoding",
            "content-length",
        }:
            raise DestinationDenied()
        if any(c in str(name) + str(value) for c in "\r\n"):
            raise DestinationDenied()


async def arequest(
    method, url, *, headers=None, params=None, json=None, timeout=30, max_bytes=1048576
):
    validate_request(method, headers, timeout, max_bytes)
    try:
        # One deadline includes DNS, TLS and the entire streamed body.
        async with asyncio.timeout(timeout):
            target = await asyncio.to_thread(resolve_destination, url)
            connector = aiohttp.TCPConnector(
                resolver=FrozenResolver(target.hostname, target.port, target.ips),
                use_dns_cache=False,
                force_close=True,
            )
            async with aiohttp.ClientSession(
                connector=connector,
                trust_env=False,
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=min(5, timeout)),
            ) as client:
                safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() != "accept-encoding"}
                safe_headers["Accept-Encoding"] = "identity"
                async with client.request(
                    method,
                    target.url,
                    headers=safe_headers,
                    params=params,
                    json=json,
                    allow_redirects=False,
                    proxy=None,
                ) as response:
                    if (
                        300 <= response.status < 400
                        or response.headers.get("Content-Encoding", "identity").lower() != "identity"
                    ):
                        raise RequestFailed()
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(min(8192, max_bytes + 1)):
                        if len(body) + len(chunk) > max_bytes:
                            raise ResponseTooLarge()
                        body.extend(chunk)
                    return SafeHttpResponse(response.status, dict(response.headers), bytes(body))
    except (DestinationDenied, RequestFailed, ResponseTooLarge):
        raise
    except (TimeoutError, aiohttp.ServerTimeoutError):
        raise RequestTimeout() from None
    except (aiohttp.ClientError, OSError, ValueError, TypeError, UnicodeError):
        raise RequestFailed() from None
