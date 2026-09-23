"""调度、租约与租户级任务隔离。"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.contracts.shared_storage_reconcile import ReconcileLockLost

# 全局测试夹具会替换 worker 包; 单独加载真实任务模块, 不测试 MagicMock。
BACKEND_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "reconcile_worker_under_test", BACKEND_ROOT / "bisheng/worker/knowledge/shared_storage_reconcile.py"
)
subject = importlib.util.module_from_spec(spec)
_runtime_name = "bisheng.worker._asyncio_utils"
_previous_runtime = sys.modules.get(_runtime_name)
sys.modules[_runtime_name] = SimpleNamespace(run_async_task=MagicMock())
try:
    spec.loader.exec_module(subject)
finally:
    # 只恢复这个替身; 不能清除加载期间注册过 ORM 表的其他模块。
    if _previous_runtime is None:
        sys.modules.pop(_runtime_name, None)
    else:
        sys.modules[_runtime_name] = _previous_runtime


def test_default_daily_schedule_and_registration():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from bisheng.core.config.settings import CeleryConf
from bisheng.worker.config import timezone
from bisheng.worker.main import bisheng_celery
task = CeleryConf().beat_schedule["fanout_shared_storage_reconcile"]
assert task["schedule"].hour == {2}
assert task["schedule"].minute == {0}
assert timezone == "Asia/Shanghai"
assert task["task"] in bisheng_celery.tasks
""",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("owned", [False, ConnectionError("redis unavailable")])
async def test_lost_or_unverifiable_lease_stops_writes(owned):
    lock = SimpleNamespace(owned=AsyncMock())
    if isinstance(owned, Exception):
        lock.owned.side_effect = owned
    else:
        lock.owned.return_value = owned
    lease = subject.ReconcileLease(lock)
    with pytest.raises(ReconcileLockLost):
        await lease.guard()
    assert lease.lost


async def test_overlapping_run_does_not_start_scan_or_release_other_lock(monkeypatch):
    lock = SimpleNamespace(acquire=AsyncMock(return_value=False), release=AsyncMock())
    connection = SimpleNamespace(lock=MagicMock(return_value=lock))
    monkeypatch.setattr(
        subject, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=connection))
    )
    factory = MagicMock(side_effect=AssertionError("must not query stores"))
    monkeypatch.setattr(subject, "SharedStorageReconcileAdapter", factory)
    result = await subject._run_tenant(1)
    assert result["status"] == "already_running"
    lock.release.assert_not_awaited()
    factory.assert_not_called()


async def test_tenant_dispatch_failure_does_not_stop_other_tenants(monkeypatch):
    monkeypatch.setattr(subject.TenantDao, "aget_children_ids_active", AsyncMock(return_value=[2, 3]))
    dispatched = []

    def dispatch(**kwargs):
        dispatched.append(kwargs["kwargs"]["tenant_id"])
        if dispatched[-1] == 2:
            raise ConnectionError("broker unavailable")

    monkeypatch.setattr(subject.reconcile_tenant_shared_storage, "apply_async", dispatch)
    assert await subject._fanout() == {"submitted": 2, "failed": 1}
    assert dispatched == [1, 2, 3]


async def test_startup_failure_releases_own_lock_and_returns_incomplete(monkeypatch):
    lock = SimpleNamespace(acquire=AsyncMock(return_value=True), release=AsyncMock())
    connection = SimpleNamespace(lock=MagicMock(return_value=lock))
    monkeypatch.setattr(
        subject, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=connection))
    )
    monkeypatch.setattr(
        subject, "load_tenant_routing_snapshot", MagicMock(side_effect=ConnectionError("database unavailable"))
    )
    result = await subject._run_tenant(1)
    assert result["status"] == "incomplete"
    lock.release.assert_awaited_once()


async def test_heartbeat_failure_marks_lease_lost(monkeypatch):
    lock = SimpleNamespace(extend=AsyncMock(side_effect=ConnectionError("redis unavailable")))
    lease = subject.ReconcileLease(lock)
    monkeypatch.setattr(subject.asyncio, "sleep", AsyncMock())
    await lease.heartbeat()
    assert lease.lost
    with pytest.raises(ReconcileLockLost):
        await lease.guard()


@pytest.mark.parametrize("publish_fails", [False, True])
async def test_reconcile_publishes_one_batch_and_preserves_pending_on_failure(monkeypatch, publish_fails):
    lock = SimpleNamespace(
        acquire=AsyncMock(return_value=True), owned=AsyncMock(return_value=True), release=AsyncMock()
    )
    connection = SimpleNamespace(lock=MagicMock(return_value=lock))
    monkeypatch.setattr(
        subject, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=connection))
    )
    monkeypatch.setattr(subject, "load_tenant_routing_snapshot", MagicMock(return_value=object()))
    monkeypatch.setattr(subject, "require_initialized_shared_routing", lambda tenant_id, snapshot: snapshot)
    store = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(subject, "SharedStorageReconcileAdapter", MagicMock(return_value=store))
    publish = MagicMock(side_effect=ConnectionError("broker unavailable") if publish_fails else None)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.document_projection",
        SimpleNamespace(enqueue_document_projection_entries=publish),
    )

    class ReconcileService:
        def __init__(self, **kwargs):
            self.dispatch = kwargs["dispatch"]

        async def run(self):
            await self.dispatch(102)
            await self.dispatch(101)
            publish.assert_not_called()
            return {"status": "complete", "rebuild_submitted": 2, "rebuild_pending": 0}

    monkeypatch.setattr(subject, "SharedStorageReconcileService", ReconcileService)
    result = await subject._run_tenant(1)
    publish.assert_called_once_with(tenant_id=1, entry_ids=[101, 102])
    assert result["status"] == ("incomplete" if publish_fails else "complete")
    assert result["rebuild_submitted"] == (0 if publish_fails else 2)
    assert result["rebuild_pending"] == (2 if publish_fails else 0)
    lock.release.assert_awaited_once()
    store.close.assert_awaited_once()
