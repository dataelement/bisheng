"""DSH request authentication with purpose-separated keys from the existing shared secret."""

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from redis.exceptions import RedisError

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshInvalidAccessTokenError

_PATH = re.compile(r"^/[A-Za-z0-9_/-]+$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class ServiceKey:
    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self):
        if not _TOKEN.fullmatch(self.key_id) or len(self.secret) < 32:
            raise ValueError("Explicit DSH key registration and at least 32 secret bytes required")


class NonceStore(Protocol):
    async def claim(self, key: str, ttl: int) -> bool: ...


class RedisNonceStore:
    def __init__(self, redis):
        self.redis = redis

    async def claim(self, key: str, ttl: int) -> bool:
        try:
            return bool(await self.redis.set(key, "1", nx=True, ex=ttl))
        except RedisError:
            raise DshAuthorizationUnavailableError() from None


def canonical(method: str, path: str, body: bytes, key: str, timestamp: str, nonce: str) -> bytes:
    if not _PATH.fullmatch(path) or "//" in path or method not in {"POST", "GET"}:
        raise ValueError("Use a canonical absolute DSH path without query, encoding or dot segments")
    return "\n".join((method, path, hashlib.sha256(body).hexdigest(), key, timestamp, nonce)).encode()


class ServiceAuth:
    def __init__(self, key: ServiceKey, nonces: NonceStore, clock: Callable[[], float] = time.time):
        self.key = key
        self.nonces = nonces
        self.clock = clock

    def sign(self, method: str, path: str, body: bytes) -> dict[str, str]:
        timestamp = str(int(self.clock()))
        nonce = secrets.token_urlsafe(24)
        message = canonical(method, path, body, self.key.key_id, timestamp, nonce)
        return {
            "X-DSH-Key-Id": self.key.key_id,
            "X-DSH-Timestamp": timestamp,
            "X-DSH-Nonce": nonce,
            "X-DSH-Signature": hmac.new(self.key.secret, message, hashlib.sha256).hexdigest(),
        }

    async def verify(self, method: str, path: str, body: bytes, headers: Mapping[str, str]) -> str:
        values = {key.lower(): value for key, value in headers.items()}
        key_id = values.get("x-dsh-key-id", "")
        timestamp = values.get("x-dsh-timestamp", "")
        nonce = values.get("x-dsh-nonce", "")
        signature = values.get("x-dsh-signature", "")
        if (
            key_id != self.key.key_id
            or not re.fullmatch(r"[0-9]{1,12}", timestamp)
            or str(int(timestamp)) != timestamp
            or abs(self.clock() - int(timestamp)) > 60
            or not _NONCE.fullmatch(nonce)
            or not re.fullmatch(r"[0-9a-f]{64}", signature)
        ):
            raise DshInvalidAccessTokenError()
        try:
            message = canonical(method, path, body, key_id, timestamp, nonce)
        except ValueError:
            raise DshInvalidAccessTokenError() from None
        expected = hmac.new(self.key.secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise DshInvalidAccessTokenError()
        # Invalid signatures must not be able to consume another request's nonce.
        if not await self.nonces.claim(f"{{dsh}}:nonce:{key_id}:{nonce}", 120):
            raise DshInvalidAccessTokenError()
        return key_id
