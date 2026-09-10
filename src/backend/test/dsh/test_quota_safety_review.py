"""Cross-replica regression for recovery publication and uncertain settlement quarantine."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from redis.exceptions import ConnectionError
from sqlmodel import Session, select

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.services.quota_operations import DshQuotaOperationsService
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest
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


async def test_other_replica_cannot_admit_between_restore_and_sql_epoch_cas(quota, usage_db):
    other = await replica(quota, epoch=2)
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version, policy.monthly_token_limit = 1, 1000
    manifest = RecoveryManifest(
        run_id=quota.topology.run_id,
        epoch=2,
        previous_epoch=1,
        evidence_object="empty@v1",
        evidence_sha256=hashlib.sha256(b"[]").hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=1,
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)],
        model_versions={4: 1},
        current_month="2026-09",
        request_count=0,
        events=[],
    )
    body = manifest.model_dump_json().encode()
    actual = DshQuotaRecoveryService(quota)

    class Recovery:
        def __init__(self):
            self.quota = quota

        async def recover(self, *args, **kwargs):
            receipt = await actual.recover(*args, **kwargs)
            with repository_scope(usage_db) as repository:
                assert repository.recovery_snapshot(20, billing_timezone="UTC")[1]["quota_epoch"] == 1
            with pytest.raises(QuotaRejected):
                await other.check_and_start(running().model_copy(update={"quota_epoch": 2}))
            assert await other.redis.hget(other.keys(running())[0], "state") == "FROZEN"
            return receipt

    class Evidence:
        async def read(self, reference, tenant_id):
            return body if reference == "manifest@v1" else b"[]"

    class Approvals:
        async def publish(self, approval, *, topology):
            await topology.check()
            with repository_scope(usage_db) as repository:
                assert repository.recovery_snapshot(20, billing_timezone="UTC")[1]["quota_epoch"] == 2
            assert await other.redis.hget(other.keys(running())[0], "state") == "READY"
            return {"epoch": approval.epoch}

    async def authorize(*_):
        return True

    service = DshQuotaOperationsService(
        recovery=Recovery(),
        repository_scope=lambda: repository_scope(usage_db),
        manifest_store=Evidence(),
        evidence_store=Evidence(),
        approval_store=Approvals(),
        authorize=authorize,
        installation_id="test",
        billing_timezone="UTC",
        now=lambda: datetime.now(UTC),
    )
    try:
        await service.recover_quota(
            command="recover",
            manifest_object="manifest@v1",
            manifest_sha256=hashlib.sha256(body).hexdigest(),
            isolation_attestation="isolated",
            actor_user_id=7,
        )
        admitted = await other.check_and_start(running().model_copy(update={"quota_epoch": 2}))
        assert await other.redis.hget(other.keys(admitted)[4], "epoch") == str(admitted.quota_epoch)
    finally:
        await other.redis.aclose()


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


async def test_recovery_receipt_cannot_finish_a_newer_owner(quota):
    manifest = RecoveryManifest(
        run_id=quota.topology.run_id,
        epoch=2,
        previous_epoch=1,
        evidence_object="empty@v1",
        evidence_sha256=hashlib.sha256(b"[]").hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=1,
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)],
        model_versions={4: 1},
        current_month="2026-09",
        request_count=0,
        events=[],
    )

    async def read(_):
        return b"[]"

    service = DshQuotaRecoveryService(quota)
    old = await service.recover(manifest, read_evidence=read, sql_events=[])
    current = await service.recover(manifest, read_evidence=read, sql_events=[])
    assert old["owner"] != current["owner"]
    with pytest.raises(QuotaRejected, match="recovery_fence_lost"):
        await quota.finish_recovery(manifest, old)
    assert await quota.redis.hget(quota.keys(running())[0], "state") == "FROZEN"
    await quota.finish_recovery(manifest, current)
    assert await quota.redis.hget(quota.keys(running())[0], "state") == "READY"
