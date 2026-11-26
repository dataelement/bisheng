"""Durable, coalescing user work on the supported standalone/Sentinel quota Redis."""

from pathlib import Path
from uuid import uuid4


def with_usage_schedule(source: str, *, stream_key: int) -> str:
    """Schedule in the same Lua invocation as the ledger mutation, including idempotent retries."""
    return (
        "local work=KEYS[#KEYS]\n"
        "local kind=redis.call('TYPE',work).ok\n"
        "if kind~='none' and kind~='zset' then return {'DENY','bad_projection_work_type'} end\n"
        "local partitions=work..':partitions'\n"
        "local kind=redis.call('TYPE',partitions).ok\n"
        "if kind~='none' and kind~='set' then return {'DENY','bad_projection_partitions_type'} end\n"
        "local function mutate()\n" + source + "\nend\n"
        "local result=mutate()\n"
        "if result[1]=='OK' or result[1]=='EXISTS' or result[1]=='CONFIRMED' or result[1]=='UNKNOWN' then\n"
        " local now=redis.call('TIME')\n"
        f" redis.call('ZADD',work,'NX',tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000),KEYS[{stream_key}])\n"
        f" redis.call('SADD',partitions,KEYS[{stream_key}])\n"
        "end\nreturn result\n"
    )


class UsageWorkQueue:
    lease_ms = 30000

    def __init__(self, quota):
        self.quota = quota
        self.ready = quota.prefix + ":projection_work"
        self.owners = quota.prefix + ":projection_work_owners"
        self.partitions = self.ready + ":partitions"

    async def _run(self, command, *args, stream=""):
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            return await self.quota.redis.eval(
                (Path(__file__).parent / "lua/usage_work.lua").read_text(),
                4,
                self.ready,
                self.owners,
                stream or self.ready,
                self.partitions,
                command,
                *args,
            )

    async def claim(self):
        return await self._run("claim", uuid4().hex, self.lease_ms)

    async def finish(self, claim, *, retry_ms=0, failed=False):
        stream, owner, last_id = claim
        return await self._run("finish", owner, last_id, retry_ms, int(failed), stream=stream)

    async def mark(self, stream):
        return await self._run("mark", stream)
