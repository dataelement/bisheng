"""Redis generation-guarded activity leases, independent of streamed tokens."""

import asyncio
from uuid import uuid4

from loguru import logger

REFRESH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('PEXPIRE', KEYS[1], ARGV[2]); return 1
end
return 0
"""
FINISH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1]); return 1
end
return 0
"""


async def shared_audit_activity(request_id):
    try:
        from bisheng.core.cache.redis_manager import get_redis_client

        async with asyncio.timeout(1):
            redis = (await get_redis_client()).async_connection
            return bool(await redis.exists(RedisAuditActivity.key(request_id)))
    except Exception as error:
        logger.warning("DSH audit shared activity unavailable ({})", type(error).__name__)
        return None


class RedisAuditActivity:
    def __init__(self, redis, *, interval, maximum, observation_window):
        self.redis, self.interval, self.maximum = redis, interval, maximum
        self.ttl = int(max(observation_window, interval * 3) * 1000)
        self.active = {}
        self.task = None
        self.closed = False
        self.finish_tasks = set()

    @staticmethod
    def key(request_id):
        return f"dsh:model-audit:activity:{request_id}"

    def started(self, request_id):
        if self.closed or len(self.active) >= self.maximum:
            return
        self.active[request_id] = [str(uuid4()), False]
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    def finished(self, request_id):
        item = self.active.pop(request_id, None)
        if item is not None:
            task = asyncio.create_task(self._finish(request_id, item[0]))
            self.finish_tasks.add(task)
            task.add_done_callback(self.finish_tasks.discard)

    async def _finish(self, request_id, generation):
        try:
            await self.redis.eval(FINISH, 1, self.key(request_id), generation)
        except Exception as error:
            # Lease loss never cancels a business call.
            logger.warning("DSH audit lease finish unavailable ({})", type(error).__name__)

    async def confirmed(self, request_id):
        try:
            return bool(await self.redis.exists(self.key(request_id)))
        except Exception as error:
            logger.warning("DSH audit activity check unavailable ({})", type(error).__name__)
            return None

    async def _run(self):
        while not self.closed:
            for request_id, item in list(self.active.items()):
                try:
                    async with asyncio.timeout(min(self.interval, 1)):
                        if not item[1]:
                            await self.redis.set(self.key(request_id), item[0], px=self.ttl, nx=True)
                            item[1] = True
                            if self.active.get(request_id) is not item:
                                await self._finish(request_id, item[0])
                        else:
                            await self.redis.eval(REFRESH, 1, self.key(request_id), item[0], self.ttl)
                except Exception as error:
                    logger.warning("DSH audit activity refresh unavailable ({})", type(error).__name__)
            await asyncio.sleep(self.interval)

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for task in self.finish_tasks:
            task.cancel()
        await asyncio.gather(*self.finish_tasks, return_exceptions=True)
