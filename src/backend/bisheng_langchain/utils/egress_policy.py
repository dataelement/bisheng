"""Strict, offline-testable egress destination policy; no HTTP transport.

Consumers MUST connect only to ``ResolvedDestination.ips`` and retain the
canonical hostname for Host/SNI/certificate checks. Resolving here and then
passing the hostname to an ordinary client does not prevent DNS rebinding.
"""

import ipaddress
import re
import socket
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[..., Iterable[tuple]]


class DestinationDenied(ValueError):
    """A malformed, unresolved or prohibited destination (safe to display)."""

    def __init__(self):
        super().__init__("Destination is not permitted")


@dataclass(frozen=True)
class ParsedDestination:
    """Original URL plus canonical connection identity; do not log the URL."""

    url: str = field(repr=False)
    scheme: str
    hostname: str
    port: int
    origin: str


@dataclass(frozen=True)
class ResolvedDestination(ParsedDestination):
    """All validated numeric IPs, in resolver order, with duplicates removed."""

    ips: tuple[str, ...]


def _hostname(value: str) -> str:
    if not value or "%" in value:
        raise DestinationDenied()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        # Do not delegate legacy IPv4 notations to platform-specific DNS parsers.
        if ":" in value or re.fullmatch(r"[0-9.]+", value):
            raise DestinationDenied() from None
    if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*", value):
        raise DestinationDenied()
    try:
        normalized = unicodedata.normalize("NFC", value).lower()
        encoded = normalized.encode("idna").decode("ascii").lower()
        # Reject lossy IDNA2003 mappings (e.g. fullwidth characters, sharp-s).
        decoded = encoded.encode("ascii").decode("idna")
        if decoded.encode("idna").decode("ascii") != encoded or (not normalized.isascii() and decoded != normalized):
            raise DestinationDenied()
    except UnicodeError:
        raise DestinationDenied() from None
    if len(encoded) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in encoded.split(".")
    ):
        raise DestinationDenied()
    return encoded


def parse_destination(url: str) -> ParsedDestination:
    """Parse an unambiguous HTTP(S) URL without resolving or allowing its IP.

    Fragments, userinfo, whitespace/control characters, backslashes, escaped
    hosts, scoped IPv6 and noncanonical legacy IPv4 notations are rejected.
    Unicode DNS names use lossless IDNA2003 only; trailing DNS dots are rejected.
    """
    if (
        not isinstance(url, str)
        or not url
        or any(char.isspace() or unicodedata.category(char).startswith("C") for char in url)
        or "\\" in url
        or "#" in url
    ):
        raise DestinationDenied()
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or "@" in parts.netloc:
            raise DestinationDenied()
        authority = parts.netloc
        if authority.startswith("["):
            end = authority.index("]")
            raw_host = authority[1:end]
            tail = authority[end + 1 :]
            if ":" not in raw_host or (tail and not re.fullmatch(r":[0-9]+", tail)):
                raise DestinationDenied()
        else:
            if authority.count(":") > 1:
                raise DestinationDenied()
            raw_host, separator, raw_port = authority.partition(":")
            if separator and not re.fullmatch(r"[0-9]+", raw_port):
                raise DestinationDenied()
        hostname = _hostname(raw_host)
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise DestinationDenied()
    except (ValueError, UnicodeError):
        raise DestinationDenied() from None
    host = f"[{hostname}]" if ":" in hostname else hostname
    origin = f"{parts.scheme}://{host}:{port}"
    return ParsedDestination(url, parts.scheme, hostname, port, origin)


_RFC1918 = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_ULA = ipaddress.ip_network("fc00::/7")
# Explicit ranges avoid Python-version-dependent is_global exemptions. Disallow
# the whole IPv6 protocol-assignment block, not merely current Teredo/ORCHID.
_SPECIAL_V4 = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_SPECIAL_V6 = tuple(
    ipaddress.ip_network(value)
    for value in (
        "::/96",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
    )
)
_METADATA_V4 = frozenset((ipaddress.ip_address("100.100.100.200"), ipaddress.ip_address("168.63.129.16")))


def _allowed(ip: IPAddress) -> bool:
    if ip.version == 4:
        if ip in _METADATA_V4 or any(ip in network for network in _SPECIAL_V4):
            return False
        private = any(ip in network for network in _RFC1918)
    else:
        # ISATAP interface identifiers embed IPv4 even in otherwise global /64s.
        isatap = (int(ip) >> 32) & 0xFFFFFFFF in (0x00005EFE, 0x02005EFE)
        if isatap or any(ip in network for network in _SPECIAL_V6):
            return False
        private = ip in _ULA
    if private:
        return False
    return ip.is_global and not (
        ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved
    )


def resolve_destination(
    url: str,
    *,
    resolver: Resolver | None = None,
) -> ResolvedDestination:
    """Validate ALL A/AAAA answers, failing closed on mixed or empty answers.

    ``resolver`` follows socket.getaddrinfo's signature. By default the current
    socket.getaddrinfo is used (patchable). This blocking function sets no DNS
    deadline; the transport must include DNS in its end-to-end deadline budget.
    DNS failures and malformed results expose no original exception details.
    """
    target = parse_destination(url)
    try:
        literal = ipaddress.ip_address(target.hostname)
    except ValueError:
        literal = None
    try:
        if literal is not None:
            ips = [literal]
        else:
            records = (resolver or socket.getaddrinfo)(
                target.hostname, target.port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
            ips = []
            for family, socktype, _proto, _canonname, sockaddr in records:
                if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM:
                    raise DestinationDenied()
                address = sockaddr[0]
                if not isinstance(address, str) or "%" in address:
                    raise DestinationDenied()
                ip = ipaddress.ip_address(address)
                if (family == socket.AF_INET) != (ip.version == 4):
                    raise DestinationDenied()
                ips.append(ip)
        if not ips or any(not _allowed(ip) for ip in ips):
            raise DestinationDenied()
    except (OSError, ValueError, TypeError, IndexError):
        raise DestinationDenied() from None
    return ResolvedDestination(
        target.url,
        target.scheme,
        target.hostname,
        target.port,
        target.origin,
        tuple(dict.fromkeys(str(ip) for ip in ips)),
    )
