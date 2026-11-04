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
    monkeypatch.setattr(user_mod, "UserDao", user_dao)

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


def test_registered_task_uses_real_reconcile_service_and_excludes_kunlian():
    # 通用 conftest 预模拟整个 Celery 包。独立进程验证真实注册与 apply。
    import subprocess
    import textwrap

    script = textwrap.dedent("""
        import asyncio
        import importlib
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from celery import Celery
        for name in ('celery.schedules', 'celery.app', 'celery.app.task', 'celery.signals'):
            importlib.import_module(name)
        app = Celery('f118-reconcile-fixture', broker='memory://', backend='cache+memory://')
        from test.fixtures.mock_services import premock_import_chain
        premock_import_chain()
        main = ModuleType('bisheng.worker.main')
        main.bisheng_celery = app
        sys.modules['bisheng.worker.main'] = main
        name = 'bisheng.worker.tenant_reconcile.tasks'
        from pathlib import Path
        for package_name, directory in (('bisheng.worker', 'bisheng/worker'), ('bisheng.worker.tenant_reconcile', 'bisheng/worker/tenant_reconcile')):
            package = ModuleType(package_name)
            package.__path__ = [str(Path(directory).resolve())]
            sys.modules[package_name] = package
        spec = importlib.util.spec_from_file_location(name, 'bisheng/worker/tenant_reconcile/tasks.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        from bisheng.database.models.department import UserDepartmentDao
        from bisheng.database.models.tenant import UserTenantDao
        from bisheng.tenant.domain.repositories.external_membership import ExternalMembershipRepository
        from bisheng.tenant.domain.services.user_tenant_reconcile_service import UserTenantReconcileContext, UserTenantReconcileService
        from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger
        from bisheng.user.domain.models.user import UserDao
        sync = AsyncMock()
        with (patch.object(module, 'run_async_task', lambda fn: asyncio.run(fn())),
              patch.object(UserDao, 'alist_users_after_id', AsyncMock(side_effect=[[SimpleNamespace(user_id=17), SimpleNamespace(user_id=18)], []])),
              patch.object(ExternalMembershipRepository, 'find_external_user_ids', AsyncMock(return_value=frozenset({17}))),
              patch.object(UserDepartmentDao, 'aget_primary_department_paths_by_user_ids', AsyncMock(return_value={})),
              patch.object(UserTenantDao, 'aget_active_tenant_ids_by_user_ids', AsyncMock(return_value={17: 7, 18: 7})),
              patch.object(UserTenantReconcileService, 'load_context', AsyncMock(return_value=UserTenantReconcileContext({}, frozenset({1, 7})))),
              patch.object(UserTenantSyncService, 'sync_user', sync)):
            task = app.tasks[name + '.reconcile_user_tenant_assignments']
            assert task.run.__globals__ is module.__dict__
            assert task.apply(throw=True, headers={'tenant_id': 1}).successful()
            sync.assert_awaited_once_with(18, trigger=UserTenantSyncTrigger.CELERY_RECONCILE)
        app.close()
        print('PASS registered Celery task -> real reconciliation service')
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS registered Celery task" in result.stdout
