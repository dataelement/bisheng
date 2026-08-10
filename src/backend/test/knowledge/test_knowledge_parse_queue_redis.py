# ruff: noqa: E402

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

# The shared test harness pre-mocks redis during collection. Load fakeredis
# against the real installed redis package, then restore the harness modules.
_REDIS_MODULE_NAMES = [name for name in list(sys.modules) if name == "redis" or name.startswith("redis.")]
_MOCKED_REDIS_MODULES = {name: sys.modules.pop(name) for name in _REDIS_MODULE_NAMES}
try:
    real_redis = importlib.import_module("redis")
    fakeredis = importlib.import_module("fakeredis")
finally:
    for name in [name for name in list(sys.modules) if name == "redis" or name.startswith("redis.")]:
        sys.modules.pop(name, None)
    sys.modules.update(_MOCKED_REDIS_MODULES)

key_slot = real_redis.cluster.key_slot

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_parse_queue_redis_repository import (
    KnowledgeParseQueueRedisRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseAttemptKind,
    KnowledgeParsePositionState,
    KnowledgeParseQueueTicket,
    KnowledgeParseTicketState,
)
from bisheng.knowledge.domain.services.knowledge_parse_queue_service import KnowledgeParseQueueService


@pytest.fixture()
def queue_repository() -> KnowledgeParseQueueRedisRepository:
    server = fakeredis.FakeServer()
    client = SimpleNamespace(
        connection=fakeredis.FakeRedis(server=server),
        async_connection=fakeredis.FakeAsyncRedis(server=server),
    )
    return KnowledgeParseQueueRedisRepository(client)


def _ticket(ticket_id: str, file_id: int, priority: KnowledgeParsePriority) -> KnowledgeParseQueueTicket:
    return KnowledgeParseQueueTicket(
        queue_ticket_id=ticket_id,
        tenant_id=1,
        knowledge_id=10,
        file_id=file_id,
        attempt_kind=KnowledgeParseAttemptKind.INITIAL,
        priority=priority,
    )


@pytest.mark.asyncio
async def test_three_level_ahead_formula_and_processing_exclusion(queue_repository) -> None:
    high = _ticket("high-1", 1, KnowledgeParsePriority.HIGH)
    medium = _ticket("medium-1", 2, KnowledgeParsePriority.MEDIUM)
    low_first = _ticket("low-1", 3, KnowledgeParsePriority.LOW)
    low_second = _ticket("low-2", 4, KnowledgeParsePriority.LOW)
    for ticket in (low_first, high, medium, low_second):
        await queue_repository.create_publishing(ticket)
        assert await queue_repository.mark_queued(ticket)

    snapshots = await queue_repository.get_file_ticket_snapshots(
        tenant_id=1,
        knowledge_id=10,
        file_ids=[1, 2, 3, 4],
    )
    assert snapshots[1][0].ahead_waiting_count == 0
    assert snapshots[2][0].ahead_waiting_count == 1
    assert snapshots[3][0].ahead_waiting_count == 2
    assert snapshots[4][0].ahead_waiting_count == 3
    assert await queue_repository.waiting_ticket_count() == 4

    assert queue_repository.begin_attempt_sync(ticket=high, attempt_id="attempt-high")
    snapshots = await queue_repository.get_file_ticket_snapshots(
        tenant_id=1,
        knowledge_id=10,
        file_ids=[2, 3],
    )
    assert snapshots[2][0].ahead_waiting_count == 0
    assert snapshots[3][0].ahead_waiting_count == 1
    assert await queue_repository.active_attempt_count() == 1
    assert await queue_repository.waiting_ticket_count() == 3


@pytest.mark.asyncio
async def test_same_ticket_overlapping_attempts_are_isolated(queue_repository) -> None:
    ticket = _ticket("ticket-overlap", 5, KnowledgeParsePriority.MEDIUM)
    await queue_repository.create_publishing(ticket)
    await queue_repository.mark_queued(ticket)
    assert queue_repository.begin_attempt_sync(ticket=ticket, attempt_id="attempt-a")
    assert queue_repository.begin_attempt_sync(ticket=ticket, attempt_id="attempt-b")
    assert await queue_repository.active_attempt_count() == 2

    assert queue_repository.finish_attempt_sync(ticket=ticket, attempt_id="attempt-a")
    snapshots = await queue_repository.get_file_ticket_snapshots(
        tenant_id=1,
        knowledge_id=10,
        file_ids=[5],
    )
    assert snapshots[5][0].state is KnowledgeParseTicketState.PROCESSING
    assert snapshots[5][0].active_attempt_count == 1

    assert queue_repository.finish_attempt_sync(ticket=ticket, attempt_id="attempt-b")
    assert await queue_repository.active_attempt_count() == 0
    assert await queue_repository.get_file_ticket_snapshots(
        tenant_id=1,
        knowledge_id=10,
        file_ids=[5],
    ) == {5: []}


@pytest.mark.asyncio
async def test_same_file_multiple_tickets_do_not_overwrite_each_other(queue_repository) -> None:
    first = _ticket("ticket-first", 6, KnowledgeParsePriority.LOW)
    second = _ticket("ticket-second", 6, KnowledgeParsePriority.HIGH)
    for ticket in (first, second):
        await queue_repository.create_publishing(ticket)
        await queue_repository.mark_queued(ticket)
    assert queue_repository.begin_attempt_sync(ticket=first, attempt_id="attempt-first")
    assert queue_repository.finish_attempt_sync(ticket=first, attempt_id="attempt-first")

    snapshots = await queue_repository.get_file_ticket_snapshots(
        tenant_id=1,
        knowledge_id=10,
        file_ids=[6],
    )
    assert [ticket.queue_ticket_id for ticket in snapshots[6]] == ["ticket-second"]


@pytest.mark.asyncio
async def test_renewed_attempt_is_not_removed_by_stale_expiry_cleanup(queue_repository) -> None:
    ticket = _ticket("ticket-renew", 7, KnowledgeParsePriority.MEDIUM)
    await queue_repository.create_publishing(ticket)
    assert queue_repository.begin_attempt_sync(ticket=ticket, attempt_id="attempt-renew", now_ms=1_000)
    assert queue_repository.renew_attempt_sync(
        ticket_id=ticket.queue_ticket_id,
        attempt_id="attempt-renew",
        now_ms=5_000,
    )

    await queue_repository._cleanup_expired_attempts(2_000)
    assert int(queue_repository.redis_client.connection.zcard(queue_repository.processing_key())) == 1


def test_all_queue_keys_share_one_cluster_slot(queue_repository) -> None:
    ticket = _ticket("slot-ticket", 8, KnowledgeParsePriority.LOW)
    keys = [
        queue_repository.sequence_key(),
        queue_repository.expires_key(),
        queue_repository.waiting_key(ticket.priority),
        queue_repository.processing_key(),
        queue_repository.ticket_key(ticket.queue_ticket_id),
        queue_repository.attempt_key("slot-attempt"),
        queue_repository.ticket_attempts_key(ticket.queue_ticket_id),
        queue_repository.file_tickets_key(1, 10, 8),
    ]
    assert len({key_slot(key.encode()) for key in keys}) == 1


@pytest.mark.asyncio
async def test_position_service_prefers_processing_then_best_queued_and_degrades(queue_repository) -> None:
    low = _ticket("position-low", 9, KnowledgeParsePriority.LOW)
    high = _ticket("position-high", 9, KnowledgeParsePriority.HIGH)
    for ticket in (low, high):
        await queue_repository.create_publishing(ticket)
        await queue_repository.mark_queued(ticket)
    service = KnowledgeParseQueueService(queue_repository)
    file = KnowledgeFile(id=9, tenant_id=1, knowledge_id=10, file_name="9.pdf")

    queued = await service.get_positions(tenant_id=1, knowledge_id=10, files=[file])
    assert queued.items[0].state is KnowledgeParsePositionState.QUEUED
    assert queued.items[0].ahead_waiting_count == 0
    assert queued.waiting_count == 2

    queue_repository.begin_attempt_sync(ticket=low, attempt_id="position-attempt")
    processing = await service.get_positions(tenant_id=1, knowledge_id=10, files=[file])
    assert processing.items[0].state is KnowledgeParsePositionState.PROCESSING
    assert processing.active_count == 1
    assert processing.waiting_count == 1

    broken_repository = SimpleNamespace(
        get_file_ticket_snapshots=AsyncFail(),
        active_attempt_count=AsyncFail(),
        waiting_ticket_count=AsyncFail(),
    )
    unavailable = await KnowledgeParseQueueService(broken_repository).get_positions(
        tenant_id=1,
        knowledge_id=10,
        files=[file],
    )
    assert unavailable.items[0].state is KnowledgeParsePositionState.UNAVAILABLE
    assert unavailable.waiting_count is None

    file.status = KnowledgeFileStatus.SUCCESS.value
    not_queued = await KnowledgeParseQueueService(broken_repository).get_positions(
        tenant_id=1,
        knowledge_id=10,
        files=[file],
    )
    assert not_queued.items[0].state is KnowledgeParsePositionState.NOT_QUEUED


class AsyncFail:
    def __call__(self, *args, **kwargs):
        async def fail():
            raise RuntimeError("redis unavailable")

        return fail()
