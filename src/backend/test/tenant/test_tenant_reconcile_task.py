"""Tests for the optimized F012 user-tenant reconcile Celery task."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.tenant.domain.constants import UserTenantSyncTrigger


def _load_tasks_module() -> ModuleType:
    celery_stub = MagicMock(name="bisheng_celery")
    celery_stub.task = lambda *args, **kwargs: lambda function: function
    sys.modules["bisheng.worker.main"] = MagicMock(bisheng_celery=celery_stub)

    worker_path = getattr(sys.modules.get("bisheng.worker"), "__path__", None)
    if not (isinstance(worker_path, list) and worker_path):
        package = ModuleType("bisheng.worker")
        package.__path__ = [str(Path(__file__).resolve().parent.parent.parent / "bisheng" / "worker")]
        sys.modules["bisheng.worker"] = package
    if "bisheng.worker.tenant_reconcile" not in sys.modules:
        package = ModuleType("bisheng.worker.tenant_reconcile")
        package.__path__ = [str(Path(sys.modules["bisheng.worker"].__path__[0]) / "tenant_reconcile")]
        sys.modules["bisheng.worker.tenant_reconcile"] = package

    tasks_path = Path(sys.modules["bisheng.worker"].__path__[0]) / "tenant_reconcile" / "tasks.py"
    spec = importlib.util.spec_from_file_location(
        "bisheng.worker.tenant_reconcile.tasks",
        tasks_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bisheng.worker.tenant_reconcile.tasks"] = module
    spec.loader.exec_module(module)
    return module


tasks_module = _load_tasks_module()


def _user(user_id: int):
    return SimpleNamespace(user_id=user_id, user_name=f"u{user_id}", delete=0)


@pytest.fixture()
def patches(monkeypatch):
    list_users = AsyncMock(name="alist_users_after_id")
    load_context = AsyncMock(name="load_context", return_value=SimpleNamespace())
    find_drifted = AsyncMock(name="find_drifted_user_ids")
    sync = AsyncMock(name="sync_user")

    import bisheng.tenant.domain.services.user_tenant_reconcile_service as reconcile_mod
    import bisheng.tenant.domain.services.user_tenant_sync_service as sync_mod

    user_mod = sys.modules.get("bisheng.user.domain.models.user")
    if user_mod is None:
        user_mod = MagicMock()
        sys.modules["bisheng.user.domain.models.user"] = user_mod
    user_dao = MagicMock()
    user_dao.alist_users_after_id = list_users
    user_mod.UserDao = user_dao

    monkeypatch.setattr(
        reconcile_mod.UserTenantReconcileService,
        "load_context",
        load_context,
    )
    monkeypatch.setattr(
        reconcile_mod.UserTenantReconcileService,
        "find_drifted_user_ids",
        find_drifted,
    )
    monkeypatch.setattr(sync_mod.UserTenantSyncService, "sync_user", sync)
    return SimpleNamespace(
        list_users=list_users,
        load_context=load_context,
        find_drifted=find_drifted,
        sync=sync,
    )


class TestReconcileAsync:
    def test_syncs_only_drifted_users(self, patches):
        users = [_user(user_id) for user_id in range(1, 6)]
        patches.list_users.side_effect = [users, []]
        patches.find_drifted.return_value = [2, 4]

        asyncio.run(tasks_module._reconcile_async())

        assert [call.args[0] for call in patches.sync.await_args_list] == [2, 4]
        for call in patches.sync.await_args_list:
            assert call.kwargs["trigger"] == UserTenantSyncTrigger.CELERY_RECONCILE

    def test_uses_keyset_pagination(self, patches, monkeypatch):
        monkeypatch.setattr(tasks_module, "BATCH_SIZE", 2)
        patches.list_users.side_effect = [
            [_user(3), _user(7)],
            [_user(9)],
            [],
        ]
        patches.find_drifted.side_effect = [[], [], []]

        asyncio.run(tasks_module._reconcile_async())

        assert [call.kwargs["last_user_id"] for call in patches.list_users.await_args_list] == [0, 7, 9]
        patches.sync.assert_not_awaited()

    def test_blocked_error_does_not_stop_other_users(self, patches):
        patches.list_users.side_effect = [[_user(1), _user(2), _user(3)], []]
        patches.find_drifted.return_value = [1, 2, 3]
        patches.sync.side_effect = [
            SimpleNamespace(id=1),
            TenantRelocateBlockedError(owned_count=2),
            SimpleNamespace(id=1),
        ]

        asyncio.run(tasks_module._reconcile_async())

        assert patches.sync.await_count == 3

    def test_generic_error_does_not_stop_other_users(self, patches):
        patches.list_users.side_effect = [[_user(1), _user(2)], []]
        patches.find_drifted.return_value = [1, 2]
        patches.sync.side_effect = [RuntimeError("db timeout"), SimpleNamespace(id=1)]

        asyncio.run(tasks_module._reconcile_async())

        assert patches.sync.await_count == 2

    def test_empty_user_table_noop(self, patches):
        patches.list_users.return_value = []

        asyncio.run(tasks_module._reconcile_async())

        patches.find_drifted.assert_not_awaited()
        patches.sync.assert_not_awaited()
