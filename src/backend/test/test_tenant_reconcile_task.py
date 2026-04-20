"""Tests for F012 6h reconcile Celery task.

Tests the internal ``_reconcile_async`` coroutine directly — the Celery
wrapper just spins up an event loop and calls through, so asserting the
orchestration (pagination, trigger name, blocked-error tolerance) is
sufficient here. The beat_schedule registration is a config-level
invariant that's easier to assert via ``CeleryConf.validate()``
in-process.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ``bisheng.worker.__init__`` eagerly imports the full task universe, which
# pulls in celery.signals and several heavy dependency chains that cannot
# be mocked cleanly in unit tests. We therefore side-load ``tasks.py``
# directly via importlib and inject fake worker-main so ``@bisheng_celery.task``
# is a passthrough.

def _load_tasks_module() -> ModuleType:
    _celery_stub = MagicMock(name='bisheng_celery')
    _celery_stub.task = lambda *a, **kw: (lambda fn: fn)  # passthrough decorator
    sys.modules['bisheng.worker.main'] = MagicMock(bisheng_celery=_celery_stub)

    # Provide a stub parent package to satisfy `bisheng.worker.tenant_reconcile.tasks`
    # resolution without triggering worker/__init__.py.
    if 'bisheng.worker' not in sys.modules or not isinstance(
        getattr(sys.modules['bisheng.worker'], '__path__', None), list,
    ):
        stub_pkg = ModuleType('bisheng.worker')
        stub_pkg.__path__ = [str(
            Path('/opt/bisheng/src/backend/bisheng/worker')
            if Path('/opt/bisheng/src/backend/bisheng/worker').exists()
            else Path(__file__).parent.parent / 'bisheng' / 'worker'
        )]
        sys.modules['bisheng.worker'] = stub_pkg
    if 'bisheng.worker.tenant_reconcile' not in sys.modules:
        sub_pkg = ModuleType('bisheng.worker.tenant_reconcile')
        sub_pkg.__path__ = [str(
            Path(sys.modules['bisheng.worker'].__path__[0]) / 'tenant_reconcile'
        )]
        sys.modules['bisheng.worker.tenant_reconcile'] = sub_pkg

    tasks_path = (
        Path(sys.modules['bisheng.worker'].__path__[0])
        / 'tenant_reconcile' / 'tasks.py'
    )
    spec = importlib.util.spec_from_file_location(
        'bisheng.worker.tenant_reconcile.tasks', tasks_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['bisheng.worker.tenant_reconcile.tasks'] = module
    spec.loader.exec_module(module)
    return module


tasks_module = _load_tasks_module()

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.tenant.domain.constants import UserTenantSyncTrigger


def _user(user_id: int):
    return SimpleNamespace(user_id=user_id, user_name=f'u{user_id}', delete=0)


@pytest.fixture()
def patches(monkeypatch):
    list_users_mock = AsyncMock(name='alist_users_paginated')
    sync_mock = AsyncMock(name='sync_user')

    # Patch the DAO + service on whatever gets imported inside the task.
    # ``bisheng.user.domain.models.user`` is pre-mocked — we poke through
    # sys.modules to swap the UserDao stub before tasks.py imports it.
    user_mod = sys.modules.get('bisheng.user.domain.models.user')
    if user_mod is None:
        user_mod = MagicMock()
        sys.modules['bisheng.user.domain.models.user'] = user_mod
    stub_user_dao = MagicMock()
    stub_user_dao.alist_users_paginated = list_users_mock
    user_mod.UserDao = stub_user_dao

    import bisheng.tenant.domain.services.user_tenant_sync_service as uts_mod
    monkeypatch.setattr(
        uts_mod.UserTenantSyncService, 'sync_user', sync_mock,
    )
    return SimpleNamespace(list_users=list_users_mock, sync=sync_mock)


class TestReconcileAsync:

    def test_scans_all_users_one_batch(self, patches):
        users = [_user(i) for i in range(1, 6)]
        patches.list_users.side_effect = [users, []]  # 1 batch then empty
        patches.sync.return_value = SimpleNamespace(id=1)

        asyncio.run(tasks_module._reconcile_async())

        assert patches.sync.await_count == 5
        # Trigger always CELERY_RECONCILE.
        for call in patches.sync.await_args_list:
            assert call.kwargs.get('trigger') == UserTenantSyncTrigger.CELERY_RECONCILE

    def test_scans_multiple_batches(self, patches, monkeypatch):
        monkeypatch.setattr(tasks_module, 'BATCH_SIZE', 2)
        batch1 = [_user(1), _user(2)]
        batch2 = [_user(3), _user(4)]
        batch3 = [_user(5)]
        patches.list_users.side_effect = [batch1, batch2, batch3, []]
        patches.sync.return_value = SimpleNamespace(id=1)

        asyncio.run(tasks_module._reconcile_async())
        assert patches.sync.await_count == 5

    def test_blocked_errors_swallowed(self, patches):
        users = [_user(1), _user(2), _user(3)]
        patches.list_users.side_effect = [users, []]
        patches.sync.side_effect = [
            SimpleNamespace(id=1),
            TenantRelocateBlockedError(owned_count=2),
            SimpleNamespace(id=1),
        ]

        # Should not raise.
        asyncio.run(tasks_module._reconcile_async())
        assert patches.sync.await_count == 3

    def test_generic_errors_swallowed_with_logging(self, patches):
        users = [_user(1), _user(2)]
        patches.list_users.side_effect = [users, []]
        patches.sync.side_effect = [
            RuntimeError('db timeout'),
            SimpleNamespace(id=1),
        ]

        # Exception on user 1 must not stop user 2's sync.
        asyncio.run(tasks_module._reconcile_async())
        assert patches.sync.await_count == 2

    def test_empty_user_table_noop(self, patches):
        patches.list_users.side_effect = [[]]
        asyncio.run(tasks_module._reconcile_async())
        patches.sync.assert_not_awaited()
