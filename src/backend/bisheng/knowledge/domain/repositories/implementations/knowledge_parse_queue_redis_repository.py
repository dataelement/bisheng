from __future__ import annotations

import time
from typing import Any

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.knowledge.domain.repositories.interfaces.knowledge_parse_queue_repository import (
    KnowledgeParseQueueRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseQueueTicket,
    KnowledgeParseTicketSnapshot,
    KnowledgeParseTicketState,
)


class KnowledgeParseQueueRedisRepository(KnowledgeParseQueueRepository):
    """Cluster-safe application-side queue visibility index."""

    HASH_TAG = "{knowledge_parse_queue}"
    PREFIX = f"knowledge_parse_queue:{HASH_TAG}"
    HARD_TTL_SECONDS = 26 * 60 * 60
    LEASE_SECONDS = 90

    _CREATE_SCRIPT = """
local seq = redis.call('INCR', KEYS[1])
redis.call('HSET', KEYS[2],
  'queue_ticket_id', ARGV[1], 'tenant_id', ARGV[2], 'knowledge_id', ARGV[3],
  'file_id', ARGV[4], 'stage', ARGV[5], 'priority', ARGV[6],
  'sequence', seq, 'state', 'publishing')
redis.call('EXPIRE', KEYS[2], ARGV[8])
redis.call('ZADD', KEYS[3], seq, ARGV[1])
redis.call('EXPIRE', KEYS[3], ARGV[8])
redis.call('ZADD', KEYS[4], ARGV[7], ARGV[1])
return seq
"""
    _MARK_QUEUED_SCRIPT = """
if redis.call('HGET', KEYS[1], 'state') ~= 'publishing' then return 0 end
redis.call('HSET', KEYS[1], 'state', 'queued')
redis.call('ZADD', KEYS[2], ARGV[1], ARGV[2])
return 1
"""
    _BEGIN_ATTEMPT_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
  local seq = redis.call('INCR', KEYS[1])
  redis.call('HSET', KEYS[2],
    'queue_ticket_id', ARGV[1], 'tenant_id', ARGV[3], 'knowledge_id', ARGV[4],
    'file_id', ARGV[5], 'stage', ARGV[6], 'priority', ARGV[7],
    'sequence', seq, 'state', 'processing')
  redis.call('ZADD', KEYS[7], seq, ARGV[1])
  redis.call('ZADD', KEYS[8], ARGV[10], ARGV[1])
else
  redis.call('HSET', KEYS[2], 'state', 'processing')
end
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('ZREM', KEYS[4], ARGV[1])
redis.call('ZREM', KEYS[5], ARGV[1])
redis.call('HSET', KEYS[9],
  'processing_attempt_id', ARGV[2], 'queue_ticket_id', ARGV[1],
  'tenant_id', ARGV[3], 'knowledge_id', ARGV[4], 'file_id', ARGV[5],
  'stage', ARGV[6], 'priority', ARGV[7], 'lease_deadline_ms', ARGV[9])
redis.call('EXPIRE', KEYS[2], ARGV[11])
redis.call('EXPIRE', KEYS[7], ARGV[11])
redis.call('EXPIRE', KEYS[9], ARGV[11])
redis.call('ZADD', KEYS[6], ARGV[9], ARGV[2])
redis.call('ZADD', KEYS[10], ARGV[8], ARGV[2])
redis.call('EXPIRE', KEYS[10], ARGV[11])
return 1
"""
    _RENEW_ATTEMPT_SCRIPT = """
if redis.call('HGET', KEYS[2], 'queue_ticket_id') ~= ARGV[2] then return 0 end
if redis.call('ZSCORE', KEYS[1], ARGV[1]) == false then return 0 end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
redis.call('HSET', KEYS[2], 'lease_deadline_ms', ARGV[3])
return 1
"""
    _FINISH_ATTEMPT_SCRIPT = """
if redis.call('HGET', KEYS[2], 'queue_ticket_id') ~= ARGV[2] then return 0 end
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('DEL', KEYS[2])
redis.call('ZREM', KEYS[3], ARGV[1])
if redis.call('ZCARD', KEYS[3]) == 0 then
  redis.call('DEL', KEYS[3])
  redis.call('ZREM', KEYS[4], ARGV[2])
  redis.call('ZREM', KEYS[5], ARGV[2])
  redis.call('ZREM', KEYS[6], ARGV[2])
  redis.call('ZREM', KEYS[7], ARGV[2])
  redis.call('ZREM', KEYS[8], ARGV[2])
  redis.call('DEL', KEYS[9])
end
return 1
"""
    _EXPIRE_ATTEMPT_SCRIPT = """
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if score == false or tonumber(score) > tonumber(ARGV[3]) then return 0 end
if redis.call('HGET', KEYS[2], 'queue_ticket_id') ~= ARGV[2] then return 0 end
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('DEL', KEYS[2])
redis.call('ZREM', KEYS[3], ARGV[1])
if redis.call('ZCARD', KEYS[3]) == 0 then
  redis.call('DEL', KEYS[3])
  redis.call('ZREM', KEYS[4], ARGV[2])
  redis.call('ZREM', KEYS[5], ARGV[2])
  redis.call('ZREM', KEYS[6], ARGV[2])
  redis.call('ZREM', KEYS[7], ARGV[2])
  redis.call('ZREM', KEYS[8], ARGV[2])
  redis.call('DEL', KEYS[9])
end
return 1
"""
    _REMOVE_TICKET_SCRIPT = """
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('ZREM', KEYS[4], ARGV[1])
redis.call('ZREM', KEYS[5], ARGV[1])
redis.call('DEL', KEYS[6])
redis.call('DEL', KEYS[7])
return 1
"""

    def __init__(self, redis_client: Any | None = None):
        self.redis_client = redis_client

    @classmethod
    def sequence_key(cls) -> str:
        return f"{cls.PREFIX}:sequence"

    @classmethod
    def expires_key(cls) -> str:
        return f"{cls.PREFIX}:ticket_expires"

    @classmethod
    def waiting_key(cls, priority: KnowledgeParsePriority) -> str:
        return f"{cls.PREFIX}:waiting:{priority.value}"

    @classmethod
    def processing_key(cls) -> str:
        return f"{cls.PREFIX}:processing_attempt_leases"

    @classmethod
    def ticket_key(cls, ticket_id: str) -> str:
        return f"{cls.PREFIX}:ticket:{ticket_id}"

    @classmethod
    def attempt_key(cls, attempt_id: str) -> str:
        return f"{cls.PREFIX}:attempt:{attempt_id}"

    @classmethod
    def ticket_attempts_key(cls, ticket_id: str) -> str:
        return f"{cls.PREFIX}:ticket:{ticket_id}:attempts"

    @classmethod
    def file_tickets_key(cls, tenant_id: int, knowledge_id: int, file_id: int) -> str:
        return f"{cls.PREFIX}:file:{tenant_id}:{knowledge_id}:{file_id}:tickets"

    async def _async_connection(self):
        client = self.redis_client or await get_redis_client()
        return client.async_connection

    def _sync_connection(self):
        client = self.redis_client or get_redis_client_sync()
        return client.connection

    async def create_publishing(self, ticket: KnowledgeParseQueueTicket) -> int:
        redis = await self._async_connection()
        now_ms = self._now_ms()
        sequence = await redis.eval(
            self._CREATE_SCRIPT,
            4,
            self.sequence_key(),
            self.ticket_key(ticket.queue_ticket_id),
            self.file_tickets_key(ticket.tenant_id, ticket.knowledge_id, ticket.file_id),
            self.expires_key(),
            ticket.queue_ticket_id,
            ticket.tenant_id,
            ticket.knowledge_id,
            ticket.file_id,
            ticket.stage.value,
            ticket.priority.value,
            now_ms + self.HARD_TTL_SECONDS * 1000,
            self.HARD_TTL_SECONDS,
        )
        ticket.sequence = int(sequence)
        return ticket.sequence

    async def mark_queued(self, ticket: KnowledgeParseQueueTicket) -> bool:
        redis = await self._async_connection()
        result = await redis.eval(
            self._MARK_QUEUED_SCRIPT,
            2,
            self.ticket_key(ticket.queue_ticket_id),
            self.waiting_key(ticket.priority),
            ticket.sequence,
            ticket.queue_ticket_id,
        )
        return bool(result)

    async def remove_ticket(self, ticket: KnowledgeParseQueueTicket) -> None:
        redis = await self._async_connection()
        await redis.eval(
            self._REMOVE_TICKET_SCRIPT,
            7,
            self.waiting_key(KnowledgeParsePriority.HIGH),
            self.waiting_key(KnowledgeParsePriority.MEDIUM),
            self.waiting_key(KnowledgeParsePriority.LOW),
            self.file_tickets_key(ticket.tenant_id, ticket.knowledge_id, ticket.file_id),
            self.expires_key(),
            self.ticket_key(ticket.queue_ticket_id),
            self.ticket_attempts_key(ticket.queue_ticket_id),
            ticket.queue_ticket_id,
        )

    def begin_attempt_sync(
        self,
        *,
        ticket: KnowledgeParseQueueTicket,
        attempt_id: str,
        now_ms: int | None = None,
    ) -> bool:
        redis = self._sync_connection()
        now_ms = now_ms or self._now_ms()
        lease_deadline_ms = now_ms + self.LEASE_SECONDS * 1000
        return bool(
            redis.eval(
                self._BEGIN_ATTEMPT_SCRIPT,
                10,
                self.sequence_key(),
                self.ticket_key(ticket.queue_ticket_id),
                self.waiting_key(KnowledgeParsePriority.HIGH),
                self.waiting_key(KnowledgeParsePriority.MEDIUM),
                self.waiting_key(KnowledgeParsePriority.LOW),
                self.processing_key(),
                self.file_tickets_key(ticket.tenant_id, ticket.knowledge_id, ticket.file_id),
                self.expires_key(),
                self.attempt_key(attempt_id),
                self.ticket_attempts_key(ticket.queue_ticket_id),
                ticket.queue_ticket_id,
                attempt_id,
                ticket.tenant_id,
                ticket.knowledge_id,
                ticket.file_id,
                ticket.stage.value,
                ticket.priority.value,
                now_ms,
                lease_deadline_ms,
                now_ms + self.HARD_TTL_SECONDS * 1000,
                self.HARD_TTL_SECONDS,
            )
        )

    def renew_attempt_sync(
        self,
        *,
        ticket_id: str,
        attempt_id: str,
        now_ms: int | None = None,
    ) -> bool:
        deadline_ms = (now_ms or self._now_ms()) + self.LEASE_SECONDS * 1000
        return bool(
            self._sync_connection().eval(
                self._RENEW_ATTEMPT_SCRIPT,
                2,
                self.processing_key(),
                self.attempt_key(attempt_id),
                attempt_id,
                ticket_id,
                deadline_ms,
            )
        )

    def finish_attempt_sync(
        self,
        *,
        ticket: KnowledgeParseQueueTicket,
        attempt_id: str,
    ) -> bool:
        return bool(self._finish_or_expire_sync(ticket=ticket, attempt_id=attempt_id))

    def _finish_or_expire_sync(
        self,
        *,
        ticket: KnowledgeParseQueueTicket,
        attempt_id: str,
        expire_before_ms: int | None = None,
    ) -> int:
        keys = self._attempt_cleanup_keys(ticket, attempt_id)
        if expire_before_ms is None:
            return int(
                self._sync_connection().eval(
                    self._FINISH_ATTEMPT_SCRIPT,
                    len(keys),
                    *keys,
                    attempt_id,
                    ticket.queue_ticket_id,
                )
                or 0
            )
        return int(
            self._sync_connection().eval(
                self._EXPIRE_ATTEMPT_SCRIPT,
                len(keys),
                *keys,
                attempt_id,
                ticket.queue_ticket_id,
                expire_before_ms,
            )
            or 0
        )

    async def _cleanup_expired_attempts(self, now_ms: int) -> None:
        redis = await self._async_connection()
        attempt_ids = await redis.zrangebyscore(self.processing_key(), "-inf", now_ms, start=0, num=1000)
        for raw_attempt_id in attempt_ids:
            attempt_id = self._decode(raw_attempt_id)
            metadata = self._decode_mapping(await redis.hgetall(self.attempt_key(attempt_id)))
            ticket = self._ticket_from_mapping(metadata)
            if ticket is None:
                await redis.zrem(self.processing_key(), attempt_id)
                continue
            keys = self._attempt_cleanup_keys(ticket, attempt_id)
            await redis.eval(
                self._EXPIRE_ATTEMPT_SCRIPT,
                len(keys),
                *keys,
                attempt_id,
                ticket.queue_ticket_id,
                now_ms,
            )

    async def _cleanup_expired_tickets(self, now_ms: int) -> None:
        redis = await self._async_connection()
        ticket_ids = await redis.zrangebyscore(self.expires_key(), "-inf", now_ms, start=0, num=1000)
        for raw_ticket_id in ticket_ids:
            ticket_id = self._decode(raw_ticket_id)
            metadata = self._decode_mapping(await redis.hgetall(self.ticket_key(ticket_id)))
            ticket = self._ticket_from_mapping(metadata)
            if ticket is not None:
                await self.remove_ticket(ticket)
                continue
            pipeline = redis.pipeline(transaction=False)
            pipeline.zrem(self.expires_key(), ticket_id)
            for priority in KnowledgeParsePriority:
                pipeline.zrem(self.waiting_key(priority), ticket_id)
            await pipeline.execute()

    async def get_file_ticket_snapshots(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        file_ids: list[int],
    ) -> dict[int, list[KnowledgeParseTicketSnapshot]]:
        now_ms = self._now_ms()
        await self._cleanup_expired_tickets(now_ms)
        await self._cleanup_expired_attempts(now_ms)
        redis = await self._async_connection()
        file_keys = [self.file_tickets_key(tenant_id, knowledge_id, file_id) for file_id in file_ids]
        pipeline = redis.pipeline(transaction=False)
        for key in file_keys:
            pipeline.zrange(key, 0, -1)
        ticket_lists = await pipeline.execute()

        ticket_ids = list(
            dict.fromkeys(self._decode(ticket_id) for ticket_list in ticket_lists for ticket_id in ticket_list)
        )
        pipeline = redis.pipeline(transaction=False)
        for ticket_id in ticket_ids:
            pipeline.hgetall(self.ticket_key(ticket_id))
            pipeline.zcount(self.ticket_attempts_key(ticket_id), "-inf", "+inf")
        raw_ticket_values = await pipeline.execute()

        tickets_by_id: dict[str, KnowledgeParseTicketSnapshot] = {}
        for index, ticket_id in enumerate(ticket_ids):
            metadata = self._decode_mapping(raw_ticket_values[index * 2])
            ticket = self._ticket_from_mapping(metadata)
            if ticket is None:
                continue
            tickets_by_id[ticket_id] = KnowledgeParseTicketSnapshot(
                **ticket.model_dump(),
                active_attempt_count=int(raw_ticket_values[index * 2 + 1] or 0),
            )

        queued_tickets = [
            ticket for ticket in tickets_by_id.values() if ticket.state is KnowledgeParseTicketState.QUEUED
        ]
        pipeline = redis.pipeline(transaction=False)
        pipeline.zcard(self.waiting_key(KnowledgeParsePriority.HIGH))
        pipeline.zcard(self.waiting_key(KnowledgeParsePriority.MEDIUM))
        high_count, medium_count = await pipeline.execute()
        higher_counts = {
            KnowledgeParsePriority.HIGH: 0,
            KnowledgeParsePriority.MEDIUM: int(high_count),
            KnowledgeParsePriority.LOW: int(high_count) + int(medium_count),
        }
        if queued_tickets:
            pipeline = redis.pipeline(transaction=False)
            for ticket in queued_tickets:
                pipeline.zrank(self.waiting_key(ticket.priority), ticket.queue_ticket_id)
            ranks = await pipeline.execute()
            for ticket, rank in zip(queued_tickets, ranks, strict=True):
                if rank is not None:
                    ticket.ahead_waiting_count = int(higher_counts[ticket.priority]) + int(rank)

        result: dict[int, list[KnowledgeParseTicketSnapshot]] = {file_id: [] for file_id in file_ids}
        for file_id, raw_ticket_ids in zip(file_ids, ticket_lists, strict=True):
            result[file_id] = [
                tickets_by_id[ticket_id]
                for raw_ticket_id in raw_ticket_ids
                if (ticket_id := self._decode(raw_ticket_id)) in tickets_by_id
            ]
        return result

    async def active_attempt_count(self) -> int:
        now_ms = self._now_ms()
        await self._cleanup_expired_tickets(now_ms)
        await self._cleanup_expired_attempts(now_ms)
        redis = await self._async_connection()
        return int(await redis.zcount(self.processing_key(), f"({now_ms}", "+inf") or 0)

    def _attempt_cleanup_keys(self, ticket: KnowledgeParseQueueTicket, attempt_id: str) -> list[str]:
        return [
            self.processing_key(),
            self.attempt_key(attempt_id),
            self.ticket_attempts_key(ticket.queue_ticket_id),
            self.file_tickets_key(ticket.tenant_id, ticket.knowledge_id, ticket.file_id),
            self.expires_key(),
            self.waiting_key(KnowledgeParsePriority.HIGH),
            self.waiting_key(KnowledgeParsePriority.MEDIUM),
            self.waiting_key(KnowledgeParsePriority.LOW),
            self.ticket_key(ticket.queue_ticket_id),
        ]

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)

    @classmethod
    def _decode_mapping(cls, mapping: dict[Any, Any]) -> dict[str, str]:
        return {cls._decode(key): cls._decode(value) for key, value in mapping.items()}

    @staticmethod
    def _ticket_from_mapping(metadata: dict[str, str]) -> KnowledgeParseQueueTicket | None:
        if not metadata.get("queue_ticket_id"):
            return None
        try:
            return KnowledgeParseQueueTicket(
                queue_ticket_id=metadata["queue_ticket_id"],
                tenant_id=int(metadata["tenant_id"]),
                knowledge_id=int(metadata["knowledge_id"]),
                file_id=int(metadata["file_id"]),
                stage=metadata["stage"],
                priority=metadata["priority"],
                sequence=int(metadata.get("sequence", 0)),
                state=metadata["state"],
            )
        except (KeyError, TypeError, ValueError):
            return None
