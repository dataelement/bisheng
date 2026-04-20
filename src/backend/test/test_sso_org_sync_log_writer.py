"""Tests for F014 ``OrgSyncLogBuffer`` + :func:`flush_log`.

The writer layer is intentionally dumb: accumulate counters, flush a
single row. Tests focus on:
- Config_id defaults to the SSO seed id (9999 or ``SSOSyncConf``).
- status derived as 'partial' when errors present else 'success'.
- error_details serialises errors + warnings together.
- Flush failures are swallowed (returning None) — must not break the
  caller.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MODULE = 'bisheng.sso_sync.domain.services.org_sync_log_writer'


@pytest.fixture()
def mock_seed_config(monkeypatch):
    import bisheng.sso_sync.domain.services.org_sync_log_writer as mod
    fake_settings = SimpleNamespace(
        sso_sync=SimpleNamespace(orphan_config_id=9999),
    )
    monkeypatch.setattr(mod, 'settings', fake_settings)
    return fake_settings


@pytest.mark.asyncio
class TestBufferAccumulation:

    async def test_warn_and_error_accumulate(self):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer,
        )
        buf = OrgSyncLogBuffer()
        buf.warn('ts_conflict', 'D1', incoming_ts=100, last_ts=200)
        buf.error('upsert', 'D2', 'parent missing')
        assert len(buf.warnings) == 1
        assert buf.warnings[0]['event_type'] == 'ts_conflict'
        assert len(buf.errors) == 1
        assert buf.errors[0]['entity_type'] == 'upsert'


@pytest.mark.asyncio
class TestFlushLog:

    async def test_flush_writes_row_with_stats(self, mock_seed_config):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        buf = OrgSyncLogBuffer(
            dept_updated=5, dept_archived=2, member_created=1,
        )
        fake_row = MagicMock(id=77)
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, return_value=fake_row,
        ) as acreate:
            result = await flush_log(buf, trigger_type='sso_realtime')

        assert result is fake_row
        acreate.assert_awaited_once()
        written = acreate.await_args.args[0]
        assert written.dept_updated == 5
        assert written.dept_archived == 2
        assert written.member_created == 1
        assert written.trigger_type == 'sso_realtime'
        assert written.status == 'success'  # no errors
        assert written.config_id == 9999  # seed default
        assert written.tenant_id == 1

    async def test_flush_uses_seed_config_id_when_not_overridden(
        self, mock_seed_config,
    ):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        buf = OrgSyncLogBuffer()
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, return_value=MagicMock(),
        ) as acreate:
            await flush_log(buf, trigger_type='sso_realtime')
        written = acreate.await_args.args[0]
        assert written.config_id == 9999

    async def test_explicit_config_id_overrides_seed(self, mock_seed_config):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, return_value=MagicMock(),
        ) as acreate:
            await flush_log(
                OrgSyncLogBuffer(),
                trigger_type='sso_realtime',
                config_id=1234,
            )
        written = acreate.await_args.args[0]
        assert written.config_id == 1234

    async def test_status_is_partial_when_errors_present(self, mock_seed_config):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        buf = OrgSyncLogBuffer()
        buf.error('upsert', 'D1', 'oops')
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, return_value=MagicMock(),
        ) as acreate:
            await flush_log(buf, trigger_type='sso_realtime')
        written = acreate.await_args.args[0]
        assert written.status == 'partial'
        # error_details includes both errors and warnings
        assert any(e.get('entity_type') == 'upsert' for e in written.error_details)

    async def test_explicit_status_overrides_derivation(self, mock_seed_config):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, return_value=MagicMock(),
        ) as acreate:
            await flush_log(
                OrgSyncLogBuffer(), trigger_type='sso_realtime',
                status='failed',
            )
        written = acreate.await_args.args[0]
        assert written.status == 'failed'

    async def test_flush_failure_returns_none(self, mock_seed_config):
        from bisheng.sso_sync.domain.services.org_sync_log_writer import (
            OrgSyncLogBuffer, flush_log,
        )
        with patch(
            f'{MODULE}.OrgSyncLogDao.acreate',
            new_callable=AsyncMock, side_effect=RuntimeError('db down'),
        ):
            result = await flush_log(OrgSyncLogBuffer(),
                                     trigger_type='sso_realtime')
        assert result is None
