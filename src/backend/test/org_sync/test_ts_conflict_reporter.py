"""Tests for F015 :class:`TsConflictReporter` (AC-12).

All external dependencies (DAO, inbox, FGA super-admin lookup, settings)
are monkeypatched so each test scripts a single scenario end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


MODULE = 'bisheng.org_sync.domain.services.ts_conflict_reporter'


def _conflict_row(external_id: str, create_time=None):
    return SimpleNamespace(
        external_id=external_id,
        create_time=create_time or datetime.utcnow(),
    )


@pytest.fixture()
def reporter_mocks(monkeypatch):
    """Patch every outbound call on TsConflictReporter by name."""
    aget_conflicts_since = AsyncMock(return_value=[])
    aget_latest_event = AsyncMock(return_value=None)
    acreate_event = AsyncMock()
    list_admins = AsyncMock(return_value=[100, 101])
    send_notice = AsyncMock()

    monkeypatch.setattr(
        f'{MODULE}.OrgSyncLogDao.aget_conflicts_since',
        aget_conflicts_since)
    monkeypatch.setattr(
        f'{MODULE}.OrgSyncLogDao.aget_latest_event', aget_latest_event)
    monkeypatch.setattr(
        f'{MODULE}.OrgSyncLogDao.acreate_event', acreate_event)
    monkeypatch.setattr(
        f'{MODULE}.list_global_super_admin_ids', list_admins)
    monkeypatch.setattr(f'{MODULE}.send_inbox_notice', send_notice)

    # Settings handle with the two thresholds the service reads.
    fake_settings = SimpleNamespace(
        reconcile=SimpleNamespace(
            weekly_conflict_threshold=3,
            daily_escalation_days=5,
        ),
    )
    monkeypatch.setattr(f'{MODULE}.settings', fake_settings)

    return SimpleNamespace(
        aget_conflicts_since=aget_conflicts_since,
        aget_latest_event=aget_latest_event,
        acreate_event=acreate_event,
        list_admins=list_admins,
        send_notice=send_notice,
        settings=fake_settings,
    )


# ---------------------------------------------------------------------------
# weekly_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWeeklyReport:

    async def test_weekly_report_aggregates_conflicts_above_threshold(
        self, reporter_mocks,
    ):
        """AC-12: ≥3 conflicts on one external_id → flagged + inbox fires."""
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X') for _ in range(4)
        ] + [
            _conflict_row('DEPT-Y') for _ in range(1)
        ]

        summary = await TsConflictReporter.weekly_report()

        assert summary['flagged_count'] == 1
        assert summary['notified'] == 2
        reporter_mocks.send_notice.assert_awaited_once()
        title = reporter_mocks.send_notice.await_args.kwargs['title']
        assert 'weekly report' in title.lower()

    async def test_weekly_report_skips_below_threshold(
        self, reporter_mocks,
    ):
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X'),
            _conflict_row('DEPT-Y'),
        ]

        summary = await TsConflictReporter.weekly_report()

        assert summary['flagged_count'] == 0
        reporter_mocks.send_notice.assert_not_awaited()
        reporter_mocks.acreate_event.assert_not_awaited()

    async def test_weekly_report_sends_inbox_to_all_global_super_admins(
        self, reporter_mocks,
    ):
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.list_admins.return_value = [7, 8, 9]
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X') for _ in range(3)
        ]

        await TsConflictReporter.weekly_report()

        reporter_mocks.send_notice.assert_awaited_once()
        kwargs = reporter_mocks.send_notice.await_args.kwargs
        assert kwargs['recipients'] == [7, 8, 9]

    async def test_weekly_report_writes_conflict_weekly_sent_marker(
        self, reporter_mocks,
    ):
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X') for _ in range(3)
        ]

        await TsConflictReporter.weekly_report()

        reporter_mocks.acreate_event.assert_awaited_once()
        kwargs = reporter_mocks.acreate_event.await_args.kwargs
        assert kwargs['event_type'] == 'conflict_weekly_sent'
        assert kwargs['level'] == 'info'


# ---------------------------------------------------------------------------
# daily_escalation_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDailyEscalation:

    async def test_daily_escalation_triggers_after_5_days_unresolved(
        self, reporter_mocks,
    ):
        """AC-12: weekly marker is 6 days old AND conflicts persist → escalate."""
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.aget_latest_event.return_value = SimpleNamespace(
            create_time=datetime.utcnow() - timedelta(days=6),
        )
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X'),
            _conflict_row('DEPT-X'),
        ]

        summary = await TsConflictReporter.daily_escalation_report()

        assert summary['escalated'] is True
        reporter_mocks.send_notice.assert_awaited_once()
        assert 'ESCALATION' in reporter_mocks.send_notice.await_args.kwargs['title']
        reporter_mocks.acreate_event.assert_awaited_once()
        assert reporter_mocks.acreate_event.await_args.kwargs['event_type'] == (
            'conflict_daily_escalation_sent'
        )

    async def test_daily_escalation_no_trigger_when_within_5_days(
        self, reporter_mocks,
    ):
        """Weekly marker is fresh → no escalation despite unresolved conflicts."""
        from bisheng.org_sync.domain.services.ts_conflict_reporter import (
            TsConflictReporter,
        )
        reporter_mocks.aget_latest_event.return_value = SimpleNamespace(
            create_time=datetime.utcnow() - timedelta(days=2),
        )
        reporter_mocks.aget_conflicts_since.return_value = [
            _conflict_row('DEPT-X') for _ in range(5)
        ]

        summary = await TsConflictReporter.daily_escalation_report()

        assert summary['escalated'] is False
        assert summary['reason'] == 'within_grace'
        reporter_mocks.send_notice.assert_not_awaited()
