"""Tests for ``OrgSyncTsGuard.check_and_update`` — the 8-case decision
matrix that enforces INV-T12 (ts max wins; same ts remove wins).

Shared by F014 realtime sync + F015 Celery reconciliation. The guard is a
pure function over ``(existing_row, incoming_ts, action)``; keep these
tests cheap and exhaustive so every regression surfaces here before it
bleeds into the integration layer.
"""

from types import SimpleNamespace

import pytest


def _row(last_sync_ts: int, is_deleted: int = 0):
    """Lightweight stand-in for a Department row — only the two fields the
    guard inspects. Keeps tests free of ORM/table setup."""
    return SimpleNamespace(last_sync_ts=last_sync_ts, is_deleted=is_deleted)


@pytest.mark.asyncio
class TestNewExternalId:

    async def test_new_upsert_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        assert await OrgSyncTsGuard.check_and_update(None, 100, 'upsert') \
            == GuardDecision.APPLY

    async def test_new_remove_skipped(self):
        """Remove on unseen external_id: nothing to delete → drop silently."""
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        assert await OrgSyncTsGuard.check_and_update(None, 100, 'remove') \
            == GuardDecision.SKIP_TS


@pytest.mark.asyncio
class TestStaleMessages:

    async def test_stale_upsert_skipped(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=200)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'upsert') \
            == GuardDecision.SKIP_TS

    async def test_stale_remove_skipped(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=200)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'remove') \
            == GuardDecision.SKIP_TS


@pytest.mark.asyncio
class TestNewerTs:

    async def test_newer_upsert_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100)
        assert await OrgSyncTsGuard.check_and_update(existing, 200, 'upsert') \
            == GuardDecision.APPLY

    async def test_newer_remove_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100)
        assert await OrgSyncTsGuard.check_and_update(existing, 200, 'remove') \
            == GuardDecision.APPLY


@pytest.mark.asyncio
class TestSameTs:
    """INV-T12 tie-breaker: when ts equals last_sync_ts, a prior remove
    (is_deleted=1) wins; later upserts are dropped. Matching same-ts
    operations (both upserts or both removes) are idempotent applies."""

    async def test_same_ts_upsert_on_active_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100, is_deleted=0)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'upsert') \
            == GuardDecision.APPLY

    async def test_same_ts_upsert_on_deleted_skipped(self):
        """INV-T12 key case: remove already applied, later upsert drops."""
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100, is_deleted=1)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'upsert') \
            == GuardDecision.SKIP_TS

    async def test_same_ts_remove_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100, is_deleted=0)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'remove') \
            == GuardDecision.APPLY

    async def test_same_ts_remove_already_deleted_applies(self):
        """Double-remove at same ts is idempotent — still APPLY, the DAO
        update is a no-op UPDATE ... SET is_deleted=1 on an already-deleted
        row."""
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=100, is_deleted=1)
        assert await OrgSyncTsGuard.check_and_update(existing, 100, 'remove') \
            == GuardDecision.APPLY


@pytest.mark.asyncio
class TestZeroTsBaseline:
    """Legacy rows (seeded before F014 landed) carry last_sync_ts=0.
    Any non-negative incoming ts should win (including the first push
    carrying ts=0 on the system-clock fallback from WeCom/Feishu)."""

    async def test_zero_ts_upsert_applies(self):
        from bisheng.org_sync.domain.services.ts_guard import (
            GuardDecision, OrgSyncTsGuard,
        )
        existing = _row(last_sync_ts=0)
        assert await OrgSyncTsGuard.check_and_update(existing, 0, 'upsert') \
            == GuardDecision.APPLY
