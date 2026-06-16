"""Regression for the standalone Linsight worker's startup cleanup.

``check_and_terminate_incomplete_tasks`` runs at worker boot, without an HTTP
request, so no tenant ContextVar is set. Under ``multi_tenant.enabled`` the first
DAO query used to raise ``NoTenantContextError`` (20004) and abort the whole
sweep, leaving every tenant's orphaned IN_PROGRESS tasks stuck IN_PROGRESS.

The fix wraps the DB body in ``bypass_tenant_filter()`` — this is a deliberate
cross-tenant sweep of every tenant's orphaned tasks. These tests assert the DB
operations execute *under* the bypass and that the bypass is released afterward.
DAO/redis are faked, so the assertion is on the active bypass flag at call time
rather than on a live tenant_filter event listener.
"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.linsight.domain import utils
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum


class _StubNodeManager:
    """Lightweight stand-in so the test never touches real Redis/worker plumbing."""

    def __init__(self, redis_client, node_id):
        self.redis_client = redis_client
        self.node_id = node_id

    async def is_node_alive(self, target_node_id):  # pragma: no cover - unused in these paths
        return False


@pytest.fixture
def patched_worker(monkeypatch):
    """Fake redis (no task owner) + stub NodeManager + no invite-code rollback.

    The worker module is injected via ``sys.modules`` rather than imported, so the
    function-local ``from bisheng.linsight.worker import NodeManager`` resolves to
    the stub without pulling in the heavy worker import chain (ollama/httpx etc.).
    """
    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.NodeManager = _StubNodeManager
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)

    fake_redis = SimpleNamespace(aget=AsyncMock(return_value=None))
    monkeypatch.setattr(utils, "get_redis_client", AsyncMock(return_value=fake_redis))
    # Patch the class (not the pydantic instance, which rejects unknown attrs).
    monkeypatch.setattr(type(utils.settings), "aget_all_config", AsyncMock(return_value={}))
    return fake_redis


async def test_query_runs_under_bypass_tenant_filter(monkeypatch, patched_worker):
    """The IN_PROGRESS query must execute while tenant filtering is bypassed."""
    seen = {}

    async def fake_get(status):
        seen["bypassed"] = is_tenant_filter_bypassed()
        seen["status"] = status
        return []  # no incomplete tasks -> early return inside the bypass block

    monkeypatch.setattr(utils.LinsightSessionVersionDao, "get_session_versions_by_status", fake_get)

    assert is_tenant_filter_bypassed() is False  # not bypassed before the call
    await utils.check_and_terminate_incomplete_tasks("node-A")

    assert seen["bypassed"] is True
    assert seen["status"] == SessionVersionStatusEnum.IN_PROGRESS
    assert is_tenant_filter_bypassed() is False  # bypass released after the call


async def test_batch_updates_run_under_bypass_tenant_filter(monkeypatch, patched_worker):
    """An orphaned task (no Redis owner) is terminated, and the batch updates that
    mark it FAILED also run under the bypass — not just the initial query."""
    orphan = SimpleNamespace(id="sv-1", user_id=42)
    flags = {}

    async def fake_get(status):
        return [orphan]

    async def fake_sv_update(**kwargs):
        flags["sv"] = is_tenant_filter_bypassed()
        flags["ids"] = kwargs["session_version_ids"]

    async def fake_task_update(**kwargs):
        flags["task"] = is_tenant_filter_bypassed()

    monkeypatch.setattr(utils.LinsightSessionVersionDao, "get_session_versions_by_status", fake_get)
    monkeypatch.setattr(utils.LinsightSessionVersionDao, "batch_update_session_versions_status", fake_sv_update)
    monkeypatch.setattr(utils.LinsightExecuteTaskDao, "batch_update_status_by_session_version_id", fake_task_update)

    await utils.check_and_terminate_incomplete_tasks("node-A")

    assert flags["sv"] is True
    assert flags["task"] is True
    assert flags["ids"] == ["sv-1"]  # the orphaned task was queued for termination
    assert is_tenant_filter_bypassed() is False
