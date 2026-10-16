"""Per-tenant/code admission leases shared by every API replica."""

import re
from uuid import uuid4

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.dsh import DshToolConcurrencyExceededError, DshToolServiceUnavailableError

_ACQUIRE = """
local now = redis.call('TIME')
local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local values = redis.call('HGETALL', KEYS[1])
if #values > 32 then return -2 end
local active = 0
for i = 1, #values, 2 do
    local deadline = tonumber(values[i + 1])
    if not deadline then return -2 end
    if deadline <= ms then redis.call('HDEL', KEYS[1], values[i])
    else active = active + 1 end
end
if active >= tonumber(ARGV[1]) then return -1 end
redis.call('HSET', KEYS[1], ARGV[2], ms + 65000)
redis.call('PEXPIRE', KEYS[1], 65000)
return 1
"""


class ToolLeases:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def key(tenant_id, tool_code):
        if type(tenant_id) is not int or tenant_id < 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,125}", tool_code):
            raise DshToolServiceUnavailableError()
        return f"dsh:tool:invoke:leases:{{{tenant_id}:{tool_code}}}"

    async def acquire(self, tenant_id, tool_code, limit):
        if type(limit) is not int or not 1 <= limit <= 16:
            raise DshToolServiceUnavailableError()
        owner = f"lease:{uuid4().hex}"
        try:
            result = await self.redis.eval(_ACQUIRE, 1, self.key(tenant_id, tool_code), limit, owner)
        except RedisError:
            raise DshToolServiceUnavailableError() from None
        if result == -1:
            raise DshToolConcurrencyExceededError()
        if result != 1:
            raise DshToolServiceUnavailableError()
        return owner

    async def release(self, tenant_id, tool_code, owner):
        try:
            await self.redis.hdel(self.key(tenant_id, tool_code), owner)
        except RedisError:
            # Cleanup is best effort: the fixed lease deadline bounds retained capacity.
            logger.warning("Tool lease cleanup unavailable tenant={} tool={}", tenant_id, tool_code)
