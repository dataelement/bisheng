# ruff: noqa: E402
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_BACKEND = Path(__file__).resolve().parents[2]

# conftest pre-mocks bisheng.worker* in sys.modules (celery breaks in tests), so
# attribute access on the mocked package yields MagicMocks. Restore __path__ on
# the mocked parents and import the *real* submodule by full dotted path.
sys.modules["bisheng.worker"].__path__ = [str(_BACKEND / "bisheng/worker")]
sys.modules["bisheng.worker.knowledge"].__path__ = [str(_BACKEND / "bisheng/worker/knowledge")]
portal_hot_search = importlib.import_module("bisheng.worker.knowledge.portal_hot_search")

from bisheng.core.context.tenant import current_tenant_id


def test_worker_package_imports_module_explicitly():
    source = (_BACKEND / "bisheng/worker/__init__.py").read_text(encoding="utf-8")
    assert "worker.knowledge.portal_hot_search" in source


def test_tasks_and_beat_registered_by_worker_package():
    """Beat publishes the fanout task and the worker package registers all three.

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
    "bisheng.worker.knowledge.portal_hot_search.trigger_portal_hot_search_rebuild",
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

    def _capture(*, kwargs=None, headers=None, queue=None):
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
    assert all(q == "knowledge_celery" for _h, q in dispatched)


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
