"""F019 T11 — admin_scope Celery sweep tests.

Tests the internal ``_cleanup_async`` coroutine directly; the Celery
wrapper just runs the event loop. AC-13 covered:

  - Keys pointing at non-active tenants are deleted.
  - Keys pointing at active tenants stay put.
  - Empty Redis scan is a no-op (no DB query fired).
  - All-active tenants is a no-op (no deletes).
  - Corrupt Redis values (non-numeric) are cleaned up as stale.
  - ``bypass_tenant_filter`` wraps the cross-tenant DB query.

Strategy mirrors ``test_tenant_reconcile_task.py``: ``bisheng.worker``'s
``__init__`` eagerly pulls the world, so we importlib-load ``tasks.py``
directly with a stubbed ``@bisheng_celery.task`` decorator.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_tasks_module() -> ModuleType:
    _celery_stub = MagicMock(name='bisheng_celery')
    _celery_stub.task = lambda *a, **kw: (lambda fn: fn)  # passthrough
    sys.modules['bisheng.worker.main'] = MagicMock(bisheng_celery=_celery_stub)

    if 'bisheng.worker' not in sys.modules or not isinstance(
        getattr(sys.modules['bisheng.worker'], '__path__', None), list,
    ):
        # Derive the worker path from this test file's location so the
        # test works under any checkout root (main repo, worktrees,
        # /opt/bisheng, /opt/bisheng-f019, etc.). A hard-coded /opt path
        # would break the moment we run inside a worktree.
        worker_path = Path(__file__).resolve().parent.parent / 'bisheng' / 'worker'
        stub_pkg = ModuleType('bisheng.worker')
        stub_pkg.__path__ = [str(worker_path)]
        sys.modules['bisheng.worker'] = stub_pkg
    if 'bisheng.worker.admin_scope' not in sys.modules:
        sub_pkg = ModuleType('bisheng.worker.admin_scope')
        sub_pkg.__path__ = [str(
            Path(sys.modules['bisheng.worker'].__path__[0]) / 'admin_scope'
        )]
        sys.modules['bisheng.worker.admin_scope'] = sub_pkg

    tasks_path = (
        Path(sys.modules['bisheng.worker'].__path__[0])
        / 'admin_scope' / 'tasks.py'
    )
    spec = importlib.util.spec_from_file_location(
        'bisheng.worker.admin_scope.tasks', tasks_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['bisheng.worker.admin_scope.tasks'] = module
    spec.loader.exec_module(module)
    return module


tasks_module = _load_tasks_module()


# ---------------------------------------------------------------------------
# Fake Redis + DAO patches
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self, store: dict[str, str]):
        self.store = dict(store)
        self.deleted: list[str] = []

    async def akeys(self, pattern: str):
        prefix = pattern.rstrip('*')
        return [k for k in self.store if k.startswith(prefix)]

    async def aget(self, key: str):
        return self.store.get(key)

    async def adelete(self, key: str):
        if key in self.store:
            del self.store[key]
            self.deleted.append(key)
            return 1
        return 0


@pytest.fixture()
def bypass_spy(monkeypatch):
    """Wrap ``bypass_tenant_filter`` so we can assert it was used."""
    from bisheng.core.context import tenant as tenant_mod
    calls = {'entered': 0, 'exited': 0}

    real_cm = tenant_mod.bypass_tenant_filter

    def _spy():
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            calls['entered'] += 1
            with real_cm():
                yield
            calls['exited'] += 1

        return _cm()

    # Replace in the tasks module's imported symbol — the function imports
    # it lazily inside ``_cleanup_async``, so we patch the source module.
    monkeypatch.setattr(tenant_mod, 'bypass_tenant_filter', _spy)
    return calls


def _patch_deps(monkeypatch, redis_store, non_active_ids):
    """Install a fake Redis + TenantDao for a single test call."""
    fake = _FakeRedis(redis_store)

    async def _get_client():
        return fake

    # Patch the module-level imports inside ``_cleanup_async``.
    import importlib
    rm_mod = importlib.import_module('bisheng.core.cache.redis_manager')
    monkeypatch.setattr(rm_mod, 'get_redis_client', _get_client)

    from bisheng.database.models.tenant import TenantDao
    monkeypatch.setattr(
        TenantDao, 'aget_non_active_ids',
        AsyncMock(return_value=list(non_active_ids)),
    )
    return fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cleanup_removes_non_active_scopes(monkeypatch, bypass_spy):
    """AC-13: keys pointing at non-active tenants → deleted."""
    fake = _patch_deps(
        monkeypatch,
        redis_store={
            'admin_scope:1': '5',   # tenant 5 disabled → DELETE
            'admin_scope:2': '6',   # tenant 6 active → KEEP
            'admin_scope:3': '7',   # tenant 7 orphaned → DELETE
        },
        non_active_ids={5, 7},
    )

    asyncio.run(tasks_module._cleanup_async())

    assert sorted(fake.deleted) == ['admin_scope:1', 'admin_scope:3']
    assert 'admin_scope:2' in fake.store
    # Bypass wrapped the DB query exactly once.
    assert bypass_spy['entered'] == 1
    assert bypass_spy['exited'] == 1


def test_cleanup_noop_when_no_keys(monkeypatch, bypass_spy):
    """Empty Redis → skip DB call entirely (fast path)."""
    fake = _patch_deps(monkeypatch, redis_store={}, non_active_ids={5})

    asyncio.run(tasks_module._cleanup_async())

    assert fake.deleted == []
    # bypass_tenant_filter must NOT be entered — proof the DB lookup was skipped.
    assert bypass_spy['entered'] == 0


def test_cleanup_noop_when_all_active(monkeypatch, bypass_spy):
    """No non-active tenants → no deletes even with scope keys present."""
    fake = _patch_deps(
        monkeypatch,
        redis_store={'admin_scope:1': '5', 'admin_scope:2': '6'},
        non_active_ids=set(),
    )

    asyncio.run(tasks_module._cleanup_async())

    assert fake.deleted == []
    assert bypass_spy['entered'] == 1


def test_cleanup_removes_corrupt_value(monkeypatch, bypass_spy):
    """Non-numeric value in Redis → cleaned up as stale."""
    fake = _patch_deps(
        monkeypatch,
        redis_store={
            'admin_scope:1': 'not-a-number',
            'admin_scope:2': '6',
        },
        non_active_ids={999},  # Neither key points at a non-active tenant.
    )

    asyncio.run(tasks_module._cleanup_async())

    # Corrupt key deleted, valid key kept.
    assert fake.deleted == ['admin_scope:1']
    assert 'admin_scope:2' in fake.store
