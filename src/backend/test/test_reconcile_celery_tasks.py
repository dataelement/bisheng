"""Tests for F015 Celery reconcile + conflict-report tasks.

Covers:

- ``_fan_out_all`` dispatches one ``reconcile_single_config`` per
  active config, skipping the F014 ``sso_realtime`` seed.
- ``_run_weekly`` / ``_run_daily_escalation`` delegate to
  :class:`TsConflictReporter`.
- ``reconcile_single_config`` swallows the lock-busy path (AC-13
  precursor).

``bisheng.worker.__init__`` eagerly imports the full task universe,
which pulls in ``celery.signals`` + heavy dependency chains that the
test infrastructure pre-mocks as MagicMock — see
``test/fixtures/mock_services.py``. We therefore side-load
``reconcile_tasks.py`` directly via importlib (same pattern as
``test_tenant_reconcile_task.py``) and inject a passthrough
``bisheng.worker.main`` stub so ``@bisheng_celery.task`` is a no-op.

AC-01 beat-schedule registration is intentionally **not** asserted
here — ``CeleryConf.validate`` runs against the pre-mocked celery
``crontab`` and produces MagicMock schedule objects, which carry no
verifiable state. Manual verification path lives in
``ac-verification.md §2.3(A)``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Side-load bisheng.worker.org_sync.reconcile_tasks without executing
# the full bisheng.worker.__init__ import chain.
# ---------------------------------------------------------------------------


def _load_reconcile_tasks_module() -> ModuleType:
    """Import ``reconcile_tasks.py`` via importlib with a stubbed worker package."""
    _celery_stub = MagicMock(name='bisheng_celery')
    # Passthrough decorator so @bisheng_celery.task keeps the function.
    _celery_stub.task = lambda *a, **kw: (lambda fn: fn)
    sys.modules['bisheng.worker.main'] = MagicMock(
        bisheng_celery=_celery_stub)

    # Stub parent packages (bisheng.worker + bisheng.worker.org_sync)
    # so relative imports resolve without firing worker/__init__.py.
    # Path is derived from this test file so the loader works from any
    # worktree/CI checkout (F012's hard-coded /opt/bisheng/ fallback
    # would shadow a worktree copy with the CI main-line tree).
    backend_root = Path(__file__).resolve().parent.parent / 'bisheng' / 'worker'
    if 'bisheng.worker' not in sys.modules or not isinstance(
        getattr(sys.modules['bisheng.worker'], '__path__', None), list,
    ):
        pkg = ModuleType('bisheng.worker')
        pkg.__path__ = [str(backend_root)]
        sys.modules['bisheng.worker'] = pkg
    if 'bisheng.worker.org_sync' not in sys.modules:
        pkg = ModuleType('bisheng.worker.org_sync')
        pkg.__path__ = [str(backend_root / 'org_sync')]
        sys.modules['bisheng.worker.org_sync'] = pkg

    tasks_path = backend_root / 'org_sync' / 'reconcile_tasks.py'
    spec = importlib.util.spec_from_file_location(
        'bisheng.worker.org_sync.reconcile_tasks', tasks_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['bisheng.worker.org_sync.reconcile_tasks'] = module
    spec.loader.exec_module(module)
    return module


tasks_module = _load_reconcile_tasks_module()


# ---------------------------------------------------------------------------
# Fan-out behaviour
# ---------------------------------------------------------------------------


class TestFanOut:

    def test_fan_out_dispatches_single_config_per_active_config(self):
        active_configs = [
            SimpleNamespace(id=1, provider='feishu'),
            SimpleNamespace(id=2, provider='wecom'),
            SimpleNamespace(id=3, provider='dingtalk'),
        ]
        # The side-loaded celery.task decorator is a passthrough, so
        # ``tasks_module.reconcile_single_config`` is a plain function
        # without ``apply_async``. Replace the attribute with a MagicMock
        # whose auto-attribute protocol gives us ``apply_async`` for free.
        import bisheng.org_sync.domain.models.org_sync as org_mod
        original_aget = org_mod.OrgSyncConfigDao.aget_all_active
        org_mod.OrgSyncConfigDao.aget_all_active = AsyncMock(
            return_value=active_configs)
        orig_fn = tasks_module.reconcile_single_config
        tasks_module.reconcile_single_config = MagicMock(
            name='reconcile_single_config')
        try:
            asyncio.run(tasks_module._fan_out_all())
            calls = tasks_module.reconcile_single_config.apply_async.call_args_list
            assert len(calls) == 3
            ids = [c.kwargs['args'][0] for c in calls]
            assert ids == [1, 2, 3]
        finally:
            org_mod.OrgSyncConfigDao.aget_all_active = original_aget
            tasks_module.reconcile_single_config = orig_fn

    def test_fan_out_skips_sso_realtime_seed(self):
        active_configs = [
            SimpleNamespace(id=1, provider='feishu'),
            SimpleNamespace(id=9999, provider='sso_realtime'),
        ]
        import bisheng.org_sync.domain.models.org_sync as org_mod
        original_aget = org_mod.OrgSyncConfigDao.aget_all_active
        org_mod.OrgSyncConfigDao.aget_all_active = AsyncMock(
            return_value=active_configs)
        orig_fn = tasks_module.reconcile_single_config
        tasks_module.reconcile_single_config = MagicMock(
            name='reconcile_single_config')
        try:
            asyncio.run(tasks_module._fan_out_all())
            calls = tasks_module.reconcile_single_config.apply_async.call_args_list
            ids = [c.kwargs['args'][0] for c in calls]
            assert ids == [1]
            assert 9999 not in ids
        finally:
            org_mod.OrgSyncConfigDao.aget_all_active = original_aget
            tasks_module.reconcile_single_config = orig_fn


# ---------------------------------------------------------------------------
# Lock-busy swallowing
# ---------------------------------------------------------------------------


class TestReconcileSingleConfig:

    def test_single_config_swallows_lock_busy_logs_warning(self, caplog):
        """AC-13 precursor — concurrent worker hits the lock; task exits cleanly."""
        from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError

        import bisheng.org_sync.domain.services.reconcile_service as svc_mod
        original = svc_mod.OrgReconcileService.reconcile_config
        svc_mod.OrgReconcileService.reconcile_config = AsyncMock(
            side_effect=SsoReconcileLockBusyError.http_exception(),
        )
        try:
            with caplog.at_level('WARNING'):
                tasks_module.reconcile_single_config(42)
            messages = [r.getMessage() for r in caplog.records]
            assert any(
                '42' in m and 'lock busy' in m for m in messages
            ), f'warning with config id + lock busy not found; saw: {messages}'
        finally:
            svc_mod.OrgReconcileService.reconcile_config = original


# ---------------------------------------------------------------------------
# Weekly / daily reporter delegation
# ---------------------------------------------------------------------------


class TestReporterDelegation:

    def test_weekly_celery_task_invokes_reporter_weekly(self):
        import bisheng.org_sync.domain.services.ts_conflict_reporter as rep_mod
        original = rep_mod.TsConflictReporter.weekly_report
        rep_mod.TsConflictReporter.weekly_report = AsyncMock()
        try:
            asyncio.run(tasks_module._run_weekly())
            rep_mod.TsConflictReporter.weekly_report.assert_awaited_once()
        finally:
            rep_mod.TsConflictReporter.weekly_report = original

    def test_daily_celery_task_invokes_reporter_daily_escalation(self):
        import bisheng.org_sync.domain.services.ts_conflict_reporter as rep_mod
        original = rep_mod.TsConflictReporter.daily_escalation_report
        rep_mod.TsConflictReporter.daily_escalation_report = AsyncMock()
        try:
            asyncio.run(tasks_module._run_daily_escalation())
            rep_mod.TsConflictReporter.daily_escalation_report.assert_awaited_once()
        finally:
            rep_mod.TsConflictReporter.daily_escalation_report = original
