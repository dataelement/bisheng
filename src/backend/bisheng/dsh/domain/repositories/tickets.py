"""Short-lived, digest-addressed identity proofs with atomic binding checks."""

import hashlib
import json
import re
import secrets

from redis.exceptions import RedisError

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshInvalidGrantError

_CONSUME = """
local payload = redis.call('GET', KEYS[1])
if not payload then return false end
local decoded = cjson.decode(payload)
if decoded.binding ~= ARGV[1] then return false end
redis.call('DEL', KEYS[1])
return payload
"""


class TicketRepository:
    def __init__(self, redis):
        self.redis = redis

    def key(self, ticket: str) -> str:
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        return f"{{dsh}}:ticket:{digest}"

    @staticmethod
    def binding(binding: dict[str, str]) -> str:
        return json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    async def issue(self, tenant_id: str, user_id: str, binding: dict[str, str], *, ttl: int = 60) -> str:
        if type(ttl) is not int or not 1 <= ttl <= 60:
            raise DshInvalidGrantError()
        ticket = secrets.token_urlsafe(32)
        payload = json.dumps({"tenant_id": tenant_id, "user_id": user_id, "binding": self.binding(binding)})
        try:
            created = await self.redis.set(self.key(ticket), payload, nx=True, ex=ttl)
        except RedisError:
            raise DshAuthorizationUnavailableError() from None
        if not created:
            raise DshAuthorizationUnavailableError()
        return ticket

    async def consume(self, ticket: str, binding: dict[str, str]) -> dict[str, str]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
            raise DshInvalidGrantError()
        try:
            payload = await self.redis.eval(_CONSUME, 1, self.key(ticket), self.binding(binding))
        except RedisError:
            raise DshAuthorizationUnavailableError() from None
        if not payload:
            raise DshInvalidGrantError()
        try:
            result = json.loads(payload)
            if not isinstance(result, dict) or not all(
                isinstance(result.get(key), str) for key in ("user_id", "tenant_id")
            ):
                raise ValueError("Invalid identity record")
            return result
        except (ValueError, TypeError):
            raise DshAuthorizationUnavailableError() from None
