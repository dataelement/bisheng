"""Unit tests for ``POST /api/v1/org-sync/execute`` (admin console「立即同步」).

The route is called directly (FastAPI's ``Depends`` is bypassed by passing
``login_user``) with the DAO, the Redis gate and the Celery task patched, so
what is asserted here is the endpoint's decision table: who may enqueue, what
is passed to the task, and how duplicate submissions are rejected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigNotFoundError,
    OrgSyncInvalidConfigError,
)
from bisheng.org_sync.api.endpoints import sync_config as ep
from bisheng.org_sync.domain.services.sync_enqueue_lock import EnqueueLock


def _config(**overrides) -> SimpleNamespace:
    base = {
        "id": 7,
        "tenant_id": 1,
        "provider": "wecom",
        "status": "active",
        "sync_status": "idle",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _user() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=1, user_id=42)


@pytest.fixture()
def env(monkeypatch):
    """Patch the endpoint's collaborators; ``state`` feeds the scenario."""
    state: dict = {}
    release = AsyncMock()
    task = MagicMock()
    task.apply_async.return_value = SimpleNamespace(id="task-1")

    async def _get_config(config_id, login_user):
        return state.get("config")

    async def _acquire(config_id):
        return state.get("lock", EnqueueLock(acquired=True, token="tok"))

    async def _locked(config_id):
        return state.get("locked", False)

    import bisheng.worker.org_sync.tasks as tasks

    monkeypatch.setattr(ep, "_get_config_or_404", _get_config)
    monkeypatch.setattr(ep, "acquire_enqueue_lock", _acquire)
    monkeypatch.setattr(ep, "release_enqueue_lock", release)
    monkeypatch.setattr(tasks, "execute_org_sync", task)
    monkeypatch.setattr(ep, "is_enqueue_locked", _locked)

    return SimpleNamespace(state=state, task=task, release=release)


async def test_execute_enqueues_with_lock_token(env):
    env.state["config"] = _config()

    resp = await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    assert resp.status_code == 200
    assert resp.data == {"config_id": 7, "task_id": "task-1"}
    # The queue is explicit: the deployment's worker consumes `-Q celery`.
    env.task.apply_async.assert_called_once_with(args=[7, 42, "tok"], queue="celery")


async def test_busy_queue_gate_returns_22003(env):
    env.state["config"] = _config()
    env.state["lock"] = EnqueueLock(acquired=False, token=None)

    resp = await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    assert resp.status_code == OrgSyncAlreadyRunningError.Code
    env.task.apply_async.assert_not_called()


async def test_running_config_returns_22003(env):
    env.state["config"] = _config(sync_status="running")

    resp = await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    assert resp.status_code == OrgSyncAlreadyRunningError.Code
    env.task.apply_async.assert_not_called()


async def test_unsupported_provider_rejected(env):
    env.state["config"] = _config(provider="feishu")

    resp = await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    assert resp.status_code == OrgSyncInvalidConfigError.Code


async def test_missing_config_rejected(env):
    env.state["config"] = None

    resp = await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    assert resp.status_code == OrgSyncConfigNotFoundError.Code


async def test_broker_failure_releases_the_gate(env):
    env.state["config"] = _config()
    env.task.apply_async.side_effect = RuntimeError("broker down")

    with pytest.raises(RuntimeError):
        await ep.execute_config(ep.OrgSyncExecuteRequest(config_id=7), login_user=_user())

    env.release.assert_awaited_once_with(7, "tok")


async def test_delete_is_blocked_while_a_run_is_queued(env):
    env.state["config"] = _config(sync_status="idle")
    env.state["locked"] = True

    resp = await ep.delete_config(7, login_user=_user())

    # `sync_status` is still idle — only the queue gate knows a run is waiting.
    assert resp.status_code == OrgSyncAlreadyRunningError.Code
