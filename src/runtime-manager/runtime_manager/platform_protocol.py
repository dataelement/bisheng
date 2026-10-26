"""Versioned runtime wire authentication; shared vectors pin both process copies."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from uuid import uuid4


class ProtocolRejected(ValueError):
    """Safe protocol failure with no credential or original request content."""


@dataclass(frozen=True)
class ServiceIdentity:
    key_id: str
    node_id: str
    roles: tuple[str, ...]


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def content_digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def canonical_message(method: str, url: str, body: bytes, timestamp: int, nonce: str, key_id: str) -> bytes:
    parts = urlsplit(url)
    path = quote(unquote(parts.path, errors="strict"), safe="/-._~")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), quote_via=quote, safe="-._~")
    target = path + ("?" + query if query else "")
    if "\n" in key_id or "\n" in nonce:
        raise ProtocolRejected("invalid_identity")
    return (
        f"v2\n{method.upper()}\n{target}\n{hashlib.sha256(body).hexdigest()}\n{timestamp}\n{nonce}\n{key_id}".encode()
    )


def signed_headers(
    method: str,
    url: str,
    body: bytes,
    *,
    key_id: str,
    secret: str,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    if not key_id or not secret:
        raise ProtocolRejected("service_identity_not_configured")
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or uuid4().hex
    signature = hmac.new(
        secret.encode(), canonical_message(method, url, body, timestamp, nonce, key_id), hashlib.sha256
    ).hexdigest()
    return {
        "X-Runtime-Key-Id": key_id,
        "X-Runtime-Timestamp": str(timestamp),
        "X-Runtime-Nonce": nonce,
        "X-Runtime-Signature": signature,
    }


async def authenticate(
    method: str,
    url: str,
    body: bytes,
    headers,
    keyring: dict,
    consume_nonce,
    *,
    required_role: str,
    now: float | None = None,
) -> ServiceIdentity:
    headers = {k.lower(): v for k, v in headers.items()}
    key_id = headers.get("x-runtime-key-id", "")
    nonce = headers.get("x-runtime-nonce", "")
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", key_id) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ProtocolRejected("invalid_identity")
    try:
        timestamp = int(headers.get("x-runtime-timestamp", ""))
    except (TypeError, ValueError):
        raise ProtocolRejected("invalid_timestamp") from None
    if abs((time.time() if now is None else now) - timestamp) >= 60:
        raise ProtocolRejected("signature_expired")
    key = keyring.get(key_id, {})
    secret = key.get("secret", "")
    roles = key.get("roles", [])
    if not secret or required_role not in roles:
        raise ProtocolRejected("service_role_refused")
    expected = hmac.new(
        secret.encode(), canonical_message(method, url, body, timestamp, nonce, key_id), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, headers.get("x-runtime-signature", "")):
        raise ProtocolRejected("signature_mismatch")
    if not await consume_nonce(f"runtime:v2:nonce:{key_id}:{nonce}", 120):
        raise ProtocolRejected("request_replayed")
    return ServiceIdentity(key_id=key_id, node_id=str(key.get("node_id", "")), roles=tuple(roles))
