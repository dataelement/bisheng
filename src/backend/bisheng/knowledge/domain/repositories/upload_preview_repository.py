"""Redis CAS serializes preview edits and the immutable registration snapshot."""

import json
from copy import deepcopy
from time import time
from uuid import uuid4

from redis.exceptions import WatchError

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingJobNotFoundError
from bisheng.core.cache.redis_manager import get_redis_client

RECEIPT_TTL = 86400
FROZEN_TTL = 7 * RECEIPT_TTL
FROZEN_PREFIX = "space_upload_frozen:"


class UploadPreviewRepository:
    @staticmethod
    def key(upload_id: str) -> str:
        return f"space_upload_receipt:{upload_id}"

    async def create(self, value: dict) -> dict:
        client = (await get_redis_client()).async_connection
        value = deepcopy(value)
        value["upload_id"] = uuid4().hex
        if not await client.set(self.key(value["upload_id"]), json.dumps(value), ex=RECEIPT_TTL, nx=True):
            raise KnowledgeOperationPlanChangedError()
        return value

    async def get(self, upload_id: str) -> dict:
        raw = await (await get_redis_client()).async_connection.get(self.key(upload_id))
        if not raw:
            raise KnowledgeProcessingJobNotFoundError()
        return json.loads(raw)

    async def mutate(self, upload_id: str, change) -> dict:
        client = (await get_redis_client()).async_connection
        key = self.key(upload_id)
        for _ in range(4):
            async with client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if not raw:
                        raise KnowledgeProcessingJobNotFoundError()
                    value = json.loads(raw)
                    frozen = change(value)
                    value["expires_at"] = int(time()) + RECEIPT_TTL
                    pipe.multi()
                    if frozen:
                        cache_key, chunks = frozen
                        pipe.hset(cache_key, mapping={str(c["metadata"]["chunk_index"]): json.dumps(c) for c in chunks})
                        pipe.expire(cache_key, FROZEN_TTL)
                    pipe.set(key, json.dumps(value), ex=RECEIPT_TTL)
                    await pipe.execute()
                    return value
                except WatchError:
                    continue
        raise KnowledgeOperationPlanChangedError()
