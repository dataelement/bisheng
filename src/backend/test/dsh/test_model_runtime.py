"""Production quota composition remains fail-closed under concurrency. AC-23, AC-31, AC-34."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.dsh import DshQuotaUnavailableError
from bisheng.dsh import runtime as module
from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_model_service import principal


async def test_concurrent_first_activation_waits_for_one_verified_approval(monkeypatch):
    topology = SimpleNamespace(ready=False, close=Mock())
    config = SimpleNamespace(
        quota_approval_object="immutable@version",
        quota_approval_sha256="a" * 64,
        quota_evidence_bucket="evidence",
        installation_id="i",
    )
    runtime = module.ModelRuntime(None, None, SimpleNamespace(topology=topology), config)
    started, release = asyncio.Event(), asyncio.Event()

    async def activate(*args, **kwargs):
        started.set()
        await release.wait()
        topology.ready = True

    from bisheng.core.storage.minio import minio_manager

    monkeypatch.setattr(
        minio_manager, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(minio_client_sync=object()))
    )
    monkeypatch.setattr(module, "MinioQuotaApprovalStore", Mock(return_value=object()))
    activation = AsyncMock(side_effect=activate)
    monkeypatch.setattr(module, "activate_from_approval", activation)
    first = asyncio.create_task(runtime.activate())
    await started.wait()
    second = asyncio.create_task(runtime.activate())
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert activation.await_count == 1
    topology.ready = False
    with pytest.raises(DshQuotaUnavailableError):
        await runtime.activate()
    assert activation.await_count == 1


async def test_month_creation_requires_sql_absence_and_permanent_redis_inventory(monkeypatch):
    usage = SimpleNamespace(read_usage=AsyncMock(side_effect=[QuotaRejected("missing_or_bad_ledger"), {"used": 0}]))
    quota = SimpleNamespace(topology=SimpleNamespace(ready=True), ensure_month=AsyncMock())
    runtime = module.ModelRuntime(None, usage, quota, object())
    proof = {
        "tenant_id": 2,
        "user_id": 20,
        "usage_month": "2026-09",
        "history_empty": True,
        "policy_version": 1,
        "model_ids": [42],
    }
    lookup = AsyncMock(return_value=proof)
    monkeypatch.setattr(module, "read_new_month_proof", lookup)
    with principal_scope(principal()):
        assert await runtime.prepare_month(principal(), "2026-09") == {"used": 0}
    quota.ensure_month.assert_awaited_once_with(2, 20, "2026-09", proof=proof)
    usage.read_usage = AsyncMock(side_effect=QuotaRejected("missing_or_bad_ledger"))
    quota.ensure_month.side_effect = QuotaRejected("lost_month_ledger")
    with pytest.raises(DshQuotaUnavailableError):
        await runtime.prepare_month(principal(), "2026-09")
    usage.read_usage = AsyncMock(side_effect=QuotaRejected("bad_counter"))
    lookup.reset_mock()
    with pytest.raises(DshQuotaUnavailableError):
        await runtime.prepare_month(principal(), "2026-09")
    lookup.assert_not_awaited()
