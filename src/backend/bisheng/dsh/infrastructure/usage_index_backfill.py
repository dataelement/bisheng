"""Offline-only discovery of retained usage streams; runtime consumers never call this module."""

import re


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


async def backfill_usage_indexes(redis, *, prefix="dsh_quota", apply=False):
    """Run with ALL producers and consumers stopped; repeat safely after interruption.

    Only scheduling indexes change. Event payloads, consumer groups, ACK state,
    request ledgers, counters and SQL are never rewritten or deleted.
    """
    if not prefix or any(character in prefix for character in "{}*?[]"):
        raise ValueError("Invalid quota index prefix")
    ready = prefix + ":projection_work"
    partitions = ready + ":partitions"
    owners = prefix + ":projection_work_owners"
    for key, expected in ((ready, "zset"), (partitions, "set"), (owners, "hash")):
        if _text(await redis.type(key)) not in {"none", expected}:
            raise ValueError("Invalid quota scheduling index type")
    counts = {"streams": 0, "backlog_streams": 0, "unindexed_partitions": 0, "unscheduled_streams": 0}
    async for stream in redis.scan_iter(match=prefix + ":*:events", count=500):
        if re.fullmatch(re.escape(prefix) + r":\{([1-9][0-9]*):([1-9][0-9]*)\}:events", _text(stream)) is None:
            raise ValueError("Malformed quota stream partition")
        if _text(await redis.type(stream)) != "stream":
            raise ValueError("Quota event key must be a Redis Stream")
        counts["streams"] += 1
        groups = await redis.xinfo_groups(stream)
        group = next((row for row in groups if _text(row["name"]) == "dsh-sql-projection-v1"), None)
        backlog = bool(
            await redis.xlen(stream)
            if group is None
            else group["pending"]
            or await redis.xrange(stream, min="(" + _text(group["last-delivered-id"]), max="+", count=1)
        )
        counts["backlog_streams"] += int(backlog)
        if apply:
            now = await redis.time()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.sadd(partitions, stream)
                # No consumer is running: expired/backoff claims from the old
                # worker can be made ready again without waiting for its lease.
                if backlog:
                    pipe.zadd(ready, {stream: now[0] * 1000 + now[1] // 1000})
                else:
                    pipe.zrem(ready, stream)
                pipe.hdel(owners, stream)
                await pipe.execute()
        if not await redis.sismember(partitions, stream):
            counts["unindexed_partitions"] += 1
        if backlog and await redis.zscore(ready, stream) is None:
            counts["unscheduled_streams"] += 1
    counts["ready"] = not (counts["unindexed_partitions"] or counts["unscheduled_streams"])
    return counts
