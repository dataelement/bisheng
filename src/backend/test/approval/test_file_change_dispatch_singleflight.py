from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.approval.test_file_change_execution_worker import _load_worker, fake_celery

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER_PATH = _BACKEND_ROOT / "bisheng" / "worker" / "knowledge" / "file_change_tasks.py"
_LEASE_PATH = _BACKEND_ROOT / "bisheng" / "worker" / "knowledge" / "file_change_dispatch_lease.py"


def _load_lease_module():
    module_name = "file_change_dispatch_lease_test_module"
    spec = importlib.util.spec_from_file_location(module_name, _LEASE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def worker():
    module = _load_worker()
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    return module


async def test_dispatch_claim_allows_only_one_outstanding_message(worker, monkeypatch):
    lease = SimpleNamespace(key="f046:dispatch:coordinate:23:41", token="lease-1")
    store = SimpleNamespace(
        claim=AsyncMock(side_effect=[lease, None]),
        release=AsyncMock(),
    )
    monkeypatch.setattr(worker, "_build_dispatch_lease_store", AsyncMock(return_value=store))
    task = SimpleNamespace(apply_async=MagicMock())

    first = await worker._dispatch_once(
        task,
        lease_key=lease.key,
        kwargs={"request_id": 41},
        headers={"tenant_id": 23},
    )
    duplicate = await worker._dispatch_once(
        task,
        lease_key=lease.key,
        kwargs={"request_id": 41},
        headers={"tenant_id": 23},
    )

    assert first is True
    assert duplicate is False
    task.apply_async.assert_called_once_with(
        kwargs={
            "request_id": 41,
            "dispatch_lease_key": lease.key,
            "dispatch_lease_token": lease.token,
        },
        headers={"tenant_id": 23},
    )


async def test_failed_publish_releases_exact_dispatch_claim(worker, monkeypatch):
    lease = SimpleNamespace(key="f046:dispatch:coordinate:23:41", token="lease-1")
    store = SimpleNamespace(claim=AsyncMock(return_value=lease), release=AsyncMock())
    monkeypatch.setattr(worker, "_build_dispatch_lease_store", AsyncMock(return_value=store))
    task = SimpleNamespace(apply_async=MagicMock(side_effect=RuntimeError("broker down")))

    with pytest.raises(RuntimeError, match="broker down"):
        await worker._dispatch_once(
            task,
            lease_key=lease.key,
            kwargs={"request_id": 41},
            headers={"tenant_id": 23},
        )

    store.release.assert_awaited_once_with(lease)


async def test_redis_failure_keeps_dispatch_live_without_lease_metadata(worker, monkeypatch):
    monkeypatch.setattr(
        worker,
        "_build_dispatch_lease_store",
        AsyncMock(side_effect=RuntimeError("redis down")),
    )
    task = SimpleNamespace(apply_async=MagicMock())

    dispatched = await worker._dispatch_once(
        task,
        lease_key="f046:dispatch:coordinate:23:41",
        kwargs={"request_id": 41},
        headers={"tenant_id": 23},
    )

    assert dispatched is True
    task.apply_async.assert_called_once_with(
        kwargs={"request_id": 41},
        headers={"tenant_id": 23},
    )


async def test_dispatch_installs_explicit_tenant_context_while_publishing(worker, monkeypatch):
    lease = SimpleNamespace(key="f046:dispatch:coordinate:23:41", token="lease-1")
    store = SimpleNamespace(claim=AsyncMock(return_value=lease), release=AsyncMock())
    monkeypatch.setattr(worker, "_build_dispatch_lease_store", AsyncMock(return_value=store))
    published_tenants = []
    task = SimpleNamespace(
        apply_async=MagicMock(side_effect=lambda **_kwargs: published_tenants.append(worker.current_tenant_id.get()))
    )
    outer_token = worker.set_current_tenant_id(1)
    try:
        dispatched = await worker._dispatch_once(
            task,
            lease_key=lease.key,
            kwargs={"request_id": 41},
            headers={"tenant_id": 23},
        )
        assert worker.current_tenant_id.get() == 1
    finally:
        worker.current_tenant_id.reset(outer_token)

    assert dispatched is True
    assert published_tenants == [23]


async def test_consumer_ignores_competing_claim_and_releases_owned_claim(worker, monkeypatch):
    lease = SimpleNamespace(key="f046:dispatch:coordinate:23:41", token="lease-1")
    store = SimpleNamespace(
        adopt_or_acquire=AsyncMock(side_effect=[False, True]),
        renew=AsyncMock(return_value=True),
        release=AsyncMock(),
    )
    monkeypatch.setattr(worker, "_build_dispatch_lease_store", AsyncMock(return_value=store))
    monkeypatch.setattr(worker, "_new_dispatch_lease", lambda **_kwargs: lease)
    business = AsyncMock(return_value={"status": "running"})

    duplicate = await worker._run_claimed_async(
        expected_key=lease.key,
        dispatch_lease_key=lease.key,
        dispatch_lease_token=lease.token,
        coroutine_factory=business,
    )
    owned = await worker._run_claimed_async(
        expected_key=lease.key,
        dispatch_lease_key=lease.key,
        dispatch_lease_token=lease.token,
        coroutine_factory=business,
    )

    assert duplicate == {"status": "deduplicated"}
    assert owned == {"status": "running"}
    business.assert_awaited_once_with()
    store.release.assert_awaited_once_with(lease)


async def test_retry_keeps_producer_claim_but_legacy_failure_releases(worker, monkeypatch):
    lease = SimpleNamespace(key="f046:dispatch:coordinate:23:41", token="lease-1")
    store = SimpleNamespace(
        adopt_or_acquire=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
        release=AsyncMock(),
    )
    monkeypatch.setattr(worker, "_build_dispatch_lease_store", AsyncMock(return_value=store))
    monkeypatch.setattr(worker, "_new_dispatch_lease", lambda **_kwargs: lease)

    async def fail():
        raise RuntimeError("temporary")

    with pytest.raises(RuntimeError, match="temporary"):
        await worker._run_claimed_async(
            expected_key=lease.key,
            dispatch_lease_key=lease.key,
            dispatch_lease_token=lease.token,
            coroutine_factory=fail,
        )
    store.release.assert_not_awaited()

    with pytest.raises(RuntimeError, match="temporary"):
        await worker._run_claimed_async(
            expected_key=lease.key,
            dispatch_lease_key=None,
            dispatch_lease_token=None,
            coroutine_factory=fail,
        )
    store.release.assert_awaited_once_with(lease)


def test_periodic_and_recovery_publishers_use_singleflight_helper():
    source = _WORKER_PATH.read_text(encoding="utf-8")
    direct_publish_lines = [line.strip() for line in source.splitlines() if ".apply_async(" in line]
    assert direct_publish_lines == [
        "execute_file_change_step.apply_async(",
        "task.apply_async(**apply_options)",
    ]


async def test_redis_dispatch_lease_uses_owner_token_for_adopt_renew_and_release():
    module = _load_lease_module()
    redis = SimpleNamespace(
        set=AsyncMock(side_effect=[True, False]),
        eval=AsyncMock(side_effect=[1, 0, 1, 1]),
    )
    store = module.FileChangeDispatchLeaseStore(redis, ttl_seconds=900)

    lease = await store.claim("f046:dispatch:coordinate:23:41")
    duplicate = await store.claim("f046:dispatch:coordinate:23:41")

    assert lease is not None
    assert duplicate is None
    assert await store.adopt_or_acquire(lease) is True
    assert await store.adopt_or_acquire(lease) is False
    assert await store.renew(lease) is True
    await store.release(lease)
    for call in redis.eval.await_args_list:
        assert call.args[2] == lease.key
        assert call.args[3] == lease.token


async def test_all_tenant_fanout_isolates_one_broker_failure(worker, monkeypatch):
    monkeypatch.setattr(worker, "_load_active_tenant_ids", AsyncMock(return_value=[11, 12, 13]))
    dispatch = AsyncMock(side_effect=[True, RuntimeError("broker down"), False])
    monkeypatch.setattr(worker, "_dispatch_once", dispatch)

    result = await worker._coordinate_all_tenants_async(
        tenant_task=worker.watchdog_tenant_file_change_executions,
        initial_kwargs={"after_request_id": 0},
        dispatch_kind="scan-watchdog",
    )

    assert result == {"processed": 3, "dispatched": 1, "failed": 1}
    assert [call.kwargs["headers"] for call in dispatch.await_args_list] == [
        {"tenant_id": 11},
        {"tenant_id": 12},
        {"tenant_id": 13},
    ]
