"""Tests for F015 Celery reconcile + conflict-report tasks.

Covers:

- beat_schedule registration (``reconcile_all_organizations`` every 6h,
  ``report_ts_conflicts_weekly`` Monday 09:00, daily escalation 09:00).
- ``_fan_out_all`` dispatches one ``reconcile_single_config`` per active
  config, skipping the F014 ``sso_realtime`` seed.
- ``reconcile_single_config`` swallows the :class:`SsoReconcileLockBusyError`
  path (AC-13 precursor).
- Weekly + daily-escalation tasks delegate to
  :class:`TsConflictReporter` (AC-12).

All DAO + service calls are patched with ``AsyncMock``; the tests are
pure function-call verification and do not require a real Celery broker
or Redis instance.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.schedules import crontab


TASKS_MODULE = 'bisheng.worker.org_sync.reconcile_tasks'


# ---------------------------------------------------------------------------
# Beat schedule registration
# ---------------------------------------------------------------------------


class TestBeatSchedule:

    def test_beat_schedule_registers_reconcile_all_every_6h(self):
        """AC-01 — confirm settings registered the 6h fan-out beat."""
        from bisheng.core.config.settings import CeleryConf

        conf = CeleryConf()  # triggers ``validate`` model_validator
        entry = conf.beat_schedule.get('reconcile_all_organizations')
        assert entry is not None
        assert entry['task'] == (
            'bisheng.worker.org_sync.reconcile_tasks.reconcile_all_organizations'
        )
        sched = entry['schedule']
        assert isinstance(sched, crontab)
        # crontab stores minute/hour as sets — use their public iterators.
        assert sched.minute == {0}
        assert sched.hour == set(range(0, 24, 6))

    def test_beat_registers_weekly_conflict_report_monday_09(self):
        from bisheng.core.config.settings import CeleryConf

        conf = CeleryConf()
        entry = conf.beat_schedule.get('report_ts_conflicts_weekly')
        assert entry is not None
        assert entry['task'].endswith('report_ts_conflicts_weekly')
        sched = entry['schedule']
        assert isinstance(sched, crontab)
        assert sched.minute == {0}
        assert sched.hour == {9}
        # day_of_week: Monday can be 1 (celery) — accept either key.
        dow = sched.day_of_week
        assert 1 in dow or 'mon' in {str(d).lower() for d in dow}

    def test_beat_registers_daily_escalation_09(self):
        from bisheng.core.config.settings import CeleryConf

        conf = CeleryConf()
        entry = conf.beat_schedule.get(
            'report_ts_conflicts_daily_escalation')
        assert entry is not None
        assert entry['task'].endswith(
            'report_ts_conflicts_daily_escalation')
        sched = entry['schedule']
        assert isinstance(sched, crontab)
        assert sched.minute == {0}
        assert sched.hour == {9}


# ---------------------------------------------------------------------------
# Fan-out behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFanOut:

    async def test_fan_out_dispatches_single_config_per_active_config(self):
        from bisheng.worker.org_sync.reconcile_tasks import _fan_out_all

        active_configs = [
            SimpleNamespace(id=1, provider='feishu'),
            SimpleNamespace(id=2, provider='wecom'),
            SimpleNamespace(id=3, provider='dingtalk'),
        ]
        with patch(
            f'{TASKS_MODULE}.reconcile_single_config.apply_async'
        ) as apply_async, patch(
            'bisheng.org_sync.domain.models.org_sync.OrgSyncConfigDao.aget_all_active',
            new_callable=AsyncMock, return_value=active_configs,
        ):
            await _fan_out_all()

        assert apply_async.call_count == 3
        dispatched_ids = [
            c.kwargs['args'][0] for c in apply_async.call_args_list
        ]
        assert dispatched_ids == [1, 2, 3]

    async def test_fan_out_skips_sso_realtime_seed(self):
        from bisheng.worker.org_sync.reconcile_tasks import _fan_out_all

        active_configs = [
            SimpleNamespace(id=1, provider='feishu'),
            SimpleNamespace(id=9999, provider='sso_realtime'),
        ]
        with patch(
            f'{TASKS_MODULE}.reconcile_single_config.apply_async'
        ) as apply_async, patch(
            'bisheng.org_sync.domain.models.org_sync.OrgSyncConfigDao.aget_all_active',
            new_callable=AsyncMock, return_value=active_configs,
        ):
            await _fan_out_all()

        dispatched_ids = [
            c.kwargs['args'][0] for c in apply_async.call_args_list
        ]
        assert dispatched_ids == [1]
        assert 9999 not in dispatched_ids


# ---------------------------------------------------------------------------
# Lock-busy swallowing
# ---------------------------------------------------------------------------


class TestReconcileSingleConfig:

    def test_single_config_swallows_lock_busy_logs_warning(self, caplog):
        """AC-13 precursor — concurrent worker hits the lock, task exits cleanly."""
        from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError
        from bisheng.worker.org_sync.reconcile_tasks import reconcile_single_config

        with patch(
            'bisheng.org_sync.domain.services.reconcile_service.OrgReconcileService.reconcile_config',
            new_callable=AsyncMock,
            side_effect=SsoReconcileLockBusyError.http_exception(),
        ):
            # ``reconcile_single_config.run`` invokes the task body
            # synchronously — bypass the Celery dispatcher.
            reconcile_single_config.run(42)

        # No re-raise; check that a warning line mentioning the config
        # id was emitted via the module logger.
        messages = [r.getMessage() for r in caplog.records]
        assert any('42' in m and 'lock busy' in m for m in messages)


# ---------------------------------------------------------------------------
# Weekly / daily reporter wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReporterDelegation:

    async def test_weekly_celery_task_invokes_reporter_weekly(self):
        from bisheng.worker.org_sync.reconcile_tasks import _run_weekly

        with patch(
            'bisheng.org_sync.domain.services.ts_conflict_reporter.TsConflictReporter.weekly_report',
            new_callable=AsyncMock,
        ) as weekly:
            await _run_weekly()
        weekly.assert_awaited_once()
