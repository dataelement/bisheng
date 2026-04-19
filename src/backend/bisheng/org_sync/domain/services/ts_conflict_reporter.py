"""F015 :class:`TsConflictReporter` — weekly + daily ts_conflict reports.

Two public entry points, both called exclusively from
:mod:`bisheng.worker.org_sync.reconcile_tasks`:

- :meth:`weekly_report` (Mon 09:00): aggregates ``ts_conflict`` event
  rows over the past 7 days; when any ``external_id`` count crosses
  ``settings.reconcile.weekly_conflict_threshold`` (default 3) sends an
  inbox notice to every global super-admin and writes a
  ``conflict_weekly_sent`` marker row.
- :meth:`daily_escalation_report` (daily 09:00): checks the age of the
  most recent ``conflict_weekly_sent`` marker. If it is older than
  ``settings.reconcile.daily_escalation_days`` (default 5) and
  conflicts are still present within that window, sends an escalation
  notice and writes a ``conflict_daily_escalation_sent`` marker so the
  next escalation only fires once the underlying issue moves.

Marker rows reuse the ``OrgSyncLog`` event-row mechanism — they keep
the reporter's state entirely inside the existing table without a
separate bookkeeping entity.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.org_sync.domain.models.org_sync import OrgSyncLogDao
from bisheng.tenant.domain.services.inbox_helper import (
    list_global_super_admin_ids,
    send_inbox_notice,
)


class TsConflictReporter:

    @classmethod
    async def weekly_report(cls) -> dict:
        """Aggregate last-7d ts_conflict events and notify admins.

        Returns a small summary dict for caller telemetry. When no
        external_id crosses the threshold the method is a no-op (no
        inbox, no marker row).
        """
        since = datetime.utcnow() - timedelta(days=7)
        rows = await OrgSyncLogDao.aget_conflicts_since(
            since=since, event_type='ts_conflict', level='warn',
        )
        counts: Dict[str, int] = {}
        for r in rows:
            if r.external_id:
                counts[r.external_id] = counts.get(r.external_id, 0) + 1

        threshold = settings.reconcile.weekly_conflict_threshold
        flagged = {ext: cnt for ext, cnt in counts.items() if cnt >= threshold}
        if not flagged:
            return {'flagged_count': 0, 'notified': 0}

        payload = {
            'window_days': 7,
            'total_conflicts': sum(counts.values()),
            'flagged_externals': [
                {
                    'external_id': ext,
                    'count': cnt,
                    'suggested_action': (
                        'Run POST /api/v1/internal/departments/relink to '
                        'realign the external_id mapping.'
                    ),
                }
                for ext, cnt in sorted(
                    flagged.items(), key=lambda kv: kv[1], reverse=True)
            ],
        }
        admins = await list_global_super_admin_ids()
        body = json.dumps(payload, ensure_ascii=False)
        if admins:
            await send_inbox_notice(
                title='Org sync ts_conflict weekly report',
                body=body, recipients=admins,
            )

        # Marker row powers the daily-escalation logic.
        try:
            await OrgSyncLogDao.acreate_event(
                event_type='conflict_weekly_sent', level='info',
                external_id=None, source_ts=None,
                config_id=0, tenant_id=1,
                error_details={'payload': payload,
                               'recipients': admins},
            )
        except Exception as exc:  # marker write must not abort the send
            logger.exception(
                f'weekly marker write failed: {exc}')

        return {'flagged_count': len(flagged), 'notified': len(admins)}

    @classmethod
    async def daily_escalation_report(cls) -> dict:
        """Fire a daily notice only when the weekly report is stale and
        conflicts persist."""
        marker = await OrgSyncLogDao.aget_latest_event(
            event_type='conflict_weekly_sent')
        if marker is None:
            return {'escalated': False, 'reason': 'no_weekly_marker'}
        marker_time = marker.create_time
        if marker_time is None:
            return {'escalated': False, 'reason': 'marker_missing_timestamp'}

        grace = timedelta(days=settings.reconcile.daily_escalation_days)
        age = datetime.utcnow() - marker_time
        if age < grace:
            return {'escalated': False, 'reason': 'within_grace'}

        since = datetime.utcnow() - grace
        rows = await OrgSyncLogDao.aget_conflicts_since(
            since=since, event_type='ts_conflict', level='warn',
        )
        if not rows:
            return {'escalated': False, 'reason': 'resolved'}

        counts: Dict[str, int] = {}
        for r in rows:
            if r.external_id:
                counts[r.external_id] = counts.get(r.external_id, 0) + 1

        admins = await list_global_super_admin_ids()
        body = json.dumps({
            'window_days': settings.reconcile.daily_escalation_days,
            'unresolved_externals': counts,
            'suggested_action': (
                'ts_conflicts persist ≥ grace window; investigate the '
                'offending source immediately or run a targeted relink.'
            ),
        }, ensure_ascii=False)
        if admins:
            await send_inbox_notice(
                title='Org sync ts_conflict daily ESCALATION',
                body=body, recipients=admins,
            )

        try:
            await OrgSyncLogDao.acreate_event(
                event_type='conflict_daily_escalation_sent', level='warn',
                external_id=None, source_ts=None,
                config_id=0, tenant_id=1,
                error_details={'unresolved_externals': counts,
                               'recipients': admins},
            )
        except Exception as exc:
            logger.exception(
                f'escalation marker write failed: {exc}')

        return {'escalated': True, 'notified': len(admins)}
