"""Redis registration, presence, and request queues for mobile access.

Keys for one desktop share the ``{desktopId}`` hash tag, so the Lua updates stay
on one Redis Cluster slot. The per-user index lives on another slot and is
repaired from the registration, which remains the ownership record.
"""

import hashlib
import json

_BIND = """
local tenant = redis.call('HGET', KEYS[1], 'tenantId')
local old = redis.call('GET', KEYS[2]) or ''
if not tenant then
    redis.call('HSET', KEYS[1], 'tenantId', ARGV[1], 'userId', ARGV[2], 'displayName', ARGV[3], 'secretHash', ARGV[4])
    if old ~= '' then redis.call('DEL', KEYS[2]) end
    return {1, old, '', ''}
end
local user = redis.call('HGET', KEYS[1], 'userId')
local sameOwner = tenant == ARGV[1] and user == ARGV[2]
local hash = redis.call('HGET', KEYS[1], 'secretHash')
if not sameOwner and hash ~= ARGV[4] then
    return {0, '', '', ''}
end
redis.call('HSET', KEYS[1], 'tenantId', ARGV[1], 'userId', ARGV[2], 'displayName', ARGV[3], 'secretHash', ARGV[4])
if old ~= '' then redis.call('DEL', KEYS[2]) end
if sameOwner then
    return {2, old, '', ''}
end
return {3, old, tenant, user}
"""

_ACTIVATE = """
local hash = redis.call('HGET', KEYS[1], 'secretHash')
if not hash or hash ~= ARGV[1] then
    return {0, ''}
end
local old = redis.call('GET', KEYS[2]) or ''
redis.call('SET', KEYS[2], ARGV[2], 'EX', tonumber(ARGV[3]))
return {1, old}
"""

_UNBIND = """
local tenant = redis.call('HGET', KEYS[1], 'tenantId')
if not tenant then
    return {1, ''}
end
if tenant ~= ARGV[1] or redis.call('HGET', KEYS[1], 'userId') ~= ARGV[2] then
    return {0, ''}
end
local old = redis.call('GET', KEYS[2]) or ''
redis.call('DEL', KEYS[1], KEYS[2])
return {1, old}
"""

_REFRESH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""

_CLEAR = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RATE = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


class MobileRegistration:
    def __init__(self, tenant_id: str, user_id: str, display_name: str, secret_hash: str):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.display_name = display_name
        self.secret_hash = secret_hash


class MobileAccessStore:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def registration_key(desktop_id: str) -> str:
        return f"dsh:mobile:{{{desktop_id}}}:registration"

    @staticmethod
    def online_key(desktop_id: str) -> str:
        return f"dsh:mobile:{{{desktop_id}}}:online"

    @staticmethod
    def request_key(desktop_id: str, connection_id: str) -> str:
        return f"dsh:mobile:{{{desktop_id}}}:request:{connection_id}"

    @staticmethod
    def response_key(desktop_id: str, request_id: str) -> str:
        return f"dsh:mobile:{{{desktop_id}}}:response:{request_id}"

    @staticmethod
    def index_key(tenant_id: str, user_id: str) -> str:
        return f"dsh:mobile:index:{tenant_id}:{user_id}"

    @staticmethod
    def rate_key(client_ip: str, desktop_id: str) -> str:
        digest = hashlib.sha256(f"{client_ip}\n{desktop_id}".encode()).hexdigest()
        return f"dsh:mobile:rate:{digest}"

    async def bind(self, desktop_id: str, tenant_id: str, user_id: str, display_name: str, secret_hash: str):
        result = await self._eval(
            _BIND,
            [self.registration_key(desktop_id), self.online_key(desktop_id)],
            [tenant_id, user_id, display_name, secret_hash],
        )
        return _bind_result(result)

    async def add_index(self, tenant_id: str, user_id: str, desktop_id: str) -> None:
        await self.redis.sadd(self.index_key(tenant_id, user_id), desktop_id)

    async def remove_index(self, tenant_id: str, user_id: str, desktop_id: str) -> None:
        await self.redis.srem(self.index_key(tenant_id, user_id), desktop_id)

    async def desktop_ids(self, tenant_id: str, user_id: str) -> list[str]:
        values = await self.redis.smembers(self.index_key(tenant_id, user_id))
        return sorted(_text(value) for value in values)

    async def read(self, desktop_id: str) -> MobileRegistration | None:
        values = await self.redis.hgetall(self.registration_key(desktop_id))
        if not values:
            return None
        decoded = {_text(key): _text(value) for key, value in values.items()}
        if not decoded.get("tenantId") or not decoded.get("userId") or not decoded.get("secretHash"):
            return None
        return MobileRegistration(
            decoded["tenantId"],
            decoded["userId"],
            decoded.get("displayName", ""),
            decoded["secretHash"],
        )

    async def activate(self, desktop_id: str, secret_hash: str, connection_id: str, ttl_seconds: int):
        result = await self._eval(
            _ACTIVATE,
            [self.registration_key(desktop_id), self.online_key(desktop_id)],
            [secret_hash, connection_id, ttl_seconds],
        )
        status, old = _pair(result)
        if status != 1:
            return None
        return old

    async def unbind(self, desktop_id: str, tenant_id: str, user_id: str):
        result = await self._eval(
            _UNBIND,
            [self.registration_key(desktop_id), self.online_key(desktop_id)],
            [tenant_id, user_id],
        )
        return _pair(result)

    async def current_connection(self, desktop_id: str) -> str:
        return _text(await self.redis.get(self.online_key(desktop_id)))

    async def refresh(self, desktop_id: str, connection_id: str, ttl_seconds: int) -> bool:
        result = await self._eval(_REFRESH, [self.online_key(desktop_id)], [connection_id, ttl_seconds])
        return int(result or 0) == 1

    async def clear_if_current(self, desktop_id: str, connection_id: str) -> None:
        await self._eval(_CLEAR, [self.online_key(desktop_id)], [connection_id])

    async def push_request(self, desktop_id: str, connection_id: str, message: dict) -> None:
        key = self.request_key(desktop_id, connection_id)
        await self.redis.rpush(key, json.dumps(message, separators=(",", ":")))
        await self.redis.expire(key, 120)

    async def pop_request(self, desktop_id: str, connection_id: str, timeout: float) -> dict | None:
        return await self._pop(self.request_key(desktop_id, connection_id), timeout)

    async def push_response(self, desktop_id: str, request_id: str, message: dict) -> None:
        key = self.response_key(desktop_id, request_id)
        await self.redis.rpush(key, json.dumps(message, separators=(",", ":")))
        await self.redis.expire(key, 60)

    async def pop_response(self, desktop_id: str, request_id: str, timeout: float) -> dict | None:
        return await self._pop(self.response_key(desktop_id, request_id), timeout)

    async def failure_count(self, client_ip: str, desktop_id: str) -> int:
        value = await self.redis.get(self.rate_key(client_ip, desktop_id))
        return int(value) if value else 0

    async def record_failure(self, client_ip: str, desktop_id: str) -> int:
        result = await self._eval(_RATE, [self.rate_key(client_ip, desktop_id)], [])
        return int(result or 0)

    async def _pop(self, key: str, timeout: float) -> dict | None:
        popped = await self.redis.blpop(key, timeout=max(timeout, 0.01))
        if not popped:
            return None
        raw = popped[1]
        try:
            message = json.loads(_text(raw))
        except json.JSONDecodeError:
            return None
        return message if isinstance(message, dict) else None

    async def _eval(self, script: str, keys: list[str], args: list):
        return await self.redis.eval(script, len(keys), *keys, *args)


def _bind_result(result) -> tuple[int, str, str, str]:
    status, previous = _pair(result)
    if not isinstance(result, (list, tuple)):
        return status, previous, "", ""
    previous_tenant = _text(result[2]) if len(result) > 2 else ""
    previous_user = _text(result[3]) if len(result) > 3 else ""
    return status, previous, previous_tenant, previous_user


def _pair(result) -> tuple[int, str]:
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return 0, ""
    return int(result[0] or 0), _text(result[1])


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)
