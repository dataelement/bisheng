"""First installation: ordinary policy intent creates the audited disabled placeholder."""

import asyncio
import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlmodel import Session

from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from bisheng.dsh.domain.services.admin_policy import DshAdminService
from bisheng.dsh.domain.services.quota_operations import DshQuotaOperationsService
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest
from bisheng.dsh.operations_runtime import OperationsRuntime, _ActivatedQuotaProxy
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_usage_repository import usage_db as usage_db


@pytest.fixture
def bootstrap_db(usage_db):
    DshAdminOperation.__table__.create(usage_db)
    try:
        yield usage_db
    finally:
        DshAdminOperation.__table__.drop(usage_db)


async def test_first_policy_pending_initialization_then_same_operation_succeeds(quota, bootstrap_db):
    usage_db = bootstrap_db
    with Session(usage_db) as session, session.begin():
        for policy in session.scalars(select(DshUserPolicy)):
            session.delete(policy)
    await quota.redis.delete(*quota.keys(running()))
    run_id = quota.topology.run_id
    quota.topology.close()

    @contextmanager
    def scope(repository):
        with Session(usage_db) as session, session.begin():
            # The production tenant-filter hook supplies this field before insertion.
            def tenant_defaults(session, *_):
                for row in session.new:
                    if isinstance(row, (DshUserPolicy, DshAdminOperation)) and row.tenant_id is None:
                        row.tenant_id = 2

            event.listen(session, "before_flush", tenant_defaults)
            yield repository(session)

    async def authorized(*_):
        return True

    runtime = object.__new__(OperationsRuntime)
    runtime.activation_lock = asyncio.Lock()
    runtime.activation_attempted = False
    runtime.quota = quota
    runtime.config = SimpleNamespace(quota_approval_object=None, quota_approval_sha256=None)
    clock = [datetime(2026, 9, 9)]
    service = DshAdminService(
        repository_scope=lambda: scope(DshPolicyRepository),
        quota=_ActivatedQuotaProxy(runtime),
        authorize=authorized,
        validate_models=authorized,
        now=lambda: clock[0],
    )
    operation_id = str(uuid4())
    result = await service.update_policy(
        user_id=20,
        model_id=4,
        actor_user_id=7,
        request=DshUserPolicyInput(
            operation_id=operation_id,
            expected_version=0,
            monthly_token_limit=1000,
            enabled=True,
        ),
    )
    assert result["status"] == "PROCESSING"
    assert result["committed_at"] is None
    assert not quota.topology.ready
    assert not await quota.redis.exists(quota.keys(running())[0])
    with scope(DshUsageRepository) as repository:
        events, policy = repository.recovery_snapshot(20, billing_timezone="UTC")
    assert events == []
    assert (policy["version"], policy["model_configs"]) == (0, [])
    assert policy["pending_operation_id"] == operation_id
    manifest = RecoveryManifest(
        run_id=run_id,
        epoch=1,
        previous_epoch=0,
        evidence_object="empty@v1",
        evidence_sha256=hashlib.sha256(b"[]").hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=0,
        model_configs=[],
        model_versions={4: 0},
        current_month="2026-09",
        request_count=0,
        events=[],
    )
    body = manifest.model_dump_json().encode()

    class Evidence:
        async def read(self, reference, tenant_id):
            assert tenant_id == 2
            return body if reference == "manifest@v1" else b"[]"

    class Approvals:
        async def publish(self, approval, *, topology):
            await topology.check()
            assert approval.run_id == run_id and approval.epoch == 1
            return {"object": "approval@v1", "sha256": "a" * 64}

    recovery = DshQuotaOperationsService(
        recovery=DshQuotaRecoveryService(quota),
        repository_scope=lambda: scope(DshUsageRepository),
        manifest_store=Evidence(),
        evidence_store=Evidence(),
        approval_store=Approvals(),
        authorize=authorized,
        installation_id="test",
        billing_timezone="UTC",
        now=lambda: clock[0].replace(tzinfo=UTC),
    )
    assert (
        await recovery.recover_quota(
            command="initialize",
            manifest_object="manifest@v1",
            manifest_sha256=hashlib.sha256(body).hexdigest(),
            isolation_attestation="first isolated primary",
            actor_user_id=7,
        )
    )["object"] == "approval@v1"
    clock[0] += timedelta(seconds=31)
    assert (await service.resume(operation_id))["status"] == "SUCCEEDED"
    with scope(DshPolicyRepository) as repository:
        assert repository.get(20).version == 1
        assert repository.get(20).pending_operation_id is None
    assert (await quota.check_and_start(running())).status == "RUNNING"
