"""T048: Coverage AC: AC-22, AC-23, AC-30, AC-31, AC-34. Real Redis only."""

import os
from datetime import datetime
from uuid import uuid4

import pytest

from bisheng.dsh.domain.repositories.usage import UsageEvent
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis, QuotaRejected
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis


def running(model=4, month="2026-09"):
    return UsageEvent(
        request_id=str(uuid4()),
        tenant_id=2,
        user_id=20,
        seat_id="seat",
        session_id="session",
        grant_version=1,
        model_id=model,
        usage_month=month,
        billing_timezone="Asia/Shanghai",
        policy_version=1,
        event_version=1,
        quota_epoch=1,
        status="RUNNING",
        started_at=datetime(2026, 9, 9),
    )


@pytest.fixture
async def quota():
    if os.environ.get("DSH_TEST_REDIS_ISOLATED") != "1" or not os.environ.get("DSH_TEST_REDIS_URL"):
        pytest.skip("Dedicated real Redis is not configured")
    redis = create_quota_redis(os.environ["DSH_TEST_REDIS_URL"])
    topology = QuotaTopology(redis)
    info = await redis.info("server")
    await topology.approve(info["run_id"], 1, old_primary_isolated=True, ledger_proven=True)
    store = QuotaRedis(redis, topology, prefix="dsh_test_" + uuid4().hex)
    # A controlled fixture seeds a proven baseline; production uses recovery.
    gate, month, models, _blocks, _, _ = store.keys(running())
    await redis.hset(
        gate,
        mapping={
            "state": "READY",
            "running_index": "1",
            "running_count": "0",
            "epoch": "1",
            "version": "1",
            "limit": "2000",
            "limit:4": "1000",
            "limit:5": "1000",
            "model:4": "1",
            "model:5": "1",
            "generation": "0",
            "month:2026-09": "1",
        },
    )
    await redis.hset(month, mapping={"state": "READY", "epoch": "1", "used": "900"})
    await redis.hset(models, mapping={"4": "900", "5": "0"})
    yield store
    redis.connection.recovery_connect_allowed = True
    keys = [key async for key in redis.scan_iter(store.prefix + "*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


async def test_actual_usage_admits_two_without_reservation(quota):
    a, b = running(), running(5)
    assert (await quota.check_and_start(a)).status == "RUNNING"
    assert (await quota.check_and_start(b)).status == "RUNNING"
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "900"
    assert await quota.redis.xlen(quota.keys(a)[5]) == 2


async def test_zero_limit_missing_key_and_bad_type_fail_closed(quota):
    event = running()
    await quota.redis.hset(quota.keys(event)[0], "limit:4", "0")
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(event)
    await quota.redis.hset(quota.keys(event)[0], "limit:4", "1000")
    await quota.redis.delete(quota.keys(event)[1])
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(event)
    await quota.redis.set(quota.keys(event)[1], "bad")
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(event)
    assert await quota.redis.exists(quota.keys(event)[4]) == 0


async def test_unknown_usage_does_not_block_new_month(quota):
    event = running(month="2026-10")
    await quota.redis.hset(quota.keys(event)[1], mapping={"state": "READY", "epoch": "1", "used": "0"})
    await quota.redis.hset(quota.keys(event)[2], mapping={"4": "0"})
    await quota.redis.sadd(quota.keys(event)[0].removesuffix(":gate") + ":unknown_usage", "old-month-request")
    assert (await quota.check_and_start(event)).status == "RUNNING"


async def test_policy_fencing_preserves_storage_block_and_retries(quota):
    e = running()
    params = {"operation_id": "op", "lease_generation": 1, "epoch": 1, "expected_version": 1}
    await quota.block_policy(2, 20, **params)
    await quota.redis.sadd(quota.keys(e)[3], "STORAGE_UNCERTAIN:x")
    await quota.install_policy(
        2, 20, **params, version=2, model_configs=[DshModelQuotaConfig(model_id=5, monthly_token_limit=2000)]
    )
    await quota.block_policy(2, 20, **{**params, "lease_generation": 2})
    with pytest.raises(QuotaRejected):
        await quota.finish_policy(2, 20, operation_id="op", lease_generation=1, epoch=1, expected_policy_version=2)
    await quota.finish_policy(2, 20, operation_id="op", lease_generation=2, epoch=1, expected_policy_version=2)
    assert await quota.redis.smembers(quota.keys(e)[3]) == {"STORAGE_UNCERTAIN:x"}
    await quota.block_policy(2, 20, **{**params, "lease_generation": 3})
    await quota.install_policy(
        2,
        20,
        **{**params, "lease_generation": 3},
        version=2,
        model_configs=[DshModelQuotaConfig(model_id=5, monthly_token_limit=2000)],
    )
    await quota.finish_policy(2, 20, operation_id="op", lease_generation=3, epoch=1, expected_policy_version=2)


async def test_stopped_projector_enforces_backpressure_at_admission(quota):
    e = running()
    # A real old unprojected stream event remains when every worker is down.
    await quota.redis.xadd(quota.keys(e)[5], {"event": e.model_dump_json()}, id="1-0")
    with pytest.raises(QuotaRejected, match="projection_backpressure"):
        await quota.check_and_start(running())
    assert await quota.redis.exists(quota.keys(e)[4]) == 0


async def test_uncertain_or_duplicate_admission_never_authorizes_replay(quota):
    e = running()
    await quota.check_and_start(e)
    with pytest.raises(QuotaRejected, match="request_already_started"):
        await quota.check_and_start(e)
    await quota.redis.hset(quota.keys(e)[0], "write_in_progress", "1")
    with pytest.raises(QuotaRejected, match="ledger_write_incomplete"):
        await quota.check_and_start(running())


async def test_policy_adds_model_only_to_intact_month_ledger(quota):
    e = running(model=6)
    params = {"operation_id": "newmodel", "lease_generation": 1, "epoch": 1, "expected_version": 1}
    await quota.block_policy(2, 20, **params)
    await quota.install_policy(
        2, 20, **params, version=2, model_configs=[DshModelQuotaConfig(model_id=6, monthly_token_limit=2000)]
    )
    await quota.finish_policy(2, 20, operation_id="newmodel", lease_generation=1, epoch=1, expected_policy_version=2)
    assert (await quota.check_and_start(e.model_copy(update={"policy_version": 2}))).status == "RUNNING"
    assert await quota.redis.hget(quota.keys(e)[2], "4") == "900"


async def test_live_usage_snapshot_is_coherent_and_not_missing_as_zero(quota):
    value = await quota.read_usage(2, 20, "2026-09")
    assert (value["used"], value["limit"], value["remaining"], value["source"]) == (900, 2000, 1100, "live")
    await quota.redis.sadd(quota.keys(running())[0].removesuffix(":gate") + ":unknown_usage", "old")
    blocked = await quota.read_usage(2, 20, "2026-09")
    assert blocked["quota_state"] == "ready"
    assert blocked["unknown_pending"] == 1
    with pytest.raises(QuotaRejected):
        await quota.read_usage(2, 20, "2026-10")
