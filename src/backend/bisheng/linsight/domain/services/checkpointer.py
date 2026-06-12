"""Plain-Redis LangGraph checkpoint saver for Linsight HITL (F035 Track B).

Replaces ``langgraph-checkpoint-redis`` which requires Redis Stack / RediSearch.
Uses only standard Redis commands — HSET/HGETALL, ZADD/ZREVRANGEBYSCORE, SCAN, DEL, EXPIRE —
so it works with any plain Redis 6+ deployment.

Key schema (all keys are UTF-8):
  Checkpoint data:
    ``linsight:ckpt:data:{thread_id}:{checkpoint_ns}:{checkpoint_id}``
    HASH fields: type, data (bytes), metadata_type, metadata (bytes), pid

  Chronological index (ZSET, score = Unix timestamp of put()):
    ``linsight:ckpt:idx:{thread_id}:{checkpoint_ns}``
    member = checkpoint_id, score = time.time()

  Pending writes per task:
    ``linsight:ckpt:write:{thread_id}:{checkpoint_ns}:{checkpoint_id}:{task_id_b64}:{idx}``
    HASH fields: task_id, channel, type, value (bytes), task_path
    task_id is base64url-encoded in the key to avoid ambiguity with the colon delimiter.

All keys expire after ``ttl_seconds`` (default: 7 days).
``adelete_thread()`` removes all keys for a thread immediately (called by the park-and-terminate path).

Thread lifecycle:
  - Park:        LangGraph interrupt() → worker releases slot
  - Resume:      /workbench/user-input lpush queue → worker picks up → Command(resume=...)
  - Terminate:   terminate endpoint calls adelete_thread() before ACKing → ensures task cannot be resumed

Usage (Track B):
    checkpointer = make_checkpointer()
    graph = create_deep_agent(..., checkpointer=checkpointer)
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    JsonPlusSerializer,
    PendingWrite,
    RunnableConfig,
)

_CKPT_DATA_KEY = "linsight:ckpt:data:{thread_id}:{checkpoint_ns}:{checkpoint_id}"
_CKPT_IDX_KEY = "linsight:ckpt:idx:{thread_id}:{checkpoint_ns}"
_CKPT_WRITE_KEY = "linsight:ckpt:write:{thread_id}:{checkpoint_ns}:{checkpoint_id}:{task_id_b64}:{idx}"
_DEFAULT_TTL = 7 * 24 * 3600  # 7 days


class PlainRedisCheckpointer(BaseCheckpointSaver):
    """LangGraph checkpoint saver backed by plain Redis (no RediSearch required).

    Thread-safe for concurrent async workers; each put() is an atomic MULTI/EXEC pipeline.
    Checkpoint serialization uses langgraph's built-in JsonPlusSerializer.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._ttl = ttl_seconds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_redis_client(self):
        from bisheng.core.cache.redis_manager import get_redis_client

        return await get_redis_client()

    @staticmethod
    def _encode_task_id(task_id: str) -> str:
        return base64.urlsafe_b64encode(task_id.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_task_id(encoded: str) -> str:
        padding = 4 - len(encoded) % 4
        return base64.urlsafe_b64decode(encoded + "=" * padding).decode()

    def _ckpt_key(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
        return _CKPT_DATA_KEY.format(thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint_id=checkpoint_id)

    def _idx_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return _CKPT_IDX_KEY.format(thread_id=thread_id, checkpoint_ns=checkpoint_ns)

    def _write_key(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        task_id: str,
        idx: int,
    ) -> str:
        return _CKPT_WRITE_KEY.format(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            task_id_b64=self._encode_task_id(task_id),
            idx=idx,
        )

    def _write_scan_pattern(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
        return _CKPT_WRITE_KEY.format(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            task_id_b64="*",
            idx="*",
        )

    async def _fetch_pending_writes(
        self,
        rc,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[PendingWrite]:
        pattern = self._write_scan_pattern(thread_id, checkpoint_ns, checkpoint_id)
        keys = [k async for k in rc.scan_iter(match=pattern, count=100)]
        if not keys:
            return []
        writes: list[PendingWrite] = []
        for key in sorted(keys):
            raw = await rc.hgetall(key)
            if not raw:
                continue
            task_id = raw[b"task_id"].decode()
            channel = raw[b"channel"].decode()
            value = self.serde.loads_typed((raw[b"type"].decode(), raw[b"value"]))
            writes.append((task_id, channel, value))
        return writes

    async def _fetch_tuple(
        self,
        rc,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> CheckpointTuple | None:
        key = self._ckpt_key(thread_id, checkpoint_ns, checkpoint_id)
        raw = await rc.hgetall(key)
        if not raw:
            return None

        checkpoint: Checkpoint = self.serde.loads_typed((raw[b"type"].decode(), raw[b"data"]))
        metadata: CheckpointMetadata = self.serde.loads_typed((raw[b"metadata_type"].decode(), raw[b"metadata"]))
        parent_id = raw.get(b"pid", b"").decode() or None
        pending_writes = await self._fetch_pending_writes(rc, thread_id, checkpoint_ns, checkpoint_id)

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_id,
                }
            }
            if parent_id
            else None,
            pending_writes=pending_writes,
        )

    # ------------------------------------------------------------------
    # BaseCheckpointSaver async API
    # ------------------------------------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config.get("configurable", {})
        thread_id: str = configurable["thread_id"]
        checkpoint_ns: str = configurable.get("checkpoint_ns", "")
        checkpoint_id: str | None = configurable.get("checkpoint_id")

        client = await self._get_redis_client()
        rc = client.async_connection

        if checkpoint_id is None:
            results = await rc.zrevrange(self._idx_key(thread_id, checkpoint_ns), 0, 0)
            if not results:
                return None
            checkpoint_id = results[0].decode()

        return await self._fetch_tuple(rc, thread_id, checkpoint_ns, checkpoint_id)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return
        configurable = config.get("configurable", {})
        thread_id: str | None = configurable.get("thread_id")
        if not thread_id:
            return
        checkpoint_ns: str = configurable.get("checkpoint_ns", "")

        client = await self._get_redis_client()
        rc = client.async_connection
        idx_key = self._idx_key(thread_id, checkpoint_ns)

        max_score: str = "+inf"
        if before:
            before_id = before.get("configurable", {}).get("checkpoint_id")
            if before_id:
                score = await rc.zscore(idx_key, before_id)
                if score is not None:
                    max_score = f"({score}"  # exclusive upper bound

        checkpoint_ids = await rc.zrevrangebyscore(
            idx_key,
            max_score,
            "-inf",
        )

        count = 0
        for cid_bytes in checkpoint_ids:
            if limit is not None and count >= limit:
                break
            checkpoint_id = cid_bytes.decode()
            tup = await self._fetch_tuple(rc, thread_id, checkpoint_ns, checkpoint_id)
            if tup is None:
                continue
            if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                continue
            yield tup
            count += 1

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        configurable = config.get("configurable", {})
        thread_id: str = configurable["thread_id"]
        checkpoint_ns: str = configurable.get("checkpoint_ns", "")
        checkpoint_id: str = checkpoint["id"]
        parent_id: str = configurable.get("checkpoint_id") or ""

        ckpt_type, ckpt_data = self.serde.dumps_typed(checkpoint)
        meta_type, meta_data = self.serde.dumps_typed(metadata)

        client = await self._get_redis_client()
        async with client.async_pipeline(transaction=True) as pipe:
            await pipe.hset(
                self._ckpt_key(thread_id, checkpoint_ns, checkpoint_id),
                mapping={
                    "type": ckpt_type,
                    "data": ckpt_data,
                    "metadata_type": meta_type,
                    "metadata": meta_data,
                    "pid": parent_id,
                },
            )
            await pipe.expire(self._ckpt_key(thread_id, checkpoint_ns, checkpoint_id), self._ttl)
            await pipe.zadd(
                self._idx_key(thread_id, checkpoint_ns),
                {checkpoint_id: time.time()},
            )
            await pipe.expire(self._idx_key(thread_id, checkpoint_ns), self._ttl)
            await pipe.execute()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config.get("configurable", {})
        thread_id: str = configurable["thread_id"]
        checkpoint_ns: str = configurable.get("checkpoint_ns", "")
        checkpoint_id: str = configurable["checkpoint_id"]

        client = await self._get_redis_client()
        async with client.async_pipeline(transaction=False) as pipe:
            for idx, (channel, value) in enumerate(writes):
                effective_idx = WRITES_IDX_MAP.get(channel, idx)
                write_key = self._write_key(thread_id, checkpoint_ns, checkpoint_id, task_id, effective_idx)
                val_type, val_data = self.serde.dumps_typed(value)
                await pipe.hset(
                    write_key,
                    mapping={
                        "task_id": task_id,
                        "channel": channel,
                        "type": val_type,
                        "value": val_data,
                        "task_path": task_path,
                    },
                )
                await pipe.expire(write_key, self._ttl)
            await pipe.execute()

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete all checkpoint data for a thread.

        Called by the park-and-terminate path so that a terminated task cannot
        be revived by a stale resume payload in the queue.
        """
        client = await self._get_redis_client()
        rc = client.async_connection
        pattern = f"linsight:ckpt:*:{thread_id}:*"
        keys = [k async for k in rc.scan_iter(match=pattern, count=100)]
        if keys:
            await rc.delete(*keys)

    # ------------------------------------------------------------------
    # Sync fallback (satisfies BaseCheckpointSaver; not used by async worker)
    # ------------------------------------------------------------------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return asyncio.get_event_loop().run_until_complete(self.aget_tuple(config))

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        async def _collect():
            return [t async for t in self.alist(config, filter=filter, before=before, limit=limit)]

        return iter(asyncio.get_event_loop().run_until_complete(_collect()))

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return asyncio.get_event_loop().run_until_complete(self.aput(config, checkpoint, metadata, new_versions))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        asyncio.get_event_loop().run_until_complete(self.aput_writes(config, writes, task_id, task_path))


def make_checkpointer(ttl_seconds: int = _DEFAULT_TTL) -> PlainRedisCheckpointer:
    """Factory used by Track B.

    Inject into ``create_deep_agent(checkpointer=make_checkpointer())``.
    Redis connection is resolved lazily on first call via ``get_redis_client()``.
    """
    return PlainRedisCheckpointer(ttl_seconds=ttl_seconds)
