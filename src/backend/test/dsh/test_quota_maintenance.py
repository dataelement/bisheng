"""AC-24/30/31/34: real capacity pressure, retention proof, and bounded fair drain."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db


def projector(quota, usage_db):
    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    return DshProjectionService(quota, repository, consumer="maintenance")


async def test_capacity_blocks_new_admission_and_display_but_allows_inflight(quota):
    event = running()
    await quota.check_and_start(event)
    quota.memory_budget_bytes = 1
    quota.memory_headroom_bytes = 0
    with pytest.raises(QuotaRejected, match="capacity_backpressure"):
        await quota.check_and_start(running())
    assert (await quota.read_usage(2, 20, "2026-09"))["quota_state"] == "unavailable"
    await quota.record_usage(terminal(event), 1)
    assert (await quota.get_request(event)).total_tokens == 300


async def test_backlog_threshold_is_shared_by_admission_and_display(quota):
    await quota.check_and_start(running())
    quota.backlog_high_watermark = 1
    with pytest.raises(QuotaRejected, match="projection_backpressure"):
        await quota.check_and_start(running())
    assert (await quota.read_usage(2, 20, "2026-09"))["quota_state"] == "unavailable"


async def test_retention_requires_confirmed_sql_age_ack_and_reliable_terminal(quota, usage_db):
    service = projector(quota, usage_db)
    a, b, c = running(), running(), running()
    for event in (a, b, c):
        await quota.check_and_start(event)
    await quota.record_usage(terminal(a), 1)
    unknown = terminal(b).model_copy(
        update={
            "status": "USAGE_UNKNOWN",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "usage_source": None,
            "settled_at": None,
        }
    )
    await quota.record_usage(unknown, 1)
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 0
    assert await service.project_batch(2, 20) == 5
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 0
    old_ms = int((datetime.now(UTC) - timedelta(days=40)).timestamp() * 1000)
    await quota.redis.hset(quota.keys(a)[4], "sql_confirmed_ms", str(old_ms))
    # Make a confirmed event pending again; cleanup must preserve the request until ACK.
    await quota.redis.xgroup_setid(quota.keys(a)[5], service.group, "0-0")
    pending = await quota.redis.xreadgroup(service.group, "other", {quota.keys(a)[5]: ">"}, count=500)
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 0
    await quota.redis.xack(quota.keys(a)[5], service.group, *[row[0] for row in pending[0][1]])
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 2
    assert await quota.get_request(a) is None
    assert (await quota.get_request(b)).status == "USAGE_UNKNOWN"
    assert (await quota.get_request(c)).status == "RUNNING"
    assert await quota.redis.zcard(quota.keys(c)[0].removesuffix(":gate") + ":running") == 1


async def test_projection_drains_bounded_batches_then_requests_continuation(quota, usage_db):
    service = projector(quota, usage_db)
    for _ in range(6):
        await quota.check_and_start(running())
    calls = 0
    original = service.project_batch

    async def count_batch(*args):
        nonlocal calls
        calls += 1
        return await original(*args)

    service.project_batch = count_batch
    result = await service.drain_user(2, 20, max_batches=1, max_seconds=10)
    assert result == (6, False)
    assert calls == 1


async def test_projection_more_than_one_batch_is_fair_and_retains_running(quota, usage_db):
    service = projector(quota, usage_db)
    for _ in range(503):
        await quota.check_and_start(running())
    assert await service.drain_user(2, 20, max_batches=1, max_seconds=10) == (500, True)
    assert await service.drain_user(2, 20, max_batches=1, max_seconds=10) == (3, False)
    assert await quota.redis.zcard(quota.keys(running())[0].removesuffix(":gate") + ":running") == 503
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 0


async def test_missing_running_index_closes_admission_and_inspection(quota, usage_db):
    event = running()
    await quota.check_and_start(event)
    await quota.redis.delete(quota.keys(event)[0].removesuffix(":gate") + ":running")
    with pytest.raises(QuotaRejected, match="running_index_missing"):
        await quota.check_and_start(running())
    with pytest.raises(QuotaRejected, match="running_index_missing"):
        await projector(quota, usage_db).inspect_running(2, 20, now=datetime.now(UTC), timeout_seconds=30)
    # Existing work may still settle even while the index requires controlled recovery.
    await quota.record_usage(terminal(event), 1)
    assert (await quota.get_request(event)).total_tokens == 300


async def test_cleanup_latest_ack_never_removes_older_pending_request(quota, usage_db):
    service = projector(quota, usage_db)
    event = running()
    await quota.check_and_start(event)
    await quota.record_usage(terminal(event), 1)
    await service.project_batch(2, 20)
    stream, request = quota.keys(event)[5], quota.keys(event)[4]
    await quota.redis.hset(request, "sql_confirmed_ms", "1")
    await quota.redis.xgroup_setid(stream, service.group, "0-0")
    pending = await quota.redis.xreadgroup(service.group, "older", {stream: ">"}, count=500)
    await quota.redis.xack(stream, service.group, pending[0][1][-1][0])
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 1
    assert await quota.get_request(event) is not None
    await quota.redis.xack(stream, service.group, pending[0][1][0][0])
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 1
    assert await quota.get_request(event) is None


async def test_cleaned_stream_does_not_leave_permanent_backpressure(quota, usage_db):
    service = projector(quota, usage_db)
    event = running()
    await quota.check_and_start(event)
    await quota.record_usage(terminal(event), 1)
    await service.project_batch(2, 20)
    await quota.redis.hset(quota.keys(event)[4], "sql_confirmed_ms", "1")
    assert await service.cleanup_batch(2, 20, retention_seconds=1) == 2
    await quota.redis.hset(quota.keys(event)[0], mapping={"limit": "3000", "limit:4": "2000"})
    assert (await quota.read_usage(2, 20, "2026-09"))["quota_state"] == "ready"
    assert (await quota.check_and_start(running())).status == "RUNNING"
