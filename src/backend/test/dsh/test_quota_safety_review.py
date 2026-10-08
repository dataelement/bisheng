"""Cross-replica regression for recovery publication and uncertain settlement quarantine."""

from contextlib import contextmanager

import pytest
from redis.exceptions import ConnectionError
from sqlmodel import Session

from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis, QuotaRejected
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db


@contextmanager
def repository_scope(engine):
    with Session(engine) as session, session.begin():
        yield DshUsageRepository(session)


async def replica(quota, epoch=1):
    import os

    redis = create_quota_redis(os.environ["DSH_TEST_REDIS_URL"])
    topology = QuotaTopology(redis)
    await topology.approve(quota.topology.run_id, epoch, old_primary_isolated=True, ledger_proven=True)
    return QuotaRedis(redis, topology, prefix=quota.prefix)


async def test_admission_never_mixes_event_and_approved_epoch(quota):
    with pytest.raises(QuotaRejected, match="epoch"):
        await quota.check_and_start(running().model_copy(update={"quota_epoch": 2}))


async def test_failed_settlement_quarantines_shared_user_without_stopping_other_inflight(quota, monkeypatch):
    other = await replica(quota)
    a, b = running(), running()
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    evaluate = quota.redis.eval

    async def fail_settlement(script, *args):
        if "reconciliation_required" in script:
            raise ConnectionError("connection failed before settlement write")
        return await evaluate(script, *args)

    monkeypatch.setattr(quota.redis, "eval", fail_settlement)
    try:
        with pytest.raises(QuotaRejected):
            await quota.record_usage(terminal(a), 1)
        assert (await other.get_request(a)).status == "USAGE_UNKNOWN"
        assert await other.redis.sismember(other.keys(a)[3], "STORAGE_UNCERTAIN:" + a.request_id)
        with pytest.raises(QuotaRejected):
            await other.check_and_start(running())
        assert (await other.record_usage(terminal(b), 1)).total_tokens == 300
        assert await other.redis.hget(other.keys(b)[1], "used") == "1200"
        assert not quota.topology.ready
    finally:
        await other.redis.aclose()


async def test_lost_settlement_reply_confirms_only_same_approved_primary(quota, monkeypatch):
    event = running()
    await quota.check_and_start(event)
    evaluate = quota.redis.eval

    async def lose_reply(script, *args):
        result = await evaluate(script, *args)
        if "reconciliation_required" in script:
            raise ConnectionError("actual settlement succeeded but reply was lost")
        return result

    monkeypatch.setattr(quota.redis, "eval", lose_reply)
    settled = terminal(event)
    assert await quota.record_usage(settled, 1) == settled
    assert not quota.topology.ready
    assert not await quota.redis.sismember(quota.keys(event)[3], "STORAGE_UNCERTAIN:" + event.request_id)
    quota.topology.run_id = "a-different-original-primary"
    assert await quota.quarantine_uncertain(settled) == "FROZEN"
    assert await quota.redis.sismember(quota.keys(event)[3], "STORAGE_UNCERTAIN:" + event.request_id)
