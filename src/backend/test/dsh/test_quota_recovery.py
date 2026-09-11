"""T052: Coverage AC: AC-22, AC-23, AC-30, AC-31, AC-34."""

import pytest

from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running


async def test_reconnect_revokes_approval_even_same_primary(quota):
    await quota.redis.connection_pool.disconnect()
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(running())
    assert quota.topology.ready is False


async def test_unproven_tail_or_old_primary_isolation_refused(quota):
    service = DshQuotaRecoveryService(quota)
    with pytest.raises(ValueError):
        RecoveryManifest(
            run_id=quota.topology.run_id,
            epoch=2,
            previous_epoch=1,
            evidence_object="audit/version",
            evidence_sha256="a" * 64,
            old_primary_isolated=False,
            confirmed_tail_complete=False,
        )
    assert service.quota is quota


async def test_missing_month_is_not_a_zero_balance(quota):
    e = running(month="2027-01")
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(e)
    assert await quota.redis.exists(quota.keys(e)[1]) == 0


async def test_audited_recovery_rebuilds_unknown_all_months(quota):
    import hashlib
    import json

    a = running()
    await quota.check_and_start(a)
    await quota.redis.hdel(quota.keys(a)[4], "retained_stream_count")  # Pre-index legacy metadata.
    evidence = json.dumps([a.model_dump(mode="json")]).encode()
    manifest = RecoveryManifest(
        run_id=quota.topology.run_id,
        epoch=2,
        previous_epoch=1,
        evidence_object="audit/version",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=1,
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)],
        current_month="2026-10",
        request_count=1,
        events=[a],
    )

    async def read(reference):
        assert reference == "audit/version"
        return evidence

    receipt = await DshQuotaRecoveryService(quota).recover(manifest, read_evidence=read, sql_events=[])
    assert quota.topology.ready
    assert await quota.redis.hget(quota.keys(a)[4], "retained_stream_count") == "2"
    assert await quota.redis.hget(quota.keys(a)[0], "running_index") == "1"
    assert await quota.redis.hget(quota.keys(a)[0], "running_count") == "0"
    assert await quota.redis.zcard(quota.keys(a)[0].removesuffix(":gate") + ":running") == 0
    assert (await quota.get_request(a)).status == "USAGE_UNKNOWN"
    assert await quota.redis.smembers(quota.keys(a)[0].removesuffix(":gate") + ":unknown_usage") == {a.request_id}
    assert await quota.redis.hget(quota.keys(running(month="2026-10"))[1], "used") == "0"
    with pytest.raises(QuotaRejected):
        await quota.check_and_start(running(month="2026-10").model_copy(update={"quota_epoch": 2}))
    await quota.finish_recovery(manifest, receipt)
    assert (await quota.read_usage(2, 20, "2026-10"))["quota_state"] == "ready"
    assert (
        await quota.check_and_start(running(month="2026-10").model_copy(update={"quota_epoch": 2}))
    ).status == "RUNNING"


async def test_incomplete_audit_cannot_restore_old_snapshot(quota):
    import hashlib

    a = running()
    await quota.check_and_start(a)
    evidence = b"[]"
    manifest = RecoveryManifest(
        run_id=quota.topology.run_id,
        epoch=2,
        previous_epoch=1,
        evidence_object="audit/version",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=1,
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)],
        current_month="2026-10",
        request_count=0,
        events=[],
    )

    async def read(reference):
        return evidence

    with pytest.raises(ValueError):
        await DshQuotaRecoveryService(quota).recover(manifest, read_evidence=read, sql_events=[])
    assert not quota.topology.ready
    assert await quota.redis.hget(quota.keys(a)[0], "state") == "FROZEN"


async def test_shared_immutable_approval_activates_only_matching_primary(quota):
    import hashlib
    import io
    from datetime import datetime
    from types import SimpleNamespace

    from bisheng.dsh.infrastructure.quota_activation import (
        MinioQuotaApprovalStore,
        QuotaApproval,
        activate_from_approval,
    )

    approval = QuotaApproval(
        run_id=quota.topology.run_id,
        epoch=1,
        recovery_evidence_object="audit/manifest@v1",
        recovery_evidence_sha256="a" * 64,
        isolation_attestation="network fencing ticket",
        approved_by=7,
        approved_at=datetime(2026, 9, 9),
    )
    body = approval.model_dump_json().encode()

    class Response(io.BytesIO):
        def release_conn(self):
            pass

    class Objects:
        def stat_object(self, *args, **kwargs):
            return SimpleNamespace(version_id="v1", size=len(body))

        def get_object(self, *args, **kwargs):
            return Response(body)

    store = MinioQuotaApprovalStore(Objects(), bucket="audit")
    quota.topology.close()
    await activate_from_approval(
        quota.topology, store, reference="dsh/quota-approvals/test/1/object@v1", sha256=hashlib.sha256(body).hexdigest()
    )
    assert quota.topology.ready
    with pytest.raises(ValueError):
        await activate_from_approval(
            quota.topology, store, reference="dsh/quota-approvals/test/1/object@v1", sha256="b" * 64
        )
    assert not quota.topology.ready


async def test_proven_new_user_and_month_do_not_clear_unknown_or_reset_loss(quota):
    proof = {
        "tenant_id": 2,
        "user_id": 99,
        "operation_id": "first-policy",
        "lease_generation": 1,
        "policy_version": 0,
        "history_empty": True,
    }
    await quota.ensure_new_user(2, 99, operation_id="first-policy", lease_generation=1, epoch=1, proof=proof)
    month = {
        "tenant_id": 2,
        "user_id": 99,
        "usage_month": "2026-10",
        "history_empty": True,
        "policy_version": 0,
        "model_configs": [],
    }
    await quota.ensure_month(2, 99, "2026-10", proof=month)
    value = await quota.read_usage(2, 99, "2026-10")
    assert value["used"] == 0 and value["limit"] == 0
    base = f"{quota.prefix}:{{2:99}}"
    await quota.redis.sadd(base + ":blocks", "STORAGE_UNCERTAIN:old")
    await quota.ensure_month(2, 99, "2026-11", proof={**month, "usage_month": "2026-11"})
    assert (await quota.read_usage(2, 99, "2026-11"))["quota_state"] == "blocked"
    await quota.redis.delete(base + ":month:2026-10")
    with pytest.raises(QuotaRejected, match="lost_month_ledger"):
        await quota.ensure_month(2, 99, "2026-10", proof=month)
