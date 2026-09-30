# ruff: noqa: E402
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[2]

# conftest pre-mocks bisheng.worker* in sys.modules (celery breaks in tests), so
# attribute access on the mocked package yields MagicMocks. Restore __path__ on
# the mocked parents and import the *real* submodule by full dotted path.
sys.modules["bisheng.worker"].__path__ = [str(_BACKEND / "bisheng/worker")]
sys.modules["bisheng.worker.knowledge"].__path__ = [str(_BACKEND / "bisheng/worker/knowledge")]
portal_hot_search = importlib.import_module("bisheng.worker.knowledge.portal_hot_search")

from bisheng.core.context.tenant import current_tenant_id


@pytest.mark.parametrize("trigger", ["scheduled", "manual"])
def test_rebuild_keeps_source_specific_retry_policy(monkeypatch, trigger):
    spec = importlib.util.spec_from_file_location("hot_search_task_test", portal_hot_search.__file__)
    worker = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "bisheng.worker.main": SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda **_kwargs: lambda fn: fn),
        ),
    }):
        spec.loader.exec_module(worker)
    failure = RuntimeError("rebuild unavailable")
    monkeypatch.setattr(worker, "run_async_task", MagicMock(side_effect=failure))
    task = SimpleNamespace(request=SimpleNamespace(retries=2), retry=MagicMock(side_effect=failure))
    with pytest.raises(RuntimeError, match="rebuild unavailable"):
        worker.rebuild_portal_hot_search_snapshot_celery(task, trigger=trigger)
    if trigger == "scheduled":
        task.retry.assert_called_once()
        assert task.retry.call_args.kwargs["max_retries"] == 3
        assert 0 <= task.retry.call_args.kwargs["countdown"] <= 4
    else:
        task.retry.assert_not_called()


def test_admin_dispatches_unified_task_with_manual_source(monkeypatch):
    from bisheng.knowledge.domain.services.portal_hot_search_admin_service import PortalHotSearchAdminService

    publish = MagicMock(return_value=SimpleNamespace(id="manual-task"))
    monkeypatch.setattr(portal_hot_search.rebuild_portal_hot_search_snapshot_celery, "apply_async", publish)
    assert PortalHotSearchAdminService._dispatch_tenant_rebuild(7) == "manual-task"
    assert publish.call_args.kwargs["kwargs"] == {"trigger": "manual"}
    assert publish.call_args.kwargs["headers"] == {"tenant_id": 7}


def test_worker_package_imports_module_explicitly():
    source = (_BACKEND / "bisheng/worker/__init__.py").read_text(encoding="utf-8")
    assert "worker.knowledge.portal_hot_search" in source


def test_tasks_and_beat_registered_by_worker_package():
    """Beat publishes fanout and the worker package registers the unified task.

    Runs in a subprocess so the celery app / settings validation happen in a
    clean process, matching test_celery_beat_task_registration.
    """
    script = r"""
import json
from bisheng.common.services.config_service import settings
from bisheng.worker.main import bisheng_celery

required = [
    "bisheng.worker.knowledge.portal_hot_search.fanout_portal_hot_search_rebuild",
    "bisheng.worker.knowledge.portal_hot_search.rebuild_portal_hot_search_snapshot",
]
missing = [name for name in required if name not in bisheng_celery.tasks]
entry = settings.celery_task.beat_schedule.get("portal_hot_search_rebuild_daily")
beat_ok = bool(entry) and entry["task"] == required[0]
print("RESULT=" + json.dumps({"missing": missing, "beat_ok": beat_ok}))
raise SystemExit(0 if (not missing and beat_ok) else 1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_fanout_dispatches_per_tenant_with_headers():
    dispatched = []

    def _capture(*, kwargs=None, headers=None, queue=None, time_limit=None):
        assert kwargs == {"trigger": "scheduled"}
        assert time_limit == 1800
        dispatched.append((headers, queue))

    original_dao = portal_hot_search.TenantDao
    original_apply = portal_hot_search.rebuild_portal_hot_search_snapshot_celery.apply_async
    portal_hot_search.TenantDao = SimpleNamespace(aget_children_ids_active=AsyncMock(return_value=[5, 7]))
    portal_hot_search.rebuild_portal_hot_search_snapshot_celery.apply_async = _capture
    try:
        count = await portal_hot_search._fanout_async()
    finally:
        portal_hot_search.TenantDao = original_dao
        portal_hot_search.rebuild_portal_hot_search_snapshot_celery.apply_async = original_apply

    assert count == 3  # default tenant + 5 + 7
    tenant_ids = sorted(h["tenant_id"] for h, _q in dispatched)
    assert tenant_ids == [1, 5, 7]
    assert all(q == "celery" for _h, q in dispatched)


@pytest.mark.asyncio
async def test_rebuild_short_circuits_when_disabled():
    original = portal_hot_search.settings
    portal_hot_search.settings = SimpleNamespace(portal_hot_search=SimpleNamespace(enabled=False))
    token = current_tenant_id.set(1)
    try:
        result = await portal_hot_search._rebuild_async()
    finally:
        current_tenant_id.reset(token)
        portal_hot_search.settings = original
    assert result == "disabled"
