"""HTTP downloads with DNS-pinned connections on every hop.

Intranet / RFC1918 destinations are permitted (product policy restored). Loopback
and link-local remain denied by ``egress_policy``. No proxy environment,
credentials, ambient cookies or automatic redirects. Keep Host/SNI on the
original hostname while connecting to a validated numeric IP. Configured object
storage is handled separately by its SDK, never an IP bypass.
"""

import asyncio
import ipaddress
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from bisheng_langchain.utils.egress_policy import _allowed, parse_destination, resolve_destination

MAX_REDIRECTS = 5
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether ``address`` is an allowed download peer (intranet OK).

    Name retained for call-site stability; policy now matches pre-hardening
    web-link rules (deny loopback/link-local/multicast/unspecified only).
    """
    return _allowed(address)


def same_origin(url: str, configured_url: str) -> bool:
    """Strict origin equality, not string-prefix trust (no userinfo/port tricks)."""
    try:
        return parse_destination(url).origin == parse_destination(configured_url).origin
    except ValueError:
        return False


def _connection(target):
    parsed = urlsplit(target.url)
    address = target.ips[0]
    host = f"[{address}]" if ":" in address else address
    pinned = urlunsplit((target.scheme, f"{host}:{target.port}", parsed.path or "/", parsed.query, ""))
    hostname = f"[{target.hostname}]" if ":" in target.hostname else target.hostname
    default_port = 443 if target.scheme == "https" else 80
    authority = hostname if target.port == default_port else f"{hostname}:{target.port}"
    return pinned, authority


def _check_peer(response, target):
    stream = response.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if not isinstance(peer, list | tuple) or not peer or str(ipaddress.ip_address(peer[0])) not in target.ips:
        raise ValueError("Unable to verify download peer address")
    # Consumers see the source URL, never the implementation's numeric IP URL.
    response.request.url = httpx.URL(target.url)


@contextmanager
def public_stream(url: str, *, headers=None):
    current = url
    try:
        with httpx.Client(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=30,
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                target = resolve_destination(current)
                pinned, authority = _connection(target)
                request_headers = dict(headers or {})
                request_headers.update({"Host": authority, "Accept-Encoding": "identity"})
                client.cookies.clear()
                with client.stream(
                    "GET", pinned, headers=request_headers, extensions={"sni_hostname": target.hostname}
                ) as response:
                    _check_peer(response, target)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Download redirect location is missing")
                        current = urljoin(current, location)
                        continue
                    yield response
                    return
            raise ValueError("Download redirects too many times")
    except httpx.HTTPError as exc:
        raise ValueError("Remote file download failed") from exc


@asynccontextmanager
async def public_astream(url: str, *, headers=None):
    current = url
    try:
        async with asyncio.timeout(60):
            async with httpx.AsyncClient(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=30,
                limits=httpx.Limits(max_keepalive_connections=0),
            ) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    target = await asyncio.to_thread(resolve_destination, current)
                    pinned, authority = _connection(target)
                    request_headers = dict(headers or {})
                    request_headers.update({"Host": authority, "Accept-Encoding": "identity"})
                    client.cookies.clear()
                    async with client.stream(
                        "GET", pinned, headers=request_headers, extensions={"sni_hostname": target.hostname}
                    ) as response:
                        _check_peer(response, target)
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("Download redirect location is missing")
                            current = urljoin(current, location)
                            continue
                        yield response
                        return
                raise ValueError("Download redirects too many times")
    except (httpx.HTTPError, TimeoutError) as exc:
        raise ValueError("Remote file download failed") from exc


class BoundedDownload:
    """File-like interface consumed by save_download_file without buffering."""

    def __init__(self, response, max_bytes=MAX_DOWNLOAD_BYTES):
        self.response, self.max_bytes = response, max_bytes

    def iter_content(self, chunk_size):
        total = 0
        for chunk in self.response.iter_bytes(chunk_size):
            total += len(chunk)
            if total > self.max_bytes:
                raise ValueError("Remote file exceeds download limit")
            yield chunk
