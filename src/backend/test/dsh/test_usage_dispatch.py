"""Real Redis/SQL acceptance for coalescing, fencing and durable usage projection."""

from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.services.usage_dispatch import UsageDispatcher
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.dsh.infrastructure.usage_work import UsageWorkQueue
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_maintenance import projector
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db


async def test_events_coalesce_and_dispatch_to_sql_within_ten_seconds(quota, usage_db):
    start = monotonic()
    work = UsageWorkQueue(quota)
    a, b = running(), running()
    await quota.check_and_start(a)
    score = await quota.redis.zscore(work.ready, quota.keys(a)[5])
    await quota.check_and_start(b)
    await quota.record_usage(terminal(a), 1)
    await quota.record_usage(terminal(b), 1)
    assert await quota.redis.zcard(work.ready) == 1
    assert await quota.redis.zscore(work.ready, quota.keys(a)[5]) == score
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    assert await dispatcher.dispatch() == 4
    assert monotonic() - start < 10
    with Session(usage_db) as db:
        rows = list(db.exec(select(DshModelCall)))
        assert len(rows) == 2
        assert all(row.status == "SUCCEEDED" and row.total_tokens == 300 for row in rows)
    assert (await quota.redis.xpending(quota.keys(a)[5], dispatcher.projection.group))["pending"] == 0
    assert await quota.redis.zcard(work.ready) == 0
    assert await dispatcher.dispatch() == 0


async def test_idle_dispatch_never_scans_or_fans_out(quota, usage_db, monkeypatch):
    scan = AsyncMock(side_effect=AssertionError("Idle dispatch must not SCAN"))
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    with monkeypatch.context() as patch:
        patch.setattr(quota.redis, "scan", scan)
        for _ in range(30):
            assert await dispatcher.dispatch() == 0
    scan.assert_not_awaited()
    assert await quota.redis.hlen(dispatcher.work.owners) == 0


async def test_dispatch_yields_after_user_bound_and_restores_tenant(quota, usage_db):
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.dsh.domain.models.user_policy import DshUserPolicy

    with Session(usage_db) as db, db.begin():
        db.add(DshUserPolicy(tenant_id=3, user_id=30, model_id=4, enabled=1, updated_by=1))
    template = quota.keys(running())
    for tenant, user in [(2, 20), (2, 21), (3, 30)]:
        event = running().model_copy(update={"tenant_id": tenant, "user_id": user})
        if (tenant, user) != (2, 20):
            for source, target in zip(template[:3], quota.keys(event)[:3], strict=True):
                await quota.redis.hset(target, mapping=await quota.redis.hgetall(source))
            await quota.redis.hset(quota.keys(event)[0], "running_count", "0")
        token = current_tenant_id.set(tenant)
        try:
            await quota.check_and_start(event)
        finally:
            current_tenant_id.reset(token)
    saved = current_tenant_id.get()
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    assert await dispatcher.dispatch(max_users=2) == 2
    assert current_tenant_id.get() == saved
    assert await quota.redis.zcard(dispatcher.work.ready) == 1
    assert await dispatcher.dispatch() == 1
    assert current_tenant_id.get() == saved


async def test_finish_cannot_erase_concurrent_new_event(quota, usage_db):
    a = running()
    await quota.check_and_start(a)
    work = UsageWorkQueue(quota)
    claim = await work.claim()
    await projector(quota, usage_db).drain_user(2, 20)
    await quota.record_usage(terminal(a), 1)
    assert await work.finish(claim) == 1
    assert await work.claim()


async def test_write_after_finish_recreates_pending_work(quota):
    a = running()
    await quota.check_and_start(a)
    work = UsageWorkQueue(quota)
    claim = await work.claim()
    assert await work.finish(claim) == 1
    assert await work.claim() == []
    await quota.record_usage(terminal(a), 1)
    assert await work.claim()


async def test_crashed_claim_reclaimed_and_stale_completion_fenced(quota):
    a = running()
    await quota.check_and_start(a)
    work = UsageWorkQueue(quota)
    old = await work.claim()
    assert await work.claim() == []
    await quota.redis.zadd(work.ready, {old[0]: 0})
    successor = await work.claim()
    assert successor[1] != old[1]
    assert await work.finish(old) == 0
    assert await quota.redis.hget(work.owners, old[0]) == successor[1]
    assert await work.finish(successor) == 1


async def test_failure_backoff_survives_concurrent_writes(quota):
    a = running()
    await quota.check_and_start(a)
    work = UsageWorkQueue(quota)
    claim = await work.claim()
    await quota.record_usage(terminal(a), 1)
    assert await work.finish(claim, retry_ms=30000, failed=True) == 1
    assert await work.claim() == []
    assert await quota.redis.zcard(work.ready) == 1


async def test_sql_failure_retains_work_and_pending_until_recovery(quota, usage_db):
    a = running()
    await quota.check_and_start(a)
    service = projector(quota, usage_db)
    original = service.repository_scope

    @contextmanager
    def failed_transaction():
        raise RuntimeError("SQL unavailable")
        yield  # pragma: no cover

    service.repository_scope = failed_transaction
    dispatcher = UsageDispatcher(service)
    assert await dispatcher.dispatch() == 0
    assert await quota.redis.zcard(dispatcher.work.ready) == 1
    assert (await quota.redis.xpending(quota.keys(a)[5], service.group))["pending"] == 1
    assert await dispatcher.work.claim() == []
    service.repository_scope = original
    await quota.redis.zadd(dispatcher.work.ready, {quota.keys(a)[5]: 0})
    assert await dispatcher.dispatch() == 1
    assert await quota.redis.zcard(dispatcher.work.ready) == 0


async def test_unknown_lag_with_empty_read_does_not_request_continuation(quota, usage_db, monkeypatch):
    await quota.check_and_start(running())
    service = projector(quota, usage_db)
    await service.drain_user(2, 20)
    original = quota.redis.xinfo_groups

    async def unknown_lag(stream):
        return [{**group, "lag": None} for group in await original(stream)]

    monkeypatch.setattr(quota.redis, "xinfo_groups", unknown_lag)
    assert await service.drain_user(2, 20) == (0, False)
    assert await UsageDispatcher(service).dispatch() == 0
    assert await quota.redis.zcard(UsageWorkQueue(quota).ready) == 0


async def test_other_consumer_pending_waits_instead_of_busy_loop(quota, usage_db):
    a = running()
    await quota.check_and_start(a)
    service = projector(quota, usage_db)
    stream = quota.keys(a)[5]
    await quota.redis.xgroup_create(stream, service.group, id="0-0")
    await quota.redis.xreadgroup(service.group, "crashed", {stream: ">"}, count=500)
    dispatcher = UsageDispatcher(service)
    assert await dispatcher.dispatch() == 0
    assert await dispatcher.work.claim() == []
    pending = await quota.redis.xpending_range(stream, service.group, "-", "+", 1)
    await quota.redis.xclaim(stream, service.group, "crashed", 0, [pending[0]["message_id"]], idle=60001)
    await quota.redis.zadd(dispatcher.work.ready, {stream: 0})
    assert await dispatcher.dispatch() == 1
    assert await quota.redis.zcard(dispatcher.work.ready) == 0


async def test_invalid_index_type_denied_before_ledger_mutation(quota):
    a = running()
    await quota.redis.set(UsageWorkQueue(quota).ready, "invalid")
    with pytest.raises(QuotaRejected, match="bad_projection_work_type"):
        await quota.check_and_start(a)
    assert not await quota.redis.exists(quota.keys(a)[4])


async def test_stale_marker_for_missing_stream_drains_once(quota, usage_db):
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    await dispatcher.work.mark(quota.keys(running())[5])
    assert await dispatcher.dispatch() == 0
    assert await quota.redis.zcard(dispatcher.work.ready) == 0


async def test_expired_projection_lease_keeps_work_scheduled(quota, usage_db, monkeypatch):
    a = running()
    await quota.check_and_start(a)
    service = projector(quota, usage_db)

    async def slow_batch(tenant, user):
        await quota.redis.delete(quota.keys(a)[0].removesuffix(":gate") + ":projection_lease")
        return 500

    monkeypatch.setattr(service, "project_batch", slow_batch)
    assert await service.drain_user(2, 20, max_seconds=60) == (500, True)


async def test_repair_rediscovers_legacy_backlog_without_celery_messages(quota, usage_db):
    await quota.check_and_start(running().model_copy(update={"started_at": datetime.now(UTC).replace(tzinfo=None)}))
    work = UsageWorkQueue(quota)
    await quota.redis.delete(work.ready)
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    for _ in range(50):
        await dispatcher.repair()
        if await quota.redis.zcard(work.ready):
            break
    assert await dispatcher.dispatch() == 1


async def test_projection_does_not_run_retention(quota, usage_db, monkeypatch):
    await quota.check_and_start(running())
    service = projector(quota, usage_db)
    cleanup = AsyncMock(side_effect=AssertionError("Retention is maintenance work"))
    monkeypatch.setattr(service, "cleanup_batch", cleanup)
    assert await UsageDispatcher(service).dispatch() == 1
    cleanup.assert_not_awaited()


@pytest.mark.parametrize("noise_count", [10000, 100000])
async def test_bootstrap_once_then_noise_never_affects_dispatch_or_inspection(
    quota, usage_db, monkeypatch, noise_count
):
    event = running().model_copy(update={"started_at": datetime.now(UTC).replace(tzinfo=None)})
    await quota.check_and_start(event)
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    work = dispatcher.work
    # Model streams written by the predecessor without either scheduling index.
    await quota.redis.delete(work.ready, work.partitions)
    for start in range(0, noise_count, 1000):
        async with quota.redis.pipeline(transaction=False) as pipe:
            for i in range(start, start + 1000):
                pipe.set(f"{quota.prefix}:unrelated:{i}", "value")
            await pipe.execute()
    complete = False
    for _ in range(500):
        complete = await dispatcher.bootstrap(max_pages=1)
        if complete:
            break
    assert complete
    assert await quota.redis.smembers(work.partitions) == {quota.keys(event)[5]}
    no_scan = AsyncMock(side_effect=AssertionError("Steady-state work must not scan the database"))
    steady_start = monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(quota.redis, "scan", no_scan)
        assert await dispatcher.bootstrap()
        assert await dispatcher.dispatch() == 1
        assert await dispatcher.repair() == 1
        assert monotonic() - steady_start < 5
        no_scan.assert_not_awaited()


async def test_partition_index_type_checked_before_admission_mutates_ledger(quota):
    event = running()
    await quota.redis.set(UsageWorkQueue(quota).partitions, "invalid")
    with pytest.raises(QuotaRejected, match="bad_projection_partitions_type"):
        await quota.check_and_start(event)
    assert not await quota.redis.exists(quota.keys(event)[4])
    assert not await quota.redis.exists(quota.keys(event)[5])


async def test_bootstrap_discards_cursor_from_a_previous_redis_generation(quota, usage_db, monkeypatch):
    dispatcher = UsageDispatcher(projector(quota, usage_db))
    base = quota.prefix + ":usage_inventory"
    await quota.redis.set(base + ":cursor", 123456)
    await quota.redis.set(base + ":cursor_generation", "old-primary")
    await quota.redis.set(base + ":generation", "old-primary")
    original, cursors = quota.redis.scan, []

    async def observe(cursor, **kwargs):
        cursors.append(cursor)
        return await original(cursor, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(quota.redis, "scan", observe)
        await dispatcher.bootstrap(max_pages=1)
    assert cursors == [0]
    assert await quota.redis.get(base + ":cursor_generation") == quota.topology.run_id
