"""Actual per-model allowance regression; no reservation and no rate-limiting semantics."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.services.quota_operations import DshQuotaOperationsService
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db


def configs(a, b):
    return [
        DshModelQuotaConfig(model_id=4, monthly_token_limit=a),
        DshModelQuotaConfig(model_id=5, monthly_token_limit=b),
    ]


def set_policies(session, entries, version=1):
    rows = list(session.scalars(select(DshUserPolicy).where(DshUserPolicy.user_id == 20)))
    existing = {row.model_id: row for row in rows}
    for row in rows:
        row.enabled = 0
    for config in entries:
        row = existing.get(config.model_id)
        if row is None:
            row = DshUserPolicy(tenant_id=2, user_id=20, model_id=config.model_id, updated_by=1)
            session.add(row)
        row.enabled, row.version, row.monthly_token_limit = 1, version, config.monthly_token_limit


async def install(quota, entries, version=2):
    current = {4, 5}
    by_model = {entry.model_id: entry for entry in entries}
    for model in sorted(current | by_model.keys()):
        entry = by_model.get(model)
        params = {
            "operation_id": f"model-{model}-{version}",
            "model_id": model,
            "lease_generation": 1,
            "epoch": 1,
            "expected_version": version - 1,
        }
        await quota.block_policy(2, 20, **params)
        await quota.install_policy(
            2,
            20,
            **params,
            version=version,
            monthly_token_limit=entry.monthly_token_limit if entry else 0,
            enabled=entry is not None,
        )
        await quota.finish_policy(
            2,
            20,
            operation_id=params["operation_id"],
            model_id=model,
            lease_generation=1,
            epoch=1,
            expected_policy_version=version,
        )


async def test_exhausted_model_does_not_borrow_or_block_another_and_inflight_may_exceed(quota):
    await install(quota, configs(900, 100))
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_and_start(running(4).model_copy(update={"policy_version": 2}))
    a, b = [running(5).model_copy(update={"policy_version": 2}) for _ in range(2)]
    await quota.check_and_start(a)
    await quota.check_and_start(b)
    assert (await quota.read_usage(2, 20, "2026-09"))["models"]["5"] == 0
    await quota.record_usage(terminal(a, amount=60), 1)
    await quota.record_usage(terminal(b, amount=60), 1)
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_and_start(running(5).model_copy(update={"policy_version": 2}))
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["used"] == 1020
    assert value["model_limits"] == {"4": 900, "5": 100}
    assert value["remaining"] == 0


async def test_zero_lower_and_removed_model_do_not_erase_or_spend_other_model_history(quota):
    await install(quota, configs(800, 0))
    for model in (4, 5):
        with pytest.raises(QuotaRejected, match="quota_exceeded"):
            await quota.check_and_start(running(model).model_copy(update={"policy_version": 2}))
    await install(quota, [DshModelQuotaConfig(model_id=5, monthly_token_limit=50)], version=3)
    value = await quota.read_usage(2, 20, "2026-09")
    assert value["used"] == 900 and value["limit"] == 50 and value["remaining"] == 50
    assert value["models"]["4"] == 900
    assert value["model_limits"] == {"5": 50}
    await quota.check_and_start(running(5).model_copy(update={"policy_version": 3}))
    with pytest.raises(QuotaRejected, match="model_not_allowed"):
        await quota.check_and_start(running(4).model_copy(update={"policy_version": 3}))


async def test_same_sum_swapped_model_limits_cannot_reuse_recovery_proof(quota, usage_db):
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version, policy.monthly_token_limit = 1, 100
        session.add(
            DshUserPolicy(
                tenant_id=2, user_id=20, model_id=5, enabled=1, version=1, monthly_token_limit=900, updated_by=1
            )
        )
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
        policy_version=2,
        model_configs=configs(900, 100),
        model_versions={4: 1, 5: 1},
        current_month="2026-09",
        request_count=0,
    )
    body = manifest.model_dump_json().encode()

    class Evidence:
        async def read(self, reference, tenant_id):
            return body

    async def authorize(*_):
        return True

    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    service = DshQuotaOperationsService(
        recovery=DshQuotaRecoveryService(quota),
        repository_scope=repository,
        manifest_store=Evidence(),
        evidence_store=Evidence(),
        approval_store=object(),
        authorize=authorize,
        billing_timezone="UTC",
        now=lambda: datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="current committed SQL policy"):
        await service.recover_quota(
            command="recover",
            manifest_object="manifest@v1",
            manifest_sha256=hashlib.sha256(body).hexdigest(),
            isolation_attestation="test",
            actor_user_id=7,
        )
    assert await quota.redis.hget(quota.keys(running())[0], "epoch") == "1"
    with repository() as repo:
        _, before = repo.recovery_snapshot(20, billing_timezone="UTC")
    with Session(usage_db) as session, session.begin():
        set_policies(session, configs(900, 100), version=1)
    with repository() as repo, pytest.raises(ValueError, match="SQL policy changed"):
        repo.complete_recovery(20, expected_policy=before, epoch=2)


def test_legacy_aggregate_only_recovery_proof_is_rejected():
    with pytest.raises(ValueError):
        RecoveryManifest(
            run_id="test",
            epoch=2,
            previous_epoch=1,
            evidence_object="old@v1",
            evidence_sha256="a" * 64,
            old_primary_isolated=True,
            confirmed_tail_complete=True,
            tenant_id=2,
            user_id=20,
            policy_version=1,
            monthly_limit=1000,
            model_ids=[4, 5],
            current_month="2026-09",
            request_count=0,
        )


def test_sql_estimate_remaining_is_per_model_and_preserves_removed_model_usage(usage_db):
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version, policy.monthly_token_limit = 1, 1000
        session.add(
            DshUserPolicy(
                tenant_id=2, user_id=20, model_id=5, enabled=1, version=1, monthly_token_limit=100, updated_by=1
            )
        )
        repo = DshUsageRepository(session)
        repo.project_batch([terminal(running(4), amount=1200), terminal(running(5), amount=20)])
    with Session(usage_db) as session, session.begin():
        repo = DshUsageRepository(session)
        value = repo.persisted_usage(20, "2026-09")
        assert (value["used"], value["limit"], value["remaining"]) == (1220, 1100, 80)
        assert value["model_limits"] == {"4": 1000, "5": 100}
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.enabled = 0
    with Session(usage_db) as session:
        value = DshUsageRepository(session).persisted_usage(20, "2026-09")
        assert (value["used"], value["limit"], value["remaining"]) == (1220, 100, 80)
        assert value["models"] == {"4": 1200, "5": 20}
        assert value["model_limits"] == {"5": 100}


async def test_new_month_proof_requires_exact_model_limits(quota, usage_db):
    await install(quota, configs(900, 100))
    with Session(usage_db) as session, session.begin():
        set_policies(session, configs(100, 900), version=2)
    with Session(usage_db) as session:
        proof = DshUsageRepository(session).new_month_proof(20, "2026-10")
    with pytest.raises(QuotaRejected, match="model_policy_mismatch"):
        await quota.ensure_month(2, 20, "2026-10", proof=proof)
    assert not await quota.redis.exists(quota.keys(running(month="2026-10"))[1])
    with Session(usage_db) as session, session.begin():
        set_policies(session, configs(900, 100), version=2)
    with Session(usage_db) as session:
        proof = DshUsageRepository(session).new_month_proof(20, "2026-10")
    await quota.ensure_month(2, 20, "2026-10", proof=proof)
    value = await quota.read_usage(2, 20, "2026-10")
    assert value["model_limits"] == {"4": 900, "5": 100}
    assert value["remaining"] == 1000


async def test_removing_an_admitted_model_still_settles_and_never_spends_new_model_allowance(quota):
    event = running(4)
    await quota.check_and_start(event)
    await install(quota, [DshModelQuotaConfig(model_id=5, monthly_token_limit=50)])
    await quota.record_usage(terminal(event), 1)
    value = await quota.read_usage(2, 20, "2026-09")
    assert (value["used"], value["limit"], value["remaining"]) == (1200, 50, 50)
    assert value["models"]["4"] == 1200
    await quota.check_and_start(running(5).model_copy(update={"policy_version": 2}))
