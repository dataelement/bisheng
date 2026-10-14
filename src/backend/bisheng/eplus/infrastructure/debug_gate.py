"""One distributed debug slot, disjoint from all production robot leases."""

import uuid
from contextlib import asynccontextmanager

from fastapi import HTTPException


class RedisDebugGate:
    def __init__(self, redis):
        self.redis = redis

    @asynccontextmanager
    async def acquire(self):
        token = uuid.uuid4().hex
        key = "eplus:debug:active-run"
        if not await self.redis.set(key, token, nx=True, ex=210):
            raise HTTPException(429, "debug capacity reached")
        try:
            yield
        finally:
            await self.redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
                1,
                key,
                token,
            )
