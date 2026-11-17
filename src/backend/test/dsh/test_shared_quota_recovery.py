"""Shared allowances survive real Redis recovery without multiplying by model count."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlmodel import Session

from bisheng.core.context.tenant import current_tenant_id
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelPolicyState, DshPolicySnapshot
from bisheng.dsh.domain.schemas.unified_policy import (
    UNLIMITED_TOKEN_LIMIT,
    CreditRuleInput,
    ModelVisibilityInput,
    PolicySubject,
)
from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_automatic_quota_recovery import connect, persist
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


@pytest.fixture
def recovery(quota):
    token = current_tenant_id.set(2)
    quota.topology.automatic = True

    def attach(limit, model_count=2):
        policy = DshPolicySnapshot(
            tenant_id=2,
            user_id=20,
            shared_token_limit=limit,
            rows=[
                DshModelPolicyState(
                    model_id=model,
                    monthly_token_limit=limit,
                    enabled=1,
                    version=1,
                    quota_epoch=1,
                    quota_sync_state="READY",
                    pending_operation_id=None,
                )
                for model in range(4, 4 + model_count)
            ],
        )
        repository = SimpleNamespace(
            automatic_recovery_snapshot=Mock(return_value=([], policy.recovery_payload(), {})),
            complete_recovery=Mock(),
        )

        @contextmanager
        def scope():
            yield repository

        quota.recovery = AutomaticQuotaRecovery(quota, scope, billing_timezone="Asia/Shanghai")
        return repository

    yield attach
    current_tenant_id.reset(token)


@pytest.mark.parametrize("limit", [UNLIMITED_TOKEN_LIMIT, 1000, 0])
@pytest.mark.parametrize("model_count", [0, 1, 2, 6])
async def test_fresh_recovery_keeps_one_personal_allowance(quota, recovery, limit, model_count):
    recovery(limit, model_count)
    await quota.redis.delete(*quota.keys(running())[:3])

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["limit"] == limit
    assert result["used"] == 0
    assert result["remaining"] == limit
    assert result["quota_state"] == "ready"
    assert result["model_limits"] == {str(model): limit for model in range(4, 4 + model_count)}


@pytest.mark.parametrize("limit", [UNLIMITED_TOKEN_LIMIT, 1000])
@pytest.mark.parametrize("old_limit", ["2000", str(UNLIMITED_TOKEN_LIMIT * 2)])
async def test_legacy_and_overflowed_ledgers_recover_without_losing_usage(quota, recovery, limit, old_limit):
    repository = recovery(limit)
    gate = quota.keys(running())[0]
    await quota.redis.hset(gate, "limit", old_limit)

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["limit"] == limit
    assert result["used"] == 900
    assert result["models"] == {"4": 900, "5": 0}
    assert result["remaining"] == max(limit - 900, 0)
    assert (await quota.read_usage(2, 20, "2026-09"))["quota_state"] == "ready"
    repository.automatic_recovery_snapshot.assert_called_once()


@pytest.mark.parametrize("bad_limit", [None, "-1", "1.0", "01", str(UNLIMITED_TOKEN_LIMIT + 1)])
async def test_invalid_shared_limit_is_not_considered_healthy(quota, recovery, bad_limit):
    repository = recovery(1000)
    await quota.read_usage(2, 20, "2026-09")
    gate = quota.keys(running())[0]
    if bad_limit is None:
        await quota.redis.hdel(gate, "limit")
    else:
        await quota.redis.hset(gate, "limit", bad_limit)

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["limit"] == 1000
    assert result["used"] == 900
    assert repository.automatic_recovery_snapshot.call_count == 2


async def test_recovery_preserves_settled_usage_and_shared_exhaustion(quota, recovery):
    recovery(1000)
    event = await quota.check_and_start(running(), monthly_token_limit=1000)
    await quota.record_usage(terminal(event, amount=100), 1)
    gate = quota.keys(event)[0]
    await quota.redis.hset(gate, "limit", str(UNLIMITED_TOKEN_LIMIT * 2))

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["used"] == 1000
    assert result["remaining"] == 0
    assert (await quota.get_request(event)).status == "SUCCEEDED"
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_and_start(running(model=5), monthly_token_limit=1000)


async def test_upgrade_preserves_running_and_unknown_requests(quota, recovery):
    recovery(UNLIMITED_TOKEN_LIMIT)
    active = await quota.check_and_start(running(), monthly_token_limit=UNLIMITED_TOKEN_LIMIT)
    unknown = await quota.check_and_start(running(model=5), monthly_token_limit=UNLIMITED_TOKEN_LIMIT)
    unknown = unknown.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2})
    await quota.record_usage(unknown, 1)
    gate = quota.keys(active)[0]
    await quota.redis.hdel(gate, "quota_limit_schema")
    await quota.redis.hset(gate, "limit", str(UNLIMITED_TOKEN_LIMIT * 2))

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["used"] == 900
    assert result["unknown_pending"] == 1
    assert (await quota.get_request(active)).status == "RUNNING"
    assert (await quota.get_request(unknown)).status == "USAGE_UNKNOWN"
    assert await quota.redis.hget(gate, "running_count") == "1"


async def test_model_limit_mismatch_triggers_recovery(quota, recovery):
    repository = recovery(1000)
    await quota.read_usage(2, 20, "2026-09")
    await quota.redis.hset(quota.keys(running())[0], "limit:4", "2000")

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["limit"] == 1000
    assert result["remaining"] == 100
    assert repository.automatic_recovery_snapshot.call_count == 2


async def test_shared_lua_still_rejects_inconsistent_model_limits(quota, recovery):
    recovery(1000)
    await quota.read_usage(2, 20, "2026-09")
    quota.recovery = None
    await quota.redis.hset(quota.keys(running())[0], "limit:4", "2000")

    with pytest.raises(QuotaRejected, match="incomplete_model_limits"):
        await quota.read_usage(2, 20, "2026-09")


@pytest.mark.parametrize("limit", [UNLIMITED_TOKEN_LIMIT, 100000])
async def test_sql_policy_and_persisted_usage_restore_one_allowance(quota, store, limit):
    with Session(store) as session, session.begin():
        repository = UnifiedPolicyRepository(session)
        for model in (7, 8):
            repository.save_visibility(model, 20, ModelVisibilityInput(version=0, everyone=True))
        if limit != UNLIMITED_TOKEN_LIMIT:
            repository.save_rule(
                PolicySubject(kind="USER", id=20), 20, CreditRuleInput(version=0, monthly_credits="0.1")
            )
    persist(store, [terminal(running(model=7), amount=100)])
    await quota.redis.delete(*quota.keys(running())[:3])
    connect(quota, store)

    result = await quota.read_usage(2, 20, "2026-09")

    assert result["limit"] == limit
    assert result["used"] == 100
    assert result["remaining"] == limit - 100
    assert result["models"] == {"7": 100, "8": 0}
