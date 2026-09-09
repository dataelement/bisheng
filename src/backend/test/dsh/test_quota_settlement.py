"""T050: Coverage AC: AC-20, AC-22, AC-23, AC-24, AC-34."""

import pytest

from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running


def terminal(event, amount=300, **changes):
    return event.model_copy(
        update=dict(
            event_version=2,
            status="SUCCEEDED",
            input_tokens=amount,
            output_tokens=0,
            total_tokens=amount,
            usage_source="PROVIDER",
            **changes,
        )
    )


async def test_inflight_excess_and_duplicate_settlement(quota):
    a, b = running(), running(5)
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    end = terminal(a)
    await quota.record_usage(end, 1)
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(running())
    await quota.record_usage(terminal(b), 1)
    await quota.record_usage(end, 1)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "1500"
    assert await quota.redis.hget(quota.keys(a)[2], "5") == "300"
    assert await quota.redis.xlen(quota.keys(a)[5]) == 4


async def test_unknown_reconciliation_removes_only_own_reason(quota):
    a, b = running(), running()
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    for e in [a, b]:
        await quota.record_usage(e.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2}), 1)
    settled = a.model_copy(
        update={
            "status": "FAILED",
            "event_version": 3,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "usage_source": "RECONCILED",
            "operation_id": "repair",
            "operation_generation": 1,
            "payload_hash": "a" * 64,
        }
    )
    await quota.claim_reconciliation(a, operation_id="repair", payload_hash="a" * 64, generation=1)
    await quota.record_usage(settled, 2)
    await quota.record_usage(settled, 2)
    assert await quota.redis.smembers(quota.keys(a)[0].removesuffix(":gate") + ":unknown_usage") == {b.request_id}
    with pytest.raises(QuotaRejected):
        await quota.record_usage(settled.model_copy(update={"operation_id": "other"}), 2)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "900"


async def test_stream_bad_type_prevents_partial_accounting(quota):
    a = running()
    await quota.check_and_start(a)
    await quota.redis.delete(quota.keys(a)[5])
    await quota.redis.set(quota.keys(a)[5], "bad")
    with pytest.raises(QuotaRejected):
        await quota.record_usage(terminal(a), 1)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "900"
    assert (await quota.get_request(a)).status == "RUNNING"


async def test_exact_int64_accounting(quota):
    a = running()
    await quota.check_and_start(a)
    amount = 9007199254740993
    await quota.record_usage(terminal(a, amount), 1)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == str(amount + 900)


async def test_reconciliation_old_worker_is_fenced(quota):
    a = running()
    await quota.check_and_start(a)
    unknown = a.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2})
    await quota.record_usage(unknown, 1)
    for generation in [1, 2]:
        await quota.claim_reconciliation(a, operation_id="repair", payload_hash="a" * 64, generation=generation)
    stale = unknown.model_copy(
        update={
            "status": "FAILED",
            "event_version": 3,
            "input_tokens": 1,
            "output_tokens": 0,
            "total_tokens": 1,
            "usage_source": "RECONCILED",
            "operation_id": "repair",
            "operation_generation": 1,
            "payload_hash": "a" * 64,
        }
    )
    with pytest.raises(QuotaRejected, match="stale_reconciliation_worker"):
        await quota.record_usage(stale, 2)
    assert await quota.redis.smembers(quota.keys(a)[3]) == set()
    assert (await quota.check_and_start(running(5))).status == "RUNNING"
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "900"
    await quota.record_usage(stale.model_copy(update={"operation_generation": 2}), 2)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "901"


async def test_unknown_usage_is_audit_only_and_does_not_block_any_model(quota):
    event = running()
    await quota.check_and_start(event)
    await quota.record_usage(event.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2}), 1)
    assert await quota.redis.smembers(quota.keys(event)[3]) == set()
    assert (await quota.read_usage(2, 20, "2026-09"))["unknown_pending"] == 1
    for model in (4, 5):
        assert (await quota.check_and_start(running(model))).status == "RUNNING"
    assert await quota.redis.hget(quota.keys(event)[1], "used") == "900"
