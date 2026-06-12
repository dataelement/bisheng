"""Tests for F014 ``DepartmentsSyncService`` — batch orchestration.

Covers AC-04, AC-09, AC-10, AC-11 plus INV-T12 same-ts corner cases.

All lower layers are AsyncMock'd; the tests assert on the number + type
of downstream calls and on the aggregated :class:`BatchResult` shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from bisheng.sso_sync.domain.schemas.payloads import (
    DepartmentUpsertItem,
    DepartmentsSyncRequest,
)


MODULE = 'bisheng.sso_sync.domain.services.departments_sync_service'


def _dept(ext='D1', *, id=11, last_sync_ts=0, is_deleted=0,
          mounted_tenant_id=None):
    return SimpleNamespace(
        id=id, external_id=ext, last_sync_ts=last_sync_ts,
        is_deleted=is_deleted, mounted_tenant_id=mounted_tenant_id,
        source='sso', path='/', parent_id=None, is_tenant_root=0,
    )


# =========================================================================
# Upsert flow
# =========================================================================

@pytest.mark.asyncio
class TestUpsertBatch:

    async def test_happy_path_new_items_applied(self):
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        payload = DepartmentsSyncRequest(
            upsert=[
                DepartmentUpsertItem(external_id='D1', name='Eng', ts=100),
                DepartmentUpsertItem(external_id='D2', name='Mkt', ts=101,
                                     parent_external_id='D1'),
            ],
            remove=[], source_ts=200,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new_callable=AsyncMock,
        ) as upsert:
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_upsert == 2
        assert result.applied_remove == 0
        assert result.skipped_ts_conflict == 0
        assert result.errors == []
        assert upsert.await_count == 2

    async def test_stale_ts_counts_as_skipped(self):
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        existing = _dept('D1', id=11, last_sync_ts=500)
        payload = DepartmentsSyncRequest(
            upsert=[
                DepartmentUpsertItem(external_id='D1', name='Eng', ts=100),
            ],
            remove=[], source_ts=100,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=existing,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new_callable=AsyncMock,
        ) as upsert:
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_upsert == 0
        assert result.skipped_ts_conflict == 1
        upsert.assert_not_awaited()

    async def test_item_ts_falls_back_to_source_ts(self):
        """Missing ``item.ts`` → use batch-level source_ts. Verifies the
        fallback used by legacy Gateway versions."""
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        payload = DepartmentsSyncRequest(
            upsert=[DepartmentUpsertItem(external_id='D1', name='Eng')],
            remove=[], source_ts=777,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new_callable=AsyncMock,
        ) as upsert:
            await DepartmentsSyncService.execute(payload)

        kwargs = upsert.await_args.kwargs
        assert kwargs['last_sync_ts'] == 777

    async def test_single_item_failure_does_not_abort_batch(self):
        """AC-11: one error → other items still processed."""
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        payload = DepartmentsSyncRequest(
            upsert=[
                DepartmentUpsertItem(external_id='GOOD', name='Eng', ts=100),
                DepartmentUpsertItem(
                    external_id='BAD', name='X',
                    parent_external_id='GHOST', ts=100,
                ),
                DepartmentUpsertItem(external_id='ALSO_GOOD', name='Mkt',
                                     ts=100),
            ],
            remove=[],
        )

        # First and third upserts succeed; second blows up.
        async def fake_upsert(*, existing, item, source, last_sync_ts,
                              parent_cache=None):
            if item.external_id == 'BAD':
                raise RuntimeError('parent missing')
            return _dept(item.external_id)

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new=fake_upsert,
        ):
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_upsert == 2
        assert len(result.errors) == 1
        assert result.errors[0]['external_id'] == 'BAD'
        assert 'parent missing' in result.errors[0]['error']


# =========================================================================
# Remove flow (AC-04 — triggers DepartmentDeletionHandler)
# =========================================================================

@pytest.mark.asyncio
class TestRemoveBatch:

    async def test_remove_mounted_triggers_deletion_handler(self):
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        from bisheng.tenant.domain.constants import DeletionSource

        dept = _dept('D99', id=99, last_sync_ts=10, mounted_tenant_id=42)
        payload = DepartmentsSyncRequest(
            upsert=[], remove=['D99'], source_ts=100,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDeletionHandler.on_deleted',
            new_callable=AsyncMock,
        ) as on_deleted:
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_remove == 1
        assert result.orphan_triggered == [42]
        on_deleted.assert_awaited_once()
        kwargs = on_deleted.await_args.kwargs
        assert kwargs['dept_id'] == 99
        assert kwargs['deletion_source'] == DeletionSource.SSO_REALTIME

    async def test_remove_unmounted_no_orphan(self):
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        dept = _dept('D50', id=50, last_sync_ts=10)
        payload = DepartmentsSyncRequest(
            upsert=[], remove=['D50'], source_ts=100,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDeletionHandler.on_deleted',
            new_callable=AsyncMock,
        ):
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_remove == 1
        assert result.orphan_triggered == []

    async def test_remove_missing_dept_is_silent(self):
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        payload = DepartmentsSyncRequest(
            upsert=[], remove=['GHOST'], source_ts=100,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock,
        ) as archive, patch(
            f'{MODULE}.DepartmentDeletionHandler.on_deleted',
            new_callable=AsyncMock,
        ) as on_deleted:
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_remove == 0
        assert result.errors == []
        archive.assert_not_awaited()
        on_deleted.assert_not_awaited()

    async def test_same_ts_upsert_after_remove_is_skipped_inv_t12(self):
        """INV-T12 same-ts tie-breaker: upsert arriving with the same ts on
        a row that already has is_deleted=1 + last_sync_ts=X is dropped."""
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        existing = _dept('D1', id=11, last_sync_ts=100, is_deleted=1)
        payload = DepartmentsSyncRequest(
            upsert=[DepartmentUpsertItem(external_id='D1', name='Eng', ts=100)],
            remove=[], source_ts=100,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=existing,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new_callable=AsyncMock,
        ) as upsert:
            result = await DepartmentsSyncService.execute(payload)

        assert result.skipped_ts_conflict == 1
        upsert.assert_not_awaited()

    async def test_mixed_upsert_and_remove_counters(self):
        """End-to-end counter aggregation sanity check."""
        from bisheng.sso_sync.domain.services.departments_sync_service import (
            DepartmentsSyncService,
        )
        upsert_existing = None
        remove_dept = _dept('D99', id=99, last_sync_ts=10,
                            mounted_tenant_id=None)

        async def fake_get(source, ext):
            return {'D1': upsert_existing, 'D99': remove_dept}.get(ext)

        payload = DepartmentsSyncRequest(
            upsert=[DepartmentUpsertItem(external_id='D1', name='Eng', ts=500)],
            remove=['D99'], source_ts=500,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new=fake_get,
        ), patch(
            f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
            new_callable=AsyncMock,
        ), patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock, return_value=remove_dept,
        ), patch(
            f'{MODULE}.DepartmentDeletionHandler.on_deleted',
            new_callable=AsyncMock,
        ):
            result = await DepartmentsSyncService.execute(payload)

        assert result.applied_upsert == 1
        assert result.applied_remove == 1
        assert result.orphan_triggered == []
