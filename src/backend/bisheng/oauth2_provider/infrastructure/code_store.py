"""Redis-backed short-lived storage for OAuth 2.0 authorization requests and codes."""

from __future__ import annotations

import json
from typing import Any

AUTH_REQUEST_PREFIX = "oauth2:req:"
AUTH_CODE_PREFIX = "oauth2:code:"
AUTH_REQUEST_TTL = 300
AUTH_CODE_TTL = 120


class OAuth2CodeStore:
    def __init__(self, redis):
        self.redis = redis

    async def save_request(self, request_id: str, payload: dict[str, Any], ttl: int = AUTH_REQUEST_TTL) -> None:
        await self.redis.set(f"{AUTH_REQUEST_PREFIX}{request_id}", json.dumps(payload), ex=ttl)

    async def read_request(self, request_id: str) -> tuple[dict[str, Any], int] | None:
        key = f"{AUTH_REQUEST_PREFIX}{request_id}"
        raw = await self.redis.get(key)
        if raw is None:
            return None
        ttl = await self.redis.ttl(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw), max(1, int(ttl) if ttl and ttl > 0 else 1)

    async def consume_request(self, request_id: str) -> dict[str, Any] | None:
        key = f"{AUTH_REQUEST_PREFIX}{request_id}"
        raw = await self._getdel(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def save_code(self, code: str, payload: dict[str, Any], ttl: int = AUTH_CODE_TTL) -> None:
        await self.redis.set(f"{AUTH_CODE_PREFIX}{code}", json.dumps(payload), ex=ttl)

    async def consume_code(self, code: str) -> dict[str, Any] | None:
        key = f"{AUTH_CODE_PREFIX}{code}"
        raw = await self._getdel(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def _getdel(self, key: str):
        if hasattr(self.redis, "getdel"):
            return await self.redis.getdel(key)
        pipe = self.redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()
        return results[0] if results else None
