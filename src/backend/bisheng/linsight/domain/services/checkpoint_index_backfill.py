"""One-time, resumable indexing of legacy checkpoints while checkpoint writers are stopped."""

from bisheng.linsight.domain.services.checkpointer import _INDEX_READY


async def backfill_checkpoint_indexes(redis, *, apply=False):
    counts = {"writes": 0, "checkpoints": 0, "unindexed_writes": 0, "unindexed_checkpoints": 0}
    # Index writes before publishing completeness markers. An interrupted run can
    # be repeated; readers fail explicitly rather than silently omit old writes.
    async for key in redis.scan_iter(match="linsight:ckpt:write:*", count=500):
        text = key.decode() if isinstance(key, bytes) else key
        base, task, idx = text.rsplit(":", 2)
        if not task or not idx.lstrip("-").isdigit():
            raise ValueError("Malformed legacy checkpoint write key")
        index = base.replace("linsight:ckpt:write:", "linsight:ckpt:writes:", 1)
        ttl = await redis.pttl(key)
        if ttl == -2:
            continue
        if ttl <= 0:
            raise ValueError("Legacy checkpoint write must have a finite positive TTL")
        counts["writes"] += 1
        if apply:
            ttl = max(ttl, await redis.pttl(index))
            async with redis.pipeline(transaction=True) as pipe:
                pipe.sadd(index, key)
                pipe.pexpire(index, ttl)
                await pipe.execute()
        if not await redis.sismember(index, key):
            counts["unindexed_writes"] += 1
    async for key in redis.scan_iter(match="linsight:ckpt:data:*", count=500):
        text = key.decode() if isinstance(key, bytes) else key
        index = text.replace("linsight:ckpt:data:", "linsight:ckpt:writes:", 1)
        ttl = await redis.pttl(key)
        if ttl == -2:
            continue
        if ttl <= 0:
            raise ValueError("Legacy checkpoint must have a finite positive TTL")
        counts["checkpoints"] += 1
        if apply:
            ttl = max(ttl, await redis.pttl(index))
            async with redis.pipeline(transaction=True) as pipe:
                pipe.sadd(index, _INDEX_READY)
                pipe.pexpire(index, ttl)
                await pipe.execute()
        if not await redis.sismember(index, _INDEX_READY):
            counts["unindexed_checkpoints"] += 1
    counts["ready"] = not (counts["unindexed_writes"] or counts["unindexed_checkpoints"])
    return counts
